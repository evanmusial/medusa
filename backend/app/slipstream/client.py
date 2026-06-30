from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import json
import os
import platform
import secrets
import signal
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services.analysis_models import MODEL_RAW_TEXT_EXTRACTION
from app.services.extraction import extract_pdf_text, sanitize_extracted_text


STATE_FILE = "slipstream-client.json"
SLIPSTREAM_CAP_IMPORT_PREPROCESS = "import_preprocess"
RUNNER_NAME = "slipstream-import-preprocess"
DEFAULT_VERSION = "slipstream-import-preprocess-1"


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def body_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def canonical_message(method: str, path: str, timestamp: str, nonce: str, digest: str) -> bytes:
    return "\n".join([method.upper(), path, timestamp, nonce, digest]).encode("utf-8")


def load_state(work_dir: Path, *, state_file: str = STATE_FILE) -> dict[str, Any]:
    state_path = work_dir / state_file
    if not state_path.exists():
        return {}
    return json.loads(state_path.read_text())


def save_state(work_dir: Path, state: dict[str, Any], *, state_file: str = STATE_FILE) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    state_path = work_dir / state_file
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True))
    try:
        state_path.chmod(0o600)
    except OSError:
        pass


def ensure_key(state: dict[str, Any]) -> Ed25519PrivateKey:
    private_key_b64 = state.get("private_key")
    if private_key_b64:
        private_key = Ed25519PrivateKey.from_private_bytes(base64.urlsafe_b64decode(private_key_b64 + "=" * (-len(private_key_b64) % 4)))
        if not state.get("public_key"):
            state["public_key"] = "ed25519:" + b64(
                private_key.public_key().public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw,
                )
            )
        return private_key
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


def parse_cpuset(value: str | None) -> set[int]:
    cpus: set[int] = set()
    for part in (value or "").split(","):
        item = part.strip()
        if not item:
            continue
        if "-" in item:
            start, end = item.split("-", 1)
            cpus.update(range(int(start), int(end) + 1))
        else:
            cpus.add(int(item))
    return {cpu for cpu in cpus if cpu >= 0}


def apply_process_affinity(cpuset: str | None) -> str | None:
    try:
        cpus = parse_cpuset(cpuset)
    except ValueError as exc:
        return f"process affinity ignored invalid CPU set {cpuset!r}: {exc}"
    if not cpus:
        return None
    if hasattr(os, "sched_setaffinity"):
        try:
            os.sched_setaffinity(0, cpus)
            return f"process affinity set to CPUs {format_cpuset(cpus)}"
        except OSError as exc:
            return f"process affinity failed for CPUs {format_cpuset(cpus)}: {exc}"
    return "process affinity unavailable on this platform"


def format_cpuset(cpus: set[int]) -> str:
    return ",".join(str(cpu) for cpu in sorted(cpus))


def prefer_performance_cores(enabled: bool) -> str | None:
    if not enabled or platform.system() != "Darwin":
        return None
    try:
        pthread = ctypes.CDLL(None).pthread_set_qos_class_self_np
    except AttributeError:
        return "macOS QoS performance hint unavailable"
    qos_class_user_initiated = 0x19
    try:
        result = pthread(qos_class_user_initiated, 0)
    except Exception as exc:  # pragma: no cover - host-specific guard
        return f"macOS QoS performance hint failed: {exc}"
    if result == 0:
        return "macOS QoS set to user-initiated for P-core preference"
    return f"macOS QoS performance hint returned {result}"


class SlipstreamClient:
    def __init__(
        self,
        server: str,
        work_dir: Path,
        *,
        verify_tls: bool = True,
        state_file: str = STATE_FILE,
        initial_state: dict[str, Any] | None = None,
        persist_state: bool = True,
    ) -> None:
        self.server = server.rstrip("/")
        self.work_dir = work_dir
        self.state_file = state_file
        self.persist_state = persist_state
        self.state_lock = threading.Lock()
        self.state = load_state(work_dir, state_file=state_file)
        if initial_state:
            self.state.update({key: value for key, value in initial_state.items() if value})
        self.private_key = ensure_key(self.state)
        self.http = httpx.Client(base_url=self.server, timeout=120.0, verify=verify_tls)

    def close(self) -> None:
        self.http.close()
        if self.persist_state:
            with self.state_lock:
                save_state(self.work_dir, self.state, state_file=self.state_file)

    def register(
        self,
        *,
        enrollment_token: str,
        name: str,
        version: str,
        capabilities: list[str],
        capacity: int,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        client_metadata = {"runner": RUNNER_NAME, **(metadata or {})}
        payload = {
            "enrollment_token": enrollment_token,
            "name": name,
            "public_key": self.state["public_key"],
            "version": version,
            "capabilities": capabilities,
            "capacity": capacity,
            "metadata": client_metadata,
        }
        response = self.http.post("/api/slipstream/register", json=payload)
        response.raise_for_status()
        data = response.json()
        with self.state_lock:
            self.state["client_id"] = data["id"]
            self.state["name"] = data["name"]
            self.state["capabilities"] = data.get("capabilities") or capabilities
            self.state["capacity"] = data.get("capacity") or capacity
            if self.persist_state:
                save_state(self.work_dir, self.state, state_file=self.state_file)
        return data

    def signed_request(self, method: str, path: str, payload: dict[str, Any] | None = None, *, lease_token: str | None = None) -> httpx.Response:
        with self.state_lock:
            client_id = self.state.get("client_id")
        if not client_id:
            raise RuntimeError("Client is not registered. Run with --enroll first.")
        body = b"" if payload is None else json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        timestamp = str(time.time())
        nonce = secrets.token_urlsafe(18)
        digest = body_hash(body)
        signature = self.private_key.sign(canonical_message(method, path, timestamp, nonce, digest))
        headers = {
            "Content-Type": "application/json",
            "X-Slipstream-Client-Id": client_id,
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

    def check_in(self, *, version: str, capabilities: list[str], capacity: int, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        client_metadata = {"runner": RUNNER_NAME, **(metadata or {})}
        result = self.signed_request(
            "POST",
            "/api/slipstream/check-in",
            {"version": version, "capabilities": capabilities, "capacity": capacity, "metadata": client_metadata},
        ).json()
        with self.state_lock:
            self.state["capabilities"] = result.get("capabilities") or capabilities
            self.state["capacity"] = result.get("capacity") or capacity
        return result

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


class LeaseHeartbeat:
    def __init__(self, client: SlipstreamClient, lease_id: str, lease_token: str, *, interval_seconds: int, initial_detail: str) -> None:
        self.client = client
        self.lease_id = lease_id
        self.lease_token = lease_token
        self.interval_seconds = max(5, interval_seconds)
        self.detail = initial_detail
        self.detail_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name=f"slipstream-heartbeat-{lease_id[:8]}", daemon=True)

    def __enter__(self) -> "LeaseHeartbeat":
        self.beat(self.detail)
        self.thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop_event.set()
        self.thread.join(timeout=5)

    def set_detail(self, detail: str) -> None:
        with self.detail_lock:
            self.detail = detail

    def current_detail(self) -> str:
        with self.detail_lock:
            return self.detail

    def beat(self, detail: str | None = None) -> None:
        if detail:
            self.set_detail(detail)
        self.client.heartbeat(self.lease_id, self.lease_token, self.current_detail())

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval_seconds):
            try:
                self.beat()
            except Exception as exc:
                print(f"Heartbeat failed for lease {self.lease_id}: {exc}", file=sys.stderr, flush=True)


def extract_pdf_manifest(
    pdf_path: Path,
    work: dict[str, Any],
    *,
    heartbeat: LeaseHeartbeat | None = None,
    provider: str = "slipstream",
) -> dict[str, Any]:
    started = time.time()
    model_preferences = work.get("model_preferences") if isinstance(work.get("model_preferences"), dict) else {}
    raw_text_extractor = str(model_preferences.get(MODEL_RAW_TEXT_EXTRACTION) or "marker")
    if heartbeat:
        heartbeat.beat(f"extracting text with {raw_text_extractor}")
    extracted = extract_pdf_text(pdf_path, extractor=raw_text_extractor)
    pages: list[dict[str, Any]] = []
    for page in extracted.pages:
        pages.append(
            {
                "page_number": page.page_number,
                "text": sanitize_extracted_text(page.text),
                "low_text": page.low_text,
                "text_source": page.source if not page.low_text else f"{page.source}_low_text",
            }
        )
    elapsed_ms = int((time.time() - started) * 1000)
    return {
        "idempotency_key": work["idempotency_key"],
        "result_kind": SLIPSTREAM_CAP_IMPORT_PREPROCESS,
        "current_step": "normalizing_pages",
        "document": {
            "page_count": extracted.page_count,
            "search_text": sanitize_extracted_text(extracted.full_text),
        },
        "pages": pages,
        "composition": [
            {
                "record_kind": "remote_stage",
                "stage_key": "slipstream_import_preprocess",
                "stage_label": "Slipstream import preprocessing",
                "provider": provider,
                "method": extracted.source,
                "model": raw_text_extractor,
                "status": "complete",
                "duration_ms": elapsed_ms,
                "message": extracted.fallback_reason,
                "metadata": {
                    "page_count": extracted.page_count,
                    "selected_extractor": raw_text_extractor,
                    "actual_extractor": extracted.source,
                    "fallback_reason": extracted.fallback_reason,
                    "work_kind": work.get("work_kind"),
                    "result_mode": work.get("result_mode"),
                },
            }
        ],
        "metadata": {
            "preprocess_evidence": {
                "selected_extractor": raw_text_extractor,
                "actual_extractor": extracted.source,
                "fallback_reason": extracted.fallback_reason,
                "page_count": extracted.page_count,
            }
        },
    }


def process_one_claim(
    client: SlipstreamClient,
    *,
    heartbeat_seconds: int,
    job_types: list[str],
    no_process: bool,
    prefer_performance: bool,
) -> bool:
    prefer_performance_cores(prefer_performance)
    claim = client.claim(job_types)
    lease = claim.get("lease")
    work = claim.get("work")
    lease_token = claim.get("lease_token")
    if not lease or not work or not lease_token:
        return False
    lease_id = lease["id"]
    job_id = work["job_id"]
    print(f"Claimed {work['job_type']} job {job_id} as lease {lease_id}.", flush=True)
    try:
        if no_process:
            client.heartbeat(lease_id, lease_token, "claimed without processing")
            return True
        if work["job_type"] != "import":
            client.fail(lease_id, lease_token, "This Slipstream runner only processes import preprocessing jobs.")
            return True
        artifact_path = client.work_dir / "artifacts" / f"{lease_id}.pdf"
        with LeaseHeartbeat(client, lease_id, lease_token, interval_seconds=heartbeat_seconds, initial_detail="claimed") as heartbeat:
            client.download_artifact(lease_id, lease_token, artifact_path)
            heartbeat.beat("artifact downloaded")
            manifest = extract_pdf_manifest(artifact_path, work, heartbeat=heartbeat)
            heartbeat.beat("submitting result")
            client.complete(lease_id, lease_token, manifest)
        print(f"Preprocessed import job {job_id} from {artifact_path}.", flush=True)
        return True
    except Exception as exc:
        try:
            client.fail(lease_id, lease_token, str(exc))
        except Exception as fail_exc:
            print(f"Failed to report lease failure for {lease_id}: {fail_exc}", file=sys.stderr, flush=True)
        raise


def runner_metadata(*, concurrency: int, cpuset: str | None, prefer_performance: bool) -> dict[str, Any]:
    return {
        "runner": RUNNER_NAME,
        "concurrency": concurrency,
        "cpuset": cpuset,
        "prefer_performance_cores": prefer_performance,
        "platform": platform.platform(),
        "hostname": platform.node(),
    }


def run_once(
    client: SlipstreamClient,
    *,
    version: str,
    capabilities: list[str],
    capacity: int,
    concurrency: int,
    job_types: list[str],
    no_process: bool,
    heartbeat_seconds: int,
    metadata: dict[str, Any],
    prefer_performance: bool,
) -> int:
    client.check_in(version=version, capabilities=capabilities, capacity=capacity, metadata=metadata)
    claimed = 0
    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="slipstream-worker") as executor:
        futures = [
            executor.submit(
                process_one_claim,
                client,
                heartbeat_seconds=heartbeat_seconds,
                job_types=job_types,
                no_process=no_process,
                prefer_performance=prefer_performance,
            )
            for _ in range(concurrency)
        ]
        for future in futures:
            if future.result():
                claimed += 1
    if not claimed:
        print("No Slipstream work available.", flush=True)
    return 0


def run_forever(
    client: SlipstreamClient,
    *,
    version: str,
    capabilities: list[str],
    capacity: int,
    concurrency: int,
    job_types: list[str],
    no_process: bool,
    heartbeat_seconds: int,
    poll_seconds: int,
    check_in_seconds: int,
    metadata: dict[str, Any],
    prefer_performance: bool,
) -> int:
    stop_event = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    last_check_in = 0.0
    in_flight: set[Future[bool]] = set()
    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="slipstream-worker") as executor:
        while not stop_event.is_set():
            now = time.time()
            if now - last_check_in >= check_in_seconds:
                client.check_in(version=version, capabilities=capabilities, capacity=capacity, metadata=metadata)
                last_check_in = now
            while len(in_flight) < concurrency and not stop_event.is_set():
                in_flight.add(
                    executor.submit(
                        process_one_claim,
                        client,
                        heartbeat_seconds=heartbeat_seconds,
                        job_types=job_types,
                        no_process=no_process,
                        prefer_performance=prefer_performance,
                    )
                )
            if not in_flight:
                stop_event.wait(poll_seconds)
                continue
            done, in_flight = wait(in_flight, timeout=poll_seconds, return_when=FIRST_COMPLETED)
            any_claimed = False
            for future in done:
                try:
                    any_claimed = future.result() or any_claimed
                except Exception as exc:
                    print(f"Slipstream worker task failed: {exc}", file=sys.stderr, flush=True)
            if not any_claimed and not in_flight:
                stop_event.wait(poll_seconds)
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a Medusa Slipstream remote import-preprocessing client.")
    parser.add_argument("--server", required=True, help="Central Medusa base URL, for example https://medusa.evan.engineer:3737")
    parser.add_argument("--work-dir", default="./data/slipstream-client", help="Ignored local directory for client key and downloaded artifacts.")
    parser.add_argument("--name", default="Slipstream client")
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--enroll", help="One-time enrollment token from Settings > Slipstream.")
    parser.add_argument("--capacity", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=None)
    parser.add_argument("--poll-seconds", type=int, default=5)
    parser.add_argument("--check-in-seconds", type=int, default=30)
    parser.add_argument("--heartbeat-seconds", type=int, default=20)
    parser.add_argument("--job-type", action="append", choices=["import"], default=None)
    parser.add_argument("--capability", action="append", choices=[SLIPSTREAM_CAP_IMPORT_PREPROCESS, "import"], default=None)
    parser.add_argument("--cpuset", default=os.getenv("MEDUSA_SLIPSTREAM_CPUSET"))
    parser.add_argument("--prefer-performance-cores", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--once", action="store_true", help="Check in, claim up to --concurrency jobs, then exit.")
    parser.add_argument("--no-process", action="store_true", help="Claim and heartbeat only; do not submit a result.")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS certificate verification for controlled local tests.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    work_dir = Path(args.work_dir).expanduser()
    capacity = max(1, int(args.capacity or 1))
    concurrency = max(1, int(args.concurrency or capacity))
    capabilities = args.capability or [SLIPSTREAM_CAP_IMPORT_PREPROCESS]
    job_types = args.job_type or ["import"]
    affinity_detail = apply_process_affinity(args.cpuset)
    qos_detail = prefer_performance_cores(args.prefer_performance_cores)
    for detail in (affinity_detail, qos_detail):
        if detail:
            print(detail, flush=True)
    metadata = runner_metadata(concurrency=concurrency, cpuset=args.cpuset, prefer_performance=args.prefer_performance_cores)
    if affinity_detail:
        metadata["affinity_detail"] = affinity_detail
    if qos_detail:
        metadata["qos_detail"] = qos_detail
    client = SlipstreamClient(args.server, work_dir, verify_tls=not args.insecure)
    try:
        if args.enroll:
            if client.state.get("client_id"):
                print(f"Slipstream client already enrolled as {client.state['client_id']}; skipping registration.", flush=True)
            else:
                registered = client.register(
                    enrollment_token=args.enroll,
                    name=args.name,
                    version=args.version,
                    capabilities=capabilities,
                    capacity=capacity,
                    metadata=metadata,
                )
                print(f"Registered Slipstream client {registered['name']} ({registered['id']}).", flush=True)
        if args.once:
            return run_once(
                client,
                version=args.version,
                capabilities=capabilities,
                capacity=capacity,
                concurrency=concurrency,
                job_types=job_types,
                no_process=args.no_process,
                heartbeat_seconds=args.heartbeat_seconds,
                metadata=metadata,
                prefer_performance=args.prefer_performance_cores,
            )
        return run_forever(
            client,
            version=args.version,
            capabilities=capabilities,
            capacity=capacity,
            concurrency=concurrency,
            job_types=job_types,
            no_process=args.no_process,
            heartbeat_seconds=args.heartbeat_seconds,
            poll_seconds=max(1, int(args.poll_seconds or 1)),
            check_in_seconds=max(5, int(args.check_in_seconds or 5)),
            metadata=metadata,
            prefer_performance=args.prefer_performance_cores,
        )
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
