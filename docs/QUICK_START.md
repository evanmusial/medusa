# Medusa Quick Start

This guide gets a fresh local Medusa checkout running with Docker Compose, then shows where to add optional LLM and storage credentials. It is intentionally short; deeper operations live in [Local Operations](LOCAL_OPERATIONS.md).

## 1. Requirements

- Docker with the Compose plugin.
- OpenSSL, used here only to make a local development certificate.
- A local clone of this repository.

## 2. Create Local Configuration

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` and set the local host, login, and local-first defaults:

```bash
MEDUSA_PUBLIC_HOST=localhost
MEDUSA_ALLOWED_HOSTS=localhost
MEDUSA_ADMIN_EMAIL=admin@medusa.local
MEDUSA_PASSWORD=replace-with-a-real-local-password
MEDUSA_ALLOW_DEFAULT_PASSWORD=false
MEDUSA_LOCAL_AUTO_LOGIN=false
MEDUSA_DATABASE_BACKUP_STORAGE=local
```

For a private single-user laptop instance, `MEDUSA_LOCAL_AUTO_LOGIN=true` can be convenient. Leave it `false` on LAN, shared, or public deployments because it bypasses the password and two-factor login prompts for browsers without a session.

## 3. Add A Local TLS Certificate

HAProxy expects certificate files under ignored local storage. For local development, a self-signed localhost certificate is enough:

```bash
mkdir -p data/haproxy data/secrets
openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
  -keyout data/haproxy/privatekey.pem \
  -out data/haproxy/fullchain.pem \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
chmod 700 data/haproxy data/secrets
chmod 600 data/haproxy/privatekey.pem data/haproxy/fullchain.pem
```

Your browser will warn about the self-signed certificate. That is expected for a quick local setup.

## 4. Start Medusa

Build and run the full local stack:

```bash
docker compose up --build
```

Open:

```text
https://localhost:3737
```

Log in with the email and password from `.env`. By default that is `admin@medusa.local` plus your `MEDUSA_PASSWORD`.

In another terminal, verify health:

```bash
curl -kfsS https://localhost:3737/api/health
```

The first startup runs PostgreSQL migrations automatically. Docker Compose exposes HAProxy on `3737`; the backend, frontend preview server, worker, PostgreSQL, and Valkey remain inside Compose networks.

## 5. Run Without Cloud Credentials

Medusa boots and imports documents without cloud credentials.

- Originals are stored on local disk under `data/originals`.
- PostgreSQL data lives in Docker's `medusa-postgres` named volume.
- Backups default to local disk under `data/backups/database`.
- Imports still extract local text when possible.
- AI-generated metadata, summaries, tags, citations, and embeddings require configured model credentials.

## 6. Configure OpenAI

Set these values in `.env`:

```bash
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5.5
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
MEDUSA_OPENAI_PRICING_TIER=standard
MEDUSA_OPENAI_SEND_PDF=true
MEDUSA_OPENAI_PDF_FILE_MAX_MB=24
```

Restart the backend and worker after changing `.env`:

```bash
docker compose up -d --build backend worker
```

Medusa uses OpenAI-compatible model tasks for document metadata, summaries, APA citation work, page normalization, embeddings, Inquests, Recon, and other enrichment paths. After login, review model choices in Settings > Import Processing.

## 7. Configure Gemini

Gemini can use either a Developer API key or Google Vertex AI/service-account credentials.

For a Developer API key, prefer an ignored secret file:

```bash
mkdir -p data/secrets
printf 'GEMINI_API_KEY=%s\n' 'replace-with-gemini-key' > data/secrets/gemini.env
chmod 600 data/secrets/gemini.env
```

Then keep this in `.env`:

```bash
GEMINI_API_KEY=
GOOGLE_GENAI_USE_VERTEXAI=false
GOOGLE_CLOUD_LOCATION=global
```

Alternatively, put `GEMINI_API_KEY=...` directly in `.env` for quick local testing. Do not commit `.env`.

For Vertex AI, use the Google service-account setup in the next section, then set:

```bash
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=global
```

Restart backend and worker after changes.

## 8. Configure Google Cloud Storage

GCS is the current cloud object-store backend for originals, figure assets, and optional database backups.

1. Create or choose a GCS bucket.
2. Create a Google service account for Medusa.
3. Grant it bucket/object permissions for the chosen bucket and prefix. A simple bucket-scoped setup is Storage Object Admin plus bucket metadata access; a tighter custom role should cover object create, read, list, delete, and bucket get.
4. Download the service-account JSON key.
5. Save it under ignored local storage:

```bash
mkdir -p data/secrets
cp /path/to/service-account.json data/secrets/service-account.json
chmod 600 data/secrets/service-account.json
```

Set `.env`:

```bash
GCS_BUCKET=your-bucket-name
GCS_PREFIX=medusa
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=global
GOOGLE_APPLICATION_CREDENTIALS=/app/data/secrets/service-account.json
MEDUSA_ENABLE_GOOGLE_VISION=true
```

Restart backend and worker:

```bash
docker compose up -d --build backend worker
```

To store full PostgreSQL backups in GCS instead of local disk, also set:

```bash
MEDUSA_DATABASE_BACKUP_STORAGE=gcs
```

GCS backups are intentionally blocked when `MEDUSA_LOCAL_AUTO_LOGIN=true`.

You can also upload/manage the Google service-account JSON from Settings > Cloud Storage after the app is running. Medusa stores the uploaded JSON under ignored managed-secret storage and records only non-secret metadata in PostgreSQL.

## 9. S3 Status

This checkout does not currently include an S3 original-storage or database-backup adapter. There are no active `S3_BUCKET`, `AWS_ACCESS_KEY_ID`, or `AWS_SECRET_ACCESS_KEY` settings consumed by the storage layer.

Use local disk or GCS for document storage today. AWS Fargate can still be used as a compute target through a Slipstream-style worker design, but that is separate from S3 object storage and should not require giving remote workers database, OpenAI, Gemini, Google Vision, GCS, or S3 credentials.

## 10. Stop And Restart

Stop the running containers:

```bash
docker compose down
```

Start again:

```bash
docker compose up --build
```

To remove the local PostgreSQL database volume, use Docker volume removal deliberately. That deletes the Medusa database, so make a backup first if anything matters.

## 11. Next Documents

- [Local Operations](LOCAL_OPERATIONS.md): full runbook for operations, credentials, backups, workers, metrics, and development.
- [AI Cost Routing](AI_COST_ROUTING.md): model/provider routing and cost-control strategy.
- [Architecture Record](ARCHITECTURE.md): product and technical design record.
