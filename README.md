# Medusa

Medusa is a local-first research library, document aggregator, and intelligent taxonomizer. It is built as a polished web app for organizing academic PDFs, extracting searchable text and metadata, generating citations and summaries, and managing project run sheets.

## What Is Implemented

- Password-protected LAN web app on port `3737`
- React research cockpit UI with day/night modes
- FastAPI backend with session cookies
- PostgreSQL schema with `pgvector`, full-text/trigram indexes, JSONB metadata, and durable import jobs
- Batch PDF upload with checksum duplicate detection
- GCS storage adapter with local fallback when credentials are not configured
- PDF extraction via PyMuPDF
- OpenAI adapter for structured metadata, summaries, topics, keywords, and embeddings
- Citation generation in APA, BibTeX, RIS, and CSL JSON
- Review queue for ambiguous citations
- Projects/run sheets with bibliography generation
- Bulk-edit API hooks for read status, priority, domains, and tags

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
```

If cloud credentials are absent, Medusa still boots and stores originals under `data/originals`. If `OPENAI_API_KEY` is absent, imports still create records and extract text, but AI metadata is marked for review.

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

## Safety Model

Imports are durable jobs stored in PostgreSQL. Each processing step records events and checkpoints, so stopping the app mid-import leaves work queued or resumable. Original files are checksum-addressed and duplicate uploads are detected before processing.
