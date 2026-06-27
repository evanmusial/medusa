# Portable Deployment

Medusa can run from a normal Ubuntu server checkout, including a dedicated host, as long as database state, ignored runtime files, and release refreshes are treated as separate concerns.

## Server-Specific Files

The default `docker-compose.yml` remains the local-development shape. Dedicated hosts can layer in `docker-compose.server.yml` to set server-only runtime constraints without changing the MacBook instance:

```bash
docker compose -f docker-compose.yml -f docker-compose.server.yml up -d --build
```

The server environment and override:

- pins all Medusa services to `MEDUSA_CPUSET`, defaulting to logical CPUs `0-5`;
- binds HAProxy through `MEDUSA_BIND_IP`, defaulting to `0.0.0.0`;
- adds a dedicated-server IPv6 HAProxy bind through `MEDUSA_BIND_IPV6`, defaulting to loopback `::1`;
- starts backend and worker with `MEDUSA_IMPORT_WORKER_CONCURRENCY=2` unless `.env` overrides it;
- starts backend and worker with `MEDUSA_DOCUMENT_CACHE_SIZE_MB=51200` unless `.env` overrides it.

Use `deploy/server/.env.server.example` as the source checklist for the server `.env`. Keep the filled `.env` untracked. For the Dallas host, the planned public URL is `https://medusa.evan.engineer:3737`, the IPv4 bind IP is `23.227.185.85`, the IPv6 bind IP is `2604:4500:a:3fb::3737`, the CPU set is `2-7`, the document cache is `51200` MB, and import worker concurrency is `2`. `MEDUSA_ALLOWED_HOSTS=*` intentionally leaves frontend Host checks open during the migration window.

Before moving from the local machine, run:

```bash
python3 scripts/medusa-portability-audit.py
```

The audit prints the files to copy, local cache/model-cache sizes, live job counts when the local Compose database is reachable, and the latest verified full database backup recorded in PostgreSQL.

On the target server after cloning and copying runtime files, run:

```bash
python3 scripts/medusa-server-doctor.py
```

The doctor checks Docker, Compose, the configured CPU set, the dedicated IPv4/IPv6 bind IPs, port `3737`, required cert/secret files, and whether the base-plus-server Compose config renders the expected HAProxy bindings.

## Let's Encrypt Certificate Helper

Server TLS certificates are installed into the ignored HAProxy mount:

```text
data/haproxy/fullchain.pem
data/haproxy/privatekey.pem
```

Use `deploy/server/medusa-certbot.sh` on the target server to keep the certbot commands reproducible. The script reads `MEDUSA_PUBLIC_HOST` and `MEDUSA_BIND_IP` from the server `.env`, requests or renews the certificate with standalone HTTP-01 validation bound to that IP, copies the live Let's Encrypt files into `data/haproxy/`, and installs a certbot deploy hook that repeats the copy after automatic renewals. The HAProxy image reads the mounted certificate files as group `99`, so the helper installs `data/haproxy` as `0750` and the PEM files as `0640` with group `99`. Standalone HTTP-01 validation requires public TCP port `80` on the bind IP to be free and reachable; Medusa itself continues to run on HTTPS port `3737`.

First issuance or replacement:

```bash
deploy/server/medusa-certbot.sh issue
```

Manual renewal:

```bash
deploy/server/medusa-certbot.sh renew
```

Renewal dry run:

```bash
deploy/server/medusa-certbot.sh dry-run
```

If certbot has not registered an account on the host yet, set `MEDUSA_CERTBOT_EMAIL` for first issuance:

```bash
MEDUSA_CERTBOT_EMAIL=admin@example.com deploy/server/medusa-certbot.sh issue
```

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
6. Fill the target `.env` from `deploy/server/.env.server.example`, including `MEDUSA_PUBLIC_HOST`, `MEDUSA_ALLOWED_HOSTS`, `MEDUSA_BIND_IP`, optional `MEDUSA_BIND_IPV6`, `MEDUSA_CPUSET`, GCS, and model-provider credentials.
7. Run `deploy/server/medusa-certbot.sh issue` on the target when the target should own its own Let's Encrypt certificate.
8. Run the server doctor on the target.
9. Start Medusa on the target:

```bash
docker compose -f docker-compose.yml -f docker-compose.server.yml up -d --build
```

10. Restore the full PostgreSQL backup from Utilities on the target.
11. Confirm health:

```bash
curl -kfsS https://medusa.evan.engineer:3737/api/health
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

Utilities and Status can also request release checks or gated maintenance runs by writing:

```text
data/deploy/release-check-request.json
data/deploy/maintenance-request.json
```

The web backend does not run `git`, `docker`, or arbitrary host scripts. A host-side agent on the server owns those operations.

Check for newer pushed code:

```bash
scripts/medusa-release-agent.py check --repo /path/to/medusa --data-dir /path/to/medusa/data
```

Apply a requested upgrade:

```bash
scripts/medusa-release-agent.py apply --repo /path/to/medusa --data-dir /path/to/medusa/data --compose-file docker-compose.yml --compose-file docker-compose.server.yml
```

Run the idle-gated maintenance lane manually:

```bash
scripts/medusa-release-agent.py auto-maintenance --repo /path/to/medusa --data-dir /path/to/medusa/data --compose-file docker-compose.yml --compose-file docker-compose.server.yml --force-window
```

The agent fetches the configured upstream, refuses risky dirty or unknown checkouts, classifies dependency/runtime changes, sets `MEDUSA_BUILD_VERSION`, `MEDUSA_BUILD_DATE`, `MEDUSA_BUILD_HASH`, and `MEDUSA_GIT_SHA` for the Compose run, rebuilds with the requested Compose files, then waits for both `/api/health` and `/` through the public TLS/proxy path. Its health probes resolve `MEDUSA_PUBLIC_HOST` to `MEDUSA_RELEASE_HEALTHCHECK_IP` when set, otherwise to `MEDUSA_BIND_IP`, then `MEDUSA_BIND_IPV6`, then localhost. Routine restarts, safe app updates, and same-tag image refreshes skip the database backup. If the classified change touches database schema/persistence, backup/restore tooling, runtime container definitions, non-patch backend runtime dependencies, or a major underlying program version such as PostgreSQL/pgvector, the agent first runs a full backend PostgreSQL backup inside the current backend container and requires a completed, uploaded, checksum-verified GCS backup before Docker Compose is invoked.

Scheduled maintenance defaults to Tuesdays and Fridays in the `03:00-06:00 America/Indiana/Indianapolis` window. It requires no active browser sessions within the five-minute grace period and no active imports, Concordance jobs, accessory summaries, backup/restore, or database maintenance. A user-requested maintenance run can override active browser sessions, but it still cannot override active document-processing or database/backup work.

A typical server setup is a timer for `check`, a path or short timer for `apply` when `data/deploy/release-request.json` appears, a Tuesday/Friday timer for `auto-maintenance`, and path units for the on-demand check and maintenance request files.

Template systemd units live under `deploy/systemd/` and assume the checkout is installed at `/opt/medusa`. `medusa.service` owns the Docker Compose app stack, `medusa-release-check.timer` periodically refreshes the release status file, `medusa-release-check.path` handles app-requested checks, `medusa-release-apply.path` watches for authenticated upgrade requests, and `medusa-maintenance.timer` plus `medusa-maintenance.path` run the idle-gated maintenance lane. Copy them to `/etc/systemd/system/`, edit paths if the host uses a different checkout location, and run them as the checkout owner so Git SSH credentials and Docker group membership are available.

```ini
ExecStart=/usr/bin/env docker compose -f docker-compose.yml -f docker-compose.server.yml up -d --build
ExecReload=/usr/bin/env docker compose -f docker-compose.yml -f docker-compose.server.yml up -d --build
ExecStop=/usr/bin/env docker compose -f docker-compose.yml -f docker-compose.server.yml stop
```

Then enable:

```bash
sudo systemctl enable --now medusa.service
sudo systemctl enable --now medusa-release-check.timer
sudo systemctl enable --now medusa-release-check.path
sudo systemctl enable --now medusa-release-apply.path
sudo systemctl enable --now medusa-maintenance.timer
sudo systemctl enable --now medusa-maintenance.path
```

For a checkout at `~/git/medusa`, replace `/opt/medusa` with the absolute home path before enabling. If Docker is installed from Snap, keep `/snap/bin` in the unit `PATH` or point `ExecStart` directly at the Snap `docker` binary.
