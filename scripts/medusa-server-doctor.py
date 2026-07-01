#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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


def env_value(env: dict[str, str], key: str, default: str | None = None) -> str | None:
    return env.get(key) or os.environ.get(key) or default


def check_cpuset_value(label: str, value: str, cpu_count: int) -> bool:
    try:
        cpus = parse_cpuset(value)
    except ValueError as exc:
        status(label, "FAIL", str(exc))
        return False
    invalid = sorted(cpu for cpu in cpus if cpu < 0 or cpu >= cpu_count)
    if invalid:
        status(label, "FAIL", f"{value} includes unavailable CPUs {invalid}; host has {cpu_count}")
        return False
    state = "OK" if len(cpus) <= max(cpu_count - 1, 0) else "WARN"
    status(label, state, f"{value} uses {len(cpus)} of {cpu_count} logical CPUs")
    return True


def host_ips() -> set[str]:
    ips = {"0.0.0.0", "127.0.0.1", "::", "::1"}
    if shutil.which("ip"):
        result = subprocess.run(["ip", "-o", "addr", "show"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for line in result.stdout.splitlines():
            for token in line.split():
                if "/" in token and (token[0].isdigit() or ":" in token):
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


def format_host_port(bind_ip: str, port: int) -> str:
    return f"[{bind_ip}]:{port}" if ":" in bind_ip else f"{bind_ip}:{port}"


def normalize_host_ip(value: str | None) -> str:
    cleaned = (value or "0.0.0.0").strip()
    if cleaned.startswith("[") and cleaned.endswith("]"):
        return cleaned[1:-1]
    return cleaned


def check_port(bind_ip: str, port: int, *, label: str | None = None) -> bool:
    family = socket.AF_INET6 if ":" in bind_ip else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    check_label = label or f"Port {port} bind"
    host_port = format_host_port(bind_ip, port)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((bind_ip, port))
    except OSError as exc:
        status(check_label, "FAIL", f"{host_port} is not available: {exc}")
        return False
    finally:
        sock.close()
    status(check_label, "OK", f"{host_port} is available")
    return True


def check_haproxy_ports(repo: Path, expected_host_ips: list[str], port: int) -> bool:
    config = run_command(
        ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.server.yml", "config", "--format", "json"],
        cwd=repo,
    )
    if config.returncode != 0:
        status("HAProxy published ports", "WARN", "could not inspect rendered Compose JSON")
        return True
    try:
        rendered = json.loads(config.stdout)
        ports = rendered["services"]["haproxy"].get("ports") or []
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        status("HAProxy published ports", "WARN", f"could not parse rendered Compose ports: {exc}")
        return True

    matches = [
        item
        for item in ports
        if str(item.get("published")) == str(port)
        and int(item.get("target", 0)) == port
        and item.get("protocol", "tcp") == "tcp"
    ]
    expected = [normalize_host_ip(item) for item in expected_host_ips]
    actual = [normalize_host_ip(item.get("host_ip")) for item in matches]
    if len(actual) != len(expected):
        expected_detail = ", ".join(format_host_port(item, port) for item in expected)
        actual_detail = ", ".join(format_host_port(item, port) for item in actual) or "none"
        status("HAProxy published ports", "FAIL", f"expected {expected_detail}; rendered {actual_detail}")
        return False
    missing = [item for item in expected if item not in actual]
    unexpected = [item for item in actual if item not in expected]
    if missing or unexpected:
        detail_parts = []
        if missing:
            detail_parts.append("missing " + ", ".join(format_host_port(item, port) for item in missing))
        if unexpected:
            detail_parts.append("unexpected " + ", ".join(format_host_port(item, port) for item in unexpected))
        status("HAProxy published ports", "FAIL", "; ".join(detail_parts))
        return False
    rendered = ", ".join(format_host_port(item, port) for item in actual)
    status("HAProxy published ports", "OK", f"renders {rendered}->{port}/tcp")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Check a dedicated server before starting Medusa.")
    parser.add_argument("--repo", type=Path, default=repo_default(), help="Medusa repository path.")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Host port expected for HAProxy. Defaults to MEDUSA_HAPROXY_PORT or 3737.",
    )
    args = parser.parse_args()
    repo = args.repo.resolve()
    if not (repo / "docker-compose.yml").exists():
        print(f"{repo} does not look like a Medusa checkout.", file=sys.stderr)
        return 2

    env = read_env(repo / ".env")
    public_host = env_value(env, "MEDUSA_PUBLIC_HOST", "") or ""
    public_port = env_value(env, "MEDUSA_PUBLIC_PORT", "3737") or "3737"
    haproxy_port = args.port or int(env_value(env, "MEDUSA_HAPROXY_PORT", "3737") or "3737")
    allowed_hosts = env_value(env, "MEDUSA_ALLOWED_HOSTS", "") or ""
    bind_ip = env_value(env, "MEDUSA_BIND_IP", "0.0.0.0") or "0.0.0.0"
    bind_ipv6 = env_value(env, "MEDUSA_BIND_IPV6", "::1") or "::1"
    cpuset_value = env_value(env, "MEDUSA_CPUSET", "0-5") or "0-5"
    app_cpuset_value = env_value(env, "MEDUSA_APP_CPUSET")
    db_cpuset_value = env_value(env, "MEDUSA_DB_CPUSET")
    worker_cpuset_value = env_value(env, "MEDUSA_WORKER_CPUSET")
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
    cpu_checks = [("MEDUSA_CPUSET", cpuset_value)]
    if app_cpuset_value:
        cpu_checks.append(("MEDUSA_APP_CPUSET", app_cpuset_value))
    if db_cpuset_value:
        cpu_checks.append(("MEDUSA_DB_CPUSET", db_cpuset_value))
    if worker_cpuset_value:
        cpu_checks.append(("MEDUSA_WORKER_CPUSET", worker_cpuset_value))
    for label, value in cpu_checks:
        if not check_cpuset_value(label, value, cpu_count):
            failures += 1
    if shutil.which("lscpu"):
        result = run_command(["lscpu", "-e=CPU,CORE,SOCKET,NODE,ONLINE"], cwd=repo)
        if result.returncode == 0:
            status("CPU topology", "INFO", "run `lscpu -e=CPU,CORE,SOCKET,NODE,ONLINE` to choose sibling-aware CPU IDs")

    if public_host:
        public_suffix = "" if public_port == "443" else f":{public_port}"
        status("MEDUSA_PUBLIC_HOST", "OK", f"https://{public_host}{public_suffix}")
    else:
        status("MEDUSA_PUBLIC_HOST", "WARN", "not set; HAProxy will fall back to medusa.home.musial.io")
    status("MEDUSA_HAPROXY_PORT", "OK", str(haproxy_port))
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
    if bind_ipv6 in ips:
        status("MEDUSA_BIND_IPV6", "OK", bind_ipv6)
    else:
        failures += 1
        status("MEDUSA_BIND_IPV6", "FAIL", f"{bind_ipv6} was not found on this host")
    if not check_port(bind_ip, haproxy_port):
        failures += 1
    if not check_port(bind_ipv6, haproxy_port, label=f"Port {haproxy_port} IPv6 bind"):
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
        if not check_haproxy_ports(repo, [bind_ip, bind_ipv6], haproxy_port):
            failures += 1
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
