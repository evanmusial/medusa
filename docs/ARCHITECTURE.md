# Medusa Design And Architecture Record

Last updated: 2026-06-17

This is the living record of Medusa's product, design, and architecture decisions. Future Codex sessions should read this before changing the app and update it when decisions change. Details matter here because Medusa is meant to become a long-lived research system, not a one-off prototype.

## Product Intent

Medusa is a local-first research document clearinghouse. It should help organize, search, read, annotate, summarize, cite, and reuse research documents across domains of knowledge and project-specific run sheets.

The product is optimized for one primary user on a trusted local network. It still requires password login because it listens on LAN-accessible port `3737`.

Core workflows:

- Batch import academic PDFs and textbook excerpts.
- Preserve original files and process them into searchable metadata, text, summaries, figures, and citation candidates.
- Run Concordance Runs to bring already-imported documents up to the current extraction, enrichment, citation, tagging, OCR, search, and asset feature set.
- Preserve document layout semantics during processing where they affect meaning, especially two-column articles and tables.
- Organize documents by nested domains, flat tags, read priority, custom attributes, and projects.
- Keep ambiguous metadata and citations visible in a review queue instead of pretending uncertain output is verified.
- Build project run sheets with resource status and exportable APA/BibTeX/RIS/CSL bibliographies.

## Design System Direction

Medusa should feel like a serious research cockpit: dense, calm, polished, and fast to scan.

Current UI architecture:

- Fixed top header with temporary `M` wordmark, global search, theme toggle, and session action.
- Left sidebar navigation: Library, Domains, Projects, Review Queue, Notes, Import, Settings.
- Main Library view uses a tri-pane layout:
  - Left filter pane for domains and tags.
  - Center dense document results.
  - Right document detail pane for PDF placeholder, citation, summary, tags, and evidence.
- Import view centers drag/drop upload plus shared defaults and live job status.
- Projects view supports project creation and bibliography generation.
- Review Queue shows citation candidates that need human attention.

Visual decisions:

- Day mode uses cool white surfaces, ink text, restrained blue primary actions, teal success, amber warnings.
- Night mode uses charcoal surfaces, high-contrast text, blue/teal accents, and soft borders.
- Avoid loud gradients, marketing-style hero layouts, decorative blobs, or oversized display typography inside the work surface.
- Use icons for actions and navigation where they improve scanning.
- Keep cards for framed tools or repeated items; do not nest cards.

## Architecture Snapshot

Runtime shape:

- `frontend`: React + TypeScript + Vite, served on port `3737`.
- `backend`: FastAPI API on internal port `8000`.
- `worker`: Python durable import processor.
- `db`: PostgreSQL with `pgvector`.
- `docker-compose.yml` wires all services and exposes only the frontend on `3737`.

Data storage:

- PostgreSQL is the system of record.
- Original files are checksum-addressed.
- GCS is the intended original-object store when `GCS_BUCKET` and Google credentials are configured.
- Local filesystem storage under `data/originals` is the fallback so the app can boot and import without cloud credentials.
- GCS service-account files live locally under ignored `data/secrets`; Compose mounts that directory read-only at `/app/data/secrets`.
- The GCS service account needs object-level create/read/delete access for the configured bucket and prefix. `storage.buckets.get` is useful for diagnostics, but object upload requires `storage.objects.create`.
- Processing cache lives under `data/processing-cache`, is ignored by git, and should only contain temporary files for queued/running/failed work.

Backend modules:

- `backend/app/main.py`: FastAPI app, auth, CRUD/search/import/project/review APIs.
- `backend/app/models.py`: ORM entities and relationships.
- `backend/app/worker.py`: long-running durable job loop.
- `backend/app/services/storage.py`: GCS/local storage adapter.
- `backend/app/services/extraction.py`: layout-aware PDF text extraction, table normalization, and chunking.
- `backend/app/services/ai.py`: OpenAI structured metadata and embedding adapter.
- `backend/app/services/ocr.py`: Google Vision adapter placeholder.
- `backend/app/services/processing.py`: import processing orchestration.
- `backend/app/services/citations.py`: APA/BibTeX/RIS/CSL formatting utilities.
- `backend/app/services/verifier.py`: Crossref lookup and verification helpers.

Frontend modules:

- `frontend/src/App.tsx`: current full application shell and views.
- `frontend/src/lib/api.ts`: API client.
- `frontend/src/types.ts`: shared frontend response types.
- `frontend/src/styles.css`: design system tokens, layout, and responsive rules.

## Data Model

Current core entities:

- `User`, `SessionToken`
- `Domain`: nestable knowledge hierarchy.
- `Tag`: flat keyword/topic label.
- `Document`: canonical research object and processing/search state.
- `DocumentVersion`: metadata correction/history snapshots.
- `DocumentPage`: extracted per-page text and low-text flags.
- `TextChunk`: chunked full text and optional embedding vector.
- `Figure`: future extracted figures/captions/gists.
- `Annotation`: future highlights and page annotations.
- `Note`: document/domain/project notes and reminders.
- `AttributeDefinition`, `DocumentAttributeValue`: custom per-document attributes.
- `Project`, `ProjectItem`, `ProjectBibliography`: run sheets and citation exports.
- `ImportBatch`, `ImportJob`, `ProcessingEvent`: durable import bookkeeping.
- `CitationCandidate`: reviewable citation/metadata candidates.

Important modeling decisions:

- Documents are soft-deleted via `deleted_at`.
- Duplicate detection starts with SHA-256 checksum.
- Citation status is explicit, with `needs_review` as the safe uncertain state.
- Metadata evidence is stored as JSON so extraction, Crossref, OpenAI, and future sources can be audited.
- Title-only citation evidence must pass a strong normalized-title match before it is stored as Crossref evidence.
- Full-text search data is stored on `Document.search_text`; chunk embeddings live on `TextChunk.embedding`.
- Future processing capabilities should be versioned so Medusa can tell which documents need a Concordance Run.

## Processing Pipeline

Current import path:

1. User uploads one or more PDFs through `/api/imports/batches`.
2. Backend hashes each file and checks for exact duplicates.
3. Original is written to GCS when configured, otherwise to local storage.
4. A local processing cache copy is saved under `data/processing-cache`.
5. `Document`, `ImportBatch`, and `ImportJob` records are committed.
6. Worker claims queued jobs and moves them through extraction, enrichment, indexing, and completion.
7. PDF text and pages are extracted with PyMuPDF using layout-aware block ordering.
8. Two-column pages should read down the left column before crossing to the right column, while full-width headers/sections remain in vertical order.
9. Detected tables are converted to Markdown and included in page text so table content is searchable and available to metadata/summarization.
10. Text is chunked for search/embedding.
11. OpenAI metadata extraction runs only when `OPENAI_API_KEY` exists; otherwise a low-confidence review record is produced.
12. Crossref lookup is attempted by DOI/title.
13. APA citation is generated. It is marked `verified` only when enough metadata exists and DOI/Crossref evidence is present.
14. Uncertain citations create `CitationCandidate` review records.
15. Successful jobs delete their local processing-cache PDF copy after indexing.

Durability decisions:

- Jobs are database-backed and step-oriented.
- Processing events are appended for auditability.
- The app must tolerate stop/start without losing queued jobs.
- Import processors should stay idempotent where possible and avoid duplicating pages/chunks when a step reruns.
- Completed jobs should not leave durable document copies in `data/processing-cache`; originals are retained in GCS or the configured local fallback store.
- Failed jobs may keep their processing-cache copy to support retry and debugging.

## Concordance Runs

Concordance Runs are retroactive upgrade jobs for the library. They bring already-imported documents into agreement with the current Medusa feature set without requiring re-upload.

Use Concordance Runs when adding or improving:

- keyword/topic extraction
- layout extraction, OCR, table handling, or figure extraction
- citation verification or formatting
- summaries, aspect-specific summaries, attributes, or notes-derived indexes
- embeddings, full-text search fields, image gists, or other search surfaces

Expected behavior:

- New features must define how they run at import time and how they apply to existing documents.
- Runs should be triggerable for the whole library, selected documents, a domain/subdomain, a project, a saved search, or a filtered result set.
- Capability versions should be recorded per document or per derived artifact so the app can find missing/outdated work.
- Concordance jobs must be durable, resumable, idempotent, and visible through processing events/progress.
- A run should avoid overwriting user-corrected metadata unless explicitly requested or unless it records a reviewable candidate.
- Ambiguous or low-confidence output should go to Review Queue rather than silently replacing trusted data.

## Security And Operations

Authentication:

- Single-user password login.
- Session cookies are HTTP-only and backed by hashed session tokens in PostgreSQL.
- Default dev credentials exist only so a fresh local stack is usable. Real use should set `MEDUSA_PASSWORD` in `.env`.

Secrets:

- `.env` is ignored.
- `.env.example` documents expected variables.
- Google service-account JSON files are ignored under `data/secrets`.
- GCS service accounts must be able to create original PDFs and extracted assets, read them back for preview/export/reprocessing, and delete temporary smoke-test objects when verifying credentials.
- Do not track API keys, service-account JSON, or generated data.

Network:

- The app listens externally on port `3737` through the frontend service.
- Backend and database are internal Docker services.

Safe deletion:

- Documents use soft delete. Original object cleanup is intentionally not automatic yet.

Verification baseline:

- `backend/.venv/bin/pytest`
- `npm --prefix frontend run build`
- `curl -sS http://localhost:3737/api/health`
- Optional: authenticated dashboard and smoke PDF upload when import behavior changes.

## Current Gaps And Intended Next Moves

Known gaps:

- No database migrations yet; schema is created by SQLAlchemy metadata.
- Concordance Runs are named and documented but not implemented yet.
- OCR path is adapter-ready but not integrated into the page extraction retry loop.
- GROBID/local scholarly parser is not wired yet.
- Figure extraction is modeled but not implemented.
- Table extraction is basic Markdown normalization; richer table objects/cell geometry are not modeled yet.
- PDF rendering/highlighting is currently a placeholder in the UI.
- Saved searches and smart filters are not implemented yet.
- Metadata correction history exists as versions, but UI editing/history is minimal.
- Auth is single-user only; no roles or sharing model.
- Backup/export is documented as an intended safety feature but not implemented.

High-value next steps:

- Add Alembic migrations before schema changes accumulate.
- Add capability-version tracking and Concordance Run job APIs before several processing features diverge.
- Build document edit UI for titles, authors, DOI, citation status, tags, domains, and custom attributes.
- Wire OCR fallback for low-text pages with Google Vision.
- Add richer layout fixtures for two-column PDFs, multi-page tables, and table-heavy papers.
- Add real PDF viewer with highlights/notes.
- Add saved searches and richer filters.
- Add backup/export command for metadata plus GCS manifest.
- Add Playwright smoke tests for login, import, library search, citation copy, project bibliography, and day/night modes.

## Decision Log

### 2026-06-17: V1 scaffold

Decision: Build Medusa as a Dockerized local-first web app with React/Vite frontend, FastAPI backend, worker service, and PostgreSQL/pgvector database.

Why: The app needs reliable metadata/search/jobs beyond SQLite, and the user wants safe stop/start behavior on a laptop with LAN access.

Consequences:

- Docker Compose is the default run path.
- Port `3737` belongs to the frontend.
- Durable processing state lives in Postgres.
- GCS/OpenAI/Vision are optional credentials at boot but first-class integration points.

### 2026-06-17: Citation accuracy policy

Decision: Generate APA immediately when possible, but mark citations `verified` only when enough metadata exists and DOI/Crossref evidence is available. Otherwise use `needs_review`.

Why: Completely accurate citations are a product requirement. Review is safer than silently promoting uncertain model output.

Consequences:

- Review Queue is a core workflow, not an error state.
- Citation candidates store evidence and confidence.

### 2026-06-17: Quiet cockpit design

Decision: Use a dense cockpit layout with restrained blue/teal/amber status colors and day/night themes.

Why: The app is for repeated research work, not marketing. It should prioritize scanning, comparison, and repeated action.

Consequences:

- Avoid hero pages, decorative gradients, and loud color.
- Prefer stable panes, tables/lists, compact buttons, and evidence panels.

### 2026-06-17: Codex architecture record

Decision: Add `AGENTS.md` and this architecture record as required context for future Codex sessions.

Why: Medusa will evolve through many iterations. A durable design and architecture memory prevents accidental drift and makes future revisions faster.

Consequences:

- Future material changes should update this file in the same change.
- `AGENTS.md` instructs Codex to read this file before architectural/design work.

### 2026-06-17: Layout-aware extraction

Decision: Treat two-column pages and tables as first-class import concerns. Extract pages from layout blocks, detect column clusters, read columns in scholarly article order, and normalize detected tables into Markdown.

Why: Academic PDFs often use two columns and dense tables. Naive text extraction can interleave columns or flatten tables into unusable text, damaging search, summaries, citation inference, and later question answering.

Consequences:

- `backend/app/services/extraction.py` owns reading-order heuristics and table Markdown conversion.
- Search and AI enrichment receive table text as structured Markdown inside page text.
- Future extraction upgrades should preserve or improve this contract rather than reverting to raw `page.get_text("text")`.

### 2026-06-17: Ephemeral processing cache

Decision: `data/processing-cache` is temporary working storage, not a durable document store. Successful jobs delete their cache copy after indexing.

Why: Originals belong in GCS or the configured local fallback store. The cache exists only to decouple uploads from worker processing and retries.

Consequences:

- Queued/running/failed jobs may retain cache files.
- Completed jobs should remove `local_cache_path` from metadata evidence and record cache cleanup.
- Future retry-from-GCS work should rehydrate cache from the original object URI when needed.

### 2026-06-17: Conservative title-only citation evidence

Decision: Keep DOI Crossref lookups, but require title-only Crossref candidates to pass a strong normalized-title similarity threshold before storing them as evidence.

Why: Short or synthetic titles can produce plausible-looking but wrong Crossref matches. Evidence attached to a document should help review, not pollute it.

Consequences:

- Title-only matches below the threshold are ignored.
- Verified citation status still requires enough metadata plus DOI or accepted Crossref evidence.

### 2026-06-17: Local GCS credential mounting

Decision: Keep GCS service-account JSON files under ignored `data/secrets` and mount that directory read-only into backend and worker containers.

Why: Medusa needs real GCS access locally, but credentials must never be committed. A repo-local ignored path is easier to move and reason about than binding a Desktop-specific absolute path.

Consequences:

- `.env` points `GOOGLE_APPLICATION_CREDENTIALS` at `/app/data/secrets/<key>.json`.
- `docker-compose.yml` mounts `./data/secrets:/app/data/secrets:ro`.
- GCS IAM should include `storage.objects.create`, `storage.objects.get`, and `storage.objects.delete` for normal app operation; `storage.objects.list` is expected for future manifest/export checks.
- Future credential rotations should replace the local JSON file and update ignored `.env` if the filename changes.

### 2026-06-17: Concordance Runs for retroactive feature upgrades

Decision: Call retroactive library upgrade jobs **Concordance Runs**.

Why: Medusa will gain document-intelligence features over time, and old imports must not be stranded on older extraction/search/citation/tagging behavior. "Concordance" has scholarly resonance and captures the goal: bringing the library back into agreement with the current system.

Consequences:

- New document-processing features should define both import-time behavior and Concordance behavior.
- Capability versions are needed so Medusa can identify stale or missing derived artifacts.
- Concordance Runs should be durable jobs with review-safe output, progress events, retry semantics, and filters for whole-library, domain, project, saved-search, and selected-document scopes.
