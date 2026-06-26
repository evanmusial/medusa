#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path


def run_command(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


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


def parse_cpuset(value: str) -> set[int]:
    cpus: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if end < start:
                raise ValueError(f"invalid CPU range {part}")
            cpus.update(range(start, end + 1))
        else:
            cpus.add(int(part))
    return cpus


def host_ips() -> set[str]:
    ips = {"0.0.0.0", "127.0.0.1", "::"}
    if shutil.which("ip"):
        result = subprocess.run(["ip", "-o", "addr", "show"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for line in result.stdout.splitlines():
            for token in line.split():
                if "/" in token and token[0].isdigit():
                    ips.add(token.split("/", 1)[0])
    if shutil.which("ifconfig"):
        result = subprocess.run(["ifconfig"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("inet "):
                parts = stripped.split()
                if len(parts) > 1:
                    ips.add(parts[1])
    return ips


def check_command(repo: Path, args: list[str], label: str) -> bool:
    result = run_command(args, cwd=repo)
    if result.returncode == 0:
        lines = (result.stdout.strip() or result.stderr.strip()).splitlines()
        detail = lines[0] if lines else "available"
        status(label, "OK", detail)
        return True
    detail = result.stderr.strip() or result.stdout.strip() or f"{args[0]} exited with {result.returncode}"
    status(label, "FAIL", detail)
    return False


def check_file(path: Path, label: str, *, required: bool = True) -> bool:
    if path.exists():
        status(label, "OK", str(path))
        return True
    status(label, "FAIL" if required else "WARN", f"{path} is missing")
    return not required


def check_port(bind_ip: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in bind_ip else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((bind_ip, port))
    except OSError as exc:
        status(f"Port {port} bind", "FAIL", f"{bind_ip}:{port} is not available: {exc}")
        return False
    finally:
        sock.close()
    status(f"Port {port} bind", "OK", f"{bind_ip}:{port} is available")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Check a dedicated server before starting Medusa.")
    parser.add_argument("--repo", type=Path, default=repo_default(), help="Medusa repository path.")
    parser.add_argument("--port", type=int, default=3737, help="Host port expected for HAProxy.")
    args = parser.parse_args()
    repo = args.repo.resolve()
    if not (repo / "docker-compose.yml").exists():
        print(f"{repo} does not look like a Medusa checkout.", file=sys.stderr)
        return 2

    env = read_env(repo / ".env")
    public_host = env.get("MEDUSA_PUBLIC_HOST") or os.environ.get("MEDUSA_PUBLIC_HOST") or ""
    allowed_hosts = env.get("MEDUSA_ALLOWED_HOSTS") or os.environ.get("MEDUSA_ALLOWED_HOSTS") or ""
    bind_ip = env.get("MEDUSA_BIND_IP") or os.environ.get("MEDUSA_BIND_IP") or "0.0.0.0"
    cpuset_value = env.get("MEDUSA_CPUSET") or os.environ.get("MEDUSA_CPUSET") or "0-5"
    failures = 0

    print(f"Medusa server doctor for {repo}")
    print("")
    for command, label in (
        (["docker", "--version"], "Docker"),
        (["docker", "compose", "version"], "Docker Compose"),
        (["git", "--version"], "Git"),
    ):
        if not check_command(repo, command, label):
            failures += 1

    docker_info = run_command(["docker", "info"], cwd=repo)
    if docker_info.returncode == 0:
        status("Docker daemon", "OK", "reachable")
    else:
        failures += 1
        status("Docker daemon", "FAIL", docker_info.stderr.strip() or docker_info.stdout.strip())

    print("")
    cpu_count = os.cpu_count() or 0
    try:
        cpus = parse_cpuset(cpuset_value)
        invalid = sorted(cpu for cpu in cpus if cpu < 0 or cpu >= cpu_count)
        if invalid:
            failures += 1
            status("MEDUSA_CPUSET", "FAIL", f"{cpuset_value} includes unavailable CPUs {invalid}; host has {cpu_count}")
        else:
            state = "OK" if len(cpus) <= max(cpu_count - 1, 0) else "WARN"
            status("MEDUSA_CPUSET", state, f"{cpuset_value} uses {len(cpus)} of {cpu_count} logical CPUs")
    except ValueError as exc:
        failures += 1
        status("MEDUSA_CPUSET", "FAIL", str(exc))
    if shutil.which("lscpu"):
        result = run_command(["lscpu", "-e=CPU,CORE,SOCKET,NODE,ONLINE"], cwd=repo)
        if result.returncode == 0:
            status("CPU topology", "INFO", "run `lscpu -e=CPU,CORE,SOCKET,NODE,ONLINE` to choose sibling-aware CPU IDs")

    if public_host:
        status("MEDUSA_PUBLIC_HOST", "OK", public_host)
    else:
        status("MEDUSA_PUBLIC_HOST", "WARN", "not set; HAProxy will fall back to medusa.home.musial.io")
    if allowed_hosts:
        detail = "open to all Host headers" if allowed_hosts.strip().lower() in {"*", "all", "true"} else allowed_hosts
        status("MEDUSA_ALLOWED_HOSTS", "OK", detail)
    else:
        status("MEDUSA_ALLOWED_HOSTS", "WARN", "not set; frontend will allow medusa.home.musial.io only")
    ips = host_ips()
    if bind_ip in ips:
        status("MEDUSA_BIND_IP", "OK", bind_ip)
    else:
        failures += 1
        status("MEDUSA_BIND_IP", "FAIL", f"{bind_ip} was not found on this host")
    if not check_port(bind_ip, args.port):
        failures += 1

    print("")
    required_files = [
        (repo / ".env", ".env"),
        (repo / "docker-compose.server.yml", "server Compose override"),
        (repo / "data" / "haproxy" / "fullchain.pem", "HAProxy certificate"),
        (repo / "data" / "haproxy" / "privatekey.pem", "HAProxy private key"),
    ]
    for path, label in required_files:
        if not check_file(path, label):
            failures += 1
    credentials = env.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if credentials.startswith("/app/data/secrets/"):
        host_credentials = repo / "data" / "secrets" / credentials.removeprefix("/app/data/secrets/")
        if not check_file(host_credentials, "Google service-account file", required=bool(env.get("GCS_BUCKET"))):
            failures += 1
    elif env.get("GCS_BUCKET"):
        status("Google service-account file", "WARN", "credential path is not under /app/data/secrets; check the mount manually")

    print("")
    config = run_command(["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.server.yml", "config"], cwd=repo)
    if config.returncode == 0:
        status("Server Compose config", "OK", "base plus server override renders")
    else:
        failures += 1
        status("Server Compose config", "FAIL", config.stderr.strip() or config.stdout.strip())

    print("")
    if failures:
        status("Server readiness", "FAIL", f"{failures} blocking check(s) failed")
        return 1
    status("Server readiness", "OK", "ready for docker compose -f docker-compose.yml -f docker-compose.server.yml up -d --build")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
