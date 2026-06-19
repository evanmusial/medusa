# Medusa Design And Architecture Record

Last updated: 2026-06-18

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
- Discover DOI-based related papers for completed documents, mark which recommendations already exist in the library, and queue open-PDF recommendations through the normal import pipeline.
- Keep ambiguous metadata and citations visible in Queue instead of pretending uncertain output is verified.
- Build project run sheets with resource status and exportable APA/BibTeX/RIS/CSL bibliographies.

## Design System Direction

Medusa should feel like a serious research cockpit: dense, calm, polished, and fast to scan.

Current UI architecture:

- Fixed top header with the Medusa emblem, global search aligned by default to the Library document-list pane, theme toggle, and session action.
- Resizable/collapsible left sidebar navigation: Library, Domains, Projects, Queue, Notes, Import, Settings.
- Main Library view uses a tri-pane layout:
  - Resizable left filter pane for domains, tags, smart filters, and saved searches. The pane has a content-aware minimum so select controls and their affordances remain visible.
  - Center dense document results with selected-document bulk edit and batch Concordance controls.
  - Resizable right document detail/correction pane for authenticated original PDF preview, normalized one-page parsed text reading, annotations, citation, summary, extracted figures, tags, domains, attributes, history, and evidence.
- Library Reader mode can expand the selected document to the whole lower work area while preserving document controls, PDF/Text tabs, citation actions, notes, and metadata sections.
- Completed DOI-bearing documents expose a Library detail-pane Recommendations panel. The panel refreshes related papers from scholarly metadata services, shows title, DOI, venue, year, source, short abstract/description, existing-library status, and open-PDF availability, supports hiding existing matches, copying just the DOI or title, and queues selected or all-new open PDFs for import.
- Import view centers immediate drag/drop upload plus a batch-defaults intake panel for optional label, priority, read status, domains, tags, and projects. Domains, tags, and projects use searchable chip pickers with restrained inline creation so bulk uploads can be organized before files are dropped.
- Import view also provides active drop-target feedback, duplicate-decision handling, and live job status with per-file step labels.
- The sidebar Import badge shows active import jobs only; the bottom of the expanded sidebar shows a clickable import progress bar with running and queued import counts, active step, and elapsed time while uploads are queued or processing. Clicking it opens Queue. The top-level Jobs metric may include imports plus Concordance work.
- Projects view supports project creation, run-sheet resource management, status/priority/used tracking, project notes, and bibliography generation.
- Queue shows queued/running import jobs with per-job stage progress and citation candidates that need human attention, and supports accepting or rejecting citation candidates.
- Notes view supports notes/reminders attached to documents, domains, projects, or the general library.
- Settings exposes preferences, day/night accent color controls, document-analysis model controls, document cache budget controls, backup/export controls for full metadata JSON and a storage manifest, and Concordance controls.
- Metadata restore is CLI-first: dry-run by default, explicit `--apply`, and intended for backup drills or fresh-database recovery.

Visual decisions:

- The header brand uses the user-provided transparent Medusa emblem SVG plus a large lowercase `medusa` wordmark in Century Schoolbook Bold, falling back to compatible local serif faces. The emblem is borderless and sized to visually match the wordmark height.
- The header brand lockup should have restrained, generous top/bottom padding plus modest side padding so the emblem and wordmark breathe without turning the header into a hero element.
- The emblem source remains black with transparency; night mode inverts it with CSS so the glyph reads light while keeping the transparent background intact. The same SVG is used as the browser favicon.
- The sidebar owns its collapse/expand control. The control belongs at the bottom of the navigation column, and collapsed navigation should retain a narrow restore rail instead of moving that control back into the header.
- Day mode uses cool white surfaces, ink text, restrained blue primary actions, teal success, amber warnings.
- Night mode uses charcoal surfaces, high-contrast text, blue/teal accents, and soft borders.
- Avoid loud gradients, marketing-style hero layouts, decorative blobs, or oversized display typography inside the work surface.
- Use icons for actions and navigation where they improve scanning.
- Dashboard metrics should read as quiet text on the work-surface background, not as button-like cards.
- Keep cards for framed tools or repeated items; do not nest cards.
- Keep cockpit spacing dense and practical; panes should prioritize scanning and repeated work over airy presentation.

## Architecture Snapshot

Runtime shape:

- `frontend`: React + TypeScript + Vite, served on port `3737`.
- `backend`: FastAPI API on internal port `8000`.
- `worker`: Python durable import processor.
- `db`: PostgreSQL with `pgvector`.
- `docker-compose.yml` wires all services and exposes only the frontend on `3737`.
- Backend and worker startup initialize PostgreSQL through Alembic migrations before normal app workflows open.

Data storage:

- PostgreSQL is the system of record.
- Alembic is the schema migration system for PostgreSQL. SQLite tests still use SQLAlchemy metadata creation for fast isolated test schemas.
- Original files are checksum-addressed. Current storage keys use `documents/<first-two-sha256-chars>/<sha256>/<original-filename>` under the configured prefix.
- GCS is the intended original-object store when `GCS_BUCKET` and Google credentials are configured.
- Local filesystem storage under `data/originals` is the fallback so the app can boot and import without cloud credentials.
- GCS service-account files live locally under ignored `data/secrets`; Compose mounts that directory read-only at `/app/data/secrets`.
- The GCS service account needs object-level create/read/delete access for the configured bucket and prefix. `storage.buckets.get` is useful for diagnostics, but object upload requires `storage.objects.create`.
- Processing/document cache lives under `data/processing-cache`, is ignored by git, and keeps local PDF copies for queued/running/failed work plus recently completed imports within the configured document cache budget.

Backend modules:

- `backend/app/main.py`: FastAPI app, auth, CRUD/search/import/project/review APIs.
- `backend/app/database.py`: database engine, session scope, Alembic startup migration runner, and SQLite/test metadata fallback.
- `backend/app/models.py`: ORM entities and relationships.
- `backend/app/worker.py`: long-running durable job loop.
- `backend/app/services/storage.py`: GCS/local storage adapter.
- `backend/app/services/analysis_models.py`: canonical document-analysis task registry, default model ids, model option lists, and task descriptions used by Settings.
- `backend/app/services/document_cache.py`: bounded local PDF cache registration, lookup, storage rehydration, and pruning.
- `backend/app/services/extraction.py`: layout-aware PDF text extraction, deterministic page text cleanup, table normalization, and chunking.
- `backend/app/services/ai.py`: OpenAI Responses API structured metadata, PDF-file context, separately configurable summary, APA candidate, topic/keyword, page text normalization calls with bounded fallback, and embedding adapter.
- `backend/app/services/ocr.py`: Google Vision adapter placeholder.
- `backend/app/services/processing.py`: import processing orchestration.
- `backend/app/services/preferences.py`: DB-backed local preferences such as import worker concurrency, accent colors, document cache size, and document-analysis model selections.
- `backend/app/services/concordance.py`: retroactive capability registry, run creation, and Concordance job processing.
- `backend/app/services/figures.py`: embedded PDF figure extraction, durable asset storage, and figure row creation.
- `backend/app/services/exports.py`: authenticated metadata export and durable storage manifest builders.
- `backend/app/services/restore.py`: metadata export validation, dry-run planning, and fresh-database restore logic.
- `backend/app/services/citations.py`: APA/BibTeX/RIS/CSL formatting utilities.
- `backend/app/services/verifier.py`: Crossref lookup and verification helpers.
- `backend/app/services/recommendations.py`: DOI normalization, OpenAlex/Semantic Scholar/Crossref related-paper adapters, recommendation caching/matching, and open-PDF recommendation import queueing.
- `backend/app/tools/restore_export.py`: CLI entry point for validating, planning, and applying metadata restores.

Frontend modules:

- `frontend/src/App.tsx`: current full application shell and views.
- `frontend/src/lib/api.ts`: API client.
- `frontend/src/types.ts`: shared frontend response types.
- `frontend/src/styles.css`: design system tokens, layout, and responsive rules.

## Data Model

Current core entities:

- `User`, `SessionToken`
- `AppPreference`: local DB-backed operational preferences such as import worker concurrency, day/night accent colors, document-analysis model choices, and document cache size.
- `Domain`: nestable knowledge hierarchy.
- `Tag`: flat keyword/topic label.
- `SavedSearch`: named query and filter presets for repeated research views and Concordance scopes.
- `Document`: canonical research object and processing/search state.
- `DocumentVersion`: metadata correction/history snapshots.
- `DocumentCapability`: per-document completion state for versioned import/concordance capabilities.
- `DocumentRecommendation`: cached DOI/title-based related-paper recommendations for a source document, including provider/relation evidence, DOI, title, authors, venue, description, open PDF/source URLs, existing-library/import matches, and import status.
- `DocumentPage`: raw extracted per-page text, normalized reader text, source, low-text flags, and optional page image URI; the document detail API exposes these pages for the full-text reader.
- `TextChunk`: chunked full text and optional embedding vector.
- `Figure`: extracted figures/captions/gists with durable asset URIs.
- `Annotation`: page-aware highlights/notes with color, body, soft delete, and reserved geometry for future PDF overlays.
- `Note`: document/domain/project notes and reminders.
- `AttributeDefinition`, `DocumentAttributeValue`: custom per-document attributes.
- `Project`, `ProjectItem`, `ProjectBibliography`: run sheets, resource status/priority/used tracking, project notes, and citation exports.
- `ImportBatch`, `ImportJob`, `ProcessingEvent`: durable import bookkeeping.
- `ConcordanceRun`, `ConcordanceJob`: durable retroactive upgrade bookkeeping.
- `CitationCandidate`: reviewable citation/metadata candidates.

Important modeling decisions:

- Documents are soft-deleted via `deleted_at`.
- Duplicate detection starts with SHA-256 checksum, but checksum is not unique in the data model because the user can deliberately import an exact duplicate.
- Import duplicate decisions are explicit: skip duplicates, overwrite an existing matching document, or import anyway as a separate document.
- Library views surface exact checksum duplicates with duplicate counts and a duplicate-status filter.
- Citation status is explicit, with `needs_review` as the safe uncertain state.
- Accepted citation candidates apply their metadata/citation to the document, set citation status to `verified`, and create a `DocumentVersion` audit snapshot.
- Metadata evidence is stored as JSON so extraction, Crossref, OpenAI, and future sources can be audited.
- Title-only citation evidence must pass a strong normalized-title match before it is stored as Crossref evidence.
- Crossref evidence may fill missing citation fields such as authors, year, venue, DOI, publisher, and source URL; it should not silently overwrite existing user-corrected fields.
- APA citations should favor DOI links whenever a DOI can be located and verified. If no DOI can be verified, the citation should prefer a direct stable source link, ideally a PDF or other static document, over a transient search or generic landing page.
- Citation and metadata text from Crossref, OpenAI, PDFs, or user review candidates should be normalized for display and exports, including decoding HTML entities such as `&amp;`, `&quot;`, and numeric character references into their actual characters.
- Recommendation matching prefers normalized DOI equality and falls back only to a strict normalized-title match. Recommendations may be cached from multiple providers; source/provider evidence is retained so a candidate can be inspected later.
- Recommendation imports do not create a parallel processing path. When an open PDF URL is available from a lawful scholarly metadata source, the download endpoint creates normal `ImportBatch` and `ImportJob` records, stores the PDF through the configured storage adapter, and lets the worker process it like any other PDF. Recommendations without open PDF URLs remain metadata-only candidates.
- Full-text search data is stored on `Document.search_text`; chunk embeddings live on `TextChunk.embedding`.
- Search and reader copy prefer `DocumentPage.normalized_text` when present and fall back to raw extracted `DocumentPage.text`.
- Document annotations contribute their body text to `Document.search_text`; deleted annotations are excluded from active document detail and search rebuilds.
- Processing capabilities are versioned so Medusa can tell which documents need a Concordance Run.

## Processing Pipeline

Current import path:

1. User uploads one or more PDFs through `/api/imports/batches`.
2. Frontend calls `/api/imports/duplicates` to hash the proposed upload set and detect exact checksum matches against the library and within the same drop.
3. If duplicates are found, the user chooses skip, overwrite, or import anyway before `/api/imports/batches` queues the batch.
4. The upload request includes current batch defaults: optional label, domain IDs, tag IDs, project IDs, priority, read status, and attributes.
5. Backend applies the duplicate strategy. Skip creates a completed `duplicate_skipped` job, overwrite reuses and reprocesses the selected existing document record, and import-anyway creates another document with the same checksum.
6. Backend applies batch defaults to each imported document and creates project run-sheet items for selected projects.
7. Original is written to GCS when configured, otherwise to local storage.
8. A document-specific local cache copy is saved under `data/processing-cache` and recorded as `document_cache_path`; the original has already been written to GCS/local storage before cache policy applies.
9. `Document`, `ImportBatch`, and `ImportJob` records are committed.
10. Worker claims queued jobs and moves them through extraction, enrichment, indexing, and completion. Import processing defaults to 4 concurrent jobs from one worker process and can be changed to any positive value in Settings.
11. PDF text and pages are extracted with PyMuPDF using layout-aware block ordering.
12. Two-column pages should read down the left column before crossing to the right column, while full-width headers/sections remain in vertical order.
13. Detected tables are converted to Markdown and included in page text so table content is searchable and available to metadata/summarization.
14. Page text is normalized into readable paragraph flow. If `OPENAI_API_KEY` and `MEDUSA_OPENAI_NORMALIZE_PAGE_TEXT=true` are configured, OpenAI conforms the text with the Settings-selected Text on Pages model while preserving wording/order; otherwise local cleanup removes common spacing and hyphenation artifacts. Page-normalization requests use `MEDUSA_OPENAI_PAGE_NORMALIZATION_TIMEOUT_SECONDS` and fall back locally on timeout/error.
15. Embedded PDF figures/images are extracted with PyMuPDF, stored through the configured storage adapter, and recorded as `Figure` rows.
16. Normalized text is chunked for search/embedding, falling back to raw extracted text when needed.
17. OpenAI metadata extraction runs only when `OPENAI_API_KEY` exists; otherwise a low-confidence review record is produced.
18. Async document-intelligence work is split into Settings-selectable tasks: Metadata, Summary, APA Citation Matching, Keywords & Topics, Text on Pages (Normalization), Text Chunk Encoding, and future Accessory Summaries. GPT-backed tasks default to `OPENAI_MODEL=gpt-5.5`; Text Chunk Encoding defaults to `OPENAI_EMBEDDING_MODEL`.
19. When `MEDUSA_OPENAI_SEND_PDF=true`, Medusa sends the original PDF as a Responses API file input alongside extracted text when the file is below `MEDUSA_OPENAI_PDF_FILE_MAX_MB`; Concordance reruns hydrate the original PDF from the local document cache or durable storage.
20. Crossref lookup is attempted by DOI/title. If Crossref evidence is available, missing citation fields are filled from that evidence without overwriting existing values.
21. APA citation is generated. It is marked `verified` only when enough metadata exists and DOI/Crossref evidence is present.
22. Uncertain citations create `CitationCandidate` review records.
23. Successful jobs retain their local PDF cache copy up to the configured Document Cache Size. Budget pruning deletes oldest non-active cache files and leaves GCS/local original storage untouched.

Durability decisions:

- Jobs are database-backed and step-oriented.
- Processing events are appended for auditability.
- The app must tolerate stop/start without losing queued jobs.
- Worker startup immediately requeues `running` imports and Concordance jobs from the previous worker process. Worker claims also use `locked_at` and `MEDUSA_WORKER_STALE_JOB_SECONDS` as a stale-lock recovery guard.
- The worker keeps an in-process set of active import job IDs so parallel import slots do not reclaim each other's long-running jobs as stale. Restart recovery still requeues interrupted jobs because that in-memory set disappears with the worker process.
- Import jobs checkpoint visible steps before long phases (`extracting`, `normalizing_pages`, `normalizing_page_<n>`, `extracting_figures`, `enriching`, `indexing`, `cleaning_cache`) so Queue does not appear frozen at `stored` during real processing.
- Container shutdown is intentionally restart-safe rather than interrupt-perfect: in-flight import threads may be terminated with the container, and the next worker startup requeues those `running` rows. The current document may repeat its current step to preserve correctness. Page normalization commits each completed page and resumes from persisted normalized pages when possible.
- Import processors should stay idempotent where possible and avoid duplicating pages/chunks when a step reruns.
- Completed jobs may keep local PDF cache copies in `data/processing-cache` within the configured budget. Originals are retained in GCS or the configured local fallback store regardless of cache pruning.
- Failed jobs may keep their processing-cache copy to support retry and debugging and are protected from budget pruning while still active/recoverable.

## Concordance Runs

Concordance Runs are retroactive upgrade jobs for the library. They bring already-imported documents into agreement with the current Medusa feature set without requiring re-upload.

Implemented foundation:

- `DocumentCapability` records document-level capability completion state.
- `ConcordanceRun` records scope, requested capability keys, status, and progress counters.
- `ConcordanceJob` records document/capability work items with target version, attempts, errors, and completion state.
- The worker processes import jobs first, up to the configured import concurrency preference, then Concordance jobs from the same durable database queue pattern.
- Settings includes a Concordance panel that can start scoped runs and display current capability/run/job status.
- The document detail pane can start a Concordance Run for the current document.

Current first capabilities:

- `page_text_normalization` v2: conforms raw extracted page text into readable paragraph flow using OpenAI when configured and local cleanup as a fallback; Concordance reruns use the original PDF context when available.
- `search_index` v2: rebuilds `Document.search_text` from title, authors, abstract, summary, APA citation, normalized pages, notes, custom attributes, tags, and domains.
- `citation_refresh` v2: regenerates Markdown APA 7 text with Crossref-backed fields and refreshes citation status; uncertain output stays in Queue for citation review.
- `summary_topics` v4: uses the configured AI adapter with extracted text plus original PDF context when available to fill missing metadata, concise Markdown summaries, APA candidates, topics, and keywords without overwriting user-corrected identity metadata.
- `figure_assets` v1: extracts embedded PDF figures/images into durable storage and attaches them to document records.
- `recommendations` v1: refreshes DOI-based related-paper recommendations from OpenAlex, Semantic Scholar, and Crossref, marks already-present library matches, and caches provider evidence without importing full text automatically.

Use Concordance Runs when adding or improving:

- keyword/topic extraction
- layout extraction, OCR, table handling, or figure extraction
- citation verification or formatting
- summaries, aspect-specific summaries, attributes, or notes-derived indexes
- embeddings, full-text search fields, image gists, or other search surfaces

Expected behavior:

- New features must define how they run at import time and how they apply to existing documents.
- Runs should be triggerable for the whole library, selected documents, a domain/subdomain, a project, a saved search, or a filtered result set.
- Current UI supports whole-library, current document, current search text, domain, and project scopes. The API supports selected-document runs through `scope_type="documents"` with document ids.
- Saved-search scopes use `SavedSearch` rows so repeated research views can be upgraded retroactively without re-entering filters.
- Capability versions should be recorded per document or per derived artifact so the app can find missing/outdated work.
- Concordance jobs must be durable, resumable, idempotent, and visible through processing events/progress.
- A run should avoid overwriting user-corrected metadata unless explicitly requested or unless it records a reviewable candidate.
- Ambiguous or low-confidence output should go to Queue for citation review rather than silently replacing trusted data.
- Model changes in Settings affect new work; older documents should be refreshed through Concordance when their derived analysis needs to match the newly selected model set.

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

Operational settings:

- `MEDUSA_IMPORT_WORKER_CONCURRENCY` sets the startup default for concurrent import processing. The built-in default is 4, and Settings accepts any positive value while warning that higher values can create a burst of OpenAI calls and cost.
- `MEDUSA_DOCUMENT_CACHE_SIZE_MB` sets the startup default for the bounded local document cache. The built-in default is 1,000 MB, and Settings can change the active value without affecting GCS/local original storage writes.
- The active import concurrency, accent color preferences, document cache size, and model selections are stored in PostgreSQL through `AppPreference` and can be changed in Settings without editing `.env`.

Safe deletion:

- Documents use soft delete. Original object cleanup is intentionally not automatic yet.
- Original PDFs are served through authenticated `/api/documents/{document_id}/original` responses and should not require public GCS objects.
- Parsed pages are served as part of authenticated `/api/documents/{document_id}` detail responses for the in-app full-text reader.
- Backup/export routes are authenticated and intentionally omit API keys, service-account credentials, password hashes, and session tokens.
- `/api/exports/metadata` returns full metadata JSON with organization state, extracted text, notes, correction history, jobs, Concordance history, and an embedded storage manifest.
- `/api/exports/storage-manifest` returns the durable original/page/figure asset URI manifest by itself.
- Metadata restore is available through `python -m app.tools.restore_export /path/to/medusa-metadata.json`.
- Restore dry-runs validate schema/safety flags, reject secret-bearing keys, report conflicts, summarize embedded storage-manifest counts, and make no writes.
- Restore applies preserve export IDs by default, restore research metadata and storage URI references, skip auth credentials/session state, and do not restore text-chunk embeddings because metadata exports intentionally omit vector values.
- Restored queued/running import and Concordance jobs are parked as `restored_paused` by default so a worker cannot accidentally replay old backup state. `--reactivate-jobs` exists for deliberate maintenance use.

Verification baseline:

- `backend/.venv/bin/pytest`
- `npm --prefix frontend run build`
- `curl -sS http://localhost:3737/api/health`
- Optional: authenticated dashboard and smoke PDF upload when import behavior changes.

## Current Gaps And Intended Next Moves

Known gaps:

- Alembic initial migration is implemented; future schema changes should add migration revisions instead of relying on metadata-only creation.
- Concordance Run foundation and scoped UI controls are implemented; arbitrary-filter scopes beyond saved searches are still future work.
- Concordance capability coverage is still early; OCR, figure caption/gist enrichment, richer layout upgrades, and arbitrary-filter scope need follow-up implementation.
- OCR path is adapter-ready but not integrated into the page extraction retry loop.
- GROBID/local scholarly parser is not wired yet.
- DOI/source-link resolution is not exhaustive yet. Citation refresh should expand beyond current DOI/title Crossref lookup to search extracted text, references, Crossref, Semantic Scholar, DOI.org, publisher pages, and web evidence before giving up on DOI discovery.
- Figure extraction stores embedded PDF images and previews them in the detail pane; figure caption/gist enrichment and region-aware figure/table geometry are still future work.
- Table extraction is basic Markdown normalization; richer table objects/cell geometry are not modeled yet.
- Original PDF preview/open is implemented through authenticated routes, and normalized parsed page text is available in a one-page reader with page arrows and page note entry. Geometric text selection/highlight overlay remains future work.
- Saved searches, smart filters, and bulk edit controls are implemented; richer multi-condition filter builders are still future work.
- Metadata correction UI exists for core identity fields, citation status, read/priority state, tags, domains, summaries, and custom attributes. Correction history is captured as `DocumentVersion` snapshots, but a fuller history diff viewer is still future work.
- Auth is single-user only; no roles or sharing model.
- Backup/export is implemented as authenticated JSON downloads. Metadata restore from those exports is implemented as a CLI-first dry-run/apply workflow; browser-based restore controls and scheduled backup drills remain future work.
- Accessory Summaries are not implemented yet; Settings already reserves a model selection for future user-prompted custom summaries that should run against the original PDF context.

High-value next steps:

- Wire OCR fallback for low-text pages with Google Vision.
- Add exhaustive DOI/source-link resolution, robust citation verification beyond Crossref basics, and richer field-level evidence review.
- Add arbitrary-filter scopes and richer saved-search management for Concordance Runs.
- Build richer history review/diff UI for manual corrections and imported metadata candidates.
- Add AI figure caption/gist enrichment and include figure gists in richer semantic search.
- Add Accessory Summaries as user-prompted custom summary jobs backed by the original PDF and the Settings-selected model.
- Add richer layout fixtures for two-column PDFs, multi-page tables, and table-heavy papers.
- Add real PDF viewer with highlights/notes.
- Add geometric PDF highlight overlays on top of the current annotation records.
- Add richer multi-condition filter builders.
- Add browser-based restore controls for metadata exports.
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

- Queue citation review is a core workflow, not an error state.
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

### 2026-06-18: Bounded processing/document cache

Decision: `data/processing-cache` is managed local working storage and a bounded document cache. Successful jobs retain cache copies until the configured Document Cache Size budget prunes older non-active files.

Why: Originals still belong in GCS or the configured local fallback store, but keeping recent imported PDFs locally makes Concordance and future Accessory Summary runs faster and less dependent on immediate storage reads.

Consequences:

- Queued/running/failed jobs retain cache files and are protected from budget pruning while recoverable.
- Completed jobs remove `local_cache_path`, retain `document_cache_path` when the file remains cached, and record budget checks in processing events.
- Cache pruning does not affect GCS/local original storage writes at upload time.
- Concordance can rehydrate a missing local cache copy from the original object URI when needed.

### 2026-06-17: Conservative title-only citation evidence

Decision: Keep DOI Crossref lookups, but require title-only Crossref candidates to pass a strong normalized-title similarity threshold before storing them as evidence.

Why: Short or synthetic titles can produce plausible-looking but wrong Crossref matches. Evidence attached to a document should help review, not pollute it.

Consequences:

- Title-only matches below the threshold are ignored.
- Verified citation status still requires enough metadata plus DOI or accepted Crossref evidence.

### 2026-06-18: Crossref fills missing citation fields

Decision: Use trusted Crossref evidence to fill blank citation metadata fields during import and Concordance citation refresh.

Why: OpenAI extraction may be unavailable, and local PDF text extraction can miss authors/year/venue even when Crossref has already matched the exact title or DOI. Storing Crossref evidence without using it leaves documents stuck with incomplete APA strings such as `(n.d.). Title.`

Consequences:

- Crossref evidence can fill missing authors, publication year, venue, publisher, DOI, and source URL.
- Existing document fields are left intact to avoid silently overwriting user-corrected metadata.
- Citation refresh can use already-stored Crossref evidence when a live lookup is unavailable.
- Broader conflict comparison and field-level review remain future work.

### 2026-06-18: Normalized page text reader

Decision: Store normalized page text separately from raw PDF extraction and make the parsed-text reader show one readable page at a time with explicit previous/next navigation.

Why: Raw PDF extraction preserves layout artifacts that are useful for debugging but poor for reading. Medusa needs contiguous paragraph flow that follows the original document order without odd spacing, while still preserving raw extraction evidence for reprocessing and comparison.

Consequences:

- `DocumentPage.normalized_text` is the preferred reader/search text; `DocumentPage.text` remains the raw extraction fallback.
- Import jobs normalize page text after layout extraction. OpenAI performs the conforming pass when configured; deterministic cleanup handles whitespace, spaced letters, hyphenated wraps, and paragraph joins when OpenAI is unavailable.
- `page_text_normalization` is a Concordance capability so older imports can be upgraded without re-uploading.
- `search_index` is versioned to v2 because it now prefers normalized page text.
- The document detail text reader displays a single page with visible arrow controls, page counter, page note action, and full-text copy.

### 2026-06-18: Navigation and batch workbench controls

Decision: Add a persistent header toggle for the left navigation, make dashboard metrics visually quiet, and expose Concordance Runs from selected rows in the document list.

Why: The cockpit should be dense without making passive information look clickable. The left navigation should get out of the way when the user wants more horizontal workspace, and selected-document workflows should support both metadata edits and retroactive processing.

Consequences:

- The sidebar collapsed state is stored locally and can be toggled from the header even while hidden.
- Dashboard metrics render directly on the grey work surface while retaining their spacing and text alignment.
- The Library bulk toolbar can queue a `documents`-scoped Concordance Run for selected document ids.
- The existing Settings Concordance panel remains the place for whole-library, saved-search, domain, and project scoped runs.

### 2026-06-18: Header and bulk tag refinement

Decision: Simplify the header wordmark, align global search with the default Library document-list pane, darken light-mode button outlines, and allow bulk custom tag nomination.

Why: The brand should read as a polished mark rather than a labeled placeholder, the search field should visually belong to the center work pane, and bulk tagging needs to support both known taxonomy terms and newly nominated terms without leaving the document list.

Consequences:

- The `Research Library` subtitle is removed from the header/login brand lockup.
- The Medusa emblem is borderless and larger; the `medusa` serif wordmark is scaled to the emblem height.
- The topbar's default grid offset aligns the global search with the Library middle pane at default pane widths.
- Light-mode secondary/icon button borders use a darker neutral token for better visibility.
- The Library bulk tag selector sorts existing tags alphabetically and includes a custom tag input that creates/applies the new tag through bulk update.

### 2026-06-18: Reader mode and Markdown citation surfaces

Decision: Add an expanded Library Reader mode, render summary/citation fields as controlled Markdown, and expose document-level citation refresh as a live, disabled-while-running action.

Why: The right detail pane is useful for preview and correction, but serious reading needs the full lower work area while keeping controls nearby. APA citations and scientific summaries also need formatting, especially italics and structured summaries, without forcing the user to read raw Markdown syntax.

Consequences:

- The Library filter pane minimum is raised and enforced through persisted pane clamping so select arrows and control text cannot be collapsed out of view.
- Document rows include a short rendered Markdown summary preview instead of leaving summary text as one large undifferentiated paragraph.
- `rich_summary` and `apa_citation` remain the database fields, but their stored value is treated as Markdown text.
- OpenAI extraction prompts now request concise Markdown summaries with labeled bullets.
- APA formatter output uses Markdown italics for APA publication elements and Crossref volume/issue/page fields when available.
- The document detail and expanded Reader surfaces include APA copy plus Check controls. Check queues a forced `citation_refresh` Concordance Run for that document and disables while a matching queued/running job exists.
- `citation_refresh` is versioned to v2 and `summary_topics` to v3 so existing imports can be conformed through Concordance Runs.

### 2026-06-18: DOI-first citation links

Decision: Make exhaustive DOI discovery the next citation-verification priority. APA citations should prefer DOI links when a DOI can be located; if no DOI is available, use the best direct stable source link, preferably a PDF or other static document.

Why: Citation accuracy includes retrievability. A correct-looking APA string is not enough if Medusa could have found the DOI or a more durable source link with deeper evidence gathering.

Consequences:

- Citation refresh should become more exhaustive than the current DOI/title Crossref lookup.
- Future DOI discovery should inspect document metadata, extracted text, references, Crossref, Semantic Scholar, DOI.org, publisher pages, and targeted web evidence.
- Every attempted source, conflict, and fallback source-link choice should be recorded as evidence for Queue inspection.
- DOI links should win over source URLs in APA output; stable PDF/static-source URLs are acceptable only when DOI resolution fails.

### 2026-06-18: Task-level model controls and PDF-context enrichment

Decision: Use `gpt-5.5` as the default GPT model for asynchronous OpenAI document-intelligence work, expose task-level overrides in Settings, and include original PDF file input when configured and size-safe.

Why: Import and Concordance jobs already run asynchronously, so Medusa can afford a slower high-quality default model, while the user may want cheaper/faster models for lower-risk tasks. Extracted text is useful, but original PDFs may preserve layout, figures, page images, and front-matter boundaries that improve extraction.

Consequences:

- `.env` should hold the private API key and `OPENAI_MODEL=gpt-5.5` as the startup default.
- Settings exposes seven document-analysis model controls: Metadata, Summary, APA Citation Matching, Keywords & Topics, Text on Pages (Normalization), Text Chunk Encoding, and future Accessory Summaries.
- The first five and future Accessory Summaries are GPT/Responses tasks. Text Chunk Encoding remains the embeddings endpoint and defaults to `OPENAI_EMBEDDING_MODEL`.
- `MEDUSA_OPENAI_SEND_PDF=true` enables Responses API file input for original PDFs below `MEDUSA_OPENAI_PDF_FILE_MAX_MB`.
- AI-generated APA citations remain candidates/evidence unless normalized metadata and trusted citation evidence support verification.
- `page_text_normalization` was raised to v2 and `summary_topics` to v4 for task-level model evidence and Concordance PDF-context reruns.

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

### 2026-06-17: Immediate import drop target

Decision: The Import dropzone should start uploads as soon as PDF files are dropped or selected, and the whole drop panel should visibly switch into an active acceptance state while files are dragged over it.

Why: Import is a high-frequency workflow. The target should feel physically obvious and should not require a second confirmation click after the user drops files in the right place.

Consequences:

- The entire dropzone surface, including the icon area, is the file target.
- Priority and read-status controls define defaults for the immediate batch.
- The UI must show an unmistakable drag-over state before drop and live upload/submission status after drop.

### 2026-06-17: Modular resizable panes

Decision: Make the main cockpit panes modular and resizable with draggable splitters. Persist user-adjusted widths locally in the browser.

Why: Research work shifts between browsing, triage, metadata review, and reading. Fixed panes force the user into one layout, while resizable panes let the interface adapt to the current task without introducing separate modes.

Consequences:

- The sidebar, Library filter pane, and Library detail pane should be resizable on desktop.
- Splitters should remain subtle, keyboard-accessible, and visually consistent with the quiet cockpit style.
- Small screens should collapse to a single-column layout and hide drag splitters.
- Default spacing should stay dense enough for research scanning, with stable dimensions so text and controls do not jump while resizing.

### 2026-06-17: Concordance Run foundation

Decision: Implement Concordance Runs as first-class durable database jobs with a versioned capability registry, document-level completion state, worker processing, and a Settings control panel.

Why: Medusa will gain extraction, citation, OCR, search, and AI features over time. Existing imports need a trustworthy way to receive those features without re-uploading files or relying on one-off maintenance scripts.

Consequences:

- New document-intelligence features should add or update a capability definition and define both import-time and Concordance behavior.
- The worker now drains import jobs before Concordance jobs so new uploads stay responsive.
- The first implemented capabilities are `search_index`, `citation_refresh`, and `summary_topics`.
- Whole-library Concordance can run from Settings now; narrower scope controls are a near-term UX follow-up.

### 2026-06-18: Correction pane and scoped Concordance controls

Decision: Make the document detail pane editable and extend Concordance controls to targeted scopes.

Why: Imported scholarly metadata will sometimes be wrong, and the user needs to correct titles, authors, DOI, tags, domains, priorities, summaries, and custom attributes without leaving the reading/browsing surface. Concordance also needs to be useful on the subset currently under review, not only the whole library.

Consequences:

- Manual corrections write `DocumentVersion` snapshots with changed fields and before/after metadata.
- Citation-affecting corrections regenerate APA text unless the user explicitly edits the APA field.
- The detail pane can run Concordance for the current document.
- Settings can run Concordance for the library, current document, current search text, a domain, or a project.
- Future work should add a richer correction-history diff viewer and arbitrary-filter Concordance scopes beyond saved searches.

### 2026-06-18: Saved searches, notes, and bulk edit

Decision: Add saved searches, smart filter controls, library bulk edit, and a notes/reminders workbench.

Why: Medusa needs to support repeated research triage, not just one-off browsing. The user should be able to save a current view, return to it, bulk assign priorities/tags/domains, and keep notes or reminders attached to documents, domains, projects, or the library.

Consequences:

- `SavedSearch` stores a named query plus filter JSON and can be used as a Concordance scope.
- The Library filter pane owns saved-search creation/application/deletion and filter selection.
- The document list supports selecting visible documents and applying read status, priority, tag, and domain updates.
- Notes and reminders have CRUD APIs and a dedicated Notes workbench.
- Document-linked notes contribute to document search text.

### 2026-06-18: Figure asset extraction

Decision: Extract embedded PDF images into durable storage during import and expose them through authenticated figure asset routes.

Why: Research documents often carry meaning in figures, diagrams, scans, and embedded images. Keeping figure assets addressable lets Medusa later generate image gists, support figure-aware search, and preview extracted media without relying on the original PDF renderer.

Consequences:

- Import processing now runs a figure extraction step before metadata enrichment while the processing-cache PDF is still available.
- `Figure` rows store page number, label, basic extraction gist, and durable asset URI.
- Figure assets use storage keys under `figures/<first-two-sha256-chars>/<sha256>/...`.
- `figure_assets` is a Concordance capability so older documents can be upgraded from their durable original object without re-upload.
- The detail pane shows extracted figure thumbnails through `/api/figures/{id}/asset`.

### 2026-06-18: Metadata backup and storage manifest exports

Decision: Add authenticated JSON exports for Medusa metadata and durable storage manifests.

Why: Medusa is meant to be safe to stop, restart, move, and back up. A metadata export gives the user a portable record of the library's research organization and processing state without copying credentials or relying on direct database access.

Consequences:

- Settings now includes backup/export controls for full metadata and the asset manifest.
- `backend/app/services/exports.py` owns export construction so future restore tooling can share the schema.
- Metadata exports include documents, extracted text, tags, domains, annotations, notes, attributes, correction history, projects, jobs, Concordance state, citation candidates, and storage URI references.
- Exports intentionally omit service-account credentials, API keys, password hashes, and session tokens.
- Restore/import from an export is still future work and should validate export schema version before writing data.

### 2026-06-18: Project run-sheet management

Decision: Turn Projects into editable run sheets with project resource rows, status, priority, used/not-used tracking, notes, and all-sources or used-only bibliography generation.

Why: Projects are the bridge between the library and an actual paper, assignment, or research task. The user needs to track which resources are candidates, being read, used, or rejected and then generate a bibliography from the exact subset that made it into the work.

Consequences:

- Project detail APIs now expose `ProjectItem` rows with linked document summaries.
- The Projects view can add library documents to a project, edit each row's status/priority/used flag/note, remove resources, and generate APA/BibTeX/RIS/CSL JSON bibliographies.
- Bibliography generation accepts a used-only mode so the final source list can exclude candidates that were not used.
- Future project work should add richer sorting/filtering, due-date/status editing, and export buttons for bibliography files.

### 2026-06-18: Actionable citation review

Decision: Add Queue actions to accept or reject citation candidates.

Why: A queue that only displays uncertainty still leaves metadata work stranded. Citation review needs a direct path to promote evidence-backed metadata into the document or dismiss bad candidates.

Consequences:

- Accepting a candidate updates the document fields represented by candidate metadata, applies candidate APA text, marks the document citation as `verified`, refreshes search text, and writes a `DocumentVersion` history record.
- Rejecting a candidate changes only the candidate status and removes it from the active citation review queue.
- Future review work should show richer side-by-side evidence and support partial field-level acceptance.

### 2026-06-18: Authenticated PDF preview and annotations

Decision: Serve original PDFs through an authenticated document route and add document annotations/highlights to the detail pane.

Why: Medusa needs to support reading and marking documents, not just cataloging metadata around them. Originals should remain private in GCS/local storage while still being previewable in the app.

Consequences:

- `/api/documents/{document_id}/original` streams the durable original object through the storage adapter with inline content disposition.
- The detail pane embeds the original PDF and provides an open-in-new-tab control.
- `Annotation` rows are now exposed through CRUD endpoints and included in document detail.
- Annotation body text contributes to document search, and soft-deleted annotations are excluded from active detail/search rebuilds.
- The current annotation UI captures page, kind, color, and body; precise geometric overlay selection is future work using the existing `geometry` field.

### 2026-06-18: Parsed full-text reader

Decision: Expose extracted `DocumentPage` rows through the document detail API and add a PDF/Text reader switch in the document pane.

Why: Original PDFs need to remain viewable, but parsed scholarly text also deserves a clean reading surface for review, search validation, and page-specific notes.

Consequences:

- `/api/documents/{document_id}` includes page text, source, low-text flags, and page image URI references.
- The document pane can switch between the authenticated original PDF and parsed page text.
- Reader page note actions prefill page-aware annotations with `kind="note"` so notes stay searchable and can later map onto geometric overlays.
- Low-text pages are visible in the reader, giving the future Google Vision OCR path an obvious review surface.

### 2026-06-18: Alembic migrations

Decision: Add Alembic as the PostgreSQL schema migration system and run migrations during backend/worker startup.

Why: Medusa's schema is broad enough that metadata-only creation is risky. Migrations give future changes an ordered, reviewable upgrade path while keeping existing local data intact.

Consequences:

- `backend/alembic.ini`, `backend/alembic/env.py`, and the initial schema revision are now included in the backend image.
- `init_db()` runs Alembic for PostgreSQL and keeps SQLAlchemy metadata creation as the SQLite/test fallback.
- The initial migration is idempotent for existing local PostgreSQL databases by creating current tables and supporting indexes only when missing.
- Future model changes must include an Alembic revision and corresponding tests or smoke verification.

### 2026-06-18: Import throughput and sidebar progress

Decision: Add DB-backed import worker concurrency preferences, default concurrent imports to four per worker process while allowing higher user-selected values, and show active import progress at the bottom of the expanded sidebar.

Why: Large batches should keep moving without requiring multiple worker containers, while the user still needs a quiet, persistent signal that queued/importing documents are making progress outside the Import view.

Consequences:

- `/api/preferences` exposes active import worker, day/night accent, document cache size, model task registry, model options, and selected model preferences. Settings saves user changes as `AppPreference`.
- The worker claims multiple import jobs up to the current preference, keeps Concordance work behind active imports, and excludes in-process import IDs from stale recovery claims.
- Import page normalization records and commits per-page checkpoint events so slow OpenAI page-normalization calls are visible as `normalizing_page_<n>` rather than a single opaque extraction step. On restart, already-normalized pages are reused when possible and missing pages are processed again.
- `/api/imports/jobs/{job_id}/rescue` can requeue failed/restored import jobs and running jobs whose worker lock is stale. Fresh running jobs are rejected to avoid racing an active worker thread.
- `/api/dashboard` includes import queued/running counts plus active batch progress totals, active step, and elapsed seconds so the sidebar can render progress without scanning the recent job list.
- The sidebar progress block is hidden when no imports are queued or running and is not shown on the collapsed rail.
