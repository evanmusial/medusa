# Dependency Update Plan

Medusa keeps runtime and package dependencies current through a twice-weekly review cadence plus an immediate lane for critical security issues. The goal is to pick up security patches and useful platform improvements without letting container images or libraries change silently under the local-first app.

## Cadence

- Renovate checks for dependency updates on Tuesdays and Fridays between 9:00 AM and 5:00 PM America/Indiana/Indianapolis.
- The host maintenance agent may apply already-merged safe updates and same-tag image/base refreshes on Tuesdays and Fridays during the quiet `03:00-06:00 America/Indiana/Indianapolis` window.
- Critical security advisories can be handled outside the twice-weekly window when waiting would leave a known exposure in a public-facing or data-adjacent component.
- Routine patch and minor updates should usually be reviewed in the next scheduled window.
- Major updates should be reviewed as explicit upgrade work with release notes, migration notes, and rollback expectations.

## Activation

The root `renovate.json` file is the checked-in update policy. To make it active, enable the Renovate GitHub app for this repository or run a Renovate bot/runner against `evanmusial/medusa` with permission to open dependency update pull requests. Until that app or runner is active, the plan is documented and versioned but will not automatically create PRs.

After activation, the first dependency dashboard should be reviewed to confirm that Docker Compose images, Dockerfiles, backend Python requirements, frontend npm dependencies, and lockfile maintenance are all being detected.

## Maintenance Apply Lane

`scripts/medusa-release-agent.py auto-maintenance` is the host-owned apply lane for already-reviewed maintenance. It runs outside the web container and can be triggered by systemd on the Tuesday/Friday quiet window or by the app writing `data/deploy/maintenance-request.json` after the user clicks `Run Maintenance Now` in Utilities or Status.

The lane is auto-eligible only for:

- Already-merged dependency-only patch or security updates.
- Same-tag runtime image/base rebuild refreshes using `docker compose up -d --build --pull always`.

The lane is approval-required for:

- Major or minor dependency jumps.
- HAProxy, Valkey, PostgreSQL, or pgvector runtime image tag changes.
- Non-dependency code diffs.
- Dirty checkouts.
- Unknown classifications.
- Any migration, release-note, or operational risk that cannot be classified as a dependency-only patch/security update.

Docker Engine and Docker Compose plugin updates are never auto-applied by Medusa. The release status surface may report host Docker/Compose versions, but host package-manager updates remain an explicit operator checklist item.

## Backup And Idle Gates

Every maintenance apply that can recreate Docker services or touch PostgreSQL is hard-gated by a fresh successful full PostgreSQL backup. The agent invokes the backend CLI inside the current backend container:

```bash
python -m app.tools.database_backup --reason pre_maintenance --wait --json
```

Success requires a complete `BackupRun`, a GCS URI, SHA-256 value, nonzero size, uploaded manifest, and checksum verification evidence. If the backup cannot be created, uploaded, and checksum-verified, no Docker or PostgreSQL patching command runs.

Scheduled maintenance also requires Medusa to be idle. Signed-in visible tabs call `/api/activity/heartbeat` roughly once per minute, and the agent treats sessions seen within the five-minute grace period as active. Scheduled maintenance blocks on active sessions, active imports, Concordance jobs, accessory summaries, backup/restore runs, and database maintenance. Explicit user approval can override active browser sessions, but not active document-processing work, backup/restore, or database maintenance.

Utilities and Status show the maintenance phase, auto-apply eligibility, active session count, active work blockers, backup gate state, backup run id, update classification, and host Docker/Compose versions. `Check Now` asks the host agent to refresh release state; `Run Maintenance Now` requests the same gated apply lane immediately.

## Covered Surfaces

- Docker Compose images, including `valkey/valkey`, `haproxy`, `pgvector`, and any server override images.
- Dockerfile base images for backend and frontend containers.
- Backend Python dependencies from `backend/requirements.txt` and `pyproject.toml`.
- Frontend npm dependencies and `package-lock.json`.
- Future GitHub Actions or workflow dependencies once workflows are added.

Medusa should keep explicit version tags instead of floating tags such as `latest`. Runtime image PRs must preserve the security boundary that only HAProxy publishes host port `3737`, and Valkey remains private to the backend/worker cache network.

## Valkey Review Checklist

For every Valkey image update:

1. Confirm the image tag remains explicit and uses the official `valkey/valkey` image.
2. Review Valkey release notes for Redis-protocol compatibility, memory-policy behavior, command changes, and security fixes.
3. Confirm `docker-compose.yml` still has no `ports:` entry for Valkey.
4. Confirm Valkey is only attached to the internal `cache` network and that only backend and worker share that network.
5. Run `docker compose config --quiet`.
6. Rebuild and start the stack in a maintenance window.
7. Verify `docker compose ps` shows only HAProxy publishing host port `3737`.
8. Verify `/api/health` through the public endpoint.
9. Verify `/api/cache/status` reports either online Valkey or a graceful degraded state.
10. Exercise manual Refresh Cache from the user menu or `/status`.

If a Valkey update fails, Medusa should remain usable as PostgreSQL-backed cache misses. Roll back by restoring the previous image tag and rebuilding the stack.

## Standard Verification

Before merging dependency update PRs:

```bash
backend/.venv/bin/pytest
npm --prefix frontend run build
docker compose config --quiet
curl -ksS https://medusa.home.musial.io:3737/api/health
```

For Docker runtime image changes, also run:

```bash
docker compose up -d --build
docker compose ps
```

For runtime refreshes in the maintenance lane, the agent uses:

```bash
docker compose up -d --build --pull always
```

The published-port invariant is:

- Public: HAProxy on host port `3737`.
- Internal only: frontend `3737`, backend `8000`, worker, PostgreSQL `5432`, Valkey `6379`, and HAProxy stats `8404`.

## Ownership And Triage

- Apply security patch PRs first, especially for HAProxy, backend/frontend base images, Python packages that parse documents, npm build tooling with known CVEs, and Valkey.
- Prefer patch updates over broad version jumps when the only reason is security.
- Bundle routine low-risk patch updates by ecosystem, but keep runtime image updates reviewable.
- Do not auto-merge Valkey, PostgreSQL, HAProxy, Python base image, or Node base image updates.
- Record any rejected update with the reason, observed failure, and next review date in the PR or TODO notes.
