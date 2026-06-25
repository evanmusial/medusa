#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


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


def build_status(args: argparse.Namespace, *, fetch: bool, phase: str | None = None, message: str | None = None, last_error: str | None = None) -> dict[str, Any]:
    repo = args.repo.resolve()
    data_dir = resolved_data_dir(args)
    status_path = args.status_file or data_dir / "deploy" / "release-status.json"
    request_path = args.request_file or data_dir / "deploy" / "release-request.json"
    branch = current_branch(repo)
    remote = args.remote
    if fetch:
        git(repo, "fetch", "--prune", remote)
    upstream = upstream_ref(repo, remote, branch, args.upstream)
    current_sha = git(repo, "rev-parse", "HEAD")
    available_sha = git(repo, "rev-parse", upstream)
    dirty = bool(git(repo, "status", "--porcelain"))
    update_available = current_sha != available_sha
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
    }
    atomic_write_json(status_path, payload)
    return payload


def write_phase(args: argparse.Namespace, phase: str, message: str, *, last_error: str | None = None, fetch: bool = False) -> None:
    build_status(args, fetch=fetch, phase=phase, message=message, last_error=last_error)


def check(args: argparse.Namespace) -> int:
    try:
        build_status(args, fetch=not args.no_fetch)
        return 0
    except Exception as exc:
        status_path = args.status_file or resolved_data_dir(args) / "deploy" / "release-status.json"
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


def health_url(repo: Path) -> tuple[list[str], str]:
    host = os.environ.get("MEDUSA_PUBLIC_HOST") or env_file_value(repo, "MEDUSA_PUBLIC_HOST") or "medusa.home.musial.io"
    url = f"https://{host}:3737/api/health"
    return ["curl", "-kfsS", "--resolve", f"{host}:3737:127.0.0.1", url], url


def wait_for_health(repo: Path, timeout_seconds: int) -> None:
    command, url = health_url(repo)
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        result = run_command(command, cwd=repo, check=False)
        if result.returncode == 0:
            return
        last_error = result.stderr.strip() or result.stdout.strip()
        time.sleep(2)
    raise RuntimeError(f"Medusa health check did not pass at {url}: {last_error}")


def apply(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    data_dir = resolved_data_dir(args)
    request_path = args.request_file or data_dir / "deploy" / "release-request.json"
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
            write_phase(args, "complete", "Medusa was already current.")
            request_path.unlink(missing_ok=True)
            return 0
        write_phase(args, "applying", f"Fast-forwarding to {available_sha[:12]}.")
        git(repo, "merge", "--ff-only", upstream)
        target_sha = git(repo, "rev-parse", "HEAD")
        target = release_version(repo, target_sha, branch, "git-local")
        env = os.environ.copy()
        env.update(
            {
                "MEDUSA_BUILD_VERSION": target["version"],
                "MEDUSA_BUILD_DATE": target["version"][:8],
                "MEDUSA_BUILD_HASH": target["git_sha_short"],
                "MEDUSA_GIT_SHA": target_sha,
            }
        )
        write_phase(args, "building", f"Building Medusa {target['version']}.")
        run_command(["docker", "compose", "up", "-d", "--build"], cwd=repo, env=env)
        write_phase(args, "verifying", "Waiting for Medusa health after upgrade.")
        wait_for_health(repo, args.health_timeout_seconds)
        request_path.unlink(missing_ok=True)
        payload = build_status(args, fetch=False, phase="complete", message=f"Medusa upgraded to {target['version']}.")
        payload["running"] = target
        payload["available"] = target
        payload["update_available"] = False
        payload["apply_available"] = False
        atomic_write_json(args.status_file or data_dir / "deploy" / "release-status.json", payload)
        return 0
    except Exception as exc:
        write_phase(args, "failed", "Medusa upgrade failed.", last_error=str(exc), fetch=False)
        print(str(exc), file=sys.stderr)
        return 1


def parser() -> argparse.ArgumentParser:
    base = argparse.ArgumentParser(description="Medusa host-side release status and upgrade agent.")
    subcommands = base.add_subparsers(dest="command", required=True)
    for name in ("check", "apply"):
        command = subcommands.add_parser(name)
        command.add_argument("--repo", type=Path, default=Path.cwd(), help="Medusa checkout path.")
        command.add_argument("--data-dir", type=Path, default=Path("data"), help="Medusa ignored data directory.")
        command.add_argument("--status-file", type=Path, default=None, help="Release status JSON path.")
        command.add_argument("--request-file", type=Path, default=None, help="Release request JSON path.")
        command.add_argument("--remote", default="origin", help="Git remote to fetch.")
        command.add_argument("--upstream", default=None, help="Git ref to compare/apply, overriding @{upstream}.")
    subcommands.choices["check"].add_argument("--no-fetch", action="store_true", help="Do not fetch before checking.")
    subcommands.choices["apply"].add_argument("--force", action="store_true", help="Apply even when no request file exists.")
    subcommands.choices["apply"].add_argument("--health-timeout-seconds", type=int, default=120)
    return base


def main() -> int:
    args = parser().parse_args()
    if args.command == "check":
        return check(args)
    if args.command == "apply":
        return apply(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
