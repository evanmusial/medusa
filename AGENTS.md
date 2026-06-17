# Codex Guidance For Medusa

Medusa is a local-first research library and assistant. Preserve the product direction: polished, quiet, research-cockpit UI; durable imports; safe stop/start behavior; PostgreSQL-backed metadata and search; GCS/OpenAI/Google Vision integrations with local/no-credential fallbacks.

## Required Project Context

Before making design, architecture, data model, processing, or UX changes, read:

- `docs/ARCHITECTURE.md`
- `README.md`

Treat `docs/ARCHITECTURE.md` as the living design and architecture record for Codex. Update it in the same change whenever work materially affects:

- Product scope, navigation, layout, visual language, or UX workflows
- Backend service boundaries, API contracts, persistence, jobs, imports, OCR, AI, storage, or search
- Database entities, relationships, indexes, migrations, or durability guarantees
- Security, auth, secret handling, network exposure, deletion/backup behavior, or safety assumptions
- Operational commands, ports, Docker services, credentials, or verification expectations

If a change is intentionally narrow and does not alter those areas, leave the architecture record alone.

## Implementation Defaults

- Keep the app runnable with `docker compose up --build` on port `3737`.
- Keep credentials out of tracked files. Use `.env` and document new variables in `.env.example`.
- Maintain local fallbacks for GCS/OpenAI/Vision where feasible so Medusa can boot without cloud credentials.
- Make import/processing work idempotent and resumable through database state.
- Treat every new document-processing capability as both an import-time feature and a retroactive library feature. Existing documents must be able to receive newer extraction, AI, OCR, citation, tagging, figure, search, or attribute logic without re-uploading.
- Call these retroactive upgrade jobs **Concordance Runs**. A Concordance Run brings previously imported documents into agreement with the current feature set.
- Design Concordance Runs around versioned capabilities, document-level completion state, durable queued jobs, clear progress/events, and safe retry semantics. They should be triggerable for the whole library, a saved search/filter, a domain, a project, or selected documents.
- Prefer focused tests for pure logic and end-to-end smoke checks for import and app health.
- Avoid introducing loud visual styling. Color should support navigation, status, and restrained emphasis.

## Verification

After meaningful changes, run the narrowest relevant checks. Current baseline:

```bash
backend/.venv/bin/pytest
npm --prefix frontend run build
curl -sS http://localhost:3737/api/health
```
