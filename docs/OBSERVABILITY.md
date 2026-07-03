# Medusa Observability

Last updated: 2026-07-02

This document owns the Prometheus metric catalog and maintained Grafana dashboard design for Medusa. The exporter lives in `backend/app/tools/prometheus_exporter.py`; the source-controlled Grafana dashboard lives in `deploy/grafana/medusa-dashboard.json`.

## Current Live State

- Grafana: `http://10.1.10.69:3000`, observed version `13.1.0`.
- Prometheus datasource in Grafana: `Prometheus` (`qgXJ0MD4k`), targeting `http://10.1.10.69:9090`.
- Maintained dashboard: existing Grafana dashboard `Medusa` (`ads7jj6`).
- Current Prometheus scrape contains `151` distinct `medusa_*` metric names across `1784` live series.
- Current scrape status observed after the Prometheus scrape repair: `up{job="medusa", instance="23.227.185.85:43737"}` is `1`.
- Current exporter freshness observed after the Prometheus scrape repair: approximately `4s`.
- Prior scrape failure observed on 2026-07-02: Prometheus scraped `https://23.227.185.85:43737/metrics` and failed TLS verification because the certificate was hostname-based and did not contain the IP address as a subject alternative name. If the target goes down again, verify the hostname/TLS `server_name` scrape configuration before trusting freshness-sensitive panels. Do not commit bearer tokens to this repository.

## Exporter Architecture

- The optional `metrics-exporter` sidecar exposes Prometheus text metrics through HAProxy on `MEDUSA_METRICS_PORT`, normally `43737`.
- `/metrics` is bearer-token protected when `MEDUSA_METRICS_REQUIRE_AUTH=true`; `/healthz` is the unauthenticated health probe.
- Heavy collectors run out of band into a Valkey-backed rendered snapshot: database, storage, and optional Docker. Routine scrapes reuse that snapshot instead of recomputing broad PostgreSQL aggregates.
- Live collectors run on each scrape: Valkey, HAProxy, private backend snapshot, and exporter self-health.
- GCS inventory metrics are intentionally excluded so observability does not create storage-listing cost or widen object visibility.
- Backend route latency comes from FastAPI middleware for `/api/*` responses only. It does not include the HAProxy restart page or React startup/loading screen, including their deliberate visible wait.

## Dashboard Contract

- Dashboard UID: `ads7jj6`; title: `Medusa`; datasource UID: `qgXJ0MD4k`.
- Variables: `ds`, `job`, `instance`, `route`, and `collector`.
- Panel types intentionally avoid Grafana `gauge`, `bargauge`, `table`, and explanatory text panels; use time series, stat sparklines, and occasional state timelines so the dashboard stays visual and glanceable.
- Every non-row panel must include a concise Grafana description for the information mouseover, naming what is measured and how to read the trend without adding visible diagnosis text to the dashboard.
- Panels must be unit-coherent and concept-coherent. Do not mix raw counts with percentage/ratio axes, currency with duration, or unrelated freshness signals in one graph. If a metric belongs near another panel but uses a different unit or answers a different question, split it into its own panel.
- Sparse or event-shaped metrics should not be stretched into wide per-label trend panels by default. Prefer aggregate envelopes, sample/activity companions, compact stats, or narrower detail panels so quiet periods do not become the dominant visual.
- Legends should remove repeated shared prefixes when the panel already supplies the context. Route latency legends strip the shared `/api/` prefix, and Medusa-scoped panels should not repeat `medusa_` in display labels.
- Graph-like panels use panel-local hover behavior: dashboard `graphTooltip` is `0`, so values appear only for the panel under the cursor. Every time series or state timeline panel uses multi-value tooltips for the hovered panel itself. Grafana's built-in shared-crosshair mode is intentionally not used because, on the local Grafana 13.1.0 instance, it suppresses the value tooltip instead of providing shared crosshair plus local values.
- First row must keep scrape health and exporter freshness visible, because stale Prometheus retention can otherwise make a broken scrape look healthy.

## Metric Catalog

Every metric emitted by the exporter source or observed in recent Prometheus retention is listed below. `job` and `instance` are Prometheus scrape labels; other labels are Medusa exporter labels. `Recent series` is the number of retained series observed during the 2026-07-02 inventory and may be zero for conditional metrics.

### Scrape And Exporter Health

| Metric | Type | Labels | Collector / refresh | Recent series | Meaning, dashboard use, and example PromQL |
| --- | --- | --- | --- | ---: | --- |
| `medusa_backend_snapshot_age_seconds` | `gauge` | `instance, job` | backend snapshot; live scrape | 1 | Age of the private backend metrics snapshot in seconds. Dashboard query: `medusa_backend_snapshot_age_seconds{job="$job", instance=~"$instance"}`. |
| `medusa_backend_snapshot_up` | `gauge` | `instance, job, reason` | backend snapshot; live scrape | 3 | Whether the private backend metrics snapshot is reachable. Dashboard query: `medusa_backend_snapshot_up{job="$job", instance=~"$instance"}`. |
| `medusa_exporter_build_info` | `gauge` | `git_sha, hostname, instance, job, version` | exporter; live scrape | 42 | Medusa metrics exporter build and host identity. Dashboard query: `medusa_exporter_build_info{job="$job", instance=~"$instance"}`. |
| `medusa_exporter_collector_cached` | `gauge` | `collector, instance, job` | exporter; live scrape | 6 | Whether the exporter collector came from the Valkey-backed heavy snapshot. Dashboard query: `medusa_exporter_collector_cached{job="$job", instance=~"$instance"}`. |
| `medusa_exporter_collector_duration_seconds` | `gauge` | `collector, instance, job` | exporter; live scrape | 6 | Exporter collector duration in seconds on its latest run. Dashboard query: `medusa_exporter_collector_duration_seconds{job="$job", instance=~"$instance"}`. |
| `medusa_exporter_collector_last_success_timestamp_seconds` | `gauge` | `collector, instance, job` | exporter; live scrape | 6 | Unix timestamp for the collector's last successful run. Dashboard query: `time() - medusa_exporter_collector_last_success_timestamp_seconds{job="$job", instance=~"$instance"}`. |
| `medusa_exporter_collector_up` | `gauge` | `collector, instance, job` | exporter; live scrape | 6 | Whether the exporter collector succeeded on its latest run. Dashboard query: `medusa_exporter_collector_up{job="$job", instance=~"$instance"}`. |
| `medusa_exporter_heavy_snapshot_age_seconds` | `gauge` | `instance, job` | exporter; live scrape | 1 | Age of the Valkey-backed heavy metrics snapshot in seconds. Dashboard query: `medusa_exporter_heavy_snapshot_age_seconds{job="$job", instance=~"$instance"}`. |
| `medusa_exporter_heavy_snapshot_duration_seconds` | `gauge` | `instance, job` | exporter; live scrape | 1 | Time spent generating the latest heavy metrics snapshot. Dashboard query: `medusa_exporter_heavy_snapshot_duration_seconds{job="$job", instance=~"$instance"}`. |
| `medusa_exporter_heavy_snapshot_samples` | `gauge` | `instance, job` | exporter; live scrape | 1 | Number of samples in the latest heavy metrics snapshot. Dashboard query: `medusa_exporter_heavy_snapshot_samples{job="$job", instance=~"$instance"}`. |
| `medusa_exporter_heavy_snapshot_up` | `gauge` | `instance, job, source` | exporter; live scrape | 1 | Whether the Valkey-backed heavy metrics snapshot is available. Dashboard query: `medusa_exporter_heavy_snapshot_up{job="$job", instance=~"$instance"}`. |
| `medusa_exporter_metric_samples` | `gauge` | `instance, job` | exporter; live scrape | 1 | Number of Prometheus metric samples rendered by this scrape. Dashboard query: `medusa_exporter_metric_samples{job="$job", instance=~"$instance"}`. |
| `medusa_exporter_scrape_duration_seconds` | `gauge` | `instance, job` | exporter; live scrape | 1 | Total exporter scrape duration in seconds. Dashboard query: `medusa_exporter_scrape_duration_seconds{job="$job", instance=~"$instance"}`. |
| `medusa_exporter_scrape_timestamp_seconds` | `gauge` | `instance, job` | exporter; live scrape | 1 | Unix timestamp for this exporter scrape. Dashboard query: `time() - medusa_exporter_scrape_timestamp_seconds{job="$job", instance=~"$instance"}`. |

### Backend And API

| Metric | Type | Labels | Collector / refresh | Recent series | Meaning, dashboard use, and example PromQL |
| --- | --- | --- | --- | ---: | --- |
| `medusa_backend_cpu_limit_cores` | `gauge` | `instance, job` | backend snapshot; live scrape | 0 | Backend cgroup CPU limit in cores. Dashboard query: `medusa_backend_cpu_limit_cores{job="$job", instance=~"$instance"}`. |
| `medusa_backend_cpu_usage_seconds_total` | `counter` | `instance, job` | backend snapshot; live scrape | 1 | Backend cgroup CPU usage seconds. Dashboard query: `rate(medusa_backend_cpu_usage_seconds_total{job="$job", instance=~"$instance"}[5m])`. |
| `medusa_backend_memory_bytes` | `gauge` | `instance, job, kind` | backend snapshot; live scrape | 3 | Backend memory usage by kind in bytes. Dashboard query: `medusa_backend_memory_bytes{job="$job", instance=~"$instance"}`. |
| `medusa_backend_process_uptime_seconds` | `gauge` | `instance, job` | backend snapshot; live scrape | 1 | Backend process uptime in seconds. Dashboard query: `medusa_backend_process_uptime_seconds{job="$job", instance=~"$instance"}`. |
| `medusa_backend_processes` | `gauge` | `instance, job` | backend snapshot; live scrape | 1 | Backend container process count. Dashboard query: `medusa_backend_processes{job="$job", instance=~"$instance"}`. |
| `medusa_backend_route_average_duration_seconds` | `gauge` | `instance, job, route` | backend snapshot; live scrape | 78 | Backend route average duration in seconds; dashboard panels multiply by `1000` and display milliseconds. Dashboard query: `medusa_backend_route_average_duration_seconds{job="$job", instance=~"$instance"}`. |
| `medusa_backend_route_last_status` | `gauge` | `instance, job, route` | backend snapshot; live scrape | 78 | Backend route latest HTTP status code. Dashboard query: `medusa_backend_route_last_status{job="$job", instance=~"$instance"}`. |
| `medusa_backend_route_p50_duration_seconds` | `gauge` | `instance, job, route` | backend snapshot; live scrape | 0 | Backend route p50 duration in seconds; dashboard panels multiply by `1000` and display milliseconds. Dashboard query: `medusa_backend_route_p50_duration_seconds{job="$job", instance=~"$instance"}`. |
| `medusa_backend_route_p90_duration_seconds` | `gauge` | `instance, job, route` | backend snapshot; live scrape | 0 | Backend route p90 duration in seconds; dashboard panels multiply by `1000` and display milliseconds. Dashboard query: `medusa_backend_route_p90_duration_seconds{job="$job", instance=~"$instance"}`. |
| `medusa_backend_route_p95_duration_seconds` | `gauge` | `instance, job, route` | backend snapshot; live scrape | 78 | Backend route p95 duration in seconds; dashboard panels multiply by `1000` and display milliseconds. Dashboard query: `medusa_backend_route_p95_duration_seconds{job="$job", instance=~"$instance"}`. |
| `medusa_backend_route_p99_duration_seconds` | `gauge` | `instance, job, route` | backend snapshot; live scrape | 0 | Backend route p99 duration in seconds; dashboard panels multiply by `1000` and display milliseconds. Dashboard query: `medusa_backend_route_p99_duration_seconds{job="$job", instance=~"$instance"}`. |
| `medusa_backend_route_samples` | `gauge` | `instance, job, route` | backend snapshot; live scrape | 78 | Backend route timing sample count. Dashboard query: `medusa_backend_route_samples{job="$job", instance=~"$instance"}`. |
| `medusa_backend_route_slow_requests` | `gauge` | `instance, job, route` | backend snapshot; live scrape | 78 | Backend route slow request count. Dashboard query: `medusa_backend_route_slow_requests{job="$job", instance=~"$instance"}`. |
| `medusa_backend_threads` | `gauge` | `instance, job` | backend snapshot; live scrape | 1 | Backend process thread count. Dashboard query: `medusa_backend_threads{job="$job", instance=~"$instance"}`. |

### TLS Certificates

| Metric | Type | Labels | Collector / refresh | Recent series | Meaning, dashboard use, and example PromQL |
| --- | --- | --- | --- | ---: | --- |
| `medusa_tls_certificate_days_remaining` | `gauge` | `host, instance, job, port, target` | tls_certificates; live scrape | 0 | Days remaining before the observed TLS certificate expires. Configure explicit public targets with `MEDUSA_METRICS_TLS_CERT_TARGETS=app=https://medusa.evan.engineer,cdn=https://assets.medusa.evan.engineer`. Dashboard query: `max(medusa_tls_certificate_days_remaining{job="$job", instance=~"$instance", target="app"})`. |
| `medusa_tls_certificate_expires_timestamp_seconds` | `gauge` | `host, instance, job, port, target` | tls_certificates; live scrape | 0 | Unix timestamp when the observed TLS certificate expires. Dashboard query: `medusa_tls_certificate_expires_timestamp_seconds{job="$job", instance=~"$instance"}`. |
| `medusa_tls_certificate_probe_up` | `gauge` | `host, instance, job, port, reason, target` | tls_certificates; live scrape | 0 | Whether the TLS certificate expiry probe succeeded. Dashboard query: `medusa_tls_certificate_probe_up{job="$job", instance=~"$instance"}`. |

### HAProxy

| Metric | Type | Labels | Collector / refresh | Recent series | Meaning, dashboard use, and example PromQL |
| --- | --- | --- | --- | ---: | --- |
| `medusa_haproxy_bytes_total` | `counter` | `direction, instance, job` | haproxy; live scrape | 2 | Total HAProxy frontend bytes. Dashboard query: `rate(medusa_haproxy_bytes_total{job="$job", instance=~"$instance"}[5m])`. |
| `medusa_haproxy_current_sessions` | `gauge` | `instance, job` | haproxy; live scrape | 1 | Current HAProxy frontend sessions. Dashboard query: `medusa_haproxy_current_sessions{job="$job", instance=~"$instance"}`. |
| `medusa_haproxy_errors_total` | `counter` | `instance, job` | haproxy; live scrape | 1 | Total HAProxy errors/retries/denials. Dashboard query: `rate(medusa_haproxy_errors_total{job="$job", instance=~"$instance"}[5m])`. |
| `medusa_haproxy_service_bytes_total` | `counter` | `direction, instance, job, kind, proxy, service, status` | haproxy; live scrape | 48 | Total HAProxy service bytes. Dashboard query: `rate(medusa_haproxy_service_bytes_total{job="$job", instance=~"$instance"}[5m])`. |
| `medusa_haproxy_service_check_duration_seconds` | `gauge` | `instance, job, kind, proxy, service, status` | haproxy; live scrape | 9 | Latest HAProxy service health-check duration. Dashboard query: `medusa_haproxy_service_check_duration_seconds{job="$job", instance=~"$instance"}`. |
| `medusa_haproxy_service_current_sessions` | `gauge` | `instance, job, kind, proxy, service, status` | haproxy; live scrape | 24 | Current HAProxy service sessions. Dashboard query: `medusa_haproxy_service_current_sessions{job="$job", instance=~"$instance"}`. |
| `medusa_haproxy_service_denied_total` | `counter` | `instance, job, kind, proxy, service, status` | haproxy; live scrape | 24 | Total HAProxy service denied requests/responses. Dashboard query: `rate(medusa_haproxy_service_denied_total{job="$job", instance=~"$instance"}[5m])`. |
| `medusa_haproxy_service_downtime_seconds` | `gauge` | `instance, job, kind, proxy, service, status` | haproxy; live scrape | 16 | HAProxy service downtime in seconds. Dashboard query: `medusa_haproxy_service_downtime_seconds{job="$job", instance=~"$instance"}`. |
| `medusa_haproxy_service_errors_total` | `counter` | `instance, job, kind, proxy, service, status` | haproxy; live scrape | 24 | Total HAProxy service errors. Dashboard query: `rate(medusa_haproxy_service_errors_total{job="$job", instance=~"$instance"}[5m])`. |
| `medusa_haproxy_service_last_change_seconds` | `gauge` | `instance, job, kind, proxy, service, status` | haproxy; live scrape | 19 | Seconds since HAProxy service status last changed. Dashboard query: `medusa_haproxy_service_last_change_seconds{job="$job", instance=~"$instance"}`. |
| `medusa_haproxy_service_redispatches_total` | `counter` | `instance, job, kind, proxy, service, status` | haproxy; live scrape | 24 | Total HAProxy service redispatches. Dashboard query: `rate(medusa_haproxy_service_redispatches_total{job="$job", instance=~"$instance"}[5m])`. |
| `medusa_haproxy_service_retries_total` | `counter` | `instance, job, kind, proxy, service, status` | haproxy; live scrape | 24 | Total HAProxy service retries. Dashboard query: `rate(medusa_haproxy_service_retries_total{job="$job", instance=~"$instance"}[5m])`. |
| `medusa_haproxy_service_session_rate` | `gauge` | `instance, job, kind, proxy, service, status` | haproxy; live scrape | 24 | Current HAProxy service session rate. Dashboard query: `medusa_haproxy_service_session_rate{job="$job", instance=~"$instance"}`. |
| `medusa_haproxy_service_sessions_total` | `counter` | `instance, job, kind, proxy, service, status` | haproxy; live scrape | 24 | Total HAProxy service sessions. Dashboard query: `rate(medusa_haproxy_service_sessions_total{job="$job", instance=~"$instance"}[5m])`. |
| `medusa_haproxy_sessions_total` | `counter` | `instance, job` | haproxy; live scrape | 1 | Total HAProxy frontend sessions. Dashboard query: `rate(medusa_haproxy_sessions_total{job="$job", instance=~"$instance"}[5m])`. |
| `medusa_haproxy_up` | `gauge` | `instance, job` | haproxy; live scrape | 1 | Whether HAProxy stats are reachable. Dashboard query: `medusa_haproxy_up{job="$job", instance=~"$instance"}`. |

### Valkey And Cache

| Metric | Type | Labels | Collector / refresh | Recent series | Meaning, dashboard use, and example PromQL |
| --- | --- | --- | --- | ---: | --- |
| `medusa_cache_backend_up` | `gauge` | `backend, instance, job` | backend snapshot; live scrape | 1 | Whether the configured Medusa response cache backend is reachable. Dashboard query: `medusa_cache_backend_up{job="$job", instance=~"$instance"}`. |
| `medusa_cache_family_events_total` | `counter` | `event, family, instance, job` | backend snapshot; live scrape | 25 | Backend process-local cache family event count. Dashboard query: `rate(medusa_cache_family_events_total{job="$job", instance=~"$instance"}[5m])`. |
| `medusa_cache_family_hit_rate` | `gauge` | `family, instance, job` | backend snapshot; live scrape | 5 | Backend process-local cache family hit rate. Dashboard query: `medusa_cache_family_hit_rate{job="$job", instance=~"$instance"}`. |
| `medusa_cache_hit_rate` | `gauge` | `backend, instance, job` | backend snapshot; live scrape | 1 | Current cache backend hit rate. Dashboard query: `medusa_cache_hit_rate{job="$job", instance=~"$instance"}`. |
| `medusa_cache_last_hydration_timestamp_seconds` | `gauge` | `instance, job` | backend snapshot; live scrape | 1 | Unix timestamp for latest cache hydration. Dashboard query: `time() - medusa_cache_last_hydration_timestamp_seconds{job="$job", instance=~"$instance"}`. |
| `medusa_cache_last_invalidation_timestamp_seconds` | `gauge` | `instance, job` | backend snapshot; live scrape | 1 | Unix timestamp for latest cache invalidation. Dashboard query: `time() - medusa_cache_last_invalidation_timestamp_seconds{job="$job", instance=~"$instance"}`. |
| `medusa_cache_last_refresh_timestamp_seconds` | `gauge` | `instance, job` | backend snapshot; live scrape | 1 | Unix timestamp for latest manual cache refresh. Dashboard query: `time() - medusa_cache_last_refresh_timestamp_seconds{job="$job", instance=~"$instance"}`. |
| `medusa_valkey_connected_clients` | `gauge` | `instance, job` | valkey; live scrape | 1 | Current Valkey connected clients. Dashboard query: `medusa_valkey_connected_clients{job="$job", instance=~"$instance"}`. |
| `medusa_valkey_error_info` | `gauge` | `error_class, instance, job` | valkey; live scrape | 0 | Class of the latest Valkey exporter error. Dashboard query: `medusa_valkey_error_info{job="$job", instance=~"$instance"}`. |
| `medusa_valkey_evicted_keys_total` | `counter` | `instance, job` | valkey; live scrape | 1 | Valkey evicted keys total. Dashboard query: `rate(medusa_valkey_evicted_keys_total{job="$job", instance=~"$instance"}[5m])`. |
| `medusa_valkey_expired_keys_total` | `counter` | `instance, job` | valkey; live scrape | 1 | Valkey expired keys total. Dashboard query: `rate(medusa_valkey_expired_keys_total{job="$job", instance=~"$instance"}[5m])`. |
| `medusa_valkey_info` | `gauge` | `instance, job, policy, version` | valkey; live scrape | 1 | Valkey version and memory policy. Dashboard query: `medusa_valkey_info{job="$job", instance=~"$instance"}`. |
| `medusa_valkey_keys` | `gauge` | `instance, job` | valkey; live scrape | 1 | Current Valkey key count. Dashboard query: `medusa_valkey_keys{job="$job", instance=~"$instance"}`. |
| `medusa_valkey_keyspace_hits_total` | `counter` | `instance, job` | valkey; live scrape | 1 | Valkey keyspace hits total. Dashboard query: `rate(medusa_valkey_keyspace_hits_total{job="$job", instance=~"$instance"}[5m])`. |
| `medusa_valkey_keyspace_misses_total` | `counter` | `instance, job` | valkey; live scrape | 1 | Valkey keyspace misses total. Dashboard query: `rate(medusa_valkey_keyspace_misses_total{job="$job", instance=~"$instance"}[5m])`. |
| `medusa_valkey_memory_bytes` | `gauge` | `instance, job, kind` | valkey; live scrape | 4 | Valkey memory by kind in bytes. Dashboard plots `used`, `rss`, and `peak` from `medusa_valkey_memory_bytes{job="$job", instance=~"$instance", kind!="max"}`; the configured `max` is rendered as the Grafana threshold line at the top of the panel. |
| `medusa_valkey_ops_per_second` | `gauge` | `instance, job` | valkey; live scrape | 1 | Current Valkey instantaneous operations per second. Dashboard query: `medusa_valkey_ops_per_second{job="$job", instance=~"$instance"}`. |
| `medusa_valkey_up` | `gauge` | `backend, instance, job` | valkey; live scrape | 1 | Whether Valkey is configured and reachable. Dashboard query: `medusa_valkey_up{job="$job", instance=~"$instance"}`. |
| `medusa_valkey_uptime_seconds` | `gauge` | `instance, job` | valkey; live scrape | 1 | Valkey uptime in seconds. Dashboard query: `medusa_valkey_uptime_seconds{job="$job", instance=~"$instance"}`. |

### Database

| Metric | Type | Labels | Collector / refresh | Recent series | Meaning, dashboard use, and example PromQL |
| --- | --- | --- | --- | ---: | --- |
| `medusa_database_info` | `gauge` | `dialect, instance, job` | database; heavy snapshot | 1 | Database identity for the Medusa metrics exporter. Dashboard query: `medusa_database_info{job="$job", instance=~"$instance"}`. |
| `medusa_database_relation_dead_tuples` | `gauge` | `instance, job, kind, relation` | database; heavy snapshot | 49 | PostgreSQL estimated dead tuples for public tables. Dashboard query: `medusa_database_relation_dead_tuples{job="$job", instance=~"$instance"}`. |
| `medusa_database_relation_heap_bytes` | `gauge` | `instance, job, kind, relation` | database; heavy snapshot | 49 | PostgreSQL public relation heap or index bytes. Dashboard query: `medusa_database_relation_heap_bytes{job="$job", instance=~"$instance"}`. |
| `medusa_database_relation_last_analyze_timestamp_seconds` | `gauge` | `instance, job, kind, relation` | database; heavy snapshot | 24 | Unix timestamp for latest analyze by public table. Dashboard query: `time() - medusa_database_relation_last_analyze_timestamp_seconds{job="$job", instance=~"$instance"}`. |
| `medusa_database_relation_last_vacuum_timestamp_seconds` | `gauge` | `instance, job, kind, relation` | database; heavy snapshot | 23 | Unix timestamp for latest vacuum by public table. Dashboard query: `time() - medusa_database_relation_last_vacuum_timestamp_seconds{job="$job", instance=~"$instance"}`. |
| `medusa_database_relation_live_tuples` | `gauge` | `instance, job, kind, relation` | database; heavy snapshot | 49 | PostgreSQL estimated live tuples for public tables. Dashboard query: `medusa_database_relation_live_tuples{job="$job", instance=~"$instance"}`. |
| `medusa_database_relation_size_bytes` | `gauge` | `instance, job, kind, relation` | database; heavy snapshot | 49 | PostgreSQL public relation total size in bytes. Dashboard query: `medusa_database_relation_size_bytes{job="$job", instance=~"$instance"}`. |
| `medusa_database_size_bytes` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Current PostgreSQL database size in bytes. Dashboard query: `medusa_database_size_bytes{job="$job", instance=~"$instance"}`. |
| `medusa_database_table_rows` | `gauge` | `instance, job, table` | database; heavy snapshot | 35 | Current row count for core Medusa tables. Dashboard query: `medusa_database_table_rows{job="$job", instance=~"$instance"}`. |

### Database Maintenance

| Metric | Type | Labels | Collector / refresh | Recent series | Meaning, dashboard use, and example PromQL |
| --- | --- | --- | --- | ---: | --- |
| `medusa_database_maintenance_active` | `gauge` | `instance, job, operation` | backend snapshot; live scrape | 2 | Whether database maintenance is active. Dashboard query: `medusa_database_maintenance_active{job="$job", instance=~"$instance"}`. |
| `medusa_database_maintenance_document_hash_missing_records` | `gauge` | `instance, job` | backend snapshot; live scrape | 1 | Database maintenance status count. Dashboard query: `medusa_database_maintenance_document_hash_missing_records{job="$job", instance=~"$instance"}`. |
| `medusa_database_maintenance_elapsed_seconds` | `gauge` | `instance, job, operation` | backend snapshot; live scrape | 1 | Active database maintenance elapsed seconds. Dashboard query: `medusa_database_maintenance_elapsed_seconds{job="$job", instance=~"$instance"}`. |
| `medusa_database_maintenance_hidden_project_items` | `gauge` | `instance, job` | backend snapshot; live scrape | 1 | Database maintenance status count. Dashboard query: `medusa_database_maintenance_hidden_project_items{job="$job", instance=~"$instance"}`. |
| `medusa_database_maintenance_import_cache_records` | `gauge` | `instance, job` | backend snapshot; live scrape | 1 | Database maintenance status count. Dashboard query: `medusa_database_maintenance_import_cache_records{job="$job", instance=~"$instance"}`. |
| `medusa_database_maintenance_orphan_import_jobs` | `gauge` | `instance, job` | backend snapshot; live scrape | 1 | Database maintenance status count. Dashboard query: `medusa_database_maintenance_orphan_import_jobs{job="$job", instance=~"$instance"}`. |
| `medusa_database_maintenance_terminal_import_jobs` | `gauge` | `instance, job` | backend snapshot; live scrape | 1 | Database maintenance status count. Dashboard query: `medusa_database_maintenance_terminal_import_jobs{job="$job", instance=~"$instance"}`. |

### Storage

| Metric | Type | Labels | Collector / refresh | Recent series | Meaning, dashboard use, and example PromQL |
| --- | --- | --- | --- | ---: | --- |
| `medusa_document_cache_file_records` | `gauge` | `instance, job` | storage; heavy snapshot | 1 | Current managed document cache file count. Dashboard query: `medusa_document_cache_file_records{job="$job", instance=~"$instance"}`. |
| `medusa_document_cache_limit_bytes` | `gauge` | `instance, job` | storage; heavy snapshot | 1 | Configured managed document cache size limit in bytes. Dashboard query: `medusa_document_cache_limit_bytes{job="$job", instance=~"$instance"}`. |
| `medusa_document_cache_size_bytes` | `gauge` | `instance, job` | storage; heavy snapshot | 1 | Current managed document cache size in bytes. Dashboard query: `medusa_document_cache_size_bytes{job="$job", instance=~"$instance"}`. |
| `medusa_storage_footprint_bytes` | `gauge` | `instance, job, storage_area` | storage; heavy snapshot | 4 | Current local Medusa storage footprint by bounded area. Dashboard query: `medusa_storage_footprint_bytes{job="$job", instance=~"$instance"}`. |
| `medusa_storage_footprint_exists` | `gauge` | `instance, job, storage_area` | storage; heavy snapshot | 4 | Whether a local Medusa storage area exists. Dashboard query: `medusa_storage_footprint_exists{job="$job", instance=~"$instance"}`. |
| `medusa_storage_footprint_files` | `gauge` | `instance, job, storage_area` | storage; heavy snapshot | 4 | Current local Medusa storage file count by bounded area. Dashboard query: `medusa_storage_footprint_files{job="$job", instance=~"$instance"}`. |

### Work Queues

| Metric | Type | Labels | Collector / refresh | Recent series | Meaning, dashboard use, and example PromQL |
| --- | --- | --- | --- | ---: | --- |
| `medusa_accessory_summary_records` | `gauge` | `attempt_bucket, instance, job, model, status` | observed live series; Prometheus retention | 1 | Observed in Prometheus retention; see exporter source for semantics. Dashboard query: `medusa_accessory_summary_records{job="$job", instance=~"$instance"}`. |
| `medusa_concordance_jobs` | `gauge` | `attempt_bucket, capability_key, instance, job, status, target_version` | observed live series; Prometheus retention | 43 | Observed in Prometheus retention; see exporter source for semantics. Dashboard query: `medusa_concordance_jobs{job="$job", instance=~"$instance"}`. |
| `medusa_concordance_run_jobs` | `gauge` | `instance, job, scope_type, state, status` | database; heavy snapshot | 12 | Current Concordance run job progress count. Dashboard query: `medusa_concordance_run_jobs{job="$job", instance=~"$instance"}`. |
| `medusa_concordance_runs` | `gauge` | `instance, job, scope_type, status` | database; heavy snapshot | 4 | Current Concordance run count. Dashboard query: `medusa_concordance_runs{job="$job", instance=~"$instance"}`. |
| `medusa_import_batch_files` | `gauge` | `instance, job, state, status` | database; heavy snapshot | 12 | Current import batch file progress count. Dashboard query: `medusa_import_batch_files{job="$job", instance=~"$instance"}`. |
| `medusa_import_batches` | `gauge` | `instance, job, status` | database; heavy snapshot | 4 | Current import batch count. Dashboard query: `medusa_import_batches{job="$job", instance=~"$instance"}`. |
| `medusa_import_job_stale_running_records` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Current running import jobs with a lock older than the configured stale-job threshold. Dashboard query: `medusa_import_job_stale_running_records{job="$job", instance=~"$instance"}`. |
| `medusa_import_jobs` | `gauge` | `attempt_bucket, current_step, instance, job, status` | observed live series; Prometheus retention | 22 | Observed in Prometheus retention; see exporter source for semantics. Dashboard query: `medusa_import_jobs{job="$job", instance=~"$instance"}`. |
| `medusa_processing_event_records` | `gauge` | `event_type, instance, job, level` | database; heavy snapshot | 51 | Current processing event count by bounded event type. Dashboard query: `medusa_processing_event_records{job="$job", instance=~"$instance"}`. |
| `medusa_queue_oldest_age_seconds` | `gauge` | `instance, job, queue` | exporter; live scrape | 2 | Oldest active import or Concordance queue item age in seconds. The dashboard adds explicit zero fallback series for empty `import` and `concordance` queues. Dashboard query: `medusa_queue_oldest_age_seconds{job="$job", instance=~"$instance"}`. |

### Slipstream

| Metric | Type | Labels | Collector / refresh | Recent series | Meaning, dashboard use, and example PromQL |
| --- | --- | --- | --- | ---: | --- |
| `medusa_slipstream_client_capacity` | `gauge` | `instance, job, status` | database; heavy snapshot | 2 | Current Slipstream client declared capacity. Dashboard query: `medusa_slipstream_client_capacity{job="$job", instance=~"$instance"}`. |
| `medusa_slipstream_clients` | `gauge` | `instance, job, status` | database; heavy snapshot | 2 | Current Slipstream client count. Dashboard query: `medusa_slipstream_clients{job="$job", instance=~"$instance"}`. |
| `medusa_slipstream_leases` | `gauge` | `instance, job, job_type, status, worker_kind` | database; heavy snapshot | 11 | Current Slipstream lease count. Dashboard query: `medusa_slipstream_leases{job="$job", instance=~"$instance"}`. |

### Library And Corpus

| Metric | Type | Labels | Collector / refresh | Recent series | Meaning, dashboard use, and example PromQL |
| --- | --- | --- | --- | ---: | --- |
| `medusa_annotations` | `gauge` | `instance, job, kind` | database; heavy snapshot | 0 | Current active annotation count for library-visible documents. Dashboard query: `medusa_annotations{job="$job", instance=~"$instance"}`. |
| `medusa_document_attribute_values` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Current document attribute value count. Dashboard query: `medusa_document_attribute_values{job="$job", instance=~"$instance"}`. |
| `medusa_document_capability_records` | `gauge` | `capability_key, instance, job, status, version` | database; heavy snapshot | 27 | Current document capability completion count. Dashboard query: `medusa_document_capability_records{job="$job", instance=~"$instance"}`. |
| `medusa_document_domain_links` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Current document-domain link count. Dashboard query: `medusa_document_domain_links{job="$job", instance=~"$instance"}`. |
| `medusa_document_page_records` | `gauge` | `instance, job, low_text, text_source` | database; heavy snapshot | 6 | Current page record count for library-visible documents. Dashboard query: `medusa_document_page_records{job="$job", instance=~"$instance"}`. |
| `medusa_document_records` | `gauge` | `citation_status, document_kind, instance, job, priority, processing_status, read_status` | database; heavy snapshot | 7 | Current non-deleted document count grouped by bounded document states. Dashboard query: `medusa_document_records{job="$job", instance=~"$instance"}`. |
| `medusa_document_soft_deleted_records` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Current soft-deleted document count. Dashboard query: `medusa_document_soft_deleted_records{job="$job", instance=~"$instance"}`. |
| `medusa_document_tag_links` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Current document-tag link count. Dashboard query: `medusa_document_tag_links{job="$job", instance=~"$instance"}`. |
| `medusa_figures` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Current figure count for library-visible documents. Dashboard query: `medusa_figures{job="$job", instance=~"$instance"}`. |
| `medusa_library_documents` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Current aggregate for library-visible documents. Dashboard query: `medusa_library_documents{job="$job", instance=~"$instance"}`. |
| `medusa_library_doi_records` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Current aggregate for library-visible documents. Dashboard query: `medusa_library_doi_records{job="$job", instance=~"$instance"}`. |
| `medusa_library_doi_covered_records` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Library-visible documents with either a recorded DOI or an explicit confirmed `No DOI` decision in document metadata evidence. Dashboard query: `medusa_library_doi_covered_records{job="$job", instance=~"$instance"} / clamp_min(medusa_library_documents{job="$job", instance=~"$instance"}, 1)`. |
| `medusa_library_duplicate_flagged_records` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Current aggregate for library-visible documents. Dashboard query: `medusa_library_duplicate_flagged_records{job="$job", instance=~"$instance"}`. |
| `medusa_library_duplicate_references` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Current aggregate for library-visible documents. Dashboard query: `medusa_library_duplicate_references{job="$job", instance=~"$instance"}`. |
| `medusa_library_indexed_character_records` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Current aggregate for library-visible documents. Dashboard query: `medusa_library_indexed_character_records{job="$job", instance=~"$instance"}`. |
| `medusa_library_indexed_word_records` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Current aggregate for library-visible documents. Dashboard query: `medusa_library_indexed_word_records{job="$job", instance=~"$instance"}`. |
| `medusa_library_missing_bibliography_records` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Current aggregate for library-visible documents. Dashboard query: `medusa_library_missing_bibliography_records{job="$job", instance=~"$instance"}`. |
| `medusa_library_missing_search_text_records` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Current aggregate for library-visible documents. Dashboard query: `medusa_library_missing_search_text_records{job="$job", instance=~"$instance"}`. |
| `medusa_library_missing_summary_records` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Current aggregate for library-visible documents. Dashboard query: `medusa_library_missing_summary_records{job="$job", instance=~"$instance"}`. |
| `medusa_library_needs_review_citations` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Current aggregate for library-visible documents. Dashboard query: `medusa_library_needs_review_citations{job="$job", instance=~"$instance"}`. |
| `medusa_library_pages` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Current aggregate for library-visible documents. Dashboard query: `medusa_library_pages{job="$job", instance=~"$instance"}`. |
| `medusa_library_parsed_character_records` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Current parsed page text aggregate for library-visible documents. Dashboard query: `medusa_library_parsed_character_records{job="$job", instance=~"$instance"}`. |
| `medusa_library_parsed_word_records` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Current parsed page text aggregate for library-visible documents. Dashboard query: `medusa_library_parsed_word_records{job="$job", instance=~"$instance"}`. |
| `medusa_library_verified_citations` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Current aggregate for library-visible documents. Dashboard query: `medusa_library_verified_citations{job="$job", instance=~"$instance"}`. |
| `medusa_note_reminders_due` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Current active notes with due reminders. Dashboard query: `medusa_note_reminders_due{job="$job", instance=~"$instance"}`. |
| `medusa_text_chunks` | `gauge` | `instance, job` | observed live series; Prometheus retention | 1 | Observed in Prometheus retention; see exporter source for semantics. Dashboard query: `medusa_text_chunks{job="$job", instance=~"$instance"}`. |
| `medusa_text_embedded_chunk_records` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Current text chunk aggregate for library-visible documents. Dashboard query: `medusa_text_embedded_chunk_records{job="$job", instance=~"$instance"}`. |
| `medusa_text_token_records` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Current text chunk aggregate for library-visible documents. Dashboard query: `medusa_text_token_records{job="$job", instance=~"$instance"}`. |

### Organization And Workspaces

| Metric | Type | Labels | Collector / refresh | Recent series | Meaning, dashboard use, and example PromQL |
| --- | --- | --- | --- | ---: | --- |
| `medusa_attribute_definitions` | `gauge` | `instance, job, value_type` | database; heavy snapshot | 1 | Current active attribute definition count. Dashboard query: `medusa_attribute_definitions{job="$job", instance=~"$instance"}`. |
| `medusa_doi_stashes` | `gauge` | `import_state, instance, job, provider, status` | database; heavy snapshot | 3 | Current DOI stash count. Dashboard query: `medusa_doi_stashes{job="$job", instance=~"$instance"}`. |
| `medusa_domains` | `gauge` | `instance, job, scope` | database; heavy snapshot | 2 | Current active domain count. Dashboard query: `medusa_domains{job="$job", instance=~"$instance"}`. |
| `medusa_portfolio_items` | `gauge` | `instance, job, status` | observed live series; Prometheus retention | 1 | Observed in Prometheus retention; see exporter source for semantics. Dashboard query: `medusa_portfolio_items{job="$job", instance=~"$instance"}`. |
| `medusa_project_bibliographies` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Current generated project bibliography count. Dashboard query: `medusa_project_bibliographies{job="$job", instance=~"$instance"}`. |
| `medusa_project_items` | `gauge` | `instance, job, priority, status, used_in_output` | database; heavy snapshot | 2 | Current project resource count. Dashboard query: `medusa_project_items{job="$job", instance=~"$instance"}`. |
| `medusa_projects` | `gauge` | `instance, job, status` | database; heavy snapshot | 1 | Current active project count. Dashboard query: `medusa_projects{job="$job", instance=~"$instance"}`. |
| `medusa_recommendations` | `gauge` | `instance, job, known_status, open_pdf_available, provider, relation_family, status` | database; heavy snapshot | 54 | Current related-paper recommendation count. Dashboard query: `medusa_recommendations{job="$job", instance=~"$instance"}`. |
| `medusa_saved_searches` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Current active saved search count. Dashboard query: `medusa_saved_searches{job="$job", instance=~"$instance"}`. |
| `medusa_tag_aliases` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Current tag alias count. Dashboard query: `medusa_tag_aliases{job="$job", instance=~"$instance"}`. |
| `medusa_tag_assessments` | `gauge` | `decision, instance, job, source, status` | database; heavy snapshot | 37 | Current document tag assessment count. Dashboard query: `medusa_tag_assessments{job="$job", instance=~"$instance"}`. |
| `medusa_tag_relationships` | `gauge` | `instance, job, relationship_type, status` | database; heavy snapshot | 2 | Current tag relationship count. Dashboard query: `medusa_tag_relationships{job="$job", instance=~"$instance"}`. |
| `medusa_tags` | `gauge` | `instance, job, kind, status` | database; heavy snapshot | 3 | Current tag count. Dashboard query: `medusa_tags{job="$job", instance=~"$instance"}`. |

### AI Costs And Pricing

| Metric | Type | Labels | Collector / refresh | Recent series | Meaning, dashboard use, and example PromQL |
| --- | --- | --- | --- | ---: | --- |
| `medusa_ai_usage_input_file_bytes` | `gauge` | `instance, job, model, provider, source, status, task_key` | database; heavy snapshot | 38 | Current AI usage input file-context bytes. Dashboard query: `medusa_ai_usage_input_file_bytes{job="$job", instance=~"$instance"}`. |
| `medusa_ai_usage_last_failure_timestamp_seconds` | `gauge` | `instance, job` | database; heavy snapshot | 1 | Unix timestamp for the latest failed AI usage ledger call. Dashboard query: `time() - medusa_ai_usage_last_failure_timestamp_seconds{job="$job", instance=~"$instance"}`. |
| `medusa_ai_usage_request_records` | `gauge` | `instance, job, model, provider, source, status, task_key` | database; heavy snapshot | 38 | Current AI usage ledger request count. Dashboard query: `medusa_ai_usage_request_records{job="$job", instance=~"$instance"}`. |
| `medusa_ai_usage_text_characters` | `gauge` | `direction, instance, job, model, provider, source, status, task_key` | database; heavy snapshot | 76 | Current AI usage text character totals. Dashboard query: `medusa_ai_usage_text_characters{job="$job", instance=~"$instance"}`. |
| `medusa_ai_usage_tokens` | `gauge` | `instance, job, model, provider, source, status, task_key, token_type` | database; heavy snapshot | 190 | Current AI usage ledger token totals. Dashboard query: `medusa_ai_usage_tokens{job="$job", instance=~"$instance"}`. |
| `medusa_composition_amount_usd` | `gauge` | `instance, job, model, provider, record_kind, stage_key, status` | database; heavy snapshot | 63 | Current document composition ledger dollar amount. Dashboard query: `medusa_composition_amount_usd{job="$job", instance=~"$instance"}`. |
| `medusa_composition_duration_seconds` | `gauge` | `instance, job, model, provider, record_kind, stage_key, status` | database; heavy snapshot | 63 | Current document composition ledger duration seconds. Dashboard query: `medusa_composition_duration_seconds{job="$job", instance=~"$instance"}`. |
| `medusa_composition_record_records` | `gauge` | `instance, job, model, provider, record_kind, stage_key, status` | database; heavy snapshot | 63 | Current document composition ledger row count. Dashboard query: `medusa_composition_record_records{job="$job", instance=~"$instance"}`. |
| `medusa_composition_tokens` | `gauge` | `instance, job, model, provider, record_kind, stage_key, status, token_type` | database; heavy snapshot | 189 | Current document composition ledger token totals. Dashboard query: `medusa_composition_tokens{job="$job", instance=~"$instance"}`. |
| `medusa_model_pricing_current_records` | `gauge` | `instance, job, price_basis, provider` | database; heavy snapshot | 3 | Current active model pricing record count. Dashboard query: `medusa_model_pricing_current_records{job="$job", instance=~"$instance"}`. |
| `medusa_model_pricing_last_checked_timestamp_seconds` | `gauge` | `instance, job, price_basis, provider` | database; heavy snapshot | 3 | Unix timestamp for latest model pricing check. Dashboard query: `time() - medusa_model_pricing_last_checked_timestamp_seconds{job="$job", instance=~"$instance"}`. |

### Backups

| Metric | Type | Labels | Collector / refresh | Recent series | Meaning, dashboard use, and example PromQL |
| --- | --- | --- | --- | ---: | --- |
| `medusa_backup_latest_age_seconds` | `gauge` | `instance, job, phase, status` | database; heavy snapshot | 2 | Age of the latest completed database backup in seconds. Dashboard query: `medusa_backup_latest_age_seconds{job="$job", instance=~"$instance"}`. |
| `medusa_backup_latest_size_bytes` | `gauge` | `instance, job, phase, status` | database; heavy snapshot | 1 | Latest database backup size in bytes. Dashboard query: `medusa_backup_latest_size_bytes{job="$job", instance=~"$instance"}`. |
| `medusa_backup_latest_verified` | `gauge` | `instance, job, phase, status` | database; heavy snapshot | 4 | Whether the latest database backup carries verification evidence. Dashboard query: `medusa_backup_latest_verified{job="$job", instance=~"$instance"}`. |
| `medusa_backup_runs` | `gauge` | `instance, job, kind, phase, status` | database; heavy snapshot | 6 | Current backup/restore run count. Dashboard query: `medusa_backup_runs{job="$job", instance=~"$instance"}`. |

### Release And Maintenance

| Metric | Type | Labels | Collector / refresh | Recent series | Meaning, dashboard use, and example PromQL |
| --- | --- | --- | --- | ---: | --- |
| `medusa_maintenance_active_session_records` | `gauge` | `instance, job, phase` | backend snapshot; live scrape | 7 | Active session count reported by maintenance readiness. Dashboard query: `medusa_maintenance_active_session_records{job="$job", instance=~"$instance"}`. |
| `medusa_maintenance_idle` | `gauge` | `instance, job, phase` | backend snapshot; live scrape | 7 | Whether release maintenance reports an idle app. Dashboard query: `medusa_maintenance_idle{job="$job", instance=~"$instance"}`. |
| `medusa_release_apply_available` | `gauge` | `instance, job, phase` | backend snapshot; live scrape | 6 | Whether a Medusa release apply is available. Dashboard query: `medusa_release_apply_available{job="$job", instance=~"$instance"}`. |
| `medusa_release_browser_reload_recommended` | `gauge` | `instance, job, phase` | backend snapshot; live scrape | 6 | Whether browser reload is recommended. Dashboard query: `medusa_release_browser_reload_recommended{job="$job", instance=~"$instance"}`. |
| `medusa_release_dirty` | `gauge` | `instance, job, phase` | backend snapshot; live scrape | 6 | Whether the host release status reports a dirty checkout. Dashboard query: `medusa_release_dirty{job="$job", instance=~"$instance"}`. |
| `medusa_release_update_available` | `gauge` | `instance, job, phase` | backend snapshot; live scrape | 6 | Whether a Medusa release update is available. Dashboard query: `medusa_release_update_available{job="$job", instance=~"$instance"}`. |

### Optional Docker

| Metric | Type | Labels | Collector / refresh | Recent series | Meaning, dashboard use, and example PromQL |
| --- | --- | --- | --- | ---: | --- |
| `medusa_docker_container_block_io_bytes_total` | `counter` | `instance, job, service` | docker; heavy snapshot, optional | 0 | Docker container block I/O bytes. Dashboard query: `rate(medusa_docker_container_block_io_bytes_total{job="$job", instance=~"$instance"}[5m])`. |
| `medusa_docker_container_cpu_seconds_total` | `counter` | `instance, job, service` | docker; heavy snapshot, optional | 0 | Docker container CPU usage seconds. Dashboard query: `rate(medusa_docker_container_cpu_seconds_total{job="$job", instance=~"$instance"}[5m])`. |
| `medusa_docker_container_image_layer_records` | `gauge` | `instance, job, service` | docker; heavy snapshot, optional | 0 | Docker image layer count for the container image. Dashboard query: `medusa_docker_container_image_layer_records{job="$job", instance=~"$instance"}`. |
| `medusa_docker_container_image_size_bytes` | `gauge` | `instance, job, service` | docker; heavy snapshot, optional | 0 | Docker container root filesystem image size in bytes. Dashboard query: `medusa_docker_container_image_size_bytes{job="$job", instance=~"$instance"}`. |
| `medusa_docker_container_memory_bytes` | `gauge` | `instance, job, service` | docker; heavy snapshot, optional | 0 | Docker container memory by kind in bytes. Dashboard query: `medusa_docker_container_memory_bytes{job="$job", instance=~"$instance"}`. |
| `medusa_docker_container_network_bytes_total` | `counter` | `instance, job, service` | docker; heavy snapshot, optional | 0 | Docker container network bytes. Dashboard query: `rate(medusa_docker_container_network_bytes_total{job="$job", instance=~"$instance"}[5m])`. |
| `medusa_docker_container_restart_records` | `gauge` | `instance, job, service` | docker; heavy snapshot, optional | 0 | Docker container restart count. Dashboard query: `medusa_docker_container_restart_records{job="$job", instance=~"$instance"}`. |
| `medusa_docker_container_started_timestamp_seconds` | `gauge` | `instance, job, service` | docker; heavy snapshot, optional | 0 | Docker container started timestamp. Dashboard query: `time() - medusa_docker_container_started_timestamp_seconds{job="$job", instance=~"$instance"}`. |
| `medusa_docker_container_state_records` | `gauge` | `instance, job, service` | docker; heavy snapshot, optional | 0 | Docker container count by Compose service and state. Dashboard query: `medusa_docker_container_state_records{job="$job", instance=~"$instance"}`. |
| `medusa_docker_container_writable_layer_bytes` | `gauge` | `instance, job, service` | docker; heavy snapshot, optional | 0 | Docker container writable layer size in bytes. Dashboard query: `medusa_docker_container_writable_layer_bytes{job="$job", instance=~"$instance"}`. |
| `medusa_docker_up` | `gauge` | `instance, job, reason` | docker; heavy snapshot, optional | 1 | Whether Docker Engine metrics are reachable. Dashboard query: `medusa_docker_up{job="$job", instance=~"$instance"}`. |

### Other

| Metric | Type | Labels | Collector / refresh | Recent series | Meaning, dashboard use, and example PromQL |
| --- | --- | --- | --- | ---: | --- |
| `medusa_notes` | `gauge` | `instance, job, kind, target` | database; heavy snapshot | 0 | Current active note count grouped by kind and attachment target. Dashboard query: `medusa_notes{job="$job", instance=~"$instance"}`. |

## Dashboard Rows

- Top strip: standalone corpus stats for total documents, total pages, citation verification coverage, DOI coverage, main-app certificate days remaining, and CDN certificate days remaining. DOI coverage counts documents with an actual DOI plus documents explicitly confirmed/verified as having no DOI. Certificate countdowns are green above 14 days, yellow from 7 to 14 days, and red below 7 days.
- `Scrape And Exporter Health`: target up/down, last exporter sample age, scrape pulse, exporter scrape duration/sample count, heavy snapshot age/duration, and collector quorum.
- `Work In Flight`: moving in-flight job counts by family for imports, Concordance, Inquests/accessory summaries, and backup/restore runs; queue age with zero rendering when no queue is active; detailed import/Concordance queue status, processing events, and Slipstream capacity/leases. The row avoids reduced total/list panels because in-flight work is a point-in-time moving value.
- `API And Proxy`: route p50, p95, and p99 latency in milliseconds using shortened route labels without the shared `/api/` prefix, route status mix by HTTP class, backend resource trends, HAProxy sessions, bytes, errors, retries, and service state.
- `Cache And Valkey`: cache hit rates, cache-family events, Valkey memory, keys, ops, evictions, and expirations.
- `Library And Storage`: library size, citation/DOI coverage ratios, extraction gaps, duplicate signals, document cache usage, and local storage footprint.
- `Database And Maintenance`: PostgreSQL size, live/dead tuple pressure, vacuum/analyze age, and maintenance cleanup counters in a balanced two-column layout.
- `AI, Cost, And Pricing`: AI request/tokens/file-context volume, composition spend, composition speed, latest AI failure age, and model-pricing freshness as separate unit-coherent panels. Composition spend/speed aggregate by stage and status in the dashboard; raw provider/model labels remain in the metrics for drill-down but are not displayed as leading legend text.
- `Backups And Releases`: latest backup age/size/verification, backup runs by status, release flags, maintenance idleness, and active sessions.

## Validation Checklist

Use these checks after exporter or dashboard changes:

```bash
jq empty deploy/grafana/medusa-dashboard.json
jq -r '.. | objects | select(has("type")) | .type' deploy/grafana/medusa-dashboard.json | rg '^(gauge|bargauge)$' && exit 1 || true
python3 -m json.tool deploy/grafana/medusa-dashboard.json >/dev/null
```

For live checks, query Prometheus through the configured datasource target and verify that dashboard PromQL returns `status=success`. If `up{job="medusa"}` is `0`, fix the scrape target/certificate mismatch before trusting freshness-sensitive panels.
