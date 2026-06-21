from __future__ import annotations

import csv
from datetime import datetime, timezone
from io import StringIO

import httpx

from app.config import get_settings
from app.schemas import HAProxyServiceStatOut, HAProxyStatsStatusOut


KIND_BY_TYPE = {
    "0": "frontend",
    "1": "backend",
    "2": "server",
    "3": "listener",
}


def _clean_key(key: str) -> str:
    return key.lstrip("# ").strip()


def _int_value(row: dict[str, str], key: str) -> int:
    raw = row.get(key, "").strip()
    if not raw:
        return 0
    try:
        return int(float(raw))
    except ValueError:
        return 0


def _optional_int_value(row: dict[str, str], key: str) -> int | None:
    raw = row.get(key, "").strip()
    if not raw:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def parse_haproxy_stats_csv(raw: str) -> list[HAProxyServiceStatOut]:
    if not raw.strip():
        return []
    lines = raw.splitlines()
    if not lines:
        return []
    lines[0] = ",".join(_clean_key(column) for column in lines[0].split(","))
    reader = csv.DictReader(StringIO("\n".join(lines)))
    services: list[HAProxyServiceStatOut] = []
    for row in reader:
        proxy_name = (row.get("pxname") or "").strip()
        service_name = (row.get("svname") or "").strip()
        if not proxy_name or not service_name:
            continue
        kind = KIND_BY_TYPE.get((row.get("type") or "").strip(), (row.get("type") or "unknown").strip() or "unknown")
        services.append(
            HAProxyServiceStatOut(
                proxy_name=proxy_name,
                service_name=service_name,
                kind=kind,
                status=(row.get("status") or "").strip() or None,
                current_sessions=_int_value(row, "scur"),
                max_sessions=_int_value(row, "smax"),
                total_sessions=_int_value(row, "stot"),
                session_rate=_int_value(row, "rate"),
                bytes_in=_int_value(row, "bin"),
                bytes_out=_int_value(row, "bout"),
                denied_requests=_int_value(row, "dreq"),
                denied_responses=_int_value(row, "dresp"),
                error_requests=_int_value(row, "ereq"),
                error_connections=_int_value(row, "econ"),
                error_responses=_int_value(row, "eresp"),
                retries=_int_value(row, "wretr"),
                redispatches=_int_value(row, "wredis"),
                active_servers=_optional_int_value(row, "act"),
                backup_servers=_optional_int_value(row, "bck"),
                check_status=(row.get("check_status") or "").strip() or None,
                check_code=_optional_int_value(row, "check_code"),
                check_duration_ms=_optional_int_value(row, "check_duration"),
                last_change_seconds=_optional_int_value(row, "lastchg"),
                downtime_seconds=_optional_int_value(row, "downtime"),
            )
        )
    return services


def haproxy_public_url() -> str:
    settings = get_settings()
    host = settings.public_host.strip() or "localhost"
    suffix = "" if settings.public_port == 443 else f":{settings.public_port}"
    return f"https://{host}{suffix}"


def haproxy_stats_status() -> HAProxyStatsStatusOut:
    settings = get_settings()
    stats_url = settings.haproxy_stats_url
    public_url = haproxy_public_url()
    checked_at = datetime.now(timezone.utc)
    try:
        response = httpx.get(stats_url, timeout=2.5)
        response.raise_for_status()
        services = parse_haproxy_stats_csv(response.text)
    except Exception as exc:
        return HAProxyStatsStatusOut(
            checked_at=checked_at,
            available=False,
            message=f"HAProxy stats unavailable: {exc}",
            public_url=public_url,
            stats_url=stats_url,
        )

    frontend_rows = [row for row in services if row.kind == "frontend"]
    total_errors = sum(
        row.denied_requests
        + row.denied_responses
        + row.error_requests
        + row.error_connections
        + row.error_responses
        + row.retries
        + row.redispatches
        for row in services
    )
    return HAProxyStatsStatusOut(
        checked_at=checked_at,
        available=True,
        message="HAProxy is terminating TLS on port 3737.",
        public_url=public_url,
        stats_url=stats_url,
        total_current_sessions=sum(row.current_sessions for row in frontend_rows),
        total_sessions=sum(row.total_sessions for row in frontend_rows),
        total_bytes_in=sum(row.bytes_in for row in frontend_rows),
        total_bytes_out=sum(row.bytes_out for row in frontend_rows),
        total_errors=total_errors,
        services=services,
    )
