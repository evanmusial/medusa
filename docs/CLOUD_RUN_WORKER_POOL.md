# Cloud Run Worker Pool

This note records the Cloud Run processing work added on top of Medusa's existing Slipstream remote-worker system. Cloud Run is a disabled-by-default runner profile, not a second queue. Workers poll Medusa over HTTPS, claim signed Slipstream leases, process one job at a time by default, heartbeat while active, and submit result manifests that Medusa validates and applies.

## What Changed

- Added Cloud Run runtime configuration in backend settings and `.env.example`.
- Added DB-backed preferences for `cloud_run_workers_enabled` and `cloud_run_worker_concurrency`.
- Added Settings controls for enabling Cloud Run and choosing the numeric worker-pool concurrency. Disabled always means target `0` instances; enabled defaults to `1`.
- Added a Settings flavor dropdown so CPU/memory size is an explicit saved preference instead of a hidden pair of env numbers.
- Added authenticated admin routes:
  - `GET /api/cloud-run/workers/status`
  - `POST /api/cloud-run/workers/scale-plan`
- Extended Slipstream signed lease claims with `worker_kind=cloud_run`.
- Extended the bundled Slipstream client with `python -m app.slipstream.client --cloud-run`.
- Added Cloud Run cost estimation helpers and a Cloud Run runtime Composition row for completed remote manifests.
- Added generated `gcloud run worker-pools` deploy/update command text in Settings.

## Defaults

Cloud Run remains off unless explicitly enabled in Settings and the environment permits Slipstream remote claims.

Default resource shape:

- CPU: `1`
- Memory: `2 GiB`
- Flavor: `Economy`
- Job types: `import`
- Desired instances: `0`
- Enabled concurrency: `1`
- Max instances: `4`
- Idle scale-down target: `300` seconds as the documented operator expectation
- Scratch storage: `/tmp` through `MEDUSA_CLOUD_RUN_WORKER_STATE_PATH`

These defaults are intentionally smaller than the earlier planning example because Medusa's first Cloud Run mode is import preprocessing through PyMuPDF/Marker-style raw text extraction, while Medusa still owns model calls, provider credentials, final DB writes, and storage state.

Settings offers four worker-pool flavors:

| Flavor | CPU | Memory | Use |
| --- | ---: | ---: | --- |
| Economy | 1 vCPU | 2 GiB | Lowest-cost import preprocessing for small batches. |
| Balanced | 2 vCPU | 4 GiB | More headroom for larger PDFs and burst imports. |
| Performance | 4 vCPU | 8 GiB | Faster preprocessing for large batch windows. |
| High Memory | 4 vCPU | 16 GiB | Extra memory for unusually large or image-heavy PDFs. |

## Security And Secrets

Cloud Run workers do not receive PostgreSQL, OpenAI, Gemini, Google Vision, or GCS credentials. They only need:

- A registered Slipstream `client_id`.
- The matching Ed25519 private key.
- HTTPS reachability to `MEDUSA_SLIPSTREAM_PUBLIC_BASE_URL`.

The Cloud Run container reads those two client-state values from Secret Manager:

- `MEDUSA_CLOUD_RUN_CLIENT_ID_SECRET`
- `MEDUSA_CLOUD_RUN_PRIVATE_KEY_SECRET`

The runtime service account should have `roles/secretmanager.secretAccessor` only on those specific secrets. Deployment/build permissions belong to the human or deployment identity, not the runtime worker identity.

Local setup already stashed the provided service-account JSON at:

```text
data/secrets/medusa-cloud-run-worker.json
```

The file is ignored by git and kept outside tracked code.

## IAM Boundary

Runtime service account:

- Secret Manager Secret Accessor on `medusa-slipstream-client-id`
- Secret Manager Secret Accessor on `medusa-slipstream-private-key`

Deployment identity:

- Cloud Run Developer, preferably project-scoped or resource-scoped.
- Artifact Registry Writer on the Medusa Docker repository.
- Service Account User on the Cloud Run runtime service account.

The runtime service account should not retain project-level Cloud Run Builder, Cloud Run Developer, or Cloud Run Invoker roles for this design.

## Cost Model

The backend constants use the current published Cloud Run worker-pool rates checked on 2026-06-30 for `us-south1`:

- vCPU: `$0.000011244` per vCPU-second
- Memory: `$0.000001235` per GiB-second

For the default Economy `1 vCPU / 2 GiB` worker shape:

- Unit cost: about `$0.000013714` per second
- Minute: about `$0.000823`
- Hour: about `$0.0494`
- Five-minute typical document: about `$0.0041`
- 100 five-minute documents: about `$0.41`
- One always-on 30-day instance: about `$35.55` gross before free-tier effects

The typical-document example remains the recent local cached PDF benchmark: 12 pages, about 273 KB, and about 50.5k extracted characters. Model and OCR costs can still dominate overall spend because Cloud Run compute is only the worker runtime layer.

Go/no-go rule: use Cloud Run for burst batches or local CPU relief. Do not leave it always on for occasional single-document imports.

## Worker Entrypoint

The worker pool command uses the existing Slipstream client:

```bash
python -m app.slipstream.client --cloud-run
```

Cloud Run mode:

- Reads `MEDUSA_SLIPSTREAM_PUBLIC_BASE_URL` from env.
- Reads `MEDUSA_CLOUD_RUN_PROJECT` from env for Secret Manager lookups.
- Reads client state from Secret Manager.
- Uses `/tmp/medusa-cloud-run/slipstream-client.json` as the scratch state path.
- Claims with `worker_kind=cloud_run`.
- Processes one active lease per process by default.
- Appends a `provider=cloud_run` runtime Composition entry.
- Exits gracefully on SIGTERM/SIGINT.

## Operational Flow

1. Enable Slipstream in Medusa with a public HTTPS base URL.
2. Create a Slipstream enrollment in Settings.
3. Register a Cloud Run client once and store the resulting `client_id` plus private key in Secret Manager.
4. Build and push the Medusa worker image to Artifact Registry. Cloud Run currently requires a `linux/amd64` image, so local Apple Silicon builds must use Buildx:

```bash
docker buildx build --platform linux/amd64 --provenance=false \
  -t us-south1-docker.pkg.dev/musial-medusa/medusa/worker:latest \
  --push ./backend
```

5. Deploy/update the worker pool with the Settings-generated command.
6. Save Cloud Run preferences in Settings:
   - enabled/disabled
   - numeric concurrency
7. Keep the pool at `0` when idle unless actively processing a batch.

Scale-down planning blocks target `0` when active Cloud Run leases exist unless explicitly forced through the API. The application currently generates the `gcloud` command; it does not run cloud deployment or scaling commands itself.

## Current Limitations

- V1 Cloud Run processing is import preprocessing only. Full Concordance remote execution still needs lease-scoped model/storage proxy endpoints and richer typed manifests for capability-specific outputs.
- Cloud Run worker pools do not have request autoscaling like Cloud Run services, so Medusa exposes target concurrency and command generation instead of pretending request autoscaling exists.
- Idle pool time that cannot be tied to a document should be recorded as an operational event later; per-document runtime is recorded through Composition rows.
- Secret Manager versions for the Slipstream `client_id` and private key must be populated after the Cloud Run client is registered.
- Marker/model cache downloads should be avoided unless the image bakes the cache or the pool is intentionally kept warm.
- V1 deploys the full backend image as the worker image. It works, but it pulls in the Marker/Torch stack and should become a lean Cloud Run worker image before frequent deployments.

## Verification

Focused coverage should include:

- Cloud Run preferences default disabled with concurrency `1`.
- Cloud Run claim rejection while disabled.
- Cloud Run claim success after enabling.
- Cost formula calculations for the default worker shape.
- Scale-to-zero blocked while Cloud Run leases are active.
- Frontend build with the Cloud Run Settings panel.
