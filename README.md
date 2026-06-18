# Medusa

Medusa is a local-first research library, document aggregator, and intelligent taxonomizer. It is built as a polished web app for organizing academic PDFs, extracting searchable text and metadata, generating citations and summaries, and managing project run sheets.

## What Is Implemented

- Password-protected LAN web app on port `3737`
- React research cockpit UI with day/night modes
- FastAPI backend with session cookies
- PostgreSQL schema with Alembic migrations, `pgvector`, full-text/trigram indexes, JSONB metadata, and durable import jobs
- Batch PDF upload with optional label, priority, read status, domain/tag/project defaults, inline organization creation, checksum duplicate detection, and explicit skip/overwrite/import-anyway choices
- GCS storage adapter with local fallback when credentials are not configured
- PDF extraction via PyMuPDF
- Authenticated original PDF preview/open route in the document detail pane and expanded Reader mode
- Parsed full-text reader with normalized one-page navigation and page note entry
- Embedded figure/image extraction into durable storage with authenticated asset preview
- OpenAI adapter for structured metadata, summaries, topics, keywords, page text normalization, and embeddings
- Citation generation in Markdown APA 7, BibTeX, RIS, and CSL JSON
- Live document-level citation check/refresh controls backed by durable Concordance jobs
- Review queue for accepting or rejecting ambiguous citations with correction history
- Projects/run sheets with add/remove resources, status/priority/used tracking, notes, and bibliography generation
- Saved searches, smart filters, bulk-edit controls with custom tag nomination, and selected-document Concordance Runs
- Concordance Runs for retroactively updating already-imported documents to current capability versions
- Document correction pane for metadata, tags, domains, custom attributes, rendered Markdown summaries/citations, duplicate visibility, and correction history
- Document annotations/highlights with page, color, note body, soft delete, and search indexing
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
MEDUSA_OPENAI_NORMALIZE_PAGE_TEXT=true
MEDUSA_OPENAI_TEXT_NORMALIZATION_PAGE_MAX_CHARS=14000
MEDUSA_OPENAI_REQUEST_TIMEOUT_SECONDS=180
MEDUSA_OPENAI_PAGE_NORMALIZATION_TIMEOUT_SECONDS=90
MEDUSA_OPENAI_EMBEDDING_TIMEOUT_SECONDS=60
```

If cloud credentials are absent, Medusa still boots and stores originals under `data/originals`. If `OPENAI_API_KEY` is absent, imports still create records and extract text, but AI metadata is marked for review.

OpenAI enrichment runs asynchronously during imports and Concordance Runs. By default, Medusa uses `gpt-5.5`, sends the original PDF as file context when the file is below the configured size cap, and normalizes extracted page text into readable paragraph flow. If OpenAI is unavailable or a page-normalization request times out, Medusa falls back to local whitespace, hyphenation, and paragraph cleanup.

Worker recovery:

```bash
MEDUSA_WORKER_STALE_JOB_SECONDS=900
```

Worker startup immediately requeues `running` import and Concordance jobs left by the previous worker process. This setting is the secondary guard for stale locks that remain while the worker is alive.

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

If the worker/container stops while a job is already marked `running`, the next worker requeues it on startup and continues from the last durable checkpoint.

Settings includes backup export controls. The full metadata export captures research metadata, extracted text, organization state, notes, corrections, jobs, Concordance history, and a durable asset manifest. The storage manifest export lists original and derived asset URIs. Exports intentionally omit API keys, service-account credentials, password hashes, and session tokens.

Metadata exports can be restored with the CLI restore tool. Restores are dry-run by default, preserve export IDs by default, skip password/session state, restore document/storage URI references, and park active job queues so a fresh worker does not unexpectedly reprocess restored history.
