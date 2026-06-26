#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ACTIVE_IMPORT_STATUSES = "'staged','queued','running','restored_paused'"
ACTIVE_JOB_STATUSES = "'queued','running'"
ACTIVE_BACKUP_STATUSES = "'queued','running'"
SECRET_KEYS = {
    "GEMINI_API_KEY",
    "MEDUSA_PASSWORD",
    "OPENAI_API_KEY",
    "SEMANTIC_SCHOLAR_API_KEY",
}


def run_command(args: list[str], *, cwd: Path, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check)


def status(label: str, state: str, detail: str = "") -> None:
    suffix = f" - {detail}" if detail else ""
    print(f"[{state}] {label}{suffix}")


def repo_default() -> Path:
    return Path(__file__).resolve().parents[1]


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError:
        return values
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def path_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for root, _dirs, files in os.walk(path):
        for filename in files:
            candidate = Path(root) / filename
            try:
                total += candidate.stat().st_size
            except OSError:
                continue
    return total


def report_path(path: Path, label: str, *, required: bool = False) -> None:
    if path.exists():
        detail = human_size(path_size(path)) if path.is_dir() else human_size(path.stat().st_size)
        status(label, "OK", f"{path} ({detail})")
    elif required:
        status(label, "MISSING", str(path))
    else:
        status(label, "WARN", f"{path} is not present")


def docker_compose_available(repo: Path) -> bool:
    result = run_command(["docker", "compose", "version"], cwd=repo)
    if result.returncode == 0:
        status("Docker Compose", "OK", result.stdout.strip())
        return True
    detail = result.stderr.strip() or result.stdout.strip() or "docker compose is unavailable"
    status("Docker Compose", "WARN", detail)
    return False


def psql(repo: Path, sql: str) -> str | None:
    result = run_command(
        ["docker", "compose", "exec", "-T", "db", "psql", "-U", "medusa", "-d", "medusa", "-Atc", sql],
        cwd=repo,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def report_database_state(repo: Path) -> None:
    if not docker_compose_available(repo):
        status("Database state", "WARN", "skipped because Docker Compose is unavailable")
        return
    version = psql(repo, "select version();")
    if not version:
        status("Database state", "WARN", "PostgreSQL container is not reachable; start Medusa for live DB checks")
        return
    status("Database state", "OK", version.splitlines()[0])
    db_size = psql(repo, "select pg_size_pretty(pg_database_size(current_database()));")
    if db_size:
        status("PostgreSQL database size", "INFO", db_size)
    checks = [
        ("Active import jobs", f"select count(*) from import_jobs where status in ({ACTIVE_IMPORT_STATUSES});"),
        ("Active Concordance jobs", f"select count(*) from concordance_jobs where status in ({ACTIVE_JOB_STATUSES});"),
        ("Active accessory summaries", f"select count(*) from document_accessory_summaries where status in ({ACTIVE_JOB_STATUSES});"),
        ("Active backup/restore runs", f"select count(*) from backup_runs where status in ({ACTIVE_BACKUP_STATUSES});"),
    ]
    for label, sql in checks:
        value = psql(repo, sql)
        if value is None:
            status(label, "WARN", "query failed")
            continue
        state = "OK" if value == "0" else "WARN"
        status(label, state, value)
    latest_backup = psql(
        repo,
        """
        select coalesce(filename, '') || '|' || coalesce(gcs_uri, '') || '|' || coalesce(sha256, '') || '|' || coalesce(completed_at::text, '')
        from backup_runs
        where kind = 'backup' and status = 'complete' and gcs_uri is not null and sha256 is not null
        order by completed_at desc nulls last, created_at desc
        limit 1;
        """,
    )
    if latest_backup:
        filename, gcs_uri, sha256, completed_at = (latest_backup.split("|") + ["", "", "", ""])[:4]
        status("Latest verified full DB backup", "OK", f"{filename or gcs_uri} completed {completed_at}; sha256 {sha256[:12]}...")
    else:
        status("Latest verified full DB backup", "WARN", "no complete GCS backup with checksum was found in backup_runs")


def report_env(repo: Path) -> None:
    env_path = repo / ".env"
    values = read_env(env_path)
    if not values:
        status(".env", "MISSING", str(env_path))
        return
    status(".env", "OK", str(env_path))
    important_keys = [
        "MEDUSA_PUBLIC_HOST",
        "MEDUSA_ALLOWED_HOSTS",
        "MEDUSA_DOCUMENT_CACHE_SIZE_MB",
        "MEDUSA_IMPORT_WORKER_CONCURRENCY",
        "GCS_BUCKET",
        "GCS_PREFIX",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "OPENAI_API_KEY",
    ]
    for key in important_keys:
        value = values.get(key, "")
        if not value:
            status(f"Env {key}", "WARN", "not set")
        elif key in SECRET_KEYS:
            status(f"Env {key}", "OK", "set")
        else:
            status(f"Env {key}", "INFO", value)
    credentials = values.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if credentials.startswith("/app/data/secrets/"):
        host_path = repo / "data" / "secrets" / credentials.removeprefix("/app/data/secrets/")
        report_path(host_path, "Google service-account file")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit local Medusa state before moving to another host.")
    parser.add_argument("--repo", type=Path, default=repo_default(), help="Medusa repository path.")
    args = parser.parse_args()
    repo = args.repo.resolve()
    if not (repo / "docker-compose.yml").exists():
        print(f"{repo} does not look like a Medusa checkout.", file=sys.stderr)
        return 2

    print(f"Medusa portability audit for {repo}")
    print("")
    report_env(repo)
    print("")
    report_path(repo / "data" / "secrets", "Secrets directory", required=True)
    report_path(repo / "data" / "managed-secrets", "Managed secrets directory")
    report_path(repo / "data" / "haproxy" / "fullchain.pem", "HAProxy certificate", required=True)
    report_path(repo / "data" / "haproxy" / "privatekey.pem", "HAProxy private key", required=True)
    report_path(repo / "data" / "originals", "Local originals directory")
    report_path(repo / "data" / "processing-cache", "Processing cache")
    report_path(repo / "data" / "model-cache", "Model cache")
    report_path(repo / "data", "Total ignored data directory")
    print("")
    report_database_state(repo)
    print("")
    status("Recommended move payload", "INFO", ".env, data/secrets, data/managed-secrets, data/haproxy, plus optional data/model-cache")
    status("System of record", "INFO", "move through Utilities full PostgreSQL backup/restore, not by copying medusa-postgres")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
