# Slipstream And Cloud Run Remote Worker Rollout

This note tracks the Slipstream remote worker work being built for Medusa production, including Cloud Run worker pools as a disabled-by-default Slipstream runner profile. It records what is changing, why it is shaped this way, how the local laptop worker is enrolled, and where operator decisions remain.

## Scope

- Build Slipstream remote workers as the shared foundation, then add Cloud Run worker pools as a default-disabled runner profile instead of a second queue.
- Keep the main FastAPI backend as the Slipstream control plane instead of introducing a second public IP, port, or service.
- Let remote workers check in over the existing authenticated HTTPS application boundary and claim only server-authorized work.
- Enroll this laptop as a remote worker. It was originally allowed up to 4 concurrent jobs, but the active local profile is now capped at 2 concurrent jobs after production load testing.
- Prefer this laptop's 12 performance cores and avoid the 4 efficiency cores where the runtime can express affinity.

## Architecture

The production backend remains the single coordinator. Remote workers connect outbound to the public Medusa HTTPS origin, register with one-time enrollment tokens, and then sign check-in, claim, heartbeat, result, and failure requests with their Ed25519 worker key. PostgreSQL remains the quorum authority through `SlipstreamLease` rows and the active-lease uniqueness constraint.

This avoids a dedicated worker service because the main backend already owns session/auth middleware, queue state, storage routes, import job transitions, and processing events. A separate port or service would add firewall, TLS, routing, auth, and deployment surface without improving the current trust or quorum model. The likely future reason to split it out would be a very large worker fleet or a separate operational team boundary; that is not the current use case.

## Data Model

Slipstream enrollments now include:

- `capabilities`: the allowed work kinds for a client. The initial capability is `import_preprocess`.
- `max_capacity`: the highest concurrency a client may request.

Clients store server-clamped capability and capacity metadata. A worker can ask for fewer slots than the enrollment allows, but not more. The server reports active and available capacity in admin client responses.

The migration is `20260630_0033_slipstream_enrollment_limits.py`; existing enrollments are backfilled to `["import_preprocess"]` and capacity `1`.

## Work Contract

Remote Slipstream workers currently claim only import-preprocess work. Cloud Run v1 uses the same scope. That means:

1. The server assigns an eligible queued import job whose document original is already stored.
2. The worker downloads the authenticated original through the server.
3. The worker extracts raw per-page text and search text using the configured raw-text extractor.
4. The worker returns a typed partial manifest containing extracted pages, composition evidence, and metadata.
5. The server applies the partial result, completes the remote lease, and requeues the import at `normalizing_pages`.
6. The central worker owns all enrichment, model calls, citation/tag logic, indexing, durable storage completion, and final document readiness.

This keeps remote laptops useful for CPU-heavy extraction while keeping credentials, OpenAI calls, GCS mutation, metadata authority, and final import state inside production.

## Client Runner

`backend/app/slipstream/client.py` is the remote worker entrypoint. It can enroll with a one-time token, persist its key/client id under the ignored worker state directory, check in on a fixed interval, maintain up to the configured concurrent leases, heartbeat while work is running, and safely report results or failures.

The local Compose profile is `docker-compose.slipstream.yml`. The ignored `.env.slipstream` file holds the production URL, enrollment token during first boot, worker name, capacity, concurrency, poll interval, heartbeat interval, and CPU selection hints. `.env.slipstream.example` documents the expected values without secrets.

The worker loop backs off after empty claim responses and transient server errors instead of immediately refilling every open concurrency slot. It also ramps claim attempts one at a time while still allowing up to the configured number of active jobs, so a multi-slot worker can process multiple documents concurrently without issuing simultaneous claim races every time capacity opens. This protects the main Medusa backend from tight claim polling when the queue is temporarily empty, when all eligible jobs are already leased, or when HAProxy/backend health is recovering. Check-in failures are logged and retried in-process so a short proxy outage does not create a container restart loop.

Import-preprocess claims filter for preprocessing-eligible steps (`stored` and `extracting`) before applying the claim window. This matters because the central worker may have many `normalizing_pages` continuation jobs queued ahead of newly stored documents; those continuation jobs belong to the server and must not block laptop workers from reaching stored import jobs.

Heartbeat requests are best-effort progress/liveness telemetry. A transient heartbeat failure is logged, but the worker continues processing and lets the final result or explicit failure report decide the lease outcome.

Cloud Run uses the same client with `python -m app.slipstream.client --cloud-run`. In that mode the worker reads the registered `client_id` and Ed25519 private key from Secret Manager, uses `/tmp` scratch storage, claims with `worker_kind=cloud_run`, defaults to one active lease per process, and returns a `provider=cloud_run` runtime Composition row. Cloud Run workers do not receive PostgreSQL, OpenAI, Gemini, Google Vision, or GCS credentials.

Settings exposes Cloud Run as a separate capacity control next to local import workers and online Slipstream clients. It is disabled by default, uses numeric concurrency to represent desired worker-pool instances, and treats disabled as a target of `0`. The sane default flavor is Economy (`1 vCPU`, `2 GiB`), import-only, max `4` instances, and target concurrency `1` when enabled; the dropdown can also save Balanced, Performance, or High Memory shapes.

At current `us-central1` worker-pool rates, the default shape costs about `$0.000823/minute`, `$0.0494/hour`, and `$0.0041` for a five-minute typical document before model/OCR costs. The UI shows these estimates and generates deploy/update command text, but Medusa does not execute cloud scaling commands itself.

## Laptop Worker Profile

This machine has 4 efficiency cores and 12 performance cores. The worker profile was initially tested at four concurrent jobs, then lowered after production showed FastAPI/DB-session saturation under four simultaneous remote claim and heartbeat streams. The current production-safe profile is set for:

- capacity: `2`
- local concurrency: `2`
- CPU budget: `12`
- requested CPU set: `4-15`

On Linux containers the client attempts `os.sched_setaffinity` for the requested CPU set. On macOS direct-host runs it attempts a high QoS class through `pthread_set_qos_class_self_np`. Docker Desktop does not provide a perfect physical P-core pinning contract, so this is best-effort: Compose constrains the worker to a 12-CPU budget, and the process requests CPUs `4-15` inside the runtime when the runtime supports it.

## Production Steps

1. Commit and push the Slipstream changes.
2. Fast-forward the production checkout.
3. Enable Slipstream in production `.env` with TLS required and the public base URL set to the production HTTPS origin.
4. Rebuild/restart the production application and run migrations.
5. Verify `/api/health`.
6. Create a one-time enrollment token for the laptop with `import_preprocess` and max capacity `4`, then advertise only the desired active local capacity in `.env.slipstream`.
7. Write the ignored local `.env.slipstream` file.
8. Start `docker compose -f docker-compose.slipstream.yml up --build -d`.
9. Confirm the client appears online, checks in regularly, and can claim up to the configured active local capacity.

## Verification

Focused backend coverage includes Slipstream enrollment clamping, stale active lease repair, partial import-preprocess result application, Cloud Run default preferences, disabled-claim rejection, default cost formulas, and scale-to-zero blocking while active Cloud Run leases exist. Frontend verification builds the Settings surface with Cloud Run disabled by default. Production verification should check health, migration state, Slipstream configuration, client online status, active leases, Cloud Run target command text, and import queue progress after the laptop worker or Cloud Run worker starts.

## Decisions Still Needed

- Whether this laptop worker should run only on demand or be left running whenever Docker Desktop is up.
- Whether future Slipstream capabilities should remain extraction-only or expand into other safe local-only Concordance work.
- Whether to add an operating-system launch agent later so the worker starts automatically after login.
