# Medusa Local Operations

Last updated: 2026-06-30

This guide keeps local setup, runtime commands, credentials, maintenance, and safety behavior out of the product-facing README. Product and architecture decisions belong in `docs/ARCHITECTURE.md`; planned work belongs in `TODO.md`.

## Quick Start

Create a local environment file:

```bash
cp .env.example .env
```

Set at least:

```bash
MEDUSA_PASSWORD=your-local-password
MEDUSA_ALLOW_DEFAULT_PASSWORD=false
```

For a single-user local instance where the browser should sign in automatically, set:

```bash
MEDUSA_LOCAL_AUTO_LOGIN=true
```

Leave auto-login disabled on LAN or public deployments. It creates a normal admin session automatically when the browser has no valid cookie, bypassing password and two-factor prompts.

Install HAProxy TLS certificate material under ignored local data storage:

```bash
mkdir -p data/haproxy
cp /path/to/fullchain.pem data/haproxy/fullchain.pem
cp /path/to/privatekey.pem data/haproxy/privatekey.pem
chgrp 99 data/haproxy data/haproxy/*.pem
chmod 750 data/haproxy
chmod 640 data/haproxy/*.pem
```

Start the app:

```bash
docker compose up --build
```

Open:

```text
https://medusa.home.musial.io:3737
```

Backend startup runs Alembic migrations for PostgreSQL before serving traffic. The base Compose stack exposes only HAProxy on `MEDUSA_HAPROXY_PORT`, defaulting to port `3737`; backend, worker, database, frontend, and Valkey stay on internal Compose networks.

The login email defaults to `admin@medusa.local`, and the first admin password comes from `MEDUSA_PASSWORD`. After first boot, the live password is the hash stored on the PostgreSQL `users` row. Settings > Account changes the live login email or password and can enable authenticator-app 2FA plus recovery codes.

## Runtime And Proxy

The base Docker Compose app stack runs HAProxy as the host-exposed service. HAProxy terminates TLS, redirects HTTP on the same port to HTTPS, routes `/api/*` to the backend, and routes browser assets to the frontend. Certificate files belong in ignored `data/haproxy/fullchain.pem` and `data/haproxy/privatekey.pem`; do not commit private keys.

Common proxy settings:

```bash
MEDUSA_PUBLIC_HOST=medusa.home.musial.io
MEDUSA_PUBLIC_PORT=3737
MEDUSA_HAPROXY_PORT=3737
MEDUSA_HAPROXY_STATS_URL=http://haproxy:8404/stats;csv
MEDUSA_ALLOWED_HOSTS=medusa.home.musial.io
```

`MEDUSA_ALLOWED_HOSTS` accepts a comma-separated Vite allowed-host list, or `*` / `all` / `true` for a controlled migration window.

For Cloudflare-proxied deployments where users visit `https://medusa.evan.engineer` but Cloudflare routes to origin port `3737`, set `MEDUSA_PUBLIC_PORT=443` while leaving `MEDUSA_HAPROXY_PORT=3737`. The release agent probes `MEDUSA_RELEASE_HEALTHCHECK_PORT` when set, otherwise `MEDUSA_HAPROXY_PORT`, so health checks should continue to target the origin listener rather than the Cloudflare edge port.

Valkey response cache settings:

```bash
MEDUSA_CACHE_BACKEND=valkey
MEDUSA_CACHE_URL=valkey://valkey:6379/0
MEDUSA_CACHE_TTL_SECONDS=604800
MEDUSA_CACHE_MAX_PAYLOAD_BYTES=33554432
MEDUSA_CACHE_STARTUP_HYDRATE=true
MEDUSA_CACHE_HYDRATE_MAX_DOCUMENTS=0
MEDUSA_CACHE_HYDRATE_PAGE_SIZE=50
MEDUSA_VALKEY_MAXMEMORY=8gb
```

Valkey stores only rebuildable API payloads and counters. PostgreSQL remains authoritative for documents, jobs, history, evidence, auth, search, and backups. Cache keys include PostgreSQL-backed revision tokens, so Refresh Cache and committed writes make stale payloads unreachable. The default response-cache TTL is seven days and the default per-payload cap is 32 MiB so large document detail, workspace, and list payloads stay hot when the Valkey memory budget allows it.
Keep startup hydration enabled on normal deployments: the backend schedules it as background work after service startup so a cleared or recreated Valkey cache begins warming as soon as Medusa is back online. Disable it only as a temporary incident mitigation if cache warming itself is making recovery unhealthy, then re-enable it once the app is stable. Startup/manual hydration warms safe PostgreSQL-derived JSON payloads broadly: dashboard/status/preferences, organization chrome, all deterministic Library filters and sorts, saved searches, document details plus adjacent document payloads, project/Recon/Portfolio workspaces, notes, review queue, finance summaries, backup status, and Concordance/job surfaces. It intentionally avoids binary downloads, auth/session routes, live host status routes, and GET routes that perform external lookups or other hidden writes.

## Metrics

Optional Prometheus metrics use an ignored bearer token:

```bash
install -d -m 700 data/secrets
printf '%s\n' 'replace-with-long-random-token' > data/secrets/prometheus-token
chmod 600 data/secrets/prometheus-token
```

Set `MEDUSA_METRICS_INTERNAL_TOKEN` in `.env`, then start or refresh the affected services:

```bash
docker compose -f docker-compose.yml -f docker-compose.server.yml -f docker-compose.metrics.yml up -d --build backend haproxy metrics-exporter
```

The exporter serves `/metrics` and `/healthz` from `python -m app.tools.prometheus_exporter`, defaulting to port `43737` inside Docker. On a server, `docker-compose.metrics.yml` lets HAProxy publish `MEDUSA_METRICS_BIND_IP:MEDUSA_METRICS_PORT` and terminate TLS with the existing Medusa certificate.

Keep the Docker socket mount in `docker-compose.metrics.yml` commented out unless container-level Docker Engine metrics are worth the host-control trust boundary.

## Credentials

Keep credentials out of tracked files. Use `.env` and ignored files under `data/secrets/` or `data/managed-secrets/`.

Google Cloud Storage:

```bash
GCS_BUCKET=your-bucket
GCS_PREFIX=medusa
GOOGLE_CLOUD_PROJECT=your-project
GOOGLE_CLOUD_LOCATION=global
GOOGLE_APPLICATION_CREDENTIALS=/app/data/secrets/service-account.json
```

Put service-account JSON under ignored `data/secrets/`. Docker Compose mounts that directory read-only into backend and worker containers. Settings > Cloud Storage can also store an uploaded service-account JSON under ignored managed-secret storage and save only non-secret path/account metadata in PostgreSQL.

OpenAI and Gemini:

```bash
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5.5
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
MEDUSA_OPENAI_PRICING_TIER=standard
GEMINI_API_KEY=
GOOGLE_GENAI_USE_VERTEXAI=false
MEDUSA_OPENAI_SEND_PDF=true
MEDUSA_OPENAI_PDF_FILE_MAX_MB=24
MEDUSA_OPENAI_COMBINE_DOCUMENT_INTELLIGENCE=false
MEDUSA_OPENAI_PROMPT_CACHE_RETENTION=24h
# GPT-5-family OpenAI Responses reasoning effort for APA Citation Matching.
MEDUSA_OPENAI_APA_REASONING_EFFORT=high
# Optional, expensive GPT-5-family reasoning effort for Bibliography Cleanup. Use high/medium/low/minimal or off.
MEDUSA_OPENAI_BIBLIOGRAPHY_REASONING_EFFORT=off
MEDUSA_OPENAI_NORMALIZE_PAGE_TEXT=true
MEDUSA_OPENAI_PAGE_NORMALIZATION_MODE=auto
MEDUSA_OPENAI_PAGE_NORMALIZATION_AUTO_MAX_PAGES=4
MEDUSA_OPENAI_TEXT_NORMALIZATION_PAGE_MAX_CHARS=14000
MEDUSA_OPENAI_REQUEST_TIMEOUT_SECONDS=180
MEDUSA_INQUEST_INLINE_TIMEOUT_SECONDS=45
MEDUSA_OPENAI_PAGE_NORMALIZATION_TIMEOUT_SECONDS=90
MEDUSA_OPENAI_EMBEDDING_TIMEOUT_SECONDS=60
```

If cloud credentials are absent, Medusa still boots and stores originals under `data/originals`. If `OPENAI_API_KEY` is absent, imports still create records and extract text, but AI metadata is marked for review.

Gemini Developer API keys may also live outside tracked files at `data/secrets/gemini.env`:

```bash
GEMINI_API_KEY=...
GOOGLE_GENAI_USE_VERTEXAI=false
```

Detailed model routing and cost strategy lives in `docs/AI_COST_ROUTING.md`.

## Recommendations And DOI Discovery

Common Related-paper and DOI discovery settings:

```bash
MEDUSA_RECOMMENDATIONS_ENABLE_OPENALEX=true
MEDUSA_RECOMMENDATIONS_ENABLE_SEMANTIC_SCHOLAR=true
MEDUSA_RECOMMENDATIONS_ENABLE_CROSSREF=true
MEDUSA_RECOMMENDATIONS_ENABLE_UNPAYWALL=true
MEDUSA_RECOMMENDATIONS_ENABLE_ARXIV=true
MEDUSA_RECOMMENDATIONS_MAX_PER_SOURCE=40
MEDUSA_RECOMMENDATIONS_REQUEST_TIMEOUT_SECONDS=16
MEDUSA_RECOMMENDATIONS_ARXIV_TITLE_LOOKUPS=8
MEDUSA_RECOMMENDATION_DOWNLOAD_TIMEOUT_SECONDS=60
MEDUSA_RECOMMENDATION_DOWNLOAD_MAX_MB=80
MEDUSA_OPENALEX_MAILTO=
MEDUSA_UNPAYWALL_EMAIL=
SEMANTIC_SCHOLAR_API_KEY=
MEDUSA_CITATION_TITLE_WEB_SEARCH=true
MEDUSA_CITATION_TITLE_WEB_SEARCH_TIMEOUT_SECONDS=8
```

Related-paper discovery uses bounded scholarly metadata providers, extracted Bibliography references, and local Library context. Google Scholar remains a user-opened search link, not an automated scraper.

## Worker And Slipstream

Worker recovery and cache settings:

```bash
MEDUSA_IMPORT_WORKER_CONCURRENCY=4
MEDUSA_WORKER_STALE_JOB_SECONDS=900
MEDUSA_DOCUMENT_CACHE_SIZE_MB=1024
MEDUSA_SLIPSTREAM_ENABLED=false
MEDUSA_SLIPSTREAM_PUBLIC_BASE_URL=
MEDUSA_SLIPSTREAM_LEASE_TTL_SECONDS=180
MEDUSA_SLIPSTREAM_HEARTBEAT_SECONDS=30
MEDUSA_SLIPSTREAM_MAX_RESULT_MB=512
MEDUSA_SLIPSTREAM_REQUIRE_TLS=true
MEDUSA_SLIPSTREAM_SIGNATURE_WINDOW_SECONDS=300
MEDUSA_CLOUD_RUN_WORKERS_ENABLED=false
MEDUSA_CLOUD_RUN_FLAVOR=economy
MEDUSA_CLOUD_RUN_PROJECT=
MEDUSA_CLOUD_RUN_REGION=us-south1
MEDUSA_CLOUD_RUN_WORKER_POOL=medusa-processing
MEDUSA_CLOUD_RUN_IMAGE=
MEDUSA_CLOUD_RUN_SERVICE_ACCOUNT=
MEDUSA_CLOUD_RUN_DESIRED_INSTANCES=0
MEDUSA_CLOUD_RUN_MAX_INSTANCES=4
MEDUSA_CLOUD_RUN_CPU=1
MEDUSA_CLOUD_RUN_MEMORY_GIB=2
MEDUSA_CLOUD_RUN_IDLE_SCALE_DOWN_SECONDS=300
MEDUSA_CLOUD_RUN_JOB_TYPES=import
MEDUSA_CLOUD_RUN_COST_WARNING_USD=2
MEDUSA_CLOUD_RUN_WORKER_STATE_PATH=/tmp/medusa-cloud-run/slipstream-client.json
MEDUSA_CLOUD_RUN_CLIENT_ID_SECRET=medusa-slipstream-client-id
MEDUSA_CLOUD_RUN_PRIVATE_KEY_SECRET=medusa-slipstream-private-key
```

Medusa defaults to four concurrent local import jobs. Settings can change the active preference without editing tracked files. Values above four are allowed but can create many provider calls and costs in a short period.

Worker startup requeues `running` import and Concordance jobs left by the previous worker process unless an active Slipstream lease owns the job.

Slipstream is disabled by default. When enabled, Settings > Slipstream creates one-time enrollment tokens scoped to explicit capabilities and a maximum concurrent slot count. Clients generate and keep their Ed25519 private key locally, register over HTTPS, poll for leased work, heartbeat while working, and upload a result manifest for Medusa to apply. Remote clients do not connect to PostgreSQL and do not need inbound ports.

The current bundled runner supports `import_preprocess`: it downloads the original PDF, runs the configured raw-text extractor, returns durable page text/search text/composition evidence, then Medusa requeues the import at `normalizing_pages` so the central worker owns enrichment, model calls, citations, tags, storage, and final completion.

Cloud Run worker pools are a disabled-by-default Slipstream profile, not a second queue. Settings > Cloud Run stores the effective enable switch, numeric target concurrency, and worker flavor; disabled means a target of `0` instances, and enabling defaults to `1`. The conservative default flavor is Economy (`1 vCPU`, `2 GiB`), import-only, maximum `4` instances, and `/tmp` scratch storage. Other saved flavors are Balanced (`2 vCPU`, `4 GiB`), Performance (`4 vCPU`, `8 GiB`), and High Memory (`4 vCPU`, `16 GiB`). Cloud Run workers run `python -m app.slipstream.client --cloud-run`, claim `worker_kind=cloud_run` leases over HTTPS, and append a Cloud Run runtime cost row to the returned Composition manifest. They do not receive PostgreSQL, OpenAI, Gemini, Google Vision, or GCS credentials.

At the current published `us-south1` Cloud Run worker-pool rates, the default shape costs about `$0.000823/minute`, `$0.0494/hour`, and roughly `$0.0041` for a five-minute typical 12-page document before model/OCR costs. Keeping one instance always on for a 30-day month is about `$35.55` gross before any free-tier effects, so Cloud Run is recommended for burst batches or local CPU relief, not occasional single-document imports.

Cloud Run runtime credentials should stay narrow. The runtime service account needs `roles/secretmanager.secretAccessor` on the Slipstream client-id and private-key secrets only. The user or deployer identity that builds/deploys needs Cloud Run deploy/update access, Artifact Registry write access, and `roles/iam.serviceAccountUser` on the runtime service account.

Example worker-pool deploy/update commands are generated in Settings > Cloud Run. The underlying command shape is:

```bash
docker buildx build --platform linux/amd64 --provenance=false \
  -t us-south1-docker.pkg.dev/PROJECT/medusa/worker:latest \
  --push ./backend
```

```bash
gcloud run worker-pools deploy medusa-processing \
  --region us-south1 \
  --image us-south1-docker.pkg.dev/PROJECT/medusa/worker:latest \
  --service-account medusa-cloud-run-worker@PROJECT.iam.gserviceaccount.com \
  --cpu 1 \
  --memory 2Gi \
  --instances 0 \
  --command python \
  --args=-m,app.slipstream.client,--cloud-run
```

The local laptop worker profile lives in `docker-compose.slipstream.yml`. Copy `.env.slipstream.example` to ignored `.env.slipstream`, set `MEDUSA_SLIPSTREAM_ENROLLMENT_TOKEN` to a fresh Settings token, then run:

```bash
docker compose -f docker-compose.slipstream.yml up --build -d
```

By default it reports capacity/concurrency 4, requests only import preprocessing, limits Docker CPU budget to 12 vCPUs, and passes `MEDUSA_SLIPSTREAM_CPUSET=4-15` as a best-effort performance-core affinity hint on a 4 efficiency / 12 performance core Mac.

Basic Slipstream client:

```bash
cd backend
python -m app.slipstream.client --server https://medusa.evan.engineer --enroll TOKEN --name "Remote worker" --capacity 4 --concurrency 4
```

## Development

Backend:

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Database migrations:

```bash
cd backend
alembic upgrade head
```

Frontend:

```bash
cd frontend
npm install
MEDUSA_API_PROXY=http://localhost:8000 npm run dev
```

When previewing the frontend against the Compose HTTPS endpoint instead of a directly exposed backend, use an alternate browser-visible API prefix and let Vite rewrite it back to `/api`:

```bash
VITE_MEDUSA_API_PREFIX=/_medusa_api MEDUSA_API_PROXY=https://localhost:3737 npm run dev -- --port 3747
```

Worker:

```bash
cd backend
python -m app.worker
```

Tests:

```bash
backend/.venv/bin/pytest
npm --prefix frontend run build
curl -sS http://localhost:3737/api/health
```

## Dependency Maintenance

Dependency freshness is tracked through `renovate.json` and the operating plan in `docs/DEPENDENCY_UPDATE_PLAN.md`. Keep dependency policy and scheduled maintenance expectations there rather than in the README.

The host release agent can run an idle-gated maintenance lane for already-merged safe updates and same-tag image/base rebuild refreshes. Routine restarts, rebuilds, safe app updates, and same-tag refreshes skip the database backup; database, backup/restore, runtime container, non-patch backend runtime dependency, PostgreSQL, and pgvector changes require a fresh verified full PostgreSQL backup before apply.

## Backup, Restore, And Portability

Use Utilities for the normal full PostgreSQL backup and restore workflow. Backup Database creates a `pg_dump` custom-format snapshot, compresses it with zstd, stores it under `data/backups/database`, and verifies the checksum. Restore Database requires confirmation and creates a fresh safety backup before applying the selected backup.

Legacy metadata JSON restore drill:

```bash
cd backend
python -m app.tools.restore_export /path/to/medusa-metadata.json
python -m app.tools.restore_export /path/to/medusa-metadata.json --apply
```

The restore command is dry-run by default, rejects secret-bearing keys, skips auth/session state, preserves storage URI references, and parks restored active queues unless `--reactivate-jobs` is explicitly supplied.

The checkout and ignored `data/` directory are portable, but the default live PostgreSQL database is stored in Docker's `medusa-postgres` named volume. Use the full database backup/restore flow when moving Medusa between hosts. Server move details live in `docs/PORTABLE_DEPLOYMENT.md`.

## Safety Model

Imports are durable PostgreSQL jobs. Manual uploads first create staged jobs that can be reviewed and released with Process Uploads. Each processing step records events and checkpoints, so stopping the app mid-import leaves work queued or resumable.

Staged, queued, running, failed, cleared, and restored-paused document rows are operational queue records only. They do not appear in Library lists, Library search, dashboard document counts, domain/tag counts, project bibliographies, recommendation existing-library matches, or Concordance scopes until processing finishes and the document becomes `ready`.

Duplicate uploads are checked before staging. Exact or strong matches ask whether to skip the duplicate, overwrite the matching document record, or import anyway as a separate document.

Local workers and Slipstream clients claim import and Concordance jobs through the same lease coordinator. PostgreSQL is the quorum authority: one active lease per `(job_type, job_id)` prevents simultaneous assignment to local and remote workers.

Utilities > Database owns manual maintenance controls such as compaction, table-statistics optimization, hidden import-cache cleanup, backup/restore, maintenance checks, and backend restart. Release and maintenance refreshes are host-agent compatible; the app writes request/status files under ignored `data/deploy/`, while host-side scripts own git, Docker, and systemd operations.

Docker image and layer sizing is unavailable from inside an ordinary container unless the Docker Engine API is exposed. To enable it for Utilities/Status inspection, add a local Compose override such as:

```yaml
services:
  backend:
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
```

Even as a read-only bind mount, the Docker socket grants the backend process broad control over the host Docker daemon. Leave it unmounted unless that visibility is worth the trust boundary.

After a released import queue drains and no queued or running import jobs remain, the worker runs PostgreSQL `VACUUM (ANALYZE)` when Postgres is the active backend.

Concordance Runs and citation refreshes are safe to leave in progress from the UI. Once the backend accepts the request, the durable database run continues through the worker queue independently of the open page, and the shell-level progress surface reconciles with refreshed run/job state.
