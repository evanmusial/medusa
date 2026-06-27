from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

from app.database import init_db, session_scope
from app.services.backups import (
    backup_run_is_verified,
    create_database_backup_run,
    launch_database_backup,
    _execute_backup_run,
)
from app.models import BackupRun


def _run_payload(run: BackupRun | None) -> dict[str, Any]:
    metadata = run.backup_metadata if run and isinstance(run.backup_metadata, dict) else {}
    return {
        "id": run.id if run else None,
        "status": run.status if run else "missing",
        "phase": run.phase if run else None,
        "progress": run.progress if run else 0,
        "storage_kind": metadata.get("storage_kind"),
        "uri": metadata.get("uri") or (run.gcs_uri if run else None),
        "gcs_uri": run.gcs_uri if run else None,
        "local_path": metadata.get("local_path"),
        "sha256": run.sha256 if run else None,
        "size_bytes": run.size_bytes if run else None,
        "status_detail": run.status_detail if run else None,
        "last_error": run.last_error if run else None,
        "verified": backup_run_is_verified(run),
        "verified_at": metadata.get("verified_at"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a verified Medusa PostgreSQL backup.")
    parser.add_argument("--reason", default="manual", help="Backup reason stored on the BackupRun row.")
    parser.add_argument("--label", default=None, help="Optional visible status label.")
    parser.add_argument("--wait", action="store_true", help="Run the backup synchronously and wait for completion.")
    parser.add_argument("--timeout-seconds", type=int, default=3600, help="Maximum wait time for asynchronous mode.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a concise status line.")
    args = parser.parse_args()

    init_db()
    with session_scope() as db:
        run = create_database_backup_run(db, reason=args.reason, label=args.label)
        run_id = run.id

    if args.wait:
        _execute_backup_run(run_id)
    else:
        launch_database_backup(run_id)
        deadline = time.monotonic() + max(1, args.timeout_seconds)
        while time.monotonic() < deadline:
            with session_scope() as db:
                run = db.get(BackupRun, run_id)
                if run and run.status not in {"queued", "running"}:
                    break
            time.sleep(2)

    with session_scope() as db:
        run = db.get(BackupRun, run_id)
        payload = _run_payload(run)

    if args.json:
        print(json.dumps(payload, sort_keys=True))
    elif payload["verified"]:
        print(f"Backup verified: {payload.get('uri') or payload.get('gcs_uri') or payload.get('local_path')}")
    else:
        print(payload.get("last_error") or payload.get("status_detail") or "Backup was not verified.", file=sys.stderr)
    return 0 if payload["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
