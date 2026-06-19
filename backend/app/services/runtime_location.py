from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit


APP_NAME = "medusa"
APP_EXPANSION = "Mapped Evidence for Discovery, Understanding, Synthesis, and Analysis"

LAN_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
    )
)


def normalize_host(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    parsed = urlsplit(raw if "://" in raw else f"//{raw}")
    host = parsed.hostname or raw
    return host.strip("[]").rstrip(".").lower() or None


def detect_server_ipv4() -> str | None:
    candidates: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            candidates.append(probe.getsockname()[0])
    except OSError:
        pass

    try:
        candidates.extend(
            info[4][0]
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM)
        )
    except OSError:
        pass

    for candidate in candidates:
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if address.version == 4 and not address.is_loopback:
            return str(address)
    return None


def resolve_ipv4(host: str | None) -> str | None:
    if not host:
        return None
    try:
        address = ipaddress.ip_address(host)
        return str(address) if address.version == 4 else None
    except ValueError:
        pass

    try:
        addresses = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return None

    for address in addresses:
        candidate = address[4][0]
        try:
            parsed = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if parsed.version == 4:
            return str(parsed)
    return None


def is_lan_ipv4(value: str | None) -> bool:
    if not value:
        return False
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address.version == 4 and any(address in network for network in LAN_NETWORKS)


def runtime_location_payload(browser_host: str | None, server_ipv4: str | None = None) -> dict[str, str | None]:
    host = normalize_host(browser_host)
    host_ipv4 = resolve_ipv4(host)

    if host in {"localhost"} or host_ipv4 in {"127.0.0.1"} or host == "::1":
        return {
            "app_name": APP_NAME,
            "expansion": APP_EXPANSION,
            "network_context": "local",
            "ipv4": None,
            "title": f"{APP_NAME} (local)",
        }

    ipv4 = host_ipv4 or server_ipv4
    if is_lan_ipv4(ipv4):
        return {
            "app_name": APP_NAME,
            "expansion": APP_EXPANSION,
            "network_context": "lan",
            "ipv4": ipv4,
            "title": f"{APP_NAME} (local: {ipv4})",
        }

    return {
        "app_name": APP_NAME,
        "expansion": APP_EXPANSION,
        "network_context": "remote",
        "ipv4": ipv4,
        "title": f"{APP_NAME} (remote: {ipv4})" if ipv4 else f"{APP_NAME} (remote)",
    }
