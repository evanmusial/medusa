from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
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


def begin_request_performance_stats() -> Any:
    return _request_stats.set(RequestPerformanceStats())


def current_request_performance_stats() -> RequestPerformanceStats | None:
    return _request_stats.get()


def reset_request_performance_stats(token: Any) -> None:
    _request_stats.reset(token)


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
