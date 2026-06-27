# Dependency Update Plan

Medusa keeps runtime and package dependencies current through a twice-weekly review cadence plus an immediate lane for critical security issues. The goal is to pick up security patches and useful platform improvements without letting container images or libraries change silently under the local-first app.

## Cadence

- Renovate checks for dependency updates on Tuesdays and Fridays between 9:00 AM and 5:00 PM America/Indiana/Indianapolis.
- Critical security advisories can be handled outside the twice-weekly window when waiting would leave a known exposure in a public-facing or data-adjacent component.
- Routine patch and minor updates should usually be reviewed in the next scheduled window.
- Major updates should be reviewed as explicit upgrade work with release notes, migration notes, and rollback expectations.

## Activation

The root `renovate.json` file is the checked-in update policy. To make it active, enable the Renovate GitHub app for this repository or run a Renovate bot/runner against `evanmusial/medusa` with permission to open dependency update pull requests. Until that app or runner is active, the plan is documented and versioned but will not automatically create PRs.

After activation, the first dependency dashboard should be reviewed to confirm that Docker Compose images, Dockerfiles, backend Python requirements, frontend npm dependencies, and lockfile maintenance are all being detected.

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

The published-port invariant is:

- Public: HAProxy on host port `3737`.
- Internal only: frontend `3737`, backend `8000`, worker, PostgreSQL `5432`, Valkey `6379`, and HAProxy stats `8404`.

## Ownership And Triage

- Apply security patch PRs first, especially for HAProxy, backend/frontend base images, Python packages that parse documents, npm build tooling with known CVEs, and Valkey.
- Prefer patch updates over broad version jumps when the only reason is security.
- Bundle routine low-risk patch updates by ecosystem, but keep runtime image updates reviewable.
- Do not auto-merge Valkey, PostgreSQL, HAProxy, Python base image, or Node base image updates.
- Record any rejected update with the reason, observed failure, and next review date in the PR or TODO notes.
