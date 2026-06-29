from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.schemas import ReleaseHistoryChangeOut, ReleaseHistoryEntryOut, ReleaseHistoryOut, ReleaseStatusOut, ReleaseVersionOut
from app.services.maintenance import DEFAULT_IDLE_GRACE_SECONDS, maintenance_readiness


STATUS_SCHEMA_VERSION = 1
RELEASE_RELOAD_PROMPT_PHASES = {"requested", "fetching", "applying", "building", "restarting", "verifying", "reload_ready"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _release_status_path() -> Path:
    settings = get_settings()
    return settings.release_status_path or settings.data_dir / "deploy" / "release-status.json"


def _release_request_path() -> Path:
    settings = get_settings()
    return settings.release_request_path or settings.data_dir / "deploy" / "release-request.json"


def _release_check_request_path() -> Path:
    return get_settings().data_dir / "deploy" / "release-check-request.json"


def _release_history_path() -> Path:
    return get_settings().data_dir / "deploy" / "release-history.json"


def _maintenance_request_path() -> Path:
    return get_settings().data_dir / "deploy" / "maintenance-request.json"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temp_path.replace(path)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _version_from_payload(value: Any, *, fallback_source: str = "status-file") -> ReleaseVersionOut | None:
    if not isinstance(value, dict):
        return None
    git_sha = value.get("git_sha")
    git_sha = git_sha if isinstance(git_sha, str) and git_sha else None
    git_sha_short = value.get("git_sha_short")
    git_sha_short = git_sha_short if isinstance(git_sha_short, str) and git_sha_short else (git_sha[:12] if git_sha else None)
    version = value.get("version")
    version = version if isinstance(version, str) and version else None
    branch = value.get("branch")
    branch = branch if isinstance(branch, str) and branch else None
    built_at = value.get("built_at") or value.get("commit_date")
    built_at = built_at if isinstance(built_at, str) and built_at else None
    source = value.get("source")
    source = source if isinstance(source, str) and source else fallback_source
    if not any([version, git_sha, branch, built_at]):
        return None
    return ReleaseVersionOut(
        version=version,
        git_sha=git_sha,
        git_sha_short=git_sha_short,
        branch=branch,
        built_at=built_at,
        source=source,
    )


def _history_change_from_payload(value: Any) -> ReleaseHistoryChangeOut | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return ReleaseHistoryChangeOut(title=cleaned, description=cleaned) if cleaned else None
    if not isinstance(value, dict):
        return None
    title = value.get("title")
    description = value.get("description")
    title = title.strip() if isinstance(title, str) else ""
    description = description.strip() if isinstance(description, str) else ""
    if not title and description:
        title = description
    if not description and title:
        description = title
    if not title or not description:
        return None
    return ReleaseHistoryChangeOut(title=title, description=description)


def _history_entry_from_payload(value: Any) -> ReleaseHistoryEntryOut | None:
    if not isinstance(value, dict):
        return None
    git_sha = value.get("git_sha")
    git_sha = git_sha if isinstance(git_sha, str) and git_sha else None
    git_sha_short = value.get("git_sha_short")
    git_sha_short = git_sha_short if isinstance(git_sha_short, str) and git_sha_short else (git_sha[:12] if git_sha else None)
    version = value.get("version")
    version = version if isinstance(version, str) and version else None
    if not git_sha and not version:
        return None
    released_at = _parse_datetime(value.get("released_at")) or _parse_datetime(value.get("recorded_at")) or _now()
    commit_date = _parse_datetime(value.get("commit_date")) or _parse_datetime(value.get("built_at"))
    changes_raw = value.get("changes")
    changes = [
        change
        for change in (_history_change_from_payload(item) for item in (changes_raw if isinstance(changes_raw, list) else []))
        if change is not None
    ]
    changed_files = value.get("changed_files")
    previous_git_sha = value.get("previous_git_sha")
    branch = value.get("branch")
    source = value.get("source")
    summary = value.get("summary")
    return ReleaseHistoryEntryOut(
        id=str(value.get("id") or git_sha or version),
        released_at=released_at,
        commit_date=commit_date,
        version=version,
        git_sha=git_sha,
        git_sha_short=git_sha_short,
        previous_git_sha=previous_git_sha if isinstance(previous_git_sha, str) and previous_git_sha else None,
        branch=branch if isinstance(branch, str) and branch else None,
        source=source if isinstance(source, str) and source else "release-agent",
        summary=summary if isinstance(summary, str) and summary else None,
        changes=changes,
        changed_files=[str(path) for path in changed_files] if isinstance(changed_files, list) else [],
    )


def release_history() -> ReleaseHistoryOut:
    payload = _read_json(_release_history_path())
    entries_raw = payload.get("entries") if payload else []
    entries = [
        entry
        for entry in (_history_entry_from_payload(item) for item in (entries_raw if isinstance(entries_raw, list) else []))
        if entry is not None
    ]
    entries.sort(key=lambda entry: entry.released_at, reverse=True)
    updated_at = _parse_datetime(payload.get("updated_at") if payload else None)
    if updated_at is None and entries:
        updated_at = entries[0].released_at
    return ReleaseHistoryOut(updated_at=updated_at, entries=entries)


def _runtime_version() -> ReleaseVersionOut:
    settings = get_settings()
    git_sha = (settings.git_sha or "").strip() or None
    git_sha_short = git_sha[:12] if git_sha else None
    build_version = (settings.build_version or "").strip()
    if not build_version and settings.build_date and settings.build_hash:
        build_version = f"{settings.build_date.strip()} ({settings.build_hash.strip()[:12]})"
    return ReleaseVersionOut(
        version=build_version or None,
        git_sha=git_sha,
        git_sha_short=git_sha_short,
        branch=None,
        built_at=None,
        source="runtime-env" if build_version or git_sha else "runtime-default",
    )


def _version_has_runtime_identity(version: ReleaseVersionOut) -> bool:
    return version.source != "runtime-default" and bool(version.version or version.git_sha)


def _versions_match(left: ReleaseVersionOut | None, right: ReleaseVersionOut | None) -> bool:
    if not left or not right:
        return False
    if left.git_sha and right.git_sha:
        return left.git_sha == right.git_sha
    if left.version and right.version:
        return left.version == right.version
    if left.git_sha_short and right.git_sha_short:
        return left.git_sha_short == right.git_sha_short
    return False


def _request_summary() -> tuple[datetime | None, str | None]:
    payload = _read_json(_release_request_path())
    return _request_summary_from_payload(payload)


def _request_summary_from_payload(payload: dict[str, Any] | None) -> tuple[datetime | None, str | None]:
    if not payload:
        return None, None
    request_id = payload.get("request_id")
    return _parse_datetime(payload.get("requested_at")), request_id if isinstance(request_id, str) else None


def release_status(client_version: str | None = None, db: Session | None = None) -> ReleaseStatusOut:
    status_path = _release_status_path()
    payload = _read_json(status_path)
    request_path = _release_request_path()
    request_exists = request_path.exists()
    maintenance_request_exists = _maintenance_request_path().exists()
    requested_at, request_id = _request_summary()
    if requested_at is None and request_id is None:
        requested_at, request_id = _request_summary_from_payload(payload)

    runtime = _runtime_version()
    status_running = _version_from_payload(payload.get("running") if payload else None) if payload else None
    status_running_stale = bool(
        status_running and _version_has_runtime_identity(runtime) and not _versions_match(status_running, runtime)
    )
    # The status file can outlive a container rebuild; browser reload decisions must use the real runtime.
    running = runtime if status_running_stale else status_running or runtime
    available = _version_from_payload(payload.get("available") if payload else None) if payload else None

    checked_at = _parse_datetime(payload.get("checked_at") if payload else None) or _now()
    dirty = bool(payload.get("dirty")) if payload else False
    raw_update_available = payload.get("update_available") if payload else None
    if status_running_stale:
        dirty = False
        if raw_update_available is False:
            available = running
    if available and _versions_match(running, available):
        update_available = False
    elif isinstance(raw_update_available, bool):
        update_available = raw_update_available
    elif available and running.git_sha and available.git_sha:
        update_available = running.git_sha != available.git_sha
    elif available and running.version and available.version:
        update_available = running.version != available.version
    else:
        update_available = False

    raw_apply_available = payload.get("apply_available") if payload else None
    apply_available = bool(raw_apply_available) and update_available and not dirty
    raw_phase = payload.get("phase") if payload else None
    phase = raw_phase if isinstance(raw_phase, str) and raw_phase else "current"
    if not update_available and phase == "update_available":
        phase = "current"
    if request_exists and phase in {"current", "update_available"}:
        phase = "requested"

    raw_message = payload.get("message") if payload else None
    message = raw_message if isinstance(raw_message, str) and raw_message else "Release status has not been checked by the host agent yet."
    if status_running_stale and not update_available and phase in {"current", "blocked"}:
        phase = "current"
        message = "Medusa is current."
    last_error = payload.get("last_error") if payload else None
    last_error = last_error if isinstance(last_error, str) and last_error else None

    maintenance = payload.get("maintenance") if payload else None
    maintenance = maintenance if isinstance(maintenance, dict) else {}
    readiness = maintenance.get("readiness") if isinstance(maintenance.get("readiness"), dict) else {}
    if db is not None:
        try:
            readiness = maintenance_readiness(
                db,
                idle_grace_seconds=int(maintenance.get("idle_grace_seconds") or DEFAULT_IDLE_GRACE_SECONDS),
            )
        except Exception:
            readiness = readiness or {}
    maintenance_blockers = readiness.get("blockers") if isinstance(readiness.get("blockers"), list) else []
    maintenance_last_checked_at = _parse_datetime(maintenance.get("checked_at"))
    maintenance_phase = str(maintenance.get("phase") or "idle")
    if maintenance_request_exists and maintenance_phase in {"idle", "current", "skipped", "blocked"}:
        maintenance_phase = "requested"

    normalized_client_version = (client_version or "").strip()
    release_reload_prompt_active = bool(request_exists or requested_at or request_id or phase in RELEASE_RELOAD_PROMPT_PHASES)
    browser_reload_recommended = bool(
        normalized_client_version
        and not update_available
        and running.version
        and normalized_client_version != running.version
        and running.source != "runtime-default"
        and release_reload_prompt_active
    )
    if browser_reload_recommended and not update_available and phase == "current":
        message = "A newer Medusa build is already running. Reload the browser to use it."
        phase = "reload_ready"

    maintenance_backup_required = bool(maintenance.get("backup_required", False))
    maintenance_backup_status = str(
        maintenance.get("backup_status") or ("not_started" if maintenance_backup_required else "not_required")
    )

    return ReleaseStatusOut(
        checked_at=checked_at,
        running=running,
        available=available,
        update_available=update_available,
        apply_available=apply_available,
        browser_reload_recommended=browser_reload_recommended,
        phase=phase,
        message=message,
        status_source=str(status_path),
        requested_at=requested_at,
        request_id=request_id,
        last_error=last_error,
        dirty=dirty,
        maintenance_phase=maintenance_phase,
        maintenance_message=maintenance.get("message") if isinstance(maintenance.get("message"), str) else None,
        maintenance_auto_apply_eligible=bool(maintenance.get("auto_apply_eligible")),
        maintenance_requires_approval=bool(maintenance.get("requires_approval")),
        maintenance_update_classification=str(maintenance.get("update_classification") or "unknown"),
        maintenance_backup_required=maintenance_backup_required,
        maintenance_backup_status=maintenance_backup_status,
        maintenance_backup_run_id=maintenance.get("backup_run_id") if isinstance(maintenance.get("backup_run_id"), str) else None,
        maintenance_idle=bool(readiness.get("idle", True)),
        maintenance_active_session_count=int(readiness.get("active_session_count") or 0),
        maintenance_blockers=[str(blocker) for blocker in maintenance_blockers],
        maintenance_window=maintenance.get("window") if isinstance(maintenance.get("window"), str) else None,
        maintenance_last_checked_at=maintenance_last_checked_at,
        docker_engine_version=maintenance.get("docker_engine_version") if isinstance(maintenance.get("docker_engine_version"), str) else None,
        docker_compose_version=maintenance.get("docker_compose_version") if isinstance(maintenance.get("docker_compose_version"), str) else None,
        docker_host_updates=str(maintenance.get("docker_host_updates") or "report_only"),
    )


def request_release_upgrade(client_version: str | None = None, requested_by: str | None = None) -> ReleaseStatusOut:
    status = release_status(client_version=client_version)
    if status.browser_reload_recommended:
        return status
    if not status.update_available:
        raise ValueError("No newer Medusa release is available.")
    if not status.apply_available:
        raise RuntimeError(status.last_error or "Medusa release upgrade requests are not available in this runtime.")
    request_id = secrets.token_urlsafe(12)
    payload = {
        "schema_version": STATUS_SCHEMA_VERSION,
        "request_id": request_id,
        "requested_at": _now().isoformat(),
        "requested_by": requested_by,
        "client_version": (client_version or "").strip() or None,
        "target": status.available.model_dump() if status.available else None,
    }
    _atomic_write_json(_release_request_path(), payload)
    return release_status(client_version=client_version)


def request_release_check(client_version: str | None = None, requested_by: str | None = None) -> ReleaseStatusOut:
    payload = {
        "schema_version": STATUS_SCHEMA_VERSION,
        "request_id": secrets.token_urlsafe(12),
        "requested_at": _now().isoformat(),
        "requested_by": requested_by,
        "client_version": (client_version or "").strip() or None,
    }
    _atomic_write_json(_release_check_request_path(), payload)
    return release_status(client_version=client_version)


def request_maintenance_run(client_version: str | None = None, requested_by: str | None = None) -> ReleaseStatusOut:
    payload = {
        "schema_version": STATUS_SCHEMA_VERSION,
        "request_id": secrets.token_urlsafe(12),
        "requested_at": _now().isoformat(),
        "requested_by": requested_by,
        "client_version": (client_version or "").strip() or None,
        "ignore_active_sessions": True,
        "force_window": True,
        "source": "user_approved",
    }
    _atomic_write_json(_maintenance_request_path(), payload)
    return release_status(client_version=client_version)
