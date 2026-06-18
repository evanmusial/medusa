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

Treat `TODO.md` as the planned-work ledger. Update it when:

- A planned item is completed, newly discovered, rescoped, or intentionally deferred.
- A user asks for "what is left," "build the rest," or similar backlog-driven work.
- Architecture notes describe a future gap that should become actionable implementation work.

Keep TODO entries concrete and checkable. Do not let `TODO.md` become a second architecture document; use it for planned items, ownerless backlog, and acceptance notes.

## Implementation Defaults

- Keep the app runnable with `docker compose up --build` on port `3737`.
- Keep credentials out of tracked files. Use `.env` and document new variables in `.env.example`.
- Maintain local fallbacks for GCS/OpenAI/Vision where feasible so Medusa can boot without cloud credentials.
- For PostgreSQL schema/model changes, add an Alembic revision and keep SQLite metadata creation working for focused tests.
- Make import/processing work idempotent and resumable through database state.
- Treat every new document-processing capability as both an import-time feature and a retroactive library feature. Existing documents must be able to receive newer extraction, AI, OCR, citation, tagging, figure, search, or attribute logic without re-uploading.
- Call these retroactive upgrade jobs **Concordance Runs**. A Concordance Run brings previously imported documents into agreement with the current feature set.
- Design Concordance Runs around versioned capabilities, document-level completion state, durable queued jobs, clear progress/events, and safe retry semantics. They should be triggerable for the whole library, a saved search/filter, a domain, a project, or selected documents.
- Prefer focused tests for pure logic and end-to-end smoke checks for import and app health.
- Avoid introducing loud visual styling. Color should support navigation, status, and restrained emphasis.

## Current Product And Architecture Record

Medusa V1 is a Dockerized local-first research cockpit:

- Frontend: React, TypeScript, Vite, Tailwind-like CSS tokens, TanStack Query, Lucide icons.
- Backend: FastAPI, SQLAlchemy, PostgreSQL, `pgvector`, durable worker process.
- Runtime: Docker Compose exposes the frontend on `3737`; backend, worker, and database remain internal services.
- Auth: single-user password login with HTTP-only session cookies.
- UI: quiet fixed header, resizable left navigation, resizable Library filter/detail panes, saved search and smart filter controls, bulk edit controls, editable document detail/correction pane with original PDF preview, expanded Reader mode, parsed full-text reader, rendered Markdown summaries/citations, and annotations, project run-sheet workspace, notes/reminders workbench, immediate PDF import dropzone, day/night modes, Settings as the operational control surface.
- Data: PostgreSQL is the system of record for metadata, jobs, search text, tags, domains, projects, notes, annotations, attributes, citations, figure records, processing events, capability state, and exportable backup metadata.
- Migrations: Alembic is the PostgreSQL schema migration path; SQLite tests use SQLAlchemy metadata creation as a local fallback.

Core document-storage rules:

- Originals are checksum-addressed. Current object layout is `documents/<first-two-sha256-chars>/<sha256>/<original-filename>` under the configured storage prefix.
- GCS is the intended durable original/assets store when configured. Current local configuration may target bucket `musial-medusa-assets`, project `musial-medusa`, and service account `medusa@musial-medusa.iam.gserviceaccount.com`.
- Service-account JSON files belong only in ignored local paths such as `data/secrets`; never commit them.
- Local storage under `data/originals` is only the no-cloud fallback.
- `data/processing-cache` is ephemeral job working storage. Completed imports should remove their cache copies. Queued/running/failed jobs may keep cache files for retry/debugging.
- Extracted durable assets such as figures/images should be stored in GCS or the local fallback using checksum/document-derived keys, with PostgreSQL rows mapping assets back to documents/pages.
- Original PDFs are served only through authenticated routes such as `/api/documents/{document_id}/original`; this supports in-app preview and open-in-new-tab without making GCS objects public.
- Parsed document pages are exposed through authenticated document detail responses and should remain available as a page-by-page reading surface where page notes/annotations can be created.
- Settings exposes authenticated JSON exports for metadata and storage manifests. Exports must omit secrets, service-account credentials, password hashes, and session tokens.
- Metadata exports can be restored with `python -m app.tools.restore_export /path/to/medusa-metadata.json`; the command is dry-run by default and requires `--apply` to write.
- Restore workflows must reject secret-bearing keys, skip password/session state, preserve storage URI references, and park restored queued/running import or Concordance jobs as `restored_paused` unless the user explicitly asks to reactivate restored queues.

Current import and processing commitments:

- Dragging PDFs onto the Import dropzone starts import immediately; the whole drop panel must show an active acceptance state.
- Imports hash before storing, detect duplicate checksums, upload originals to storage, create durable database jobs, and let the worker process them.
- Extraction must respect scholarly layouts. Two-column reading order, table text, and later figure/caption extraction are not optional polish; they affect search, summaries, and citation accuracy.
- Embedded PDF figures/images are extracted into durable storage during import when available and can be added to older documents through the `figure_assets` Concordance capability.
- Citation generation may happen immediately, but only evidence-backed citations should be marked `verified`; uncertain citations go to Review Queue.
- APA citation output should favor DOI links whenever a DOI can be located and verified. If no DOI can be verified, use the best direct stable source link, preferably a PDF or other static document, and store evidence for the fallback.
- DOI matching is an important next priority and should be exhaustive: inspect document metadata, extracted text, references, Crossref, Semantic Scholar, DOI.org, publisher pages, and targeted web evidence before giving up.
- Accepting a citation candidate applies its metadata/citation to the document, marks the citation verified, and records `DocumentVersion` history. Rejecting a candidate should clear it from active review without changing the document.
- Manual document corrections should create `DocumentVersion` history with before/after snapshots, refresh citation/search surfaces when relevant, and preserve evidence rather than erasing it.
- Document annotations/highlights are soft-deleted, page-aware, color-aware, and included in document search. Geometry is reserved for future PDF overlay highlights.
- Notes and reminders may attach to documents, domains, projects, or the general library. Document-linked notes must contribute to document search.
- Project run sheets should track resources, status, priority, used/not-used state, project notes, and generated bibliographies for all sources or used-only sources.
- OpenAI, GCS, and Google Vision must remain integration points with local/no-credential fallbacks where practical.
- Async OpenAI document-intelligence work should default to `gpt-5.5` and may send original PDF file context through the Responses API when `MEDUSA_OPENAI_SEND_PDF=true` and the file is below `MEDUSA_OPENAI_PDF_FILE_MAX_MB`.
- AI-generated APA citation text is useful as a candidate/evidence surface, but verified citation status still depends on normalized metadata plus trusted evidence such as DOI/Crossref or explicit user acceptance.

Current GCS and credential notes:

- Expected variables are documented in `.env.example`; private values live in `.env`.
- Compose mounts `./data/secrets:/app/data/secrets:ro` for backend and worker containers.
- A valid local service-account key may exist at `data/secrets/musial-medusa-c5a56e32f65c.json`; this file is ignored and must remain untracked.

Concordance Runs:

- Every new document-processing ability must be available both at import time and retroactively through Concordance Runs.
- Concordance Runs are durable upgrade jobs for already-imported documents. They bring prior imports into agreement with the current feature set.
- Concordance scope supports the whole library, current document/selected documents through API, current search, saved search, domain, and project. Richer arbitrary filtered result sets remain future work.
- Concordance work must use versioned capabilities, document-level completion state, queued jobs, processing events, visible progress, and safe retries.
- Current first capabilities are search index rebuilds, Markdown APA citation refreshes, PDF-aware AI metadata/summary/topic refreshes, and figure asset extraction.
- Do not silently overwrite user-corrected metadata during Concordance work. Fill missing fields or create reviewable candidates unless the user explicitly asks for replacement.

## Verification

After meaningful changes, run the narrowest relevant checks. Current baseline:

```bash
backend/.venv/bin/pytest
npm --prefix frontend run build
curl -sS http://localhost:3737/api/health
```
