from __future__ import annotations

import re
from collections import defaultdict, deque
from contextvars import ContextVar
from dataclasses import dataclass
from math import ceil
from time import perf_counter
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine


@dataclass
class RequestPerformanceStats:
    sql_count: int = 0
    sql_ms: float = 0.0


_request_stats: ContextVar[RequestPerformanceStats | None] = ContextVar("medusa_request_performance_stats", default=None)
_installed_engine_ids: set[int] = set()
_route_samples: dict[str, deque[tuple[float, int]]] = defaultdict(lambda: deque(maxlen=200))
_route_slow_counts: dict[str, int] = defaultdict(int)
_route_last_status: dict[str, int] = {}
_UUID_RE = re.compile(r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?=/|$)")
_NUMBER_RE = re.compile(r"/\d+(?=/|$)")


def begin_request_performance_stats() -> Any:
    return _request_stats.set(RequestPerformanceStats())


def current_request_performance_stats() -> RequestPerformanceStats | None:
    return _request_stats.get()


def reset_request_performance_stats(token: Any) -> None:
    _request_stats.reset(token)


def normalize_route_path(path: str) -> str:
    normalized = _UUID_RE.sub("/{id}", path)
    normalized = _NUMBER_RE.sub("/{n}", normalized)
    return normalized


def record_route_performance(path: str, elapsed_ms: float, status_code: int, slow_threshold_ms: float) -> None:
    route = normalize_route_path(path)
    _route_samples[route].append((elapsed_ms, status_code))
    _route_last_status[route] = status_code
    if elapsed_ms >= slow_threshold_ms:
        _route_slow_counts[route] += 1


def _nearest_rank_percentile(sorted_values: list[float], quantile: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, max(0, ceil(len(sorted_values) * quantile) - 1))
    return sorted_values[index]


def route_performance_summary(limit: int = 8) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for route, samples in _route_samples.items():
        if not samples:
            continue
        durations = sorted(value for value, _ in samples)
        average_ms = sum(durations) / len(durations)
        rows.append(
            {
                "route": route,
                "count": len(samples),
                "p50_ms": _nearest_rank_percentile(durations, 0.50),
                "p90_ms": _nearest_rank_percentile(durations, 0.90),
                "p95_ms": _nearest_rank_percentile(durations, 0.95),
                "p99_ms": _nearest_rank_percentile(durations, 0.99),
                "average_ms": average_ms,
                "slow_count": _route_slow_counts.get(route, 0),
                "last_status": _route_last_status.get(route),
            }
        )
    rows.sort(key=lambda row: (row["p95_ms"], row["count"]), reverse=True)
    return rows[:limit]


def install_sqlalchemy_performance_timing(engine: Engine) -> None:
    engine_id = id(engine)
    if engine_id in _installed_engine_ids:
        return
    _installed_engine_ids.add(engine_id)

    @event.listens_for(engine, "before_cursor_execute")
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        context._medusa_query_started_at = perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        started_at = getattr(context, "_medusa_query_started_at", None)
        stats = current_request_performance_stats()
        if started_at is None or stats is None:
            return
        stats.sql_count += 1
        stats.sql_ms += (perf_counter() - started_at) * 1000
