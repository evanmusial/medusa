from __future__ import annotations

import re
import os
import platform
import shutil
import signal
import socket
import subprocess
import threading
import time
from datetime import datetime, timezone
from html import unescape
from importlib import metadata
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings
from app.schemas import (
    ContainerDockerImageOut,
    ContainerDockerLayerOut,
    ContainerFilesystemOut,
    ContainerFootprintStatusOut,
    ContainerPathFootprintOut,
    ContainerRestartOut,
    ContainerRuntimeVersionOut,
)


_PROCESS_STARTED_AT = time.time()
_RESTART_LOCK = threading.Lock()
_RESTART_REQUESTED_AT: datetime | None = None
_RESTART_REQUESTED_MONOTONIC: float | None = None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _read_int(path: Path) -> int | None:
    raw = _read_text(path)
    if raw is None or raw == "" or raw == "max":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _read_key_values(path: Path) -> dict[str, str]:
    raw = _read_text(path)
    if not raw:
        return {}
    values: dict[str, str] = {}
    for line in raw.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            values[parts[0]] = parts[1]
    return values


def _bounded_limit(value: int | None) -> int | None:
    if value is None:
        return None
    # Docker/cgroup v1 commonly uses enormous sentinel values for "unlimited".
    return None if value >= 2**60 else value


def _memory_current_bytes() -> int | None:
    return _read_int(Path("/sys/fs/cgroup/memory.current")) or _read_int(
        Path("/sys/fs/cgroup/memory/memory.usage_in_bytes")
    )


def _memory_limit_bytes() -> int | None:
    return _bounded_limit(
        _read_int(Path("/sys/fs/cgroup/memory.max"))
        or _read_int(Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"))
    )


def _memory_peak_bytes() -> int | None:
    return _bounded_limit(
        _read_int(Path("/sys/fs/cgroup/memory.peak"))
        or _read_int(Path("/sys/fs/cgroup/memory/memory.max_usage_in_bytes"))
    )


def _cpu_limit_cores() -> float | None:
    raw = _read_text(Path("/sys/fs/cgroup/cpu.max"))
    if raw:
        parts = raw.split()
        if len(parts) >= 2 and parts[0] != "max":
            try:
                quota = float(parts[0])
                period = float(parts[1])
            except ValueError:
                quota = 0
                period = 0
            if quota > 0 and period > 0:
                return quota / period
    quota = _read_int(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us"))
    period = _read_int(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us"))
    if quota and quota > 0 and period and period > 0:
        return quota / period
    return None


def _cpu_usage_seconds() -> float | None:
    values = _read_key_values(Path("/sys/fs/cgroup/cpu.stat"))
    if "usage_usec" in values:
        try:
            return int(values["usage_usec"]) / 1_000_000
        except ValueError:
            return None
    usage_ns = _read_int(Path("/sys/fs/cgroup/cpuacct/cpuacct.usage"))
    return usage_ns / 1_000_000_000 if usage_ns is not None else None


def _process_rss_bytes() -> int | None:
    raw = _read_text(Path("/proc/self/statm"))
    if not raw:
        return None
    parts = raw.split()
    if len(parts) < 2:
        return None
    try:
        return int(parts[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError):
        return None


def _thread_count() -> int | None:
    values = _read_key_values(Path("/proc/self/status"))
    raw = values.get("Threads:")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _process_count() -> int | None:
    proc = Path("/proc")
    if not proc.exists():
        return None
    try:
        return sum(1 for path in proc.iterdir() if path.name.isdigit())
    except OSError:
        return None


def _is_containerized() -> bool:
    if Path("/.dockerenv").exists():
        return True
    cgroup = _read_text(Path("/proc/1/cgroup")) or ""
    return any(marker in cgroup for marker in ("docker", "containerd", "kubepods"))


def _container_restart_capability() -> tuple[bool, str, str]:
    if not _is_containerized():
        return (
            False,
            "unavailable",
            "Container restart is disabled outside Docker so a local development server is not killed.",
        )
    return (
        True,
        "process_exit",
        "Restart sends the backend process a termination signal; Docker restarts the backend container.",
    )


def _schedule_process_restart(delay_seconds: float) -> None:
    def restart() -> None:
        time.sleep(delay_seconds)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=restart, name="medusa-container-restart", daemon=True).start()


def request_container_restart(delay_seconds: float = 0.75) -> ContainerRestartOut:
    global _RESTART_REQUESTED_AT, _RESTART_REQUESTED_MONOTONIC

    available, restart_mode, restart_note = _container_restart_capability()
    if not available:
        raise RuntimeError(restart_note)

    with _RESTART_LOCK:
        now_monotonic = time.monotonic()
        if _RESTART_REQUESTED_MONOTONIC is not None and now_monotonic - _RESTART_REQUESTED_MONOTONIC < 10:
            return ContainerRestartOut(
                status="scheduled",
                message="Backend container restart is already scheduled.",
                restart_mode=restart_mode,
                poll_after_seconds=2.0,
            )
        _RESTART_REQUESTED_AT = datetime.now(timezone.utc)
        _RESTART_REQUESTED_MONOTONIC = now_monotonic
        _schedule_process_restart(delay_seconds)

    return ContainerRestartOut(
        status="scheduled",
        message="Backend container restart scheduled. Waiting for backend health is safe now.",
        restart_mode=restart_mode,
        poll_after_seconds=2.0,
    )


def _path_footprint(label: str, path: Path) -> ContainerPathFootprintOut:
    exists = path.exists()
    if not exists:
        return ContainerPathFootprintOut(label=label, path=str(path), exists=False)
    if path.is_file():
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        return ContainerPathFootprintOut(label=label, path=str(path), exists=True, size_bytes=size, file_count=1)

    total_bytes = 0
    file_count = 0
    directory_count = 0
    for root, dirnames, filenames in os.walk(path):
        directory_count += len(dirnames)
        root_path = Path(root)
        for filename in filenames:
            candidate = root_path / filename
            try:
                if candidate.is_file():
                    total_bytes += candidate.stat().st_size
                    file_count += 1
            except OSError:
                continue
    return ContainerPathFootprintOut(
        label=label,
        path=str(path),
        exists=True,
        size_bytes=total_bytes,
        file_count=file_count,
        directory_count=directory_count,
    )


def _disk_usage(path: Path) -> ContainerFilesystemOut | None:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    if not candidate.exists():
        return None
    try:
        usage = shutil.disk_usage(candidate)
    except OSError:
        return None
    return ContainerFilesystemOut(
        path=str(path),
        total_bytes=usage.total,
        used_bytes=usage.used,
        free_bytes=usage.free,
    )


def _first_nonempty_line(output: str) -> str:
    for line in output.splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned
    return ""


def _run_version_command(
    name: str,
    command: list[str],
    source: str,
    *,
    note: str | None = None,
) -> ContainerRuntimeVersionOut:
    try:
        result = subprocess.run(
            command,
            check=False,
            stderr=subprocess.STDOUT,
            stdout=subprocess.PIPE,
            text=True,
            timeout=2.5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ContainerRuntimeVersionOut(
            name=name,
            version="Unavailable",
            source=source,
            status="unavailable",
            note=str(exc),
        )
    output = _first_nonempty_line(result.stdout or "")
    if result.returncode != 0 or not output:
        return ContainerRuntimeVersionOut(
            name=name,
            version="Unavailable",
            source=source,
            status="unavailable",
            note=output or f"command exited {result.returncode}",
        )
    return ContainerRuntimeVersionOut(name=name, version=output, source=source, note=note)


def _docker_socket_path() -> Path:
    return Path(os.environ.get("MEDUSA_DOCKER_SOCKET_PATH") or "/var/run/docker.sock")


def _docker_socket_available(path: Path) -> bool:
    try:
        return path.exists() and path.is_socket()
    except OSError:
        return False


def _docker_api_get(client: httpx.Client, path: str) -> dict[str, Any] | list[dict[str, Any]]:
    response = client.get(path)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, (dict, list)) else {}


def _current_container_identifiers() -> list[str]:
    candidates: list[str] = []
    hostname = socket.gethostname().strip()
    if hostname:
        candidates.append(hostname)
    cgroup = _read_text(Path("/proc/self/cgroup")) or ""
    for match in re.findall(r"([0-9a-f]{12,64})", cgroup):
        if match not in candidates:
            candidates.append(match)
    return candidates


def _docker_container_detail(client: httpx.Client) -> dict[str, Any] | None:
    for identifier in _current_container_identifiers():
        try:
            payload = _docker_api_get(client, f"/containers/{identifier}/json")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                continue
            raise
        return payload if isinstance(payload, dict) else None
    return None


def _docker_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _docker_id_key(value: str | None) -> str:
    return (value or "").removeprefix("sha256:").strip()


def _docker_image_matches(candidate: dict[str, Any], image_id: str, repo_tags: list[str]) -> bool:
    candidate_id = _docker_id_key(str(candidate.get("Id") or ""))
    target_id = _docker_id_key(image_id)
    if candidate_id and target_id and (candidate_id == target_id or candidate_id.startswith(target_id) or target_id.startswith(candidate_id)):
        return True
    candidate_tags = {str(tag) for tag in candidate.get("RepoTags") or []}
    return bool(candidate_tags.intersection(repo_tags))


def _docker_image_df(images: list[dict[str, Any]], image_id: str, repo_tags: list[str]) -> dict[str, Any] | None:
    for image in images:
        if _docker_image_matches(image, image_id, repo_tags):
            return image
    return None


def _clean_docker_created_by(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("/bin/sh -c #(nop) ", "").replace("/bin/sh -c ", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:240]


def _docker_layers(history: list[dict[str, Any]]) -> list[ContainerDockerLayerOut]:
    layers: list[ContainerDockerLayerOut] = []
    for row in history[:40]:
        raw_tags = row.get("Tags") or []
        tags = [str(tag) for tag in raw_tags if tag]
        layers.append(
            ContainerDockerLayerOut(
                id=str(row.get("Id") or "<missing>"),
                created_by=_clean_docker_created_by(row.get("CreatedBy")),
                size_bytes=max(0, _docker_int(row.get("Size")) or 0),
                tags=tags,
                comment=str(row.get("Comment") or "").strip() or None,
            )
        )
    return layers


def _docker_current_image(socket_path: Path) -> ContainerDockerImageOut | None:
    transport = httpx.HTTPTransport(uds=str(socket_path))
    with httpx.Client(transport=transport, base_url="http://docker", timeout=2.5) as client:
        container = _docker_container_detail(client)
        if not container:
            return None
        image_ref = str(container.get("Image") or (container.get("Config") or {}).get("Image") or "").strip()
        if not image_ref:
            return None
        image_detail_payload = _docker_api_get(client, f"/images/{image_ref}/json")
        image_detail = image_detail_payload if isinstance(image_detail_payload, dict) else {}
        image_id = str(image_detail.get("Id") or image_ref)
        repo_tags = [str(tag) for tag in image_detail.get("RepoTags") or [] if tag and tag != "<none>:<none>"]
        if not repo_tags:
            config_image = str((container.get("Config") or {}).get("Image") or "").strip()
            repo_tags = [config_image] if config_image else []

        df_payload = _docker_api_get(client, "/system/df")
        df_images = df_payload.get("Images") if isinstance(df_payload, dict) else []
        df_image = _docker_image_df(df_images if isinstance(df_images, list) else [], image_id, repo_tags)
        history_payload = _docker_api_get(client, f"/images/{image_id}/history")
        history = history_payload if isinstance(history_payload, list) else []
        layers = _docker_layers(history)
        rootfs_layers = (image_detail.get("RootFS") or {}).get("Layers") or []
        layer_count = len(rootfs_layers) or sum(1 for layer in layers if layer.size_bytes > 0) or len(layers)
        shared_size = _docker_int((df_image or {}).get("SharedSize"))
        unique_size = _docker_int((df_image or {}).get("UniqueSize"))
        if unique_size is None:
            image_size = _docker_int((df_image or {}).get("Size")) or _docker_int(image_detail.get("Size"))
            unique_size = image_size - shared_size if image_size is not None and shared_size is not None else None
        return ContainerDockerImageOut(
            id=image_id,
            repo_tags=repo_tags,
            size_bytes=_docker_int((df_image or {}).get("Size")) or _docker_int(image_detail.get("Size")),
            virtual_size_bytes=_docker_int((df_image or {}).get("VirtualSize")) or _docker_int(image_detail.get("VirtualSize")),
            shared_size_bytes=shared_size,
            unique_size_bytes=unique_size,
            containers=_docker_int((df_image or {}).get("Containers")),
            layer_count=layer_count,
            layers=layers,
        )


def docker_image_status(socket_path: Path) -> tuple[bool, str, ContainerDockerImageOut | None]:
    if not _docker_socket_available(socket_path):
        return (
            False,
            "Docker socket is not mounted; image and layer sizes are unavailable from inside this container. "
            "Mount the Docker socket only if you accept that it grants the backend broad host Docker control.",
            None,
        )
    try:
        docker_image = _docker_current_image(socket_path)
    except Exception as exc:
        return (
            True,
            f"Docker socket is mounted, but Medusa could not query Docker Engine: {exc}",
            None,
        )
    if not docker_image:
        return (
            True,
            "Docker socket is mounted, but Medusa could not match this backend process to a Docker container image.",
            None,
        )
    return (
        True,
        "Docker socket is mounted; showing image and layer sizes for the current backend image. "
        "Mounting the socket grants the backend broad host Docker control even though Medusa only performs read-only queries.",
        docker_image,
    )


def _python_package_version(name: str, package: str) -> ContainerRuntimeVersionOut:
    try:
        version = metadata.version(package)
    except metadata.PackageNotFoundError:
        return ContainerRuntimeVersionOut(
            name=name,
            version="Unavailable",
            source=f"Python package {package}",
            status="unavailable",
            note="package is not installed in this runtime.",
        )
    return ContainerRuntimeVersionOut(name=name, version=version, source=f"Python package {package}")


def _haproxy_stats_page_url(stats_url: str) -> str:
    return stats_url.replace(";csv", "")


def parse_haproxy_version_from_stats_html(html: str) -> tuple[str | None, str | None]:
    text = unescape(html)
    match = re.search(r"HAProxy version\s+([^,<]+)(?:,\s*released\s*([^<\n]+))?", text, flags=re.IGNORECASE)
    if not match:
        return None, None
    version = match.group(1).strip()
    release_date = match.group(2).strip() if match.group(2) else None
    return version, release_date


def _haproxy_runtime_version(stats_url: str) -> ContainerRuntimeVersionOut:
    stats_page_url = _haproxy_stats_page_url(stats_url)
    try:
        response = httpx.get(stats_page_url, timeout=2.5)
        response.raise_for_status()
    except Exception as exc:
        return ContainerRuntimeVersionOut(
            name="HAProxy",
            version="Unavailable",
            source=stats_page_url,
            status="unavailable",
            note=f"Could not reach HAProxy stats page: {exc}",
        )
    version, release_date = parse_haproxy_version_from_stats_html(response.text)
    if not version:
        return ContainerRuntimeVersionOut(
            name="HAProxy",
            version="Unavailable",
            source=stats_page_url,
            status="unavailable",
            note="Stats page did not include a parseable HAProxy version.",
        )
    note = f"Released {release_date}; Compose image tag haproxy:3.0-alpine." if release_date else "Compose image tag haproxy:3.0-alpine."
    return ContainerRuntimeVersionOut(name="HAProxy", version=version, source=stats_page_url, note=note)


def runtime_versions() -> list[ContainerRuntimeVersionOut]:
    settings = get_settings()
    versions = [
        _haproxy_runtime_version(settings.haproxy_stats_url),
        ContainerRuntimeVersionOut(
            name="Python",
            version=platform.python_version(),
            source="Backend image python:3.12-slim",
            note=platform.python_implementation(),
        ),
        _python_package_version("FastAPI", "fastapi"),
        _python_package_version("Uvicorn", "uvicorn"),
        _python_package_version("SQLAlchemy", "sqlalchemy"),
        _python_package_version("Alembic", "alembic"),
        _python_package_version("PyMuPDF", "PyMuPDF"),
        _python_package_version("Marker PDF", "marker-pdf"),
        _run_version_command("PostgreSQL client", ["psql", "--version"], "backend container binary"),
        _run_version_command("Zstandard CLI", ["zstd", "--version"], "backend container binary"),
        _run_version_command("curl", ["curl", "--version"], "backend container binary"),
    ]
    return versions


def container_footprint_status() -> ContainerFootprintStatusOut:
    settings = get_settings()
    data_dir = settings.data_dir
    model_cache_dir = Path(os.environ.get("XDG_CACHE_HOME") or data_dir / "model-cache")
    paths = [
        _path_footprint("Data volume", data_dir),
        _path_footprint("Local originals", settings.local_storage_dir),
        _path_footprint("Processing cache", data_dir / "processing-cache"),
        _path_footprint("Model cache", model_cache_dir),
        _path_footprint("Managed secrets", data_dir / "managed-secrets"),
        _path_footprint("Mounted secrets", data_dir / "secrets"),
    ]
    data_footprint = paths[0]
    docker_socket_available, docker_engine_note, docker_image = docker_image_status(_docker_socket_path())
    restart_available, restart_mode, restart_note = _container_restart_capability()
    return ContainerFootprintStatusOut(
        checked_at=datetime.now(timezone.utc),
        hostname=socket.gethostname(),
        containerized=_is_containerized(),
        docker_socket_available=docker_socket_available,
        docker_engine_note=docker_engine_note,
        docker_image=docker_image,
        restart_available=restart_available,
        restart_mode=restart_mode,
        restart_note=restart_note,
        restart_requested_at=_RESTART_REQUESTED_AT,
        process_uptime_seconds=max(0, int(time.time() - _PROCESS_STARTED_AT)),
        memory_current_bytes=_memory_current_bytes(),
        memory_limit_bytes=_memory_limit_bytes(),
        memory_peak_bytes=_memory_peak_bytes(),
        process_rss_bytes=_process_rss_bytes(),
        cpu_limit_cores=_cpu_limit_cores(),
        cpu_usage_seconds=_cpu_usage_seconds(),
        process_count=_process_count(),
        thread_count=_thread_count(),
        platform=platform.platform(),
        python_version=platform.python_version(),
        data_dir=str(data_dir),
        data_dir_size_bytes=data_footprint.size_bytes,
        data_filesystem=_disk_usage(data_dir),
        root_filesystem=_disk_usage(Path("/")),
        paths=paths,
        runtime_versions=runtime_versions(),
    )
