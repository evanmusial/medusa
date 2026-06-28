# Medusa

Medusa stands for **Metadata-Enhanced Document Understanding, Search, and Analysis**. It is a local-first research library, document aggregator, and intelligent taxonomizer, built as a polished web app for organizing academic PDFs, DOCX/RTF/HTML/plain-text sources, extracting searchable text and metadata, generating citations and summaries, managing project run sheets, and keeping versioned user documents in Portfolio.

## What Is Implemented

- Password-protected LAN web app behind HAProxy TLS on port `3737`, with database-backed password hashes, optional authenticator-app 2FA, and an explicit local-only auto-login flag for single-user development instances
- React research cockpit UI with day/night modes, open-canvas workbenches, an app-wide Quick Switcher, browser-local recently viewed document shortcuts, Library density preferences, darker light-theme contrast grays, and restrained icon-left action buttons
- Lowercase contextual browser titles such as `medusa | DOCUMENT_TITLE`, `medusa | PROJECT_TITLE`, or the current workspace name
- Bookmarkable top-level workspace URLs plus document focus links such as `/documents/{document_id}` for opening Library with a specific document selected and scrolled into view, and `/documents/{document_id}/reader` for expanded Reader mode with list-position restoration on close
- Icon-only header Status button linking to `/status`, with build/version identity, short commit hash, uptime, memory and disk footprints, runtime versions, proxy status, and storage path details
- FastAPI backend with session cookies
- PostgreSQL schema with Alembic migrations, `pgvector`, full-text/trigram indexes, JSONB metadata, and durable import jobs
- Slipstream remote-processing leases for registered outbound-polling clients, with signed requests, one active lease per job, Settings enrollment controls, and Queue rows that distinguish Local worker from Slipstream clients
- Internal Valkey response cache for rebuildable dashboard, Library list/detail, organization, and Status payloads, guarded by PostgreSQL-backed cache revisions plus manual Refresh Cache and Hydrate Cache controls in the user menu and Status page
- Optional Prometheus text exporter sidecar on port `43737`, with bearer-token `/metrics`, a private backend snapshot endpoint, PostgreSQL/Valkey/HAProxy/job/corpus/cost/cache/container metrics, and no GCS bucket inventory scraping
- Batch PDF, DOCX, RTF, HTML, and plain-text/Markdown upload with optional label, priority, read status, domain/tag/project defaults, inline organization creation, robust duplicate detection using SHA-256, MD5, DOI, normalized title, and supporting metadata, explicit skip/overwrite/import-anyway choices, local PDF mezzanine conversion for non-PDF sources, staged upload rows with rough per-file and grand-total cost previews, Process Uploads and staged-upload cleanup actions, staged-document invisibility from Library/search until import completion, and active-first progress-shaded import processing rows with model/cost detail
- Portfolio workspace for user-authored research and education documents, with PDF/DOCX/RTF/TXT/Markdown version uploads, hidden source-preserving document processing, immutable lineage edges, rubric/reference/feedback materials, Library-resource suggestions, baseline assessment runs, generated preview, source download, and version metadata comparison
- Recon workspace for corpus-grounded Library inquiries, with durable questions, Library/domain/project/saved-search scopes, Source Finder and Quick Answer modes, cost/token estimates, evidence-backed answers, optional pgvector retrieval, Portfolio resource-suggestion reuse, and Concordance-backed semantic-index refresh for older imports
- GCS storage adapter with local fallback when credentials are not configured
- Raw text extraction preference with Local choices for Docling, Marker, and PyMuPDF; Marker is the default preference and PyMuPDF remains the bundled local fallback
- Authenticated original PDF preview/open/download route in the document detail pane and expanded Reader mode
- Parsed full-text reader with normalized one-page navigation, PDF/Text switching, search-within-document match counts and page jumping, page-aware Reader Notes/annotations with selected-text quotes plus search/edit/delete, rendered LaTeX formulas in read mode, side-by-side compare mode for editing extracted text beside the original PDF, Scrub cleanup for repeated selected text, and page-scoped visual scans from the PDF preview footer that show selectable review candidates before anything is kept
- Cropped figure/chart/photo extraction into durable storage with 300 DPI rendered crops, authenticated asset preview, editable labels/descriptions, deletion controls, page geometry, and one-page Reader rescue scans
- OpenAI adapter for structured metadata, visible author contact emails, summaries, tag suggestions, page text normalization, and embeddings
- OpenAI usage ledger with Finances rollups for last day/month/3 months/all time, calls, tokens, estimated known-model costs, cached input tokens, PDF/file context bytes, recent errors, shell-level failed-call alerts, trend lines, pie charts, and task/model breakdowns
- Utilities workspace with Bulk Intake duplicate preflight for large document drops, stage-new-only handoff to the normal Import queue, Database maintenance actions for compaction, table-statistics optimization, document MD5 hash backfill from cache/durable storage, hidden import-cache cleanup with live counts, full backup/restore, idle-gated maintenance check/run controls, Ingestion History batch audit rows, Docker/container footprint stats, runtime binary/package versions, HAProxy TLS/proxy stats, and backend-container restart with health polling
- Per-document Cost Composition tracking for imports, including persisted pre-processing estimates, estimate-vs-actual comparison, stage timings, provider/model spend, local processing duration, processing issues, and the exact pipeline/method/model path used to generate the document
- Citation generation in validated Markdown APA 7 reference-list and parenthetical in-text forms, with model/provenance tracking, plus BibTeX, RIS, and CSL JSON
- Live document-level DOI, citation, summary, bibliography, tag, and formula-capture controls backed by durable Concordance jobs
- Related-paper recommendations with default hidden-existing filtering, extracted Bibliography reference-list seeds, Unpaywall/arXiv PDF availability enrichment, Google Scholar search links, DOI/title copy actions, DOI stashing plus Wishlist wording for non-open DOI leads, a lane-filtered Acquisition Stashes view with hand-entered DOI lookup, Needs PDF/Open PDF/Queued/In Library status, DOI copy, title-copying manual Sci-Hub DOI links, resolver-backed DOI imports, stash PDF uploads that enter the normal import queue, source-document/source-evidence links, Library validation links for matched stash targets, and stash-record deletion for already-imported matches
- Reserved header progress control for imports, Concordance, and citation-refresh work, so job feedback continues after navigating away from the page that started the work without shifting the header actions; active imports show count/percent, ETA, and known spend, and the latest recently completed import batch stays visible with actual cost until dismissed or it ages out of top-chrome feedback
- Async action feedback: job-starting buttons turn soft blue with the button icon spinning and a slim progress bar while work is in flight, blend through green on success, flash red on failure, and show a concise error popover when startup or completion fails
- App-styled delayed tooltips on buttons, action links, dropdowns, checkboxes, and text inputs, including disabled-state reasons where actions are unavailable
- App-styled confirmation and acknowledgement modals with darkened backdrops instead of native browser confirm/alert boxes
- Activity workspace that unifies existing import batches/jobs, Concordance work, backups/restores, and citation review items into lane-filtered operational history
- Corpus Health workspace for DOI/citation/summary/identity/organization/duplicate/failure review with sampled document shortcuts and repair entry points
- Queue view with Import-style progress-shaded import rows, a latest import receipt for completed-batch file/cost/preset/duration review, animated processing glyphs, model/cost/stage detail, row retry/cancel, Process Uploads, Retry Failed, Clear, and Clear Failed controls, plus bounded citation-review cards with accept/reject actions and correction history
- Projects/run sheets with add/remove resources, status/priority/used tracking, notes, bibliography generation, and pane-constrained controls that keep long document titles from spilling into Bibliography
- Domains management with searchable alphabetized nested trees, top-level/child creation, rename, move, description and tag metadata, color, soft delete, document-count visibility, description/document-based tag suggestions, comma-list tag paste review, and affected-document search/history updates
- Tags management with sortable counts and governance status, scoped tag search, shift-click range selection for visible sorted/filtered rows, audited rename, confirmed merge into an existing or newly named tag, remembered merge aliases for future tag suggestions, flattened keyword/topic distinctions, and a right-side Optimize workbench using the same Tag Suggestions model as import tag creation that keeps the user in the loop for merge suggestions, orphaned-tag merge/prune cleanup, semantic relationships, candidate promotion/retirement, and weak document-tag pruning, with individual approvals or one-click approval of the current plan plus top progress feedback while the plan is building or bulk apply runs
- Saved searches with rename/duplicate/update/delete management, smart filters, visible active search/filter chips, searchable filter/bulk dropdowns with Enter-to-select behavior, visible priority flags and confirmed `No DOI` flags in Library rows, audited title cleanup, selection-based Trash, and bulk-edit controls with custom tag nomination
- Concordance Runs for retroactively updating already-imported documents to current capability versions, including manual Formula Capture refinement, with pre-run cost estimates and same-model no-op planning
- Document correction pane with configurable sticky identity fields, organized preview/Reader actions, metadata correction, inline alphabetical tag add/remove/Refresh controls, DOI Copy/Edit/Refresh/Verify/No DOI, domains, custom attributes, rendered Markdown summaries/citations/bibliographies, rich Markdown summary and Bibliography editing, inline citation edits, manual DOI/APA/Bibliography verification with confirmation-gated edit/refresh unverify behavior, extracted-text cleanup, confirmation-gated single-document Trash, duplicate visibility plus side-by-side duplicate resolution or false-positive dismissal from Library, and complete correction history with Restore as Current
- Inquests for user-prompted document questions, using the Settings-selected default model or chosen model, saved inline with optional titles, and deferred to durable worker jobs when inline answering times out
- Notes and reminders attached to documents, domains, projects, or the general library
- Full PostgreSQL database backup/restore from Utilities, using local disk by default, zstd compression, likely backup-size estimates, backup-size trend graph, total listed-backup size, SHA-256 verification, header progress, and mandatory pre-restore safety backups
- Host-agent-compatible release and maintenance status checks with authenticated `Upgrade Now`, `Reload Now`, `Check Now`, and `Run Maintenance Now` controls; maintenance applies require idle/active-work gates, while verified PostgreSQL backups are required only for database, backup/restore, runtime container, or major underlying program changes
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

For a single-user local instance where the browser should sign in automatically, set:

```bash
MEDUSA_LOCAL_AUTO_LOGIN=true
```

Leave this disabled on LAN/public deployments. It creates a normal admin session automatically when the browser has no valid cookie, bypassing password and two-factor prompts.

Install the HAProxy TLS certificate material under ignored local data storage:

```bash
mkdir -p data/haproxy
cp /path/to/fullchain.pem data/haproxy/fullchain.pem
cp /path/to/privatekey.pem data/haproxy/privatekey.pem
chgrp 99 data/haproxy data/haproxy/*.pem
chmod 750 data/haproxy
chmod 640 data/haproxy/*.pem
```

Then run:

```bash
docker compose up --build
```

Backend startup runs Alembic migrations for PostgreSQL automatically before serving traffic. The default Compose stack also starts internal Valkey with no host-exposed port on a private cache network shared only by the backend and worker; if Valkey is unavailable, Medusa falls back to PostgreSQL reads and reports degraded cache status.

Open:

```text
https://medusa.home.musial.io:3737
```

Plain HTTP requests on port `3737` redirect to `https://medusa.home.musial.io:3737` on the same port. HAProxy renders the redirect and health-check host from `MEDUSA_PUBLIC_HOST` at container startup. The bundled local deployment expects a certificate that covers `*.home.musial.io`; change `MEDUSA_PUBLIC_HOST`, `MEDUSA_ALLOWED_HOSTS`, and the certificate files together for another domain.

The login email defaults to `admin@medusa.local` and the first admin password comes from `MEDUSA_PASSWORD` in `.env`. Those `.env` values seed the account when Medusa creates it for the first time; after that, Medusa uses the hashed password stored on the PostgreSQL `users` row, and Settings > Account changes the live login email or password without rewriting the seed. Settings > Account can also enable authenticator-app 2FA, show a setup key for manual entry, require a current TOTP code before enabling, and issue one-time recovery codes for later login or disablement.

## TLS And HAProxy

The base Docker Compose app stack runs HAProxy as the only host-exposed service on port `3737`. HAProxy terminates TLS, redirects plain HTTP on the same port to HTTPS, routes `/api/*` to the internal backend service, and routes browser shell/assets to the internal frontend service. Backend, worker, database, and frontend ports stay on Compose networks; Valkey is additionally isolated on an internal cache-only network with no published port.

Certificate files belong in ignored `data/haproxy/fullchain.pem` and `data/haproxy/privatekey.pem`. Compose combines them into HAProxy's runtime PEM inside the container; the HAProxy image reads these files as UID/GID `99`, so server installs should make `data/haproxy` group-executable and the PEM files group-readable by group `99` without making the private key world-readable. Do not commit certificate private keys.

```bash
MEDUSA_PUBLIC_HOST=medusa.home.musial.io
MEDUSA_HAPROXY_STATS_URL=http://haproxy:8404/stats;csv
MEDUSA_ALLOWED_HOSTS=medusa.home.musial.io
```

`MEDUSA_ALLOWED_HOSTS` accepts a comma-separated Vite allowed-host list, or `*` / `all` / `true` to allow any Host header during a controlled migration window.

Valkey response cache:

```bash
MEDUSA_CACHE_BACKEND=valkey
MEDUSA_CACHE_URL=valkey://valkey:6379/0
MEDUSA_CACHE_TTL_SECONDS=3600
MEDUSA_CACHE_MAX_PAYLOAD_BYTES=2097152
MEDUSA_VALKEY_MAXMEMORY=8gb
```

Valkey stores only derived, rebuildable API payloads and counters. PostgreSQL remains authoritative for documents, search, jobs, history, evidence, auth, and backups. Cache keys include PostgreSQL `cache_revisions`, so manual Refresh Cache and relevant committed writes make older payloads unreachable even if old Valkey keys remain until TTL/LRU eviction. Hydrate Cache preloads the current revision's deterministic Library pages, saved-search pages, organization/status/dashboard payloads, and visible document details from live PostgreSQL data without turning Valkey into a second database; large payloads still obey `MEDUSA_CACHE_MAX_PAYLOAD_BYTES`. The default Valkey memory limit is 8 GB. Settings > Preferences can change the saved Valkey Memory Limit and apply it to the running Valkey service; `MEDUSA_VALKEY_MAXMEMORY` remains the startup fallback. The profile menu shows cache utilization at a glance with a mini graph, and Status includes a Valkey resource monitor for used memory versus limit, peak memory, RSS, keys, evictions, expiry, connected clients, and ops/sec.

Dependency freshness is tracked through `renovate.json` and the twice-weekly operating plan in `docs/DEPENDENCY_UPDATE_PLAN.md`. Enable the Renovate GitHub app or a Renovate runner for the repo so the checked-in policy actually opens PRs. The host release agent can run an idle-gated Tuesday/Friday maintenance lane for already-merged safe updates and same-tag image/base rebuild refreshes. Routine restarts, rebuilds, safe app updates, and same-tag refreshes skip the database backup; a fresh verified full PostgreSQL backup is required only when the classified change touches database schema/persistence, backup/restore tooling, runtime container definitions, non-patch backend runtime dependencies, or major underlying program versions such as PostgreSQL/pgvector. Runtime image updates, including Valkey, should keep explicit tags, preserve the private cache network, and verify that the base app stack still publishes only HAProxy on port `3737`; the optional metrics overlay may additionally publish the bearer-protected exporter on the configured monitoring bind IP and port. Docker Engine and Compose plugin updates are report-only host recommendations, not auto-applied by Medusa.

HAProxy's stats listener is internal-only. Utilities reads the authenticated backend endpoint `/api/utilities/haproxy/status`, which summarizes the internal CSV stats feed.

Optional Prometheus metrics:

```bash
install -d -m 700 data/secrets
printf '%s\n' 'replace-with-long-random-token' > data/secrets/prometheus-token
chmod 600 data/secrets/prometheus-token
```

Then set `MEDUSA_METRICS_INTERNAL_TOKEN` in `.env` so both backend and exporter see the same private snapshot token, and start or refresh the two affected services:

```bash
docker compose -f docker-compose.yml -f docker-compose.server.yml -f docker-compose.metrics.yml up -d --build backend haproxy metrics-exporter
```

The exporter serves `/metrics` and `/healthz` from `python -m app.tools.prometheus_exporter`, defaulting to port `43737` inside Docker. On a server, `docker-compose.metrics.yml` lets HAProxy publish `MEDUSA_METRICS_BIND_IP:MEDUSA_METRICS_PORT` and terminate TLS with the existing Medusa certificate, so Prometheus should scrape `https://medusa.evan.engineer:43737/metrics`. Inside the exporter container, `MEDUSA_METRICS_BIND_HOST` should remain `0.0.0.0`. `/metrics` requires `Authorization: Bearer <token>` from `MEDUSA_METRICS_BEARER_TOKEN` or the preferred ignored token file `MEDUSA_METRICS_BEARER_TOKEN_FILE=/app/data/secrets/prometheus-token`. Set the same `MEDUSA_METRICS_INTERNAL_TOKEN` for the backend and exporter to enable the private `/api/internal/metrics/snapshot` feed for backend process/cache/release/maintenance metrics. Expensive corpus, storage, and optional Docker metrics are seeded into Valkey on exporter startup and refreshed out-of-band every `MEDUSA_METRICS_HEAVY_TTL_SECONDS`; each scrape only renders that Valkey snapshot plus lightweight live checks. The Docker socket mount in `docker-compose.metrics.yml` stays commented out unless container-level Docker Engine metrics are worth the host-control trust boundary. The exporter intentionally skips node-exporter-style host metrics and GCS bucket inventory/cost metrics.

HAProxy keeps five-minute client/server timeouts so synchronous plan-building requests can finish while the UI progress state remains visible. The Docker frontend service builds and serves the compiled Vite bundle so browser reloads switch to hashed assets instead of a development module graph; direct `npm run dev` previews can still use Vite's API proxy. Tags > Optimize also skips the model planner on broad scopes and returns a deterministic local governance plan quickly enough for whole-library cleanup.

When the internal frontend service has no healthy HAProxy backend server during maintenance or restart, HAProxy serves a branded Medusa waiting page for normal browser routes and refreshes it automatically. `/api/*` requests still fail while the app is unavailable, and the waiting page carries `X-Medusa-Restarting: true` so frontend readiness checks cannot mistake it for the real app shell. HAProxy serves compact proxy-safe emblem derivatives from `deploy/haproxy/` for that fallback path because inline `http-request return file` assets must stay below HAProxy's response buffer limit.

## Credentials

Google Cloud Storage:

```bash
GCS_BUCKET=your-bucket
GCS_PREFIX=medusa
GOOGLE_CLOUD_PROJECT=your-project
GOOGLE_CLOUD_LOCATION=global
GOOGLE_APPLICATION_CREDENTIALS=/app/data/secrets/service-account.json
```

Put the service-account JSON under ignored `data/secrets/`; Docker Compose mounts that directory read-only into backend and worker containers. The service account needs object create/read/list/delete access on the configured bucket and prefix for originals and derived assets. Database backups stay local by default; if a non-local server deliberately sets `MEDUSA_DATABASE_BACKUP_STORAGE=gcs`, backup verification is stored in manifest objects and does not require object metadata update permission.

Settings > Cloud Storage now shows the active GCS bucket and can save it to the local preferences table so future backend and worker operations default to that saved bucket. The same panel reads the bucket lifecycle policy when bucket metadata is available, summarizing storage-class transitions such as Nearline/Coldline/Archive moves and delete conditions in plain language. The panel also accepts an uploaded Google service-account JSON key; uploaded keys are stored under ignored `data/managed-secrets` with restrictive file permissions, and only the service account name/project/path summary is stored in PostgreSQL. When an uploaded key is available, Medusa prefers it for GCS, Google Vision, and Gemini/Vertex operations. If no Settings-managed key has been uploaded, the service account name field reads `None, please upload a service account JSON`; Google clients then use the configured `GOOGLE_APPLICATION_CREDENTIALS` service-account JSON where present, while Gemini can use `GEMINI_API_KEY` as its no-service-account fallback.

OpenAI:

```bash
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5.5
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
MEDUSA_OPENAI_PRICING_TIER=standard
GEMINI_API_KEY=
GOOGLE_GENAI_USE_VERTEXAI=false
MEDUSA_OPENAI_SEND_PDF=true
MEDUSA_OPENAI_PDF_FILE_MAX_MB=24
MEDUSA_OPENAI_COMBINE_DOCUMENT_INTELLIGENCE=false
MEDUSA_OPENAI_PROMPT_CACHE_RETENTION=24h
MEDUSA_OPENAI_NORMALIZE_PAGE_TEXT=true
MEDUSA_OPENAI_PAGE_NORMALIZATION_MODE=auto
MEDUSA_OPENAI_PAGE_NORMALIZATION_AUTO_MAX_PAGES=4
MEDUSA_OPENAI_TEXT_NORMALIZATION_PAGE_MAX_CHARS=14000
MEDUSA_OPENAI_REQUEST_TIMEOUT_SECONDS=180
MEDUSA_INQUEST_INLINE_TIMEOUT_SECONDS=45
MEDUSA_OPENAI_PAGE_NORMALIZATION_TIMEOUT_SECONDS=90
MEDUSA_OPENAI_EMBEDDING_TIMEOUT_SECONDS=60
```

Recommendations:

```bash
MEDUSA_RECOMMENDATIONS_ENABLE_OPENALEX=true
MEDUSA_RECOMMENDATIONS_ENABLE_SEMANTIC_SCHOLAR=true
MEDUSA_RECOMMENDATIONS_ENABLE_CROSSREF=true
MEDUSA_RECOMMENDATIONS_ENABLE_UNPAYWALL=true
MEDUSA_RECOMMENDATIONS_ENABLE_ARXIV=true
MEDUSA_RECOMMENDATIONS_MAX_PER_SOURCE=40
MEDUSA_RECOMMENDATIONS_REQUEST_TIMEOUT_SECONDS=16
MEDUSA_RECOMMENDATIONS_ARXIV_TITLE_LOOKUPS=8
MEDUSA_RECOMMENDATION_DOWNLOAD_TIMEOUT_SECONDS=60
MEDUSA_RECOMMENDATION_DOWNLOAD_MAX_MB=80
MEDUSA_OPENALEX_MAILTO=
MEDUSA_UNPAYWALL_EMAIL=
SEMANTIC_SCHOLAR_API_KEY=
MEDUSA_CITATION_TITLE_WEB_SEARCH=true
MEDUSA_CITATION_TITLE_WEB_SEARCH_TIMEOUT_SECONDS=8
```

Related-paper discovery uses bounded OpenAlex, Semantic Scholar, and Crossref title/topic/evidence search; DOI/reference graph calls when DOI exists; any extracted source Bibliography on the document; and a bounded context expansion through Library documents that share projects, domains, tags, authors, or nearby publication years. A ready document no longer needs a DOI or bibliography before Related can try discovery as long as it has a searchable title. Source and context-neighbor bibliography references are parsed locally into DOI/title candidates, then the normal enrichment and duplicate-suppression passes can add open PDF evidence or mark library/stash/import matches. Unpaywall and arXiv enrich those candidates with open PDF links before they are queued for import; set `MEDUSA_UNPAYWALL_EMAIL` to a real contact email to enable Unpaywall lookups. The Library detail Related modal defaults to a Discover view that suppresses library-held, queued-import, and already-stashed DOI candidates while keeping an Already Known audit view, relation-family filters, compact evidence chips, Stash/Wishlist actions, and manual Google Scholar links rather than automated Scholar scraping. It groups provider-discovered, search-discovered, and context-derived Other Related Articles beside Bibliography Sources, preserving raw extracted citation text and attaching recommendation actions when a bibliography source has been parsed into an enriched candidate. The Stashes workspace opens as an acquisition workbench with Wishlist, Open PDF, Queued, In Library, and All lanes so useful non-open DOI leads remain visible without pretending a PDF is available.

Citation DOI discovery also uses Semantic Scholar title lookup and, when enabled, a targeted `"paper title" DOI` static web-search fallback after local text and Crossref title matching fail. Any DOI found this way is stored in document metadata evidence before the normal citation refresh path tries Crossref again and generates APA output.

If cloud credentials are absent, Medusa still boots and stores originals under `data/originals`. If `OPENAI_API_KEY` is absent, imports still create records and extract text, but AI metadata is marked for review.

The checkout and ignored `data/` directory are portable, but the default live PostgreSQL database is not stored inside the repo. Compose keeps it in Docker's `medusa-postgres` named volume, while `./data:/app/data` carries originals, processing cache files, managed secrets, home/cache directories, and local model weights. To move a library to another host, prefer the Utilities full database backup/restore workflow. The dedicated-server path uses `docker-compose.server.yml`, `deploy/server/.env.server.example`, `deploy/server/medusa-certbot.sh`, `scripts/medusa-portability-audit.py`, and `scripts/medusa-server-doctor.py` to make CPU pinning, IPv4/IPv6 bind-IP setup, TLS certificate installation, cache sizing, required file copies, and target readiness explicit without changing the local Compose default. A portable live instance that relocates PostgreSQL storage itself should use a deliberate Compose override that bind-mounts PostgreSQL onto a reliable external SSD; ordinary USB flash drives are better suited for carrying exports, backups, and local object snapshots than for hosting the active database. See `docs/PORTABLE_DEPLOYMENT.md` for the server move and release-agent flow.

Gemini Developer API keys can be stored outside tracked files at `data/secrets/gemini.env`:

```bash
GEMINI_API_KEY=...
GOOGLE_GENAI_USE_VERTEXAI=false
```

That directory is ignored by git and mounted into backend/worker containers. Settings > Import Processing > Shared Model Defaults lists supported Google Gemini text-generation options in a separate Google section beside OpenAI options, excluding preview and deprecated/shutdown models. Current Google choices include Gemini 3.1 Flash-Lite and the Gemini 2.5 Pro/Flash/Flash-Lite family; `gemini-*-latest` aliases remain selectable but resolve to those current priced families for cost estimates. Gemini document-intelligence calls use extracted text only in the current implementation; PDF file-context attachment remains on the OpenAI Responses path.

OpenAI enrichment runs asynchronously during imports and Concordance Runs. By default, Medusa keeps citation-critical metadata and APA fallback matching on `gpt-5.5`, runs summaries on `gpt-5.4`, runs tag suggestion extraction on `gpt-5.4-mini`, uses `gpt-5-mini` for ad hoc Bibliography Cleanup with targeted author-loss repair before the `gpt-5.4-mini` safety retry when cleanup is incomplete, low-confidence, still drops visible authors, or adds duplicate references, and uses `gpt-5.4` for manual Formula Capture; Settings can override each task. Formula Capture is a manual Concordance refinement pass only: it captures visible formulas as LaTeX/MathJax-compatible page evidence, appends searchable formula notes to non-manual parsed page text, renders recognized formula delimiters as math in read mode, and protects manually edited pages from overwrite. Import-time bibliography extraction remains local by default, orders strong non-marker two-column reference pages by detected column, and preserves native PDF line order on marker-heavy numbered reference pages, while document-level Bibliography Refresh first re-extracts the source reference section locally and then asks the selected Bibliography Cleanup model to return APA-sorted Markdown entries, one per source, with personal authors inverted to `Surname, Initials.`, entries sorted by first-author surname, and intelligent grouping and italics preserved. Bibliography Refresh gives completeness wide latitude: extracted lists up to 300 entries and 120,000 characters can go through model cleanup, while larger lists are preserved with separator-insensitive deterministic first-author sorting and explicit skip evidence instead of being truncated; if fresh extraction would reduce an existing bibliography of at least three entries, the existing bibliography is preserved with `rejected_regression_existing_bibliography` evidence; model cleanup output that drops visible coauthors is first sent through an author-preserving repair retry with the missing author token groups and rejected cleanup output, and cleanup that still returns fewer entries than extraction, drops visible coauthors, adds duplicate entries, reports very low confidence, or inserts missing-field placeholders is retried once with the fallback model when available, then rejected or sanitized if still unsafe, the complete deterministic extraction is kept when cleanup is unsafe, and document detail reports the skip or rejection beside the bibliography. The Settings task is labeled Tag Suggestions even though the compatible internal key remains `keywords_topics`. Tag prompts receive a compact manifest of existing canonical/candidate tags and scan that inventory before proposing new labels, while still allowing new concise tags for conceptually missing labels. Suggested tag names resolve through remembered merge aliases, then pass through tag-governance scoring before Medusa attaches or creates tags. The scorer is existing-first, not existing-only: it combines alias memory, deterministic similarity, optional cached embedding similarity, library/status/relationship context, cluster-aware checks, and semantic covered-by checks, then scores each candidate on document relevance, library fit, and novelty value. Import attachment is intentionally aggressive: at most five scored tags may attach per document, at most one can be a brand-new candidate tag, low-value form/generic labels are skipped, and near-existing candidates are reused or recorded for review instead of creating another tag. Strong new concepts become attached `candidate` tags only when they clear higher relevance/novelty thresholds; weak or redundant candidates are recorded but not attached. General `summary_topics` Concordance tag updates remain additive so broad Concordance does not silently strip manual organization, while the document detail Tag Refresh button queues a forced `tag_refresh` job that removes that document's current tag links, reruns the same import-style Tag Suggestions and governance process, reuses existing tags where they suffice, and creates at most one new candidate tag when the current inventory does not cover a supported concept. Weak assignment removal outside that explicit document refresh still happens only through Optimize pruning approval. Optimize uses the same current Tag Suggestions model preference that import uses for tag creation on narrower scopes, but scopes above the 300-tag model inventory cap skip the model planner and return deterministic cleanup plans quickly; deterministic orphan, relationship, status, and pruning checks still review the full scope. True zero-link orphan tags are merged into a useful used tag when deterministic variant/prefix/semantic checks find a strong target, otherwise they can be pruned entirely by approval; one-use candidates can be retired when they lack durable evidence; one-use canonicals can be downgraded until repeated use proves them; and singleton assignments without scoring history can be pruned by approval. Text Chunk Encoding uses the OpenAI embeddings endpoint and offers `text-embedding-3-small`, `text-embedding-3-large`, and `text-embedding-ada-002`, with `text-embedding-3-small` remaining the default. Metadata extraction may send the original PDF as file context when the file is below the configured size cap, but summary and tag suggestion calls use extracted text only. Default generated document summaries and Inquest answers are prompted as complete-sentence technical paragraphs written at a graduate academic level suitable for a master's-degree reader that open with the document's substantive claim, problem, method, finding, or conceptual contribution instead of author/year/medium/source-title framing; they cover original ideas or concepts, subject-matter areas, research questions raised, conclusions or novel insights, surprising or counterintuitive results when present, academic context, main takeaways near the end, and adjacent research areas or related topics worth pursuing for continued reading, without bold, italics, bullets, em dashes, fancy quotes, standalone headings, single-word openings, or leaked schema metadata unless the user explicitly asks for another format. Summary cleanup also strips accidental trailing `confidence` or `needs_review_reasons` blocks and common bibliographic lead-ins before storage. Inquests try to answer inline using `MEDUSA_INQUEST_INLINE_TIMEOUT_SECONDS` before falling back to the durable worker queue. APA reference-list and parenthetical in-text citation text are generated together, normalized, and validated as a pair; malformed supplied candidates fall back to deterministic metadata formatting without a second model call. Reference-list text is generated deterministically from DOI/Crossref evidence whenever possible; `gpt-5.5` APA matching is used only when Crossref/DOI evidence is missing or ambiguous. `MEDUSA_OPENAI_COMBINE_DOCUMENT_INTELLIGENCE=true` restores the previous single structured `core_document_intelligence` Responses call for metadata, summary, APA candidate, and tag suggestions. `MEDUSA_OPENAI_PROMPT_CACHE_RETENTION=24h` configures prompt-cache retention hints keyed by document checksum for retries and Concordance reruns; Medusa hashes overlong cache keys to fit the Responses API 64-character key limit and omits the retention hint when the installed OpenAI SDK does not expose that Responses parameter.

Page text normalization is local-first: `MEDUSA_OPENAI_PAGE_NORMALIZATION_MODE=auto` locally cleans normal pages and escalates only low-text or artifact-heavy pages, capped by `MEDUSA_OPENAI_PAGE_NORMALIZATION_AUTO_MAX_PAGES`. Auto mode sends page text only, not the full PDF per page. Set the mode to `always` only when you intentionally want the older all-pages OpenAI normalization behavior. Graphics are stored as cropped assets with labels/captions rather than converted into Markdown. If OpenAI is unavailable or a page-normalization request times out, Medusa falls back to local whitespace, hyphenation, and paragraph cleanup.

Reader compare mode shows authenticated rendered PDF pages and the current parsed page side by side. The compact Library detail preview renders only the focused PDF page, while expanded Reader mode gives the PDF preview, parsed text, and compare panes the available window-height frame below the document controls and tabs; PDF page previews render at 2.5x scale. The parsed page can be edited in place, saves as manual normalized text, rebuilds document search, and writes a `DocumentVersion` row with page-level before/after snapshots. The parsed-text pane has a compact search control that counts case-insensitive matches across parsed pages, jumps to previous/next matching pages, and highlights matches on the current read-mode page. Reader Notes below the reader provide a page-aware annotation composer with kind, color, page, body, optional selected parsed-text quote evidence, annotation search, page jump, inline edit, and delete; annotation body text contributes to document search. The parsed-text pane also repeats page navigation and Copy/Edit controls at the bottom, switching to Save/Cancel while editing. The editor tool strip includes Scrub, which removes the selected exact text from all parsed page text and shows the document-wide match count while text is highlighted. Expanded Compare mode lets full-document PDF scrolling drive page changes and keeps the text pane synchronized to the visible PDF page, while text-side scrolling only nudges the PDF within the current page so longer parsed text can be read to the bottom without auto-advancing. Scan Page runs a local page visual pass, then shows a review panel with page-map boxes, 300 DPI candidate thumbnails, individual selection, Keep selected, and Discard; keeping selected candidates is the step that replaces that page's stored figures and writes document history. Stored figure cards can be relabeled, given corrected captions/descriptions, or deleted; each correction rebuilds document search and writes history. History entries can be stepped through and restored with Restore as Current, which applies the chosen snapshot to the live searchable document while appending a new history row. Escape closes or collapses the active Medusa-owned popover, dialog, editor, composer, or expanded Reader surface, and Download Original uses Settings > Download Naming to render attachment filenames; the default template is `$title ($year)` and `.pdf` is implicit.

Raw text extraction is controlled separately in Settings. The Raw Text Extraction selector is grouped into Local options (Docling, Marker, PyMuPDF) and OpenAI model fallbacks. Settings has Save All controls at the top and bottom of the view so display, cache, runtime, accent, citation convention, and model preferences are saved together. The Preferences panel currently offers APA (7th Ed.) as the citation convention. Marker is the default preference and is installed in the backend/worker image; its model cache lives under `data/model-cache` through the Compose volume, so a first use may download local weights but later imports reuse them. PyMuPDF remains the built-in no-credential fallback when Marker is unavailable or times out.

Finances records and displays AI usage from completed and failed OpenAI Responses/embeddings calls and Gemini `generateContent` calls: provider, task, model, document/job context, token counts, cached input tokens where reported, output tokens, PDF/file context bytes, and recent errors. The app shell also watches the dashboard's fresh failed-call notices and shows dismissible alerts with task, model, document, error text, and a Finances shortcut when new failed provider calls are recorded; older failures stay visible in Finances without being replayed as live alerts. Dollar totals are estimates from Medusa's tracked model-pricing history using official provider token prices. OpenAI GPT usage is priced with `MEDUSA_OPENAI_PRICING_TIER` (`standard`, `batch`, `flex`, or `priority`), embeddings use their published input-token rate, and Google Gemini text usage uses Developer API paid-tier standard pricing. Unknown or unavailable models are counted as unpriced because model pricing and project access can change independently of the local app. Settings > Import Processing > Shared Model Defaults shows the active OpenAI pricing tier, when pricing was last refreshed, provides a Refresh Models & Pricing action, and warns when configured tier rows are missing or pricing is more than two days old. Refreshes update the existing active history row when prices are unchanged and add a new historical row only when a model's price changes, so usage can be costed against the price that applied when the call was recorded. Finances can group usage by model, task, document, calendar day, or calendar hour, with a cost trend line plus cost-by-model and token-by-task pie charts for the selected period.

Document Composition is available from the Library detail actions when a document is selected. Imports now write granular `DocumentCompositionRecord` rows for the staged cost estimate, second-pass local stages, synced model usage, processing warnings/errors, and manual edits. The Composition dialog shows the persisted estimate versus actual recorded model spend, a Cost Composition pie chart with dollar values, provider spend, local processing time, a React Flow pipeline chart with connected steps in import execution order, and a Processing Issues section when warnings or errors occurred. The pipeline chart includes OCR audit, page normalization, structured-table evidence, visual extraction/context, bibliography extraction, and the specific models active for downstream processing; later Concordance Runs append their capability/model-call nodes, including manual Formula Capture, with Concordance labels. Older documents without composition rows show "not available." While imports are active, the reserved header progress control includes current known dollar spend so far.

Before broad Concordance starts, Settings estimates the selected scope and capabilities, including planned jobs, same-model no-ops, already queued work, current-version skips, unpriced routes, and estimated cloud spend. The document-level Concord button fetches the same estimate before confirmation. Concordance skips model-backed fields when document evidence or usage history shows the field already used the currently selected model, while changed model routes can still queue even if the capability version is otherwise current.

Async document work is started from the app shell, not only from the page-level component that owns the button. DOI, citation, summary, bibliography, Formula Capture, and Concordance refresh actions immediately turn soft blue with their own icon spinning and a slim in-button progress bar, then the reserved header progress control follows active durable imports and background runs even if the user switches views. Page-local buttons still give a short green success blend or red result flash; failures also surface a concise error message. Failed provider calls recorded in the usage ledger additionally surface through the shell-level model-call alert so repeated API failures are visible even when the owning workspace is not open.

Worker recovery:

```bash
MEDUSA_IMPORT_WORKER_CONCURRENCY=4
MEDUSA_WORKER_STALE_JOB_SECONDS=900
MEDUSA_DOCUMENT_CACHE_SIZE_MB=1024
MEDUSA_SLIPSTREAM_ENABLED=false
MEDUSA_SLIPSTREAM_PUBLIC_BASE_URL=
MEDUSA_SLIPSTREAM_LEASE_TTL_SECONDS=180
MEDUSA_SLIPSTREAM_HEARTBEAT_SECONDS=30
MEDUSA_SLIPSTREAM_MAX_RESULT_MB=512
MEDUSA_SLIPSTREAM_REQUIRE_TLS=true
```

Medusa defaults to four concurrent import jobs. The env var sets the startup default, and Settings lets the local user change the active preference without editing tracked files. Values above four are allowed but can generate many OpenAI calls and costs over a short period. Manual batch uploads are staged first; the worker only claims them after Process Uploads promotes staged rows into the queued pipeline.

Worker startup immediately requeues `running` import and Concordance jobs left by the previous worker process. This setting is the secondary guard for stale locks that remain while the worker is alive.

Slipstream is disabled by default. When enabled, Settings > Slipstream can create one-time enrollment tokens for remote clients. Clients generate and keep their Ed25519 private key locally, register over HTTPS, poll the central app for one leased job at a time, heartbeat while working, and upload a result manifest for Medusa to apply. Remote clients do not connect to PostgreSQL and do not need inbound ports.

The document cache size defaults to 1,024 MB. It controls how many completed import PDFs are kept locally under `data/processing-cache` for Concordance and Inquest work; originals are still written to GCS or local durable storage at upload time. Clearing staged uploads removes their managed processing-cache copies and staged original objects before deleting their queue-only records. Settings shows the current cache footprint rounded to the nearest MB. Settings > Download Naming controls suggested original-PDF download names with `$title`, `$year`, `$authors`, `$author`, and `$pages` tokens.

## Development

Architecture and design context for future work lives in `docs/ARCHITECTURE.md`; performance scaling notes live in `docs/PERFORMANCE_ROADMAP.md`. Codex-specific project guidance lives in `AGENTS.md`; keep these current when design or architecture changes.

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

When previewing the frontend against the Compose HTTPS endpoint instead of a directly exposed backend, use an alternate browser-visible API prefix and let Vite rewrite it back to `/api`:

```bash
VITE_MEDUSA_API_PREFIX=/_medusa_api MEDUSA_API_PROXY=https://localhost:3737 npm run dev -- --port 3747
```

Worker:

```bash
cd backend
python -m app.worker
```

Basic Slipstream client:

```bash
cd backend
python -m app.slipstream.client --server https://medusa.home.musial.io:3737 --enroll TOKEN --name "Remote worker"
```

The bundled client stores its key/state under ignored local data by default. It currently provides a conservative PDF text-import runner and submits manifest-based results back to the central app; richer model-backed and capability-specific remote runners should keep cloud/provider secrets central.

Tests:

```bash
pytest
```

Full database backup and restore:

Use Utilities for the normal backup workflow. Backup Database shows a likely compressed size, then creates a `pg_dump` custom-format snapshot, compresses it with zstd, stores it under `data/backups/database`, and verifies the stored checksum. Restore Database is shown beside the backup selector, requires confirmation, and restores from a listed local backup by default; it always completes and verifies a fresh safety backup before applying the restore. After `pg_restore`, Medusa repairs backup/restore history so active rows inherited from the restored snapshot do not block future backup or restore work. Utilities also shows the count and total compressed size of all listed backup dumps. GCS database backups are opt-in with `MEDUSA_DATABASE_BACKUP_STORAGE=gcs` and are blocked when `MEDUSA_LOCAL_AUTO_LOGIN=true`.

Legacy metadata JSON restore drill:

```bash
cd backend
python -m app.tools.restore_export /path/to/medusa-metadata.json
python -m app.tools.restore_export /path/to/medusa-metadata.json --apply
```

The restore command validates schema/safety flags, rejects secret-bearing keys, reports conflicts and skipped auth records, and parks restored queued/running jobs as `restored_paused` unless `--reactivate-jobs` is explicitly supplied.

## Safety Model

Imports are durable jobs stored in PostgreSQL. Manual uploads first create staged jobs that can be reviewed, added to by later batches, and released with Process Uploads; each processing step then records events and checkpoints, so stopping the app mid-import leaves work queued or resumable. Staged, queued, running, failed, cleared, and restored-paused document rows are queue/operations records only: they do not appear in Library lists, Library search, dashboard document counts, domain/tag document counts, project bibliographies, recommendations' existing-library matches, or Concordance scopes until processing finishes and the document becomes `ready`. PDF uploads are stored as-is; HTML and plain-text/Markdown uploads are parsed for source structure, converted locally into PDF mezzanine originals, and then stored through the same GCS/local paths. Upload source bytes are checksum-addressed for duplicate detection before processing.

Duplicate uploads are checked before staging. When an exact checksum match is found against a Library-visible document or an active/recoverable import row, the Import view asks whether to skip the duplicate, overwrite the matching document record, or import anyway as a separate document. Cleared/canceled queue-only rows are ignored so abandoned staged uploads do not block future imports. Library filters can also show duplicate matches already in the collection, and Library duplicate review can mark a pair as different documents so future scans and row badges ignore that false positive.

Staged and queued upload rows show rough dollar estimates from stored page counts, the selected Import Processing preset, known model-pricing history, prior import usage exemplars by task/model when available, and prior estimate-vs-actual accuracy when Medusa has completed examples. The persisted estimate includes step-level metadata for local-only stages, pending OCR/visual-model integrations, capped page-normalization calls, shared metadata/summary/citation/tag/embedding models, and the selected preset snapshot. Import and Queue also show a rough grand total for the staged/queued upload set before processing starts.

If the worker/container stops while a job is already marked `running`, the next worker requeues it on startup and continues from the last durable checkpoint. In-flight documents may repeat the current step, and page normalization resumes from persisted page checkpoints when possible.

Local workers and Slipstream clients claim import and Concordance jobs through the same lease coordinator. PostgreSQL is the quorum authority: a partial unique active-lease constraint allows only one active lease per `(job_type, job_id)`, so a job can be assigned to one local worker or one Slipstream client but not both. Slipstream leases heartbeat every 30 seconds by default and expire after 180 seconds without a heartbeat, returning the job to the queue with a processing event. Late results from expired or canceled leases are rejected if the job has been re-leased; duplicate result submissions for the accepted lease are idempotent.

The Import page can release staged uploads with Process Uploads or discard all staged uploads with Clear Staged, which removes their queue-only document/job rows, managed processing-cache files, and staged original storage objects. The Import Queue can release staged uploads, retry failed imports in bulk, retry individual queued/failed/restored jobs, cancel individual staged/queued/failed/restored rows, and clear staged/queued/failed/restored rows into a terminal `cleared` state. Fresh running jobs are protected from manual retry, cancel, or clear to avoid racing an active worker.

Utilities > Database provides manual maintenance controls. Compact Database starts a visible background PostgreSQL `VACUUM (FULL, ANALYZE)` job where available, Optimize Database starts a visible background `ANALYZE` job to refresh table statistics, and Clear Import Cache removes terminal hidden import records, stale project-resource links, managed processing-cache files, and staged original objects that are already excluded from active Library and Queue surfaces. Managed cache-file and staged-original deletion is best effort, so an unavailable storage backend does not block removing the stale hidden database rows. It does not clear Library-visible documents or staged/queued/running/failed/restored-paused import rows. Utilities polls maintenance status while long-running database work is active so the page shows elapsed time instead of holding a single opaque browser request. Utilities also shows Database Backup & Restore plus host-agent maintenance status: Check Now requests a release-status refresh, and Run Maintenance Now requests the idle-gated maintenance lane for already-merged safe updates and same-tag image refreshes. The host agent still blocks on active document work, backup/restore, database maintenance, unknown-risk changes, and any missing or unverifiable pre-maintenance verified backup when the classified change requires one. Utilities also shows container footprint stats from inside the backend runtime, including cgroup memory/CPU, process uptime, data-volume usage, path-level storage footprints, and Docker image/layer sizes when the Docker Engine socket has been deliberately mounted into the backend container. When the socket is not mounted, the Status and Utilities backend-image cards still show the backend base-image identity from runtime inventory and state that layer sizing is disabled. The same Container Footprint section lists runtime versions for HAProxy, Python, key backend packages, PostgreSQL client, zstd, curl, frontend Node.js, Vite, and the frontend build stamp so base-image and binary freshness are visible from the app. Below that, HAProxy Statistics reports the TLS endpoint, frontend/backend status, sessions, traffic, health-check detail, and proxy errors from HAProxy's internal CSV stats feed. Restart Backend terminates the backend process after the API response returns; the Compose backend service uses `restart: unless-stopped`, so Docker brings it back and the frontend polls `/api/health` until the backend is healthy again.

Release and maintenance refreshes are host-agent compatible. The backend reads `data/deploy/release-status.json` and writes `data/deploy/release-request.json` when the user clicks the header `Upgrade Now` button; Utilities and Status can also write `release-check-request.json` and `maintenance-request.json` for on-demand checks or safe maintenance. If the status file's running build is stale after a container rebuild, the backend uses its current runtime build identity for browser reload decisions so `Reload Now` cannot loop on old JSON. The browser tab that starts an upgrade warns about unsaved edits, locks the UI while the host agent works, polls release status through restart gaps, verifies both `/api/health` and the exact app-shell route that will be reloaded after completion, then cache-busting reloads into the new browser bundle before returning control. All signed-in tabs also show the blocking overlay when a scheduled or user-requested maintenance apply starts. When an explicit release request has just completed and the current browser bundle is stale, the header action is labeled `Reload Now`; clicking it performs the same health and app-shell readiness checks before reloading instead of requesting another server update. Settled maintenance/runtime refresh status does not keep prompting old browser bundles after the server is already current, so stale tabs are not left with a persistent reload button just because their embedded build stamp differs from the server. The server-side `scripts/medusa-release-agent.py` checks upstream git state, refuses dirty checkouts, classifies dependency/runtime risk, fast-forwards only for approved upgrade paths, persists explicit build identity variables into ignored `.env`, runs the policy-based verified backup gate only for database/runtime-sensitive changes, rebuilds Compose with those variables and any configured Compose override files, can perform same-tag refreshes with `--pull always`, and updates the status file only after the backend health endpoint and GUI shell route pass through the public proxy. Its health probes resolve `MEDUSA_PUBLIC_HOST` to `MEDUSA_RELEASE_HEALTHCHECK_IP` when set, otherwise to `MEDUSA_BIND_IP`, then `MEDUSA_BIND_IPV6`, then localhost. Template systemd units under `deploy/systemd/` can own the Compose stack and wire the release checker/apply watcher plus twice-weekly maintenance timer/path on a server such as carrot. The app itself does not run arbitrary git or Docker commands.

Docker image and layer sizing is not available from inside an ordinary container unless the Docker Engine API is exposed. To enable it, add a local Compose override such as:

```yaml
services:
  backend:
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
```

Even as a read-only bind mount, the Docker socket grants the backend process broad control over the host Docker daemon. Leave it unmounted unless you explicitly want Utilities to query image/layer sizes.

After a released import queue drains and no queued/running import jobs remain, the worker runs PostgreSQL `VACUUM (ANALYZE)` across the database when Medusa is using Postgres.

Concordance Runs and citation refreshes are also safe to leave in progress from the UI. Once the backend accepts the request, the durable database run continues through the worker queue independently of the currently open page, and the shell-level progress shelf reconciles with refreshed run/job state.

Utilities includes full database backup and restore controls. Backups are named with `YYYYMMDD-HHMMSS` plus the short hostname, compressed with zstd, stored under `data/backups/database` by default, and checksum-verified after storage. The Backup Database control shows a likely backup size based on current PostgreSQL database size and the latest completed backup when available, Utilities shows the total size of all listed backups, and recent backup/restore run history remains visible instead of only the newest row. Browser restore uses a selected backup, asks for confirmation, is gated by a fresh verified safety backup, then applies with `pg_restore` and runs migrations. A full database restore may replace auth rows, password hashes, sessions, and 2FA secrets, so the browser may need to sign in again afterward.

For portability, treat those PostgreSQL backups as the supported way to move the system of record between machines. Copying the repo or `data/` directory alone does not copy the Docker named database volume; direct database-directory portability requires an explicit bind mount and storage hardware suitable for PostgreSQL writes.

Utilities also keeps legacy metadata export links. The full metadata export captures research metadata, extracted text, organization state, notes, corrections, jobs, Concordance history, and a durable asset manifest. The storage manifest export lists original and derived asset URIs. These JSON exports intentionally omit API keys, service-account credentials, password hashes, session tokens, TOTP secrets, and recovery-code hashes.

Metadata exports can be restored with the CLI restore tool. Restores are dry-run by default, preserve export IDs by default, skip password/session state, restore document/storage URI references, and park active job queues so a fresh worker does not unexpectedly reprocess restored history.
