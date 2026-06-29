#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


SCHEMA_VERSION = 1
MAX_RELEASE_HISTORY_ENTRIES = 120
DEFAULT_MAINTENANCE_WINDOW = "03:00-06:00"
DEFAULT_MAINTENANCE_TIMEZONE = "America/Indiana/Indianapolis"
DEFAULT_IDLE_GRACE_SECONDS = 300
DEPENDENCY_FILES = {
    "backend/requirements.txt",
    "frontend/package.json",
    "frontend/package-lock.json",
    "renovate.json",
}
RUNTIME_FILES = {
    "backend/Dockerfile",
    "frontend/Dockerfile",
    "docker-compose.yml",
    "docker-compose.server.yml",
    "docker-compose.metrics.yml",
}
BACKUP_REQUIRED_FILES = {
    "backend/Dockerfile",
    "docker-compose.yml",
    "docker-compose.server.yml",
    "backend/app/database.py",
    "backend/app/models.py",
    "backend/app/services/backups.py",
    "backend/app/services/restore.py",
    "backend/app/tools/database_backup.py",
    "backend/app/tools/restore_export.py",
}
BACKUP_REQUIRED_PREFIXES = ("backend/alembic/",)
DOC_PREFIXES = ("docs/",)
DOC_FILES = {"README.md", "TODO.md"}
METRICS_COMPOSE_FILE = "docker-compose.metrics.yml"
HAPROXY_CERT_FILES = (
    ("fullchain.pem", "HAProxy certificate"),
    ("privatekey.pem", "HAProxy private key"),
)
TRUTHY_VALUES = {"1", "true", "yes", "on", "enabled"}
FALSEY_VALUES = {"0", "false", "no", "off", "disabled"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_command(args: list[str], *, cwd: Path, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=str(cwd), env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"{args[0]} exited with {result.returncode}"
        raise RuntimeError(detail)
    return result


def git(repo: Path, *args: str, check: bool = True) -> str:
    result = run_command(["git", *args], cwd=repo, check=check)
    return result.stdout.strip()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temp_path.replace(path)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def resolved_data_dir(args: argparse.Namespace) -> Path:
    data_dir = args.data_dir
    if data_dir.is_absolute():
        return data_dir.resolve()
    return (args.repo.resolve() / data_dir).resolve()


def status_file_path(args: argparse.Namespace) -> Path:
    return args.status_file or resolved_data_dir(args) / "deploy" / "release-status.json"


def release_request_path(args: argparse.Namespace) -> Path:
    return args.request_file or resolved_data_dir(args) / "deploy" / "release-request.json"


def release_check_request_path(args: argparse.Namespace) -> Path:
    return resolved_data_dir(args) / "deploy" / "release-check-request.json"


def maintenance_request_path(args: argparse.Namespace) -> Path:
    return resolved_data_dir(args) / "deploy" / "maintenance-request.json"


def release_history_path(args: argparse.Namespace) -> Path:
    return args.history_file or resolved_data_dir(args) / "deploy" / "release-history.json"


def env_file_value(repo: Path, key: str) -> str | None:
    env_path = repo / ".env"
    try:
        lines = env_path.read_text().splitlines()
    except FileNotFoundError:
        return None
    prefix = f"{key}="
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or not stripped.startswith(prefix):
            continue
        return stripped[len(prefix) :].strip().strip("'\"") or None
    return None


def env_flag_value(repo: Path, key: str) -> bool | None:
    raw = os.environ.get(key)
    if raw is None:
        raw = env_file_value(repo, key)
    if raw is None:
        return None
    normalized = raw.strip().lower()
    if normalized in TRUTHY_VALUES:
        return True
    if normalized in FALSEY_VALUES:
        return False
    return None


def host_path_for_container_data_path(repo: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        try:
            relative = path.relative_to("/app/data")
        except ValueError:
            return path
        return repo / "data" / relative
    return repo / path


def metrics_overlay_enabled(repo: Path) -> bool:
    explicit = env_flag_value(repo, "MEDUSA_METRICS_OVERLAY")
    if explicit is not None:
        return explicit
    explicit = env_flag_value(repo, "MEDUSA_METRICS_ENABLED")
    if explicit is not None:
        return explicit
    if not (repo / METRICS_COMPOSE_FILE).exists():
        return False
    if os.environ.get("MEDUSA_METRICS_INTERNAL_TOKEN") or env_file_value(repo, "MEDUSA_METRICS_INTERNAL_TOKEN"):
        return True
    if os.environ.get("MEDUSA_METRICS_BEARER_TOKEN") or env_file_value(repo, "MEDUSA_METRICS_BEARER_TOKEN"):
        return True
    token_file = os.environ.get("MEDUSA_METRICS_BEARER_TOKEN_FILE") or env_file_value(repo, "MEDUSA_METRICS_BEARER_TOKEN_FILE")
    token_path = host_path_for_container_data_path(repo, token_file)
    if token_path and token_path.is_file():
        return True
    return (repo / "data" / "secrets" / "prometheus-token").is_file()


def resolved_compose_files(args: argparse.Namespace) -> list[str]:
    repo = args.repo.resolve()
    compose_files = list(args.compose_file or ["docker-compose.yml"])
    names = {Path(compose_file).name for compose_file in compose_files}
    if METRICS_COMPOSE_FILE not in names and metrics_overlay_enabled(repo):
        compose_files.append(METRICS_COMPOSE_FILE)
    return compose_files


def validate_haproxy_tls_material(repo: Path) -> None:
    cert_dir = repo / "data" / "haproxy"
    missing: list[str] = []
    for filename, label in HAPROXY_CERT_FILES:
        path = cert_dir / filename
        if not path.is_file() or path.stat().st_size <= 0:
            missing.append(f"{path} ({label})")
    if missing:
        joined = "; ".join(missing)
        raise RuntimeError(
            "HAProxy TLS material is missing; refusing to restart Compose services. "
            "Install data/haproxy/fullchain.pem and data/haproxy/privatekey.pem, then retry. "
            f"Missing: {joined}"
        )


def env_assignment(key: str, value: str) -> str:
    return f"{key}={json.dumps(value)}"


def persist_build_identity(repo: Path, target: dict[str, Any]) -> dict[str, str]:
    values = {
        "MEDUSA_BUILD_VERSION": str(target["version"]),
        "MEDUSA_BUILD_DATE": str(target["version"])[:8],
        "MEDUSA_BUILD_HASH": str(target["git_sha_short"]),
        "MEDUSA_GIT_SHA": str(target["git_sha"]),
    }
    env_path = repo / ".env"
    try:
        lines = env_path.read_text().splitlines()
    except FileNotFoundError:
        lines = []
    seen: set[str] = set()
    next_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip() if stripped and not stripped.startswith("#") and "=" in stripped else ""
        if key in values:
            next_lines.append(env_assignment(key, values[key]))
            seen.add(key)
            continue
        next_lines.append(line)
    missing = [key for key in values if key not in seen]
    if missing:
        if next_lines and next_lines[-1].strip():
            next_lines.append("")
        next_lines.append("# Medusa release identity; maintained by scripts/medusa-release-agent.py.")
        next_lines.extend(env_assignment(key, values[key]) for key in missing)
    env_path.write_text("\n".join(next_lines).rstrip() + "\n")
    return values


def current_branch(repo: Path) -> str:
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    return branch if branch != "HEAD" else "detached"


def upstream_ref(repo: Path, remote: str, branch: str, override: str | None = None) -> str:
    if override:
        return override
    configured = git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}", check=False)
    return configured or f"{remote}/{branch}"


def release_version(repo: Path, sha: str, branch: str, source: str) -> dict[str, Any]:
    commit_day = git(repo, "show", "-s", "--format=%cd", "--date=format:%Y%m%d", sha)
    committed_at = git(repo, "show", "-s", "--format=%cI", sha)
    short_sha = sha[:12]
    return {
        "version": f"{commit_day} ({short_sha})",
        "git_sha": sha,
        "git_sha_short": short_sha,
        "branch": branch,
        "built_at": committed_at,
        "source": source,
    }


def _ensure_sentence(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip()
    if not cleaned:
        return ""
    cleaned = cleaned[:1].upper() + cleaned[1:]
    return cleaned if cleaned.endswith((".", "!", "?")) else f"{cleaned}."


def _human_release_subject(subject: str) -> str:
    cleaned = re.sub(r"\s+", " ", subject).strip()
    conventional = re.match(r"^(?P<kind>[a-z]+)(?:\([^)]+\))?!?:\s*(?P<summary>.+)$", cleaned, flags=re.IGNORECASE)
    if conventional:
        cleaned = conventional.group("summary").strip()
    return cleaned


def release_changes(repo: Path, previous_sha: str, target_sha: str) -> list[dict[str, str]]:
    output = git(repo, "log", "--reverse", "--format=%H%x1f%s", f"{previous_sha}..{target_sha}", check=False)
    changes: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in output.splitlines():
        if not line.strip():
            continue
        _sha, _, subject = line.partition("\x1f")
        title = _human_release_subject(subject)
        description = _ensure_sentence(title)
        if not title or description in seen:
            continue
        seen.add(description)
        changes.append({"title": title, "description": description})
    return changes


def append_release_history(
    args: argparse.Namespace,
    *,
    previous_sha: str,
    target_sha: str,
    target: dict[str, Any],
    source: str,
    classification: dict[str, Any] | None = None,
) -> None:
    if previous_sha == target_sha:
        return
    path = release_history_path(args)
    payload = read_json(path) or {}
    entries = payload.get("entries") if isinstance(payload.get("entries"), list) else []
    if any(isinstance(entry, dict) and entry.get("git_sha") == target_sha for entry in entries):
        return
    changes = release_changes(args.repo.resolve(), previous_sha, target_sha)
    if not changes:
        changes = [{"title": "Release applied", "description": "Medusa was updated to this build."}]
    changed_files = (classification or {}).get("changed_files")
    entry = {
        "id": str(target.get("git_sha") or target_sha),
        "released_at": utc_now(),
        "commit_date": target.get("built_at"),
        "version": target.get("version"),
        "git_sha": target.get("git_sha") or target_sha,
        "git_sha_short": target.get("git_sha_short") or target_sha[:12],
        "previous_git_sha": previous_sha,
        "branch": target.get("branch"),
        "source": source,
        "summary": f"{len(changes)} change{'s' if len(changes) != 1 else ''} from {previous_sha[:12]} to {target_sha[:12]}.",
        "changes": changes,
        "changed_files": changed_files if isinstance(changed_files, list) else _changed_files(args.repo.resolve(), previous_sha, target_sha),
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": utc_now(),
        "entries": [entry, *entries][:MAX_RELEASE_HISTORY_ENTRIES],
    }
    atomic_write_json(path, payload)


def docker_host_versions(repo: Path) -> dict[str, str | None]:
    docker = run_command(["docker", "--version"], cwd=repo, check=False)
    compose = run_command(["docker", "compose", "version"], cwd=repo, check=False)
    return {
        "docker_engine_version": docker.stdout.strip() if docker.returncode == 0 else None,
        "docker_compose_version": compose.stdout.strip() if compose.returncode == 0 else None,
        "docker_host_updates": "report_only",
    }


def _changed_files(repo: Path, current_sha: str, available_sha: str) -> list[str]:
    output = git(repo, "diff", "--name-only", f"{current_sha}..{available_sha}", check=False)
    return [line.strip() for line in output.splitlines() if line.strip()]


def _commit_subjects(repo: Path, current_sha: str, available_sha: str) -> list[str]:
    output = git(repo, "log", "--format=%s", f"{current_sha}..{available_sha}", check=False)
    return [line.strip() for line in output.splitlines() if line.strip()]


def _git_show_file(repo: Path, sha: str, path: str) -> str | None:
    result = run_command(["git", "show", f"{sha}:{path}"], cwd=repo, check=False)
    return result.stdout if result.returncode == 0 else None


def _semver(value: str | None) -> tuple[int, int, int] | None:
    if not value:
        return None
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def _package_json_versions(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    versions: dict[str, str] = {}
    for section in ("dependencies", "devDependencies"):
        values = payload.get(section)
        if isinstance(values, dict):
            versions.update({str(name): str(version) for name, version in values.items()})
    return versions


def _requirements_versions(raw: str | None) -> dict[str, str]:
    versions: dict[str, str] = {}
    for line in (raw or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"([A-Za-z0-9_.-]+)\s*(?:\[.*?\])?\s*(?:==|>=|~=)\s*([0-9][^,;\s]*)", stripped)
        if match:
            versions[match.group(1).lower()] = match.group(2)
    return versions


def _versions_are_patch_only(before: dict[str, str], after: dict[str, str]) -> bool:
    changed = False
    for name, next_value in after.items():
        previous_value = before.get(name)
        if previous_value == next_value:
            continue
        previous = _semver(previous_value)
        current = _semver(next_value)
        if not previous or not current:
            return False
        if previous[:2] != current[:2] or current[2] < previous[2]:
            return False
        changed = True
    removed_or_changed = set(before) - set(after)
    return changed and not removed_or_changed


def dependency_updates_are_patch_or_security(repo: Path, current_sha: str, available_sha: str, changed_files: list[str]) -> bool:
    subjects = " ".join(_commit_subjects(repo, current_sha, available_sha)).lower()
    if re.search(r"\b(security|cve-|vulnerability|ghsa-|advisory)\b", subjects):
        return True
    checked = False
    if "frontend/package.json" in changed_files:
        before = _package_json_versions(_git_show_file(repo, current_sha, "frontend/package.json"))
        after = _package_json_versions(_git_show_file(repo, available_sha, "frontend/package.json"))
        if not _versions_are_patch_only(before, after):
            return False
        checked = True
    if "backend/requirements.txt" in changed_files:
        before = _requirements_versions(_git_show_file(repo, current_sha, "backend/requirements.txt"))
        after = _requirements_versions(_git_show_file(repo, available_sha, "backend/requirements.txt"))
        if not _versions_are_patch_only(before, after):
            return False
        checked = True
    return checked or "frontend/package-lock.json" in changed_files


def _path_requires_backup(path: str) -> bool:
    return path in BACKUP_REQUIRED_FILES or any(path.startswith(prefix) for prefix in BACKUP_REQUIRED_PREFIXES)


def backup_policy_for_update(classification: dict[str, Any]) -> dict[str, Any]:
    changed_files = [str(path) for path in classification.get("changed_files") or []]
    update_class = str(classification.get("classification") or "unknown")
    if update_class == "dirty_checkout":
        return {
            "backup_required": False,
            "backup_reason": "Maintenance is blocked by local checkout changes before backup policy applies.",
        }
    if update_class == "runtime_refresh":
        return {
            "backup_required": False,
            "backup_reason": "Same-tag runtime refreshes do not change the database or PostgreSQL version.",
        }
    if any(_path_requires_backup(path) for path in changed_files):
        return {
            "backup_required": True,
            "backup_reason": "Database schema, persistence, backup/restore, or runtime container files changed.",
        }
    if update_class == "dependency_requires_review" and "backend/requirements.txt" in changed_files:
        return {
            "backup_required": True,
            "backup_reason": "A non-patch backend dependency update can affect the running program or database tooling.",
        }
    return {
        "backup_required": False,
        "backup_reason": "No database schema, PostgreSQL/runtime image, or backup/restore surface changed.",
    }


def with_backup_policy(classification: dict[str, Any]) -> dict[str, Any]:
    return {**classification, **backup_policy_for_update(classification)}


def classify_update(repo: Path, current_sha: str, available_sha: str, dirty: bool) -> dict[str, Any]:
    if dirty:
        return with_backup_policy({
            "classification": "dirty_checkout",
            "auto_apply_eligible": False,
            "requires_approval": True,
            "changed_files": [],
            "reason": "The server checkout has local changes.",
        })
    if current_sha == available_sha:
        return with_backup_policy({
            "classification": "runtime_refresh",
            "auto_apply_eligible": True,
            "requires_approval": False,
            "changed_files": [],
            "reason": "No newer git release is available; runtime images can be refreshed from explicit tags.",
        })
    changed_files = _changed_files(repo, current_sha, available_sha)
    meaningful = [path for path in changed_files if path not in DOC_FILES and not path.startswith(DOC_PREFIXES)]
    if any(path in RUNTIME_FILES for path in meaningful):
        return with_backup_policy({
            "classification": "runtime_image_or_build_change",
            "auto_apply_eligible": False,
            "requires_approval": True,
            "changed_files": changed_files,
            "reason": "Runtime image or Docker build files changed and require explicit approval.",
        })
    if meaningful and all(path in DEPENDENCY_FILES for path in meaningful):
        auto = dependency_updates_are_patch_or_security(repo, current_sha, available_sha, meaningful)
        return with_backup_policy({
            "classification": "dependency_patch_or_security" if auto else "dependency_requires_review",
            "auto_apply_eligible": auto,
            "requires_approval": not auto,
            "changed_files": changed_files,
            "reason": "Dependency-only patch/security update." if auto else "Dependency update is not clearly patch/security-only.",
        })
    return with_backup_policy({
        "classification": "application_or_unknown_change",
        "auto_apply_eligible": False,
        "requires_approval": True,
        "changed_files": changed_files,
        "reason": "The update changes application code or an unknown surface.",
    })


def build_status(args: argparse.Namespace, *, fetch: bool, phase: str | None = None, message: str | None = None, last_error: str | None = None) -> dict[str, Any]:
    repo = args.repo.resolve()
    data_dir = resolved_data_dir(args)
    status_path = status_file_path(args)
    request_path = release_request_path(args)
    branch = current_branch(repo)
    remote = args.remote
    if fetch:
        git(repo, "fetch", "--prune", remote)
    upstream = upstream_ref(repo, remote, branch, args.upstream)
    current_sha = git(repo, "rev-parse", "HEAD")
    available_sha = git(repo, "rev-parse", upstream)
    dirty = bool(git(repo, "status", "--porcelain"))
    update_available = current_sha != available_sha
    classification = classify_update(repo, current_sha, available_sha, dirty)
    docker_versions = docker_host_versions(repo)
    request = read_json(request_path)
    default_phase = "update_available" if update_available else "current"
    if request and update_available:
        default_phase = "requested"
    if dirty and update_available:
        default_phase = "blocked"
    status_message = message
    if not status_message:
        if dirty:
            status_message = "The server checkout has local changes; automatic upgrade is blocked."
        elif update_available:
            status_message = "A newer Medusa release is available."
        else:
            status_message = "Medusa is current."
    backup_required = bool(classification["backup_required"])
    payload = {
        "schema_version": SCHEMA_VERSION,
        "checked_at": utc_now(),
        "phase": phase or default_phase,
        "message": status_message,
        "remote": remote,
        "upstream": upstream,
        "dirty": dirty,
        "update_available": update_available,
        "apply_available": bool(update_available and not dirty),
        "running": release_version(repo, current_sha, branch, "git-local"),
        "available": release_version(repo, available_sha, branch, "git-upstream"),
        "request_id": request.get("request_id") if request else None,
        "requested_at": request.get("requested_at") if request else None,
        "last_error": last_error,
        "maintenance": {
            "checked_at": utc_now(),
            "phase": "update_available" if update_available else "current",
            "message": classification["reason"],
            "update_classification": classification["classification"],
            "auto_apply_eligible": bool(classification["auto_apply_eligible"] and not dirty),
            "requires_approval": bool(classification["requires_approval"] or dirty),
            "backup_required": backup_required,
            "backup_status": "not_started" if backup_required else "not_required",
            "backup_reason": classification.get("backup_reason"),
            "backup_run_id": None,
            "changed_files": classification["changed_files"],
            "window": getattr(args, "maintenance_window", DEFAULT_MAINTENANCE_WINDOW),
            **docker_versions,
        },
    }
    atomic_write_json(status_path, payload)
    return payload


def write_phase(args: argparse.Namespace, phase: str, message: str, *, last_error: str | None = None, fetch: bool = False) -> None:
    build_status(args, fetch=fetch, phase=phase, message=message, last_error=last_error)


def update_maintenance_status(args: argparse.Namespace, phase: str, message: str, **fields: Any) -> dict[str, Any]:
    path = status_file_path(args)
    payload = read_json(path)
    if not payload:
        payload = build_status(args, fetch=False)
    maintenance = payload.get("maintenance") if isinstance(payload.get("maintenance"), dict) else {}
    backup_required = bool(fields.pop("backup_required", maintenance.get("backup_required", False)))
    backup_status = fields.pop("backup_status", maintenance.get("backup_status") or ("not_started" if backup_required else "not_required"))
    maintenance.update(
        {
            "checked_at": utc_now(),
            "phase": phase,
            "message": message,
            "backup_required": backup_required,
            "backup_status": backup_status,
            **fields,
        }
    )
    payload["maintenance"] = maintenance
    atomic_write_json(path, payload)
    return payload


def compose_base_command(args: argparse.Namespace) -> list[str]:
    command = ["docker", "compose"]
    for compose_file in resolved_compose_files(args):
        command.extend(["-f", compose_file])
    return command


def compose_exec_command(args: argparse.Namespace, service: str, command_args: list[str]) -> list[str]:
    return [*compose_base_command(args), "exec", "-T", service, *command_args]


def run_backend_json(args: argparse.Namespace, command_args: list[str]) -> dict[str, Any]:
    result = run_command(compose_exec_command(args, "backend", command_args), cwd=args.repo.resolve(), check=False)
    output = result.stdout.strip()
    payload: dict[str, Any] = {}
    if output:
        try:
            payload = json.loads(output.splitlines()[-1])
        except json.JSONDecodeError:
            payload = {}
    if result.returncode != 0:
        detail = payload.get("last_error") or payload.get("status_detail") or result.stderr.strip() or output or "backend command failed"
        raise RuntimeError(str(detail))
    return payload


def check_maintenance_readiness(args: argparse.Namespace, *, ignore_active_sessions: bool = False) -> dict[str, Any]:
    command = [
        "python",
        "-m",
        "app.tools.maintenance_readiness",
        "--idle-grace-seconds",
        str(max(1, args.idle_grace_seconds)),
        "--json",
    ]
    if ignore_active_sessions:
        command.append("--ignore-active-sessions")
    payload = run_backend_json(args, command)
    if not payload.get("idle"):
        blockers = payload.get("blockers") if isinstance(payload.get("blockers"), list) else []
        raise RuntimeError("; ".join(str(blocker) for blocker in blockers) or "Medusa is not idle.")
    return payload


def run_pre_maintenance_backup(args: argparse.Namespace, *, reason: str) -> dict[str, Any]:
    update_maintenance_status(
        args,
        "backup",
        "Creating a verified full database backup before maintenance.",
        backup_required=True,
        backup_status="running",
    )
    payload = run_backend_json(
        args,
        [
            "python",
            "-m",
            "app.tools.database_backup",
            "--reason",
            reason,
            "--label",
            "Pre-maintenance backup.",
            "--wait",
            "--json",
        ],
    )
    if not payload.get("verified"):
        raise RuntimeError(payload.get("last_error") or payload.get("status_detail") or "Pre-maintenance backup was not verified.")
    update_maintenance_status(
        args,
        "backup_complete",
        "Verified full database backup completed.",
        backup_required=True,
        backup_status="complete",
        backup_run_id=payload.get("id"),
    )
    return payload


def check(args: argparse.Namespace) -> int:
    try:
        build_status(args, fetch=not args.no_fetch)
        release_check_request_path(args).unlink(missing_ok=True)
        return 0
    except Exception as exc:
        status_path = status_file_path(args)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "checked_at": utc_now(),
            "phase": "failed",
            "message": "Release status check failed.",
            "update_available": False,
            "apply_available": False,
            "dirty": False,
            "running": {"source": "unknown"},
            "available": None,
            "last_error": str(exc),
        }
        atomic_write_json(status_path, payload)
        print(str(exc), file=sys.stderr)
        return 1


def release_healthcheck_ip(repo: Path) -> str:
    configured = os.environ.get("MEDUSA_RELEASE_HEALTHCHECK_IP") or env_file_value(repo, "MEDUSA_RELEASE_HEALTHCHECK_IP")
    if configured:
        return configured
    bind_ip = os.environ.get("MEDUSA_BIND_IP") or env_file_value(repo, "MEDUSA_BIND_IP")
    if bind_ip and bind_ip not in {"0.0.0.0", "::"}:
        return bind_ip
    bind_ipv6 = os.environ.get("MEDUSA_BIND_IPV6") or env_file_value(repo, "MEDUSA_BIND_IPV6")
    if bind_ipv6 and bind_ipv6 not in {"::", "::1"}:
        return bind_ipv6
    return "127.0.0.1"


def curl_resolve_address(address: str) -> str:
    return f"[{address}]" if ":" in address and not address.startswith("[") else address


def probe_url(repo: Path, path: str) -> tuple[list[str], str]:
    host = os.environ.get("MEDUSA_PUBLIC_HOST") or env_file_value(repo, "MEDUSA_PUBLIC_HOST") or "medusa.home.musial.io"
    address = curl_resolve_address(release_healthcheck_ip(repo))
    url = f"https://{host}:3737{path}"
    return ["curl", "-kfsS", "--connect-timeout", "5", "--max-time", "10", "--resolve", f"{host}:3737:{address}", url], url


def health_url(repo: Path) -> tuple[list[str], str]:
    return probe_url(repo, "/api/health")


def app_shell_url(repo: Path) -> tuple[list[str], str]:
    return probe_url(repo, "/")


def compose_up_command(args: argparse.Namespace, *, pull_always: bool = False) -> list[str]:
    command = compose_base_command(args)
    command.extend(["up", "-d", "--build"])
    if pull_always:
        command.extend(["--pull", "always"])
    return command


def compose_passthrough(args: argparse.Namespace) -> int:
    compose_args = list(args.compose_args)
    if compose_args and compose_args[0] == "--":
        compose_args = compose_args[1:]
    if not compose_args:
        print("No docker compose arguments supplied.", file=sys.stderr)
        return 2
    command = [*compose_base_command(args), *compose_args]
    return subprocess.run(command, cwd=str(args.repo.resolve())).returncode


def wait_for_health(repo: Path, timeout_seconds: int) -> None:
    probes = [health_url(repo), app_shell_url(repo)]
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        failures: list[str] = []
        for command, url in probes:
            result = run_command(command, cwd=repo, check=False)
            if result.returncode == 0:
                continue
            detail = result.stderr.strip() or result.stdout.strip() or f"curl exited with {result.returncode}"
            failures.append(f"{url}: {detail}")
        if not failures:
            return
        last_error = "; ".join(failures)
        time.sleep(2)
    raise RuntimeError(f"Medusa health checks did not pass: {last_error}")


def _parse_window(value: str) -> tuple[int, int, int, int]:
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})\s*", value)
    if not match:
        raise ValueError("Maintenance window must be HH:MM-HH:MM.")
    start_hour, start_minute, end_hour, end_minute = (int(part) for part in match.groups())
    if start_hour > 23 or end_hour > 23 or start_minute > 59 or end_minute > 59:
        raise ValueError("Maintenance window times are out of range.")
    return start_hour, start_minute, end_hour, end_minute


def in_maintenance_window(window: str, timezone_name: str) -> bool:
    now = datetime.now(ZoneInfo(timezone_name))
    if now.weekday() not in {1, 4}:
        return False
    start_hour, start_minute, end_hour, end_minute = _parse_window(window)
    start = now.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    end = now.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
    if end <= start:
        return now >= start or now < end
    return start <= now < end


def auto_maintenance(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    request_path = maintenance_request_path(args)
    request = read_json(request_path)
    requested = bool(request)
    force_window = bool(args.force_window or args.force or (request or {}).get("force_window"))
    ignore_active_sessions = bool(args.ignore_active_sessions or requested or (request or {}).get("ignore_active_sessions"))
    try:
        if not force_window and not in_maintenance_window(args.maintenance_window, args.maintenance_timezone):
            status = build_status(args, fetch=not args.no_fetch)
            backup_required = bool((status.get("maintenance") or {}).get("backup_required"))
            update_maintenance_status(
                args,
                "skipped",
                "Outside the configured Tuesday/Friday maintenance window.",
                window=args.maintenance_window,
                backup_required=backup_required,
                backup_status="not_started" if backup_required else "not_required",
            )
            return 0

        status = build_status(args, fetch=not args.no_fetch)
        classification = status["maintenance"]
        backup_required = bool(classification.get("backup_required"))
        backup_status = "not_started" if backup_required else "not_required"
        backup: dict[str, Any] | None = None
        validate_haproxy_tls_material(repo)
        update_maintenance_status(
            args,
            "readiness",
            "Checking idle and background-work gates before maintenance.",
            window=args.maintenance_window,
            backup_required=backup_required,
            backup_status=backup_status,
        )
        readiness = check_maintenance_readiness(args, ignore_active_sessions=ignore_active_sessions)
        if classification.get("requires_approval"):
            update_maintenance_status(
                args,
                "blocked",
                classification.get("message") or "Update requires explicit approval.",
                readiness=readiness,
                backup_required=backup_required,
                backup_status=backup_status,
            )
            return 0

        if backup_required:
            update_maintenance_status(
                args,
                "backup_required",
                "Maintenance gates passed; creating required full database backup.",
                readiness=readiness,
                backup_required=True,
                backup_status="not_started",
            )
            backup = run_pre_maintenance_backup(args, reason="pre_maintenance")
            backup_status = "complete"
        else:
            update_maintenance_status(
                args,
                "applying",
                "Maintenance gates passed; database backup is not required for this refresh.",
                readiness=readiness,
                backup_required=False,
                backup_status="not_required",
                backup_run_id=None,
            )

        branch = current_branch(repo)
        upstream = upstream_ref(repo, args.remote, branch, args.upstream)
        previous_sha = git(repo, "rev-parse", "HEAD")
        available_sha = git(repo, "rev-parse", upstream)
        applied_git_update = previous_sha != available_sha
        if applied_git_update:
            update_maintenance_status(
                args,
                "applying",
                f"Fast-forwarding auto-eligible maintenance release to {available_sha[:12]}.",
                backup_required=backup_required,
                backup_status=backup_status,
                backup_run_id=backup.get("id") if backup else None,
            )
            git(repo, "merge", "--ff-only", upstream)

        target_sha = git(repo, "rev-parse", "HEAD")
        target = release_version(repo, target_sha, branch, "git-local")
        build_identity = persist_build_identity(repo, target)
        env = os.environ.copy()
        env.update(build_identity)
        update_maintenance_status(
            args,
            "building",
            "Refreshing Medusa runtime images and rebuilding Compose services.",
            backup_required=backup_required,
            backup_status=backup_status,
            backup_run_id=backup.get("id") if backup else None,
        )
        run_command(compose_up_command(args, pull_always=True), cwd=repo, env=env)
        update_maintenance_status(
            args,
            "verifying",
            "Waiting for Medusa health after maintenance.",
            backup_required=backup_required,
            backup_status=backup_status,
            backup_run_id=backup.get("id") if backup else None,
        )
        wait_for_health(repo, args.health_timeout_seconds)
        request_path.unlink(missing_ok=True)
        payload = build_status(args, fetch=False, phase="complete", message=f"Medusa maintenance completed for {target['version']}.")
        payload["running"] = target
        payload["available"] = target
        payload["update_available"] = False
        payload["apply_available"] = False
        maintenance = payload.get("maintenance") if isinstance(payload.get("maintenance"), dict) else {}
        maintenance.update(
            {
                "phase": "complete",
                "message": (
                    "Maintenance completed after verified full database backup."
                    if backup_required
                    else "Maintenance completed; database backup was not required for this refresh."
                ),
                "backup_required": backup_required,
                "backup_status": backup_status,
                "backup_run_id": backup.get("id") if backup else None,
                "readiness": readiness,
            }
        )
        payload["maintenance"] = maintenance
        atomic_write_json(status_file_path(args), payload)
        if applied_git_update:
            append_release_history(
                args,
                previous_sha=previous_sha,
                target_sha=target_sha,
                target=target,
                source="maintenance",
                classification=classification,
            )
        return 0
    except Exception as exc:
        payload = read_json(status_file_path(args)) or {}
        maintenance = payload.get("maintenance") if isinstance(payload.get("maintenance"), dict) else {}
        backup_required = bool(maintenance.get("backup_required", False))
        update_maintenance_status(
            args,
            "failed",
            "Medusa maintenance failed.",
            last_error=str(exc),
            backup_required=backup_required,
            backup_status="failed" if backup_required else str(maintenance.get("backup_status") or "not_required"),
        )
        print(str(exc), file=sys.stderr)
        return 1


def apply(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    data_dir = resolved_data_dir(args)
    request_path = release_request_path(args)
    request = read_json(request_path)
    if not request and not args.force:
        print(f"No release request found at {request_path}.", file=sys.stderr)
        return 0
    try:
        write_phase(args, "fetching", "Fetching the latest Medusa release.", fetch=True)
        branch = current_branch(repo)
        upstream = upstream_ref(repo, args.remote, branch, args.upstream)
        current_sha = git(repo, "rev-parse", "HEAD")
        available_sha = git(repo, "rev-parse", upstream)
        dirty = bool(git(repo, "status", "--porcelain"))
        if dirty:
            raise RuntimeError("The server checkout has local changes; refusing automatic upgrade.")
        if current_sha == available_sha:
            persist_build_identity(repo, release_version(repo, current_sha, branch, "git-local"))
            write_phase(args, "complete", "Medusa was already current.")
            request_path.unlink(missing_ok=True)
            return 0
        classification = classify_update(repo, current_sha, available_sha, dirty=False)
        backup_required = bool(classification.get("backup_required"))
        backup_status = "not_started" if backup_required else "not_required"
        backup: dict[str, Any] | None = None
        validate_haproxy_tls_material(repo)
        update_maintenance_status(
            args,
            "readiness",
            "Checking maintenance readiness before upgrade.",
            backup_required=backup_required,
            backup_status=backup_status,
            backup_reason=classification.get("backup_reason"),
            changed_files=classification.get("changed_files"),
            update_classification=classification.get("classification"),
        )
        readiness = check_maintenance_readiness(args, ignore_active_sessions=True)
        if backup_required:
            update_maintenance_status(
                args,
                "backup_required",
                "Medusa is ready for approved upgrade; creating required backup.",
                readiness=readiness,
                backup_required=True,
                backup_status="not_started",
            )
            backup = run_pre_maintenance_backup(args, reason="pre_upgrade")
            backup_status = "complete"
        else:
            update_maintenance_status(
                args,
                "applying",
                "Medusa is ready for approved upgrade; database backup is not required for this update.",
                readiness=readiness,
                backup_required=False,
                backup_status="not_required",
                backup_run_id=None,
            )
        write_phase(args, "applying", f"Fast-forwarding to {available_sha[:12]}.")
        git(repo, "merge", "--ff-only", upstream)
        target_sha = git(repo, "rev-parse", "HEAD")
        target = release_version(repo, target_sha, branch, "git-local")
        build_identity = persist_build_identity(repo, target)
        env = os.environ.copy()
        env.update(build_identity)
        write_phase(args, "building", f"Building Medusa {target['version']}.")
        update_maintenance_status(
            args,
            "building",
            (
                f"Building Medusa {target['version']} after verified backup."
                if backup_required
                else f"Building Medusa {target['version']} without a database backup; none required by policy."
            ),
            backup_required=backup_required,
            backup_status=backup_status,
            backup_run_id=backup.get("id") if backup else None,
        )
        run_command(compose_up_command(args, pull_always=args.pull_always), cwd=repo, env=env)
        write_phase(args, "verifying", "Waiting for Medusa health after upgrade.")
        wait_for_health(repo, args.health_timeout_seconds)
        payload = build_status(args, fetch=False, phase="complete", message=f"Medusa upgraded to {target['version']}.")
        payload["running"] = target
        payload["available"] = target
        payload["update_available"] = False
        payload["apply_available"] = False
        maintenance = payload.get("maintenance") if isinstance(payload.get("maintenance"), dict) else {}
        maintenance.update(
            {
                "phase": "complete",
                "message": (
                    f"Medusa upgraded to {target['version']} after verified backup."
                    if backup_required
                    else f"Medusa upgraded to {target['version']}; database backup was not required."
                ),
                "backup_required": backup_required,
                "backup_status": backup_status,
                "backup_run_id": backup.get("id") if backup else None,
            }
        )
        payload["maintenance"] = maintenance
        atomic_write_json(status_file_path(args), payload)
        append_release_history(
            args,
            previous_sha=current_sha,
            target_sha=target_sha,
            target=target,
            source="upgrade",
            classification=classification,
        )
        request_path.unlink(missing_ok=True)
        return 0
    except Exception as exc:
        payload = read_json(status_file_path(args)) or {}
        maintenance = payload.get("maintenance") if isinstance(payload.get("maintenance"), dict) else {}
        backup_required = bool(maintenance.get("backup_required", False))
        update_maintenance_status(
            args,
            "failed",
            "Medusa upgrade failed.",
            last_error=str(exc),
            backup_required=backup_required,
            backup_status="failed" if backup_required else str(maintenance.get("backup_status") or "not_required"),
        )
        write_phase(args, "failed", "Medusa upgrade failed.", last_error=str(exc), fetch=False)
        print(str(exc), file=sys.stderr)
        return 1


def parser() -> argparse.ArgumentParser:
    base = argparse.ArgumentParser(description="Medusa host-side release status and upgrade agent.")
    subcommands = base.add_subparsers(dest="command", required=True)
    for name in ("check", "apply", "auto-maintenance", "compose"):
        command = subcommands.add_parser(name)
        command.add_argument("--repo", type=Path, default=Path.cwd(), help="Medusa checkout path.")
        command.add_argument("--data-dir", type=Path, default=Path("data"), help="Medusa ignored data directory.")
        command.add_argument("--status-file", type=Path, default=None, help="Release status JSON path.")
        command.add_argument("--request-file", type=Path, default=None, help="Release request JSON path.")
        command.add_argument("--history-file", type=Path, default=None, help="Release history JSON path.")
        command.add_argument("--remote", default="origin", help="Git remote to fetch.")
        command.add_argument("--upstream", default=None, help="Git ref to compare/apply, overriding @{upstream}.")
        command.add_argument(
            "--compose-file",
            action="append",
            default=None,
            help="Compose file to include for apply; repeat for overrides. Defaults to docker-compose.yml.",
        )
    subcommands.choices["compose"].add_argument("compose_args", nargs=argparse.REMAINDER, help="Arguments passed through to docker compose.")
    subcommands.choices["check"].add_argument("--no-fetch", action="store_true", help="Do not fetch before checking.")
    subcommands.choices["apply"].add_argument("--force", action="store_true", help="Apply even when no request file exists.")
    subcommands.choices["apply"].add_argument("--health-timeout-seconds", type=int, default=120)
    subcommands.choices["apply"].add_argument("--idle-grace-seconds", type=int, default=DEFAULT_IDLE_GRACE_SECONDS)
    subcommands.choices["apply"].add_argument("--pull-always", action="store_true", help="Pull explicit image tags while rebuilding.")
    subcommands.choices["auto-maintenance"].add_argument("--no-fetch", action="store_true", help="Do not fetch before checking.")
    subcommands.choices["auto-maintenance"].add_argument("--force", action="store_true", help="Run even when no request file exists and outside the window.")
    subcommands.choices["auto-maintenance"].add_argument("--force-window", action="store_true", help="Ignore the configured quiet window.")
    subcommands.choices["auto-maintenance"].add_argument("--ignore-active-sessions", action="store_true", help="Ignore active browser sessions but not active work.")
    subcommands.choices["auto-maintenance"].add_argument("--idle-grace-seconds", type=int, default=DEFAULT_IDLE_GRACE_SECONDS)
    subcommands.choices["auto-maintenance"].add_argument("--maintenance-window", default=DEFAULT_MAINTENANCE_WINDOW)
    subcommands.choices["auto-maintenance"].add_argument("--maintenance-timezone", default=DEFAULT_MAINTENANCE_TIMEZONE)
    subcommands.choices["auto-maintenance"].add_argument("--health-timeout-seconds", type=int, default=120)
    return base


def main() -> int:
    args = parser().parse_args()
    if args.command == "compose":
        return compose_passthrough(args)
    if args.command == "check":
        return check(args)
    if args.command == "apply":
        return apply(args)
    if args.command == "auto-maintenance":
        return auto_maintenance(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
