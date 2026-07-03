from app.services import performance


def _clear_route_performance_state() -> None:
    performance._route_samples.clear()
    performance._route_slow_counts.clear()
    performance._route_last_status.clear()


def test_route_performance_summary_reports_percentiles_in_milliseconds():
    _clear_route_performance_state()
    try:
        for elapsed_ms in range(10, 110, 10):
            performance.record_route_performance("/api/documents/123", elapsed_ms, 200, slow_threshold_ms=75)

        rows = performance.route_performance_summary()

        assert rows == [
            {
                "route": "/api/documents/{n}",
                "count": 10,
                "p50_ms": 50,
                "p90_ms": 90,
                "p95_ms": 100,
                "p99_ms": 100,
                "average_ms": 55,
                "slow_count": 3,
                "last_status": 200,
            }
        ]
    finally:
        _clear_route_performance_state()
