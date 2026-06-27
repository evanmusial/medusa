from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import fitz
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


STATE_FILE = "slipstream-client.json"


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def body_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def canonical_message(method: str, path: str, timestamp: str, nonce: str, digest: str) -> bytes:
    return "\n".join([method.upper(), path, timestamp, nonce, digest]).encode("utf-8")


def load_state(work_dir: Path) -> dict[str, Any]:
    state_path = work_dir / STATE_FILE
    if not state_path.exists():
        return {}
    return json.loads(state_path.read_text())


def save_state(work_dir: Path, state: dict[str, Any]) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    state_path = work_dir / STATE_FILE
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True))
    try:
        state_path.chmod(0o600)
    except OSError:
        pass


def ensure_key(state: dict[str, Any]) -> Ed25519PrivateKey:
    private_key_b64 = state.get("private_key")
    if private_key_b64:
        return Ed25519PrivateKey.from_private_bytes(base64.urlsafe_b64decode(private_key_b64 + "=" * (-len(private_key_b64) % 4)))
    private_key = Ed25519PrivateKey.generate()
    state["private_key"] = b64(
        private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    state["public_key"] = "ed25519:" + b64(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
    return private_key


class SlipstreamClient:
    def __init__(self, server: str, work_dir: Path, *, verify_tls: bool = True) -> None:
        self.server = server.rstrip("/")
        self.work_dir = work_dir
        self.state = load_state(work_dir)
        self.private_key = ensure_key(self.state)
        self.http = httpx.Client(base_url=self.server, timeout=120.0, verify=verify_tls)

    def close(self) -> None:
        self.http.close()
        save_state(self.work_dir, self.state)

    def register(self, *, enrollment_token: str, name: str, version: str, capabilities: list[str], capacity: int) -> dict[str, Any]:
        payload = {
            "enrollment_token": enrollment_token,
            "name": name,
            "public_key": self.state["public_key"],
            "version": version,
            "capabilities": capabilities,
            "capacity": capacity,
            "metadata": {"runner": "basic-pdf-text"},
        }
        response = self.http.post("/api/slipstream/register", json=payload)
        response.raise_for_status()
        data = response.json()
        self.state["client_id"] = data["id"]
        self.state["name"] = data["name"]
        self.state["capabilities"] = capabilities
        save_state(self.work_dir, self.state)
        return data

    def signed_request(self, method: str, path: str, payload: dict[str, Any] | None = None, *, lease_token: str | None = None) -> httpx.Response:
        if not self.state.get("client_id"):
            raise RuntimeError("Client is not registered. Run with --enroll first.")
        body = b"" if payload is None else json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        timestamp = str(time.time())
        nonce = secrets.token_urlsafe(18)
        digest = body_hash(body)
        signature = self.private_key.sign(canonical_message(method, path, timestamp, nonce, digest))
        headers = {
            "Content-Type": "application/json",
            "X-Slipstream-Client-Id": self.state["client_id"],
            "X-Slipstream-Timestamp": timestamp,
            "X-Slipstream-Nonce": nonce,
            "X-Slipstream-Body-SHA256": digest,
            "X-Slipstream-Signature": b64(signature),
        }
        if lease_token:
            headers["X-Slipstream-Lease-Token"] = lease_token
        response = self.http.request(method, path, content=body, headers=headers)
        response.raise_for_status()
        return response

    def check_in(self, *, version: str, capabilities: list[str], capacity: int) -> dict[str, Any]:
        return self.signed_request(
            "POST",
            "/api/slipstream/check-in",
            {"version": version, "capabilities": capabilities, "capacity": capacity, "metadata": {"runner": "basic-pdf-text"}},
        ).json()

    def claim(self, job_types: list[str]) -> dict[str, Any]:
        return self.signed_request("POST", "/api/slipstream/leases/claim", {"job_types": job_types}).json()

    def heartbeat(self, lease_id: str, lease_token: str, detail: str) -> None:
        self.signed_request("POST", f"/api/slipstream/leases/{lease_id}/heartbeat", {"detail": detail}, lease_token=lease_token)

    def download_artifact(self, lease_id: str, lease_token: str, destination: Path) -> Path:
        response = self.signed_request("GET", f"/api/slipstream/leases/{lease_id}/artifact", None, lease_token=lease_token)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.content)
        return destination

    def complete(self, lease_id: str, lease_token: str, manifest: dict[str, Any]) -> dict[str, Any]:
        return self.signed_request("POST", f"/api/slipstream/leases/{lease_id}/results", manifest, lease_token=lease_token).json()

    def fail(self, lease_id: str, lease_token: str, error: str) -> dict[str, Any]:
        return self.signed_request("POST", f"/api/slipstream/leases/{lease_id}/fail", {"error": error}, lease_token=lease_token).json()


def extract_pdf_manifest(pdf_path: Path, work: dict[str, Any]) -> dict[str, Any]:
    started = time.time()
    pages: list[dict[str, Any]] = []
    search_parts: list[str] = []
    with fitz.open(pdf_path) as doc:
        for index, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            pages.append({"page_number": index, "text": text, "normalized_text": text, "text_source": "slipstream"})
            search_parts.append(text)
        page_count = doc.page_count
    elapsed_ms = int((time.time() - started) * 1000)
    return {
        "idempotency_key": work["idempotency_key"],
        "current_step": "complete",
        "document": {
            "page_count": page_count,
            "search_text": "\n\n".join(search_parts),
        },
        "pages": pages,
        "composition": [
            {
                "record_kind": "remote_stage",
                "stage_key": "slipstream_pdf_text",
                "stage_label": "Slipstream PDF text extraction",
                "provider": "slipstream",
                "method": "pymupdf_basic_text",
                "status": "complete",
                "duration_ms": elapsed_ms,
                "metadata": {"page_count": page_count},
            }
        ],
    }


def run_once(client: SlipstreamClient, *, version: str, capabilities: list[str], capacity: int, job_types: list[str], no_process: bool) -> int:
    client.check_in(version=version, capabilities=capabilities, capacity=capacity)
    claim = client.claim(job_types)
    lease = claim.get("lease")
    work = claim.get("work")
    lease_token = claim.get("lease_token")
    if not lease or not work or not lease_token:
        print("No Slipstream work available.")
        return 0
    lease_id = lease["id"]
    print(f"Claimed {work['job_type']} job {work['job_id']} as lease {lease_id}.")
    if no_process:
        client.heartbeat(lease_id, lease_token, "claimed without processing")
        print("Processing skipped because --no-process is set.")
        return 0
    if work["job_type"] != "import":
        client.fail(lease_id, lease_token, "This basic client only processes import jobs automatically.")
        print("Failed non-import job because the basic client cannot process it automatically.")
        return 2
    artifact_path = client.work_dir / "artifacts" / f"{lease_id}.pdf"
    client.download_artifact(lease_id, lease_token, artifact_path)
    client.heartbeat(lease_id, lease_token, "artifact downloaded")
    manifest = extract_pdf_manifest(artifact_path, work)
    client.complete(lease_id, lease_token, manifest)
    print(f"Completed import job {work['job_id']} from {artifact_path}.")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a Medusa Slipstream remote processing client.")
    parser.add_argument("--server", required=True, help="Central Medusa base URL, for example https://medusa.home.musial.io:3737")
    parser.add_argument("--work-dir", default="./data/slipstream-client", help="Ignored local directory for client key and downloaded artifacts.")
    parser.add_argument("--name", default="Slipstream client")
    parser.add_argument("--version", default="slipstream-basic-1")
    parser.add_argument("--enroll", help="One-time enrollment token from Settings > Slipstream.")
    parser.add_argument("--capacity", type=int, default=1)
    parser.add_argument("--job-type", action="append", choices=["import", "concordance"], default=None)
    parser.add_argument("--capability", action="append", choices=["import", "concordance"], default=None)
    parser.add_argument("--once", action="store_true", help="Check in, claim at most one job, then exit.")
    parser.add_argument("--no-process", action="store_true", help="Claim and heartbeat only; do not submit a result.")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS certificate verification for controlled local tests.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    work_dir = Path(args.work_dir).expanduser()
    capabilities = args.capability or ["import"]
    job_types = args.job_type or capabilities
    client = SlipstreamClient(args.server, work_dir, verify_tls=not args.insecure)
    try:
        if args.enroll:
            registered = client.register(
                enrollment_token=args.enroll,
                name=args.name,
                version=args.version,
                capabilities=capabilities,
                capacity=args.capacity,
            )
            print(f"Registered Slipstream client {registered['name']} ({registered['id']}).")
        if args.once or args.enroll:
            return run_once(
                client,
                version=args.version,
                capabilities=capabilities,
                capacity=args.capacity,
                job_types=job_types,
                no_process=args.no_process,
            )
        while True:
            exit_code = run_once(
                client,
                version=args.version,
                capabilities=capabilities,
                capacity=args.capacity,
                job_types=job_types,
                no_process=args.no_process,
            )
            if exit_code:
                return exit_code
            time.sleep(5)
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
