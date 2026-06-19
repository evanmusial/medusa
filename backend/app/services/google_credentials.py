from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings


GOOGLE_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
SERVICE_ACCOUNT_NONE_LABEL = "None, please upload a service account JSON"


def managed_google_service_account_path(settings: Settings | None = None) -> Path:
    active_settings = settings or get_settings()
    return active_settings.data_dir / "managed-secrets" / "google-service-account.json"


def parse_service_account_json(content: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Uploaded file is not valid service account JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Uploaded file must contain a service account JSON object.")
    if payload.get("type") != "service_account":
        raise ValueError("Uploaded JSON is not a Google service account key.")
    client_email = str(payload.get("client_email") or "").strip()
    private_key = str(payload.get("private_key") or "").strip()
    project_id = str(payload.get("project_id") or "").strip()
    if not client_email or not private_key:
        raise ValueError("Service account JSON must include client_email and private_key.")
    return {
        "display_name": client_email,
        "project_id": project_id or None,
        "payload": payload,
    }


def service_account_summary_from_file(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_file():
        return None
    try:
        parsed = parse_service_account_json(candidate.read_bytes())
    except ValueError:
        return None
    return {
        "display_name": parsed["display_name"],
        "project_id": parsed["project_id"],
        "path": str(candidate),
    }


def store_managed_service_account_json(content: bytes, uploaded_filename: str | None = None) -> dict[str, Any]:
    parsed = parse_service_account_json(content)
    target = managed_google_service_account_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(target.parent, 0o700)
    temp_path = target.with_suffix(".json.tmp")
    fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(parsed["payload"], handle, indent=2)
            handle.write("\n")
        os.replace(temp_path, target)
        os.chmod(target, 0o600)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return {
        "display_name": parsed["display_name"],
        "project_id": parsed["project_id"],
        "path": str(target),
        "uploaded_filename": uploaded_filename or "service-account.json",
    }


def load_service_account_credentials(path: str | Path):
    from google.oauth2 import service_account

    return service_account.Credentials.from_service_account_file(
        str(path),
        scopes=[GOOGLE_CLOUD_PLATFORM_SCOPE],
    )
