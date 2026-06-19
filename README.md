# Medusa

Medusa is a local-first research library, document aggregator, and intelligent taxonomizer. It is built as a polished web app for organizing academic PDFs, extracting searchable text and metadata, generating citations and summaries, and managing project run sheets.

## What Is Implemented

- Password-protected LAN web app on port `3737`
- React research cockpit UI with day/night modes
- FastAPI backend with session cookies
- PostgreSQL schema with Alembic migrations, `pgvector`, full-text/trigram indexes, JSONB metadata, and durable import jobs
- Batch PDF upload with optional label, priority, read status, domain/tag/project defaults, inline organization creation, checksum duplicate detection, and explicit skip/overwrite/import-anyway choices
- GCS storage adapter with local fallback when credentials are not configured
- Raw text extraction preference with Local choices for Docling, Marker, and PyMuPDF; Marker is the default preference and PyMuPDF remains the bundled local fallback
- Authenticated original PDF preview/open route in the document detail pane and expanded Reader mode
- Parsed full-text reader with normalized one-page navigation
- Cropped figure/chart/photo extraction into durable storage with authenticated asset preview, labels, captions, and page geometry
- OpenAI adapter for structured metadata, visible author contact emails, summaries, topics, keywords, page text normalization, and embeddings
- OpenAI usage ledger with Budget rollups for last day/month/3 months/all time, calls, tokens, estimated known-model costs, cached input tokens, PDF/file context bytes, recent errors, and task/model breakdowns
- Citation generation in Markdown APA 7, BibTeX, RIS, and CSL JSON
- Live document-level citation check/refresh controls backed by durable Concordance jobs
- Reserved header progress control for imports, Concordance, and citation-check work, so job feedback continues after navigating away from the page that started the work without shifting the header actions
- Async action feedback: job-starting buttons turn green with a small progress bar while work is in flight, flash green on success, flash red on failure, and show a concise error popover when startup or completion fails
- Queue view for import work and accepting or rejecting ambiguous citations with correction history
- Projects/run sheets with add/remove resources, status/priority/used tracking, notes, bibliography generation, and pane-constrained controls that keep long document titles from spilling into Bibliography
- Saved searches, smart filters, bulk-edit controls with custom tag nomination, and selected-document Concordance Runs
- Concordance Runs for retroactively updating already-imported documents to current capability versions
- Document correction pane for metadata, tags, domains, custom attributes, rendered Markdown summaries/citations, duplicate visibility, and correction history
- Accessory Summaries for user-prompted focused summaries, queued as durable worker jobs with the Settings-selected default model and inline optional titles
- Stored document annotations/highlights with page, color, note body, soft delete, and search indexing; Library creation controls are deferred for a quieter redesign
- Notes and reminders attached to documents, domains, projects, or the general library
- Authenticated JSON backup exports for metadata and storage manifests, excluding secrets and session tokens
- CLI restore tooling for metadata exports, with dry-run validation by default and parked restored job queues

## Quick Start

```bash
cp .env.example .env
```

Edit `.env` and set at least:

```bash
MEDUSA_PASSWORD=your-local-password
MEDUSA_ALLOW_DEFAULT_PASSWORD=false
```

Then run:

```bash
docker compose up --build
```

Backend startup runs Alembic migrations for PostgreSQL automatically before serving traffic.

Open:

```text
http://localhost:3737
```

The default email is `admin@medusa.local` unless changed in `.env`.

## Credentials

Google Cloud Storage:

```bash
GCS_BUCKET=your-bucket
GCS_PREFIX=medusa
GOOGLE_CLOUD_PROJECT=your-project
GOOGLE_APPLICATION_CREDENTIALS=/app/data/secrets/service-account.json
```

Put the service-account JSON under ignored `data/secrets/`; Docker Compose mounts that directory read-only into backend and worker containers. The service account needs object create/read/delete access on the configured bucket and prefix.

OpenAI:

```bash
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5.5
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
MEDUSA_OPENAI_SEND_PDF=true
MEDUSA_OPENAI_PDF_FILE_MAX_MB=24
MEDUSA_OPENAI_COMBINE_DOCUMENT_INTELLIGENCE=false
MEDUSA_OPENAI_PROMPT_CACHE_RETENTION=24h
MEDUSA_OPENAI_NORMALIZE_PAGE_TEXT=true
MEDUSA_OPENAI_PAGE_NORMALIZATION_MODE=auto
MEDUSA_OPENAI_PAGE_NORMALIZATION_AUTO_MAX_PAGES=4
MEDUSA_OPENAI_TEXT_NORMALIZATION_PAGE_MAX_CHARS=14000
MEDUSA_OPENAI_REQUEST_TIMEOUT_SECONDS=180
MEDUSA_OPENAI_PAGE_NORMALIZATION_TIMEOUT_SECONDS=90
MEDUSA_OPENAI_EMBEDDING_TIMEOUT_SECONDS=60
```

If cloud credentials are absent, Medusa still boots and stores originals under `data/originals`. If `OPENAI_API_KEY` is absent, imports still create records and extract text, but AI metadata is marked for review.

OpenAI enrichment runs asynchronously during imports and Concordance Runs. By default, Medusa keeps citation-critical metadata and APA fallback matching on `gpt-5.5`, runs summaries on `gpt-5.4`, and runs keywords/topics on `gpt-5.4-mini`; Settings can override each task. Metadata extraction may send the original PDF as file context when the file is below the configured size cap, but summary and keyword/topic calls use extracted text only. APA text is generated deterministically from DOI/Crossref evidence whenever possible; `gpt-5.5` APA matching is used only when Crossref/DOI evidence is missing or ambiguous. `MEDUSA_OPENAI_COMBINE_DOCUMENT_INTELLIGENCE=true` restores the previous single structured `core_document_intelligence` Responses call for metadata, summary, APA candidate, and keywords/topics. `MEDUSA_OPENAI_PROMPT_CACHE_RETENTION=24h` sends prompt-cache hints keyed by document checksum for retries and Concordance reruns.

Page text normalization is local-first: `MEDUSA_OPENAI_PAGE_NORMALIZATION_MODE=auto` locally cleans normal pages and escalates only low-text or artifact-heavy pages, capped by `MEDUSA_OPENAI_PAGE_NORMALIZATION_AUTO_MAX_PAGES`. Auto mode sends page text only, not the full PDF per page. Set the mode to `always` only when you intentionally want the older all-pages OpenAI normalization behavior. Graphics are stored as cropped assets with labels/captions rather than converted into Markdown. If OpenAI is unavailable or a page-normalization request times out, Medusa falls back to local whitespace, hyphenation, and paragraph cleanup.

Raw text extraction is controlled separately in Settings. The Raw Text Extraction selector is grouped into Local options (Docling, Marker, PyMuPDF) and OpenAI model fallbacks. Marker is the default preference and is installed in the backend/worker image; its model cache lives under `data/model-cache` through the Compose volume, so a first use may download local weights but later imports reuse them. PyMuPDF remains the built-in no-credential fallback when Marker is unavailable or times out.

Budget records and displays OpenAI usage from completed and failed Responses/embeddings calls: task, model, document/job context, token counts, cached input tokens, output tokens, PDF/file context bytes, and recent errors. Dollar totals are estimates from Medusa's local known-model standard pricing table; unknown models are counted as unpriced because model pricing can change independently of the local app.

Async document work is started from the app shell, not only from the page-level component that owns the button. Citation checks and Concordance controls immediately turn green with a small in-button progress bar, then the reserved header progress control follows active durable imports and background runs even if the user switches views. Page-local buttons still give a short green or red result flash; failures also surface a concise error message.

Worker recovery:

```bash
MEDUSA_IMPORT_WORKER_CONCURRENCY=4
MEDUSA_WORKER_STALE_JOB_SECONDS=900
MEDUSA_DOCUMENT_CACHE_SIZE_MB=1000
```

Medusa defaults to four concurrent import jobs. The env var sets the startup default, and Settings lets the local user change the active preference without editing tracked files. Values above four are allowed but can generate many OpenAI calls and costs over a short period.

Worker startup immediately requeues `running` import and Concordance jobs left by the previous worker process. This setting is the secondary guard for stale locks that remain while the worker is alive.

The document cache size defaults to 1,000 MB. It controls how many completed import PDFs are kept locally under `data/processing-cache` for Concordance and Accessory Summary work; originals are still written to GCS or local durable storage at upload time.

## Development

Architecture and design context for future work lives in `docs/ARCHITECTURE.md`. Codex-specific project guidance lives in `AGENTS.md`; keep both current when design or architecture changes.

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

Worker:

```bash
cd backend
python -m app.worker
```

Tests:

```bash
pytest
```

Restore drill:

```bash
cd backend
python -m app.tools.restore_export /path/to/medusa-metadata.json
python -m app.tools.restore_export /path/to/medusa-metadata.json --apply
```

The restore command validates schema/safety flags, rejects secret-bearing keys, reports conflicts and skipped auth records, and parks restored queued/running jobs as `restored_paused` unless `--reactivate-jobs` is explicitly supplied.

## Safety Model

Imports are durable jobs stored in PostgreSQL. Each processing step records events and checkpoints, so stopping the app mid-import leaves work queued or resumable. Original files are checksum-addressed and duplicate uploads are detected before processing.

Duplicate uploads are checked before queueing. When an exact checksum match is found, the Import view asks whether to skip the duplicate, overwrite the matching document record, or import anyway as a separate document. Library filters can also show exact checksum duplicates already in the collection.

If the worker/container stops while a job is already marked `running`, the next worker requeues it on startup and continues from the last durable checkpoint. In-flight documents may repeat the current step, and page normalization resumes from persisted page checkpoints when possible.

The Import screen can also rescue failed imports or stale locked imports by requeueing the job. Fresh running jobs are protected from manual requeue to avoid racing an active worker.

Concordance Runs and citation checks are also safe to leave in progress from the UI. Once the backend accepts the request, the durable database run continues through the worker queue independently of the currently open page, and the shell-level progress shelf reconciles with refreshed run/job state.

Settings includes backup export controls. The full metadata export captures research metadata, extracted text, organization state, notes, corrections, jobs, Concordance history, and a durable asset manifest. The storage manifest export lists original and derived asset URIs. Exports intentionally omit API keys, service-account credentials, password hashes, and session tokens.

Metadata exports can be restored with the CLI restore tool. Restores are dry-run by default, preserve export IDs by default, skip password/session state, restore document/storage URI references, and park active job queues so a fresh worker does not unexpectedly reprocess restored history.
