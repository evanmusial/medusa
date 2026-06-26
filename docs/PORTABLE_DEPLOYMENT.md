# Portable Deployment

Medusa can run from a normal Ubuntu server checkout, including carrot, as long as database state, ignored runtime files, and release refreshes are treated as separate concerns.

## Server-Specific Files

The default `docker-compose.yml` remains the local-development shape. Dedicated hosts can layer in `docker-compose.server.yml` to set server-only runtime constraints without changing the MacBook instance:

```bash
docker compose -f docker-compose.yml -f docker-compose.server.yml up -d --build
```

The server override:

- pins all Medusa services to `MEDUSA_CPUSET`, defaulting to logical CPUs `0-5`;
- binds HAProxy to `MEDUSA_BIND_IP`, defaulting to `0.0.0.0`;
- starts backend and worker with `MEDUSA_IMPORT_WORKER_CONCURRENCY=2` unless `.env` overrides it;
- starts backend and worker with `MEDUSA_DOCUMENT_CACHE_SIZE_MB=51200` unless `.env` overrides it.

Use `deploy/server/.env.server.example` as the source checklist for the server `.env`. Keep the filled `.env` untracked.

Before moving from the local machine, run:

```bash
python3 scripts/medusa-portability-audit.py
```

The audit prints the files to copy, local cache/model-cache sizes, live job counts when the local Compose database is reachable, and the latest verified full database backup recorded in PostgreSQL.

On the target server after cloning and copying runtime files, run:

```bash
python3 scripts/medusa-server-doctor.py
```

The doctor checks Docker, Compose, the configured CPU set, the dedicated bind IP, port `3737`, required cert/secret files, and whether the base-plus-server Compose config renders.

## Move A Library To Another Host

1. Run the portability audit on the source machine.
2. Stop or pause active imports, Concordance Runs, backups, and restores on the source machine.
3. Create a full PostgreSQL backup from Utilities and verify it completed.
4. Clone the repository on the target server.
5. Copy ignored runtime files from the source:
   - `.env`
   - `data/secrets/`
   - `data/managed-secrets/`
   - `data/haproxy/fullchain.pem`
   - `data/haproxy/privatekey.pem`
   - optionally `data/model-cache/` to avoid first-run model downloads.
   - optionally `data/processing-cache/` to avoid rehydrating recent PDFs.
   - copy `data/originals/` when local fallback storage contains authoritative originals that are not in GCS.
6. Fill the target `.env` from `deploy/server/.env.server.example`, including `MEDUSA_BIND_IP`, `MEDUSA_CPUSET`, host/domain values, GCS, and model-provider credentials.
7. Run the server doctor on the target.
8. Start Medusa on the target:

```bash
docker compose -f docker-compose.yml -f docker-compose.server.yml up -d --build
```

9. Restore the full PostgreSQL backup from Utilities on the target.
10. Confirm health:

```bash
curl -kfsS https://medusa.home.musial.io:3737/api/health
```

The default `medusa-postgres` Docker named volume is host-local and is not copied by moving the checkout or `data/`. Use the full database backup/restore workflow as the system-of-record move.

## Cache Portability

`data/processing-cache` can be copied to avoid rehydrating recent PDFs, and `data/model-cache` can be copied to avoid first-run local model downloads. These caches are useful but not authoritative. Originals remain in GCS or `data/originals`; when a document cache file is missing, Medusa can recreate it from the durable original URI when storage credentials and objects are available.

## Release Status And Upgrade Requests

Medusa reads release state from:

```text
data/deploy/release-status.json
```

When the authenticated user clicks `Upgrade Now`, Medusa writes:

```text
data/deploy/release-request.json
```

The web backend does not run `git`, `docker`, or arbitrary host scripts. A host-side agent on the server owns those operations.

Check for newer pushed code:

```bash
scripts/medusa-release-agent.py check --repo /path/to/medusa --data-dir /path/to/medusa/data
```

Apply a requested upgrade:

```bash
scripts/medusa-release-agent.py apply --repo /path/to/medusa --data-dir /path/to/medusa/data
```

The agent fetches the configured upstream, refuses to deploy from a dirty checkout, fast-forwards only, sets `MEDUSA_BUILD_VERSION`, `MEDUSA_BUILD_DATE`, `MEDUSA_BUILD_HASH`, and `MEDUSA_GIT_SHA` for the Compose run, rebuilds with `docker compose up -d --build`, then waits for `/api/health`.

A typical server setup is a timer for `check` plus a path or short timer for `apply` when `data/deploy/release-request.json` appears.

Template systemd units live under `deploy/systemd/` and assume the checkout is installed at `/opt/medusa`. `medusa.service` owns the Docker Compose app stack, `medusa-release-check.timer` periodically refreshes the release status file, and `medusa-release-apply.path` watches for authenticated upgrade requests written by the app. Copy them to `/etc/systemd/system/`, edit paths if carrot uses a different checkout location, and adjust `medusa.service` to use the server override if this host should run with `docker-compose.server.yml`:

```ini
ExecStart=/usr/bin/env docker compose -f docker-compose.yml -f docker-compose.server.yml up -d --build
ExecReload=/usr/bin/env docker compose -f docker-compose.yml -f docker-compose.server.yml up -d --build
```

Then enable:

```bash
sudo systemctl enable --now medusa.service
sudo systemctl enable --now medusa-release-check.timer
sudo systemctl enable --now medusa-release-apply.path
```

For a checkout at `~/git/medusa`, replace `/opt/medusa` with the absolute home path before enabling. If Docker is installed from Snap, keep `/snap/bin` in the unit `PATH` or point `ExecStart` directly at the Snap `docker` binary.
