# Medusa

Medusa stands for **Mapped Evidence for Discovery, Understanding, Synthesis, and Analysis**. It is a local-first research library, document aggregator, and intelligent taxonomizer, built as a polished web app for organizing academic PDFs, HTML documents, and plain-text sources, extracting searchable text and metadata, generating citations and summaries, and managing project run sheets.

## What Is Implemented

- Password-protected LAN web app behind HAProxy TLS on port `3737`
- React research cockpit UI with day/night modes, darker light-theme contrast grays, and restrained icon-left action buttons
- Lowercase contextual browser titles such as `medusa | DOCUMENT_TITLE`, `medusa | PROJECT_TITLE`, or the current workspace name
- Bookmarkable top-level workspace URLs plus document focus links such as `/documents/{document_id}` for opening Library with a specific document selected
- FastAPI backend with session cookies
- PostgreSQL schema with Alembic migrations, `pgvector`, full-text/trigram indexes, JSONB metadata, and durable import jobs
- Batch PDF, HTML, and plain-text/Markdown upload with optional label, priority, read status, domain/tag/project defaults, inline organization creation, checksum duplicate detection, explicit skip/overwrite/import-anyway choices, local PDF mezzanine conversion for non-PDF sources, staged upload rows with rough per-file and grand-total cost previews, Process Uploads and staged-upload cleanup actions, staged-document invisibility from Library/search until import completion, and active-first progress-shaded import processing rows with model/cost detail
- GCS storage adapter with local fallback when credentials are not configured
- Raw text extraction preference with Local choices for Docling, Marker, and PyMuPDF; Marker is the default preference and PyMuPDF remains the bundled local fallback
- Authenticated original PDF preview/open/download route in the document detail pane and expanded Reader mode
- Parsed full-text reader with normalized one-page navigation, PDF/Text switching, side-by-side compare mode for editing extracted text beside the original PDF, Scrub cleanup for repeated selected text, and page-scoped visual scans from the PDF preview footer that show selectable review candidates before anything is kept
- Cropped figure/chart/photo extraction into durable storage with 300 DPI rendered crops, authenticated asset preview, editable labels/descriptions, deletion controls, page geometry, and one-page Reader rescue scans
- OpenAI adapter for structured metadata, visible author contact emails, summaries, tag suggestions, page text normalization, and embeddings
- OpenAI usage ledger with Budget & Costs rollups for last day/month/3 months/all time, calls, tokens, estimated known-model costs, cached input tokens, PDF/file context bytes, recent errors, trend lines, pie charts, and task/model breakdowns
- Utilities workspace with Database maintenance actions for compaction, table-statistics optimization, hidden import-cache cleanup with a live cleanup count, Docker/container footprint stats, runtime binary/package versions, HAProxy TLS/proxy stats, and backend-container restart with health polling
- Per-document Cost Composition tracking for imports, including persisted pre-processing estimates, estimate-vs-actual comparison, stage timings, provider/model spend, local processing duration, processing issues, and the exact pipeline/method/model path used to generate the document
- Citation generation in Markdown APA 7 reference-list and in-text forms, with model/provenance tracking, plus BibTeX, RIS, and CSL JSON
- Live document-level DOI, citation, summary, bibliography, and tag refresh controls backed by durable Concordance jobs
- Related-paper recommendations with default hidden-existing filtering, extracted Bibliography reference-list seeds, Unpaywall/arXiv PDF availability enrichment, Google Scholar search links, DOI/title copy actions, DOI stashing, a sortable Stashes view with DOI copy, title-copying manual Sci-Hub DOI links, resolver-backed DOI imports, stash PDF uploads that enter the normal import queue, and DOI/title-match cleanup for already-imported stash targets
- Reserved header progress control for imports, Concordance, and citation-refresh work, so job feedback continues after navigating away from the page that started the work without shifting the header actions
- Async action feedback: job-starting buttons turn soft blue with the button icon spinning and a slim progress bar while work is in flight, blend through green on success, flash red on failure, and show a concise error popover when startup or completion fails
- App-styled delayed tooltips on buttons, action links, dropdowns, checkboxes, and text inputs, including disabled-state reasons where actions are unavailable
- Queue view with Import-style progress-shaded import rows, animated processing glyphs, model/cost/stage detail, row retry/cancel, Process Uploads, Retry Failed, Clear, and Clear Failed controls, plus bounded citation-review cards with accept/reject actions and correction history
- Projects/run sheets with add/remove resources, status/priority/used tracking, notes, bibliography generation, and pane-constrained controls that keep long document titles from spilling into Bibliography
- Domains management with searchable alphabetized nested trees, top-level/child creation, rename, move, description and tag metadata, color, soft delete, document-count visibility, and affected-document search/history updates
- Tags management with sortable counts and governance status, scoped tag search, shift-click range selection for visible sorted/filtered rows, audited rename, confirmed merge into an existing or newly named tag, remembered merge aliases for future tag suggestions, flattened keyword/topic distinctions, and a right-side Optimize workbench using the same Tag Suggestions model as import tag creation that keeps the user in the loop for merge suggestions, orphaned-tag merge/prune cleanup, semantic relationships, candidate promotion/retirement, and weak document-tag pruning, with individual approvals or one-click approval of the current plan plus top progress feedback while the plan is building or bulk apply runs
- Saved searches, smart filters, searchable filter/bulk dropdowns with Enter-to-select behavior, visible priority flags in Library rows and saved-search summaries, audited title cleanup, and bulk-edit controls with custom tag nomination
- Concordance Runs for retroactively updating already-imported documents to current capability versions, with pre-run cost estimates and same-model no-op planning
- Document correction pane for metadata, inline alphabetical tag add/remove/Refresh controls, DOI Copy/Edit/Refresh, domains, custom attributes, rendered Markdown summaries/citations, rich Markdown summary editing, inline citation edits, extracted-text cleanup, duplicate visibility, and complete correction history with Restore as Current
- Accessory Summaries for user-prompted focused summaries, queued as durable worker jobs with the Settings-selected default model and inline optional titles
- Stored document annotations/highlights with page, color, note body, soft delete, and search indexing; Library creation controls are deferred for a quieter redesign
- Notes and reminders attached to documents, domains, projects, or the general library
- Full PostgreSQL database backup/restore from Utilities, using GCS, zstd compression, likely backup-size estimates, total listed-backup size, SHA-256 upload verification, header progress, and mandatory pre-restore safety backups
- Host-agent-compatible release status checks with an authenticated header `Upgrade Now` prompt when newer pushed code or a newer running build is available
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

Install the HAProxy TLS certificate material under ignored local data storage:

```bash
mkdir -p data/haproxy
cp /path/to/fullchain.pem data/haproxy/fullchain.pem
cp /path/to/privatekey.pem data/haproxy/privatekey.pem
chmod 600 data/haproxy/*.pem
```

Then run:

```bash
docker compose up --build
```

Backend startup runs Alembic migrations for PostgreSQL automatically before serving traffic.

Open:

```text
https://medusa.home.musial.io:3737
```

Plain HTTP requests on port `3737` redirect to `https://medusa.home.musial.io:3737` on the same port. The bundled deployment expects a certificate that covers `*.home.musial.io`; change `MEDUSA_PUBLIC_HOST`, the HAProxy redirect/check host, and the certificate files together for another local domain.

The login email defaults to `admin@medusa.local` and the first admin password comes from `MEDUSA_PASSWORD` in `.env`. Those `.env` values seed the account when Medusa creates it for the first time; after that, change the live login email or password from Settings > Account.

## TLS And HAProxy

Docker Compose runs HAProxy as the only host-exposed service on port `3737`. HAProxy terminates TLS, redirects plain HTTP on the same port to HTTPS, and proxies Medusa to the internal frontend service. Backend, worker, database, and frontend ports stay on the Compose network.

Certificate files belong in ignored `data/haproxy/fullchain.pem` and `data/haproxy/privatekey.pem`. Compose combines them into HAProxy's runtime PEM inside the container; do not commit certificate private keys.

```bash
MEDUSA_PUBLIC_HOST=medusa.home.musial.io
MEDUSA_HAPROXY_STATS_URL=http://haproxy:8404/stats;csv
MEDUSA_ALLOWED_HOSTS=medusa.home.musial.io
```

HAProxy's stats listener is internal-only. Utilities reads the authenticated backend endpoint `/api/utilities/haproxy/status`, which summarizes the internal CSV stats feed.

HAProxy and the Vite API proxy keep five-minute client/server timeouts so synchronous plan-building requests can finish while the UI progress state remains visible. Tags > Optimize also skips the model planner on broad scopes and returns a deterministic local governance plan quickly enough for whole-library cleanup.

## Credentials

Google Cloud Storage:

```bash
GCS_BUCKET=your-bucket
GCS_PREFIX=medusa
GOOGLE_CLOUD_PROJECT=your-project
GOOGLE_CLOUD_LOCATION=global
GOOGLE_APPLICATION_CREDENTIALS=/app/data/secrets/service-account.json
```

Put the service-account JSON under ignored `data/secrets/`; Docker Compose mounts that directory read-only into backend and worker containers. The service account needs object create/read/list/delete access on the configured bucket and prefix. Backup verification is stored in manifest objects and does not require object metadata update permission.

Settings > Cloud Storage now shows the active GCS bucket and can save it to the local preferences table so future backend and worker operations default to that saved bucket. The same panel accepts an uploaded Google service-account JSON key; uploaded keys are stored under ignored `data/managed-secrets` with restrictive file permissions, and only the service account name/project/path summary is stored in PostgreSQL. When an uploaded key is available, Medusa prefers it for GCS, Google Vision, and Gemini/Vertex operations. If no Settings-managed key has been uploaded, the service account name field reads `None, please upload a service account JSON`; Google clients then use the configured `GOOGLE_APPLICATION_CREDENTIALS` service-account JSON where present, while Gemini can use `GEMINI_API_KEY` as its no-service-account fallback.

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
```

Related-paper discovery uses OpenAlex, Semantic Scholar, Crossref, and any extracted source Bibliography on the document to find candidates. Bibliography references are parsed locally into DOI/title candidates, then the normal enrichment and duplicate-suppression passes can add open PDF evidence or mark library/stash/import matches. Unpaywall and arXiv enrich those candidates with open PDF links before they are queued for import; set `MEDUSA_UNPAYWALL_EMAIL` to a real contact email to enable Unpaywall lookups. The Library detail Related modal defaults to a Discover view that suppresses library-held, queued-import, and already-stashed DOI candidates while keeping an Already Known audit view, relation-family filters, compact evidence chips, Stash actions, and manual Google Scholar links rather than automated Scholar scraping. It groups provider-discovered Other Related Articles beside Bibliography Sources, preserving raw extracted citation text and attaching recommendation actions when a bibliography source has been parsed into an enriched candidate.

If cloud credentials are absent, Medusa still boots and stores originals under `data/originals`. If `OPENAI_API_KEY` is absent, imports still create records and extract text, but AI metadata is marked for review.

The checkout and ignored `data/` directory are portable, but the default live PostgreSQL database is not stored inside the repo. Compose keeps it in Docker's `medusa-postgres` named volume, while `./data:/app/data` carries originals, processing cache files, managed secrets, home/cache directories, and local model weights. To move a library to another host, prefer the Utilities full database backup/restore workflow. A portable live instance should use a deliberate Compose override that bind-mounts PostgreSQL onto a reliable external SSD; ordinary USB flash drives are better suited for carrying exports, backups, and local object snapshots than for hosting the active database. See `docs/PORTABLE_DEPLOYMENT.md` for the server move and release-agent flow.

Gemini Developer API keys can be stored outside tracked files at `data/secrets/gemini.env`:

```bash
GEMINI_API_KEY=...
GOOGLE_GENAI_USE_VERTEXAI=false
```

That directory is ignored by git and mounted into backend/worker containers. Settings > Import Processing > Shared Model Defaults lists supported Google Gemini text-generation options in a separate Google section beside OpenAI options, excluding preview and deprecated/shutdown models. Current Google choices include Gemini 3.1 Flash-Lite and the Gemini 2.5 Pro/Flash/Flash-Lite family; `gemini-*-latest` aliases remain selectable but resolve to those current priced families for cost estimates. Gemini document-intelligence calls use extracted text only in the current implementation; PDF file-context attachment remains on the OpenAI Responses path.

OpenAI enrichment runs asynchronously during imports and Concordance Runs. By default, Medusa keeps citation-critical metadata and APA fallback matching on `gpt-5.5`, runs summaries on `gpt-5.4`, runs tag suggestion extraction on `gpt-5.4-mini`, and uses `gpt-5.4-nano` for ad hoc Bibliography Cleanup; Settings can override each task. Import-time bibliography extraction remains local by default, while document-level Bibliography Refresh first re-extracts the source reference section locally and then asks the selected Bibliography Cleanup model to return APA-sorted Markdown entries, one per source, with personal authors inverted to `Surname, Initials.`, entries sorted by first-author surname, and intelligent grouping and italics preserved. The Settings task is labeled Tag Suggestions even though the compatible internal key remains `keywords_topics`. Tag prompts receive a compact manifest of existing canonical/candidate tags and scan that inventory before proposing new labels, while still allowing new concise tags for conceptually missing labels. Suggested tag names resolve through remembered merge aliases, then pass through tag-governance scoring before Medusa attaches or creates tags. The scorer is existing-first, not existing-only: it combines alias memory, deterministic similarity, optional cached embedding similarity, library/status/relationship context, cluster-aware checks, and semantic covered-by checks, then scores each candidate on document relevance, library fit, and novelty value. Import attachment is intentionally aggressive: at most five scored tags may attach per document, at most one can be a brand-new candidate tag, low-value form/generic labels are skipped, and near-existing candidates are reused or recorded for review instead of creating another tag. Strong new concepts become attached `candidate` tags only when they clear higher relevance/novelty thresholds; weak or redundant candidates are recorded but not attached. General `summary_topics` Concordance tag updates remain additive so broad Concordance does not silently strip manual organization, while the document detail Tag Refresh button queues a forced `tag_refresh` job that removes that document's current tag links, reruns the same import-style Tag Suggestions and governance process, reuses existing tags where they suffice, and creates at most one new candidate tag when the current inventory does not cover a supported concept. Weak assignment removal outside that explicit document refresh still happens only through Optimize pruning approval. Optimize uses the same current Tag Suggestions model preference that import uses for tag creation on narrower scopes, but scopes above the 300-tag model inventory cap skip the model planner and return deterministic cleanup plans quickly; deterministic orphan, relationship, status, and pruning checks still review the full scope. True zero-link orphan tags are merged into a useful used tag when deterministic variant/prefix/semantic checks find a strong target, otherwise they can be pruned entirely by approval; one-use candidates can be retired when they lack durable evidence; one-use canonicals can be downgraded until repeated use proves them; and singleton assignments without scoring history can be pruned by approval. Text Chunk Encoding uses the OpenAI embeddings endpoint and offers `text-embedding-3-small`, `text-embedding-3-large`, and `text-embedding-ada-002`, with `text-embedding-3-small` remaining the default. Metadata extraction may send the original PDF as file context when the file is below the configured size cap, but summary and tag suggestion calls use extracted text only. Default generated document summaries and Accessory Summaries are prompted as complete-sentence technical paragraphs written at a graduate academic level suitable for a master's-degree reader that begin with the paper's broad facts and purpose, provide key findings and concrete facts early, avoid starting sentences with prepositions, then summarize main points, ideas, methods, findings, and concepts without bold, italics, bullets, em dashes, fancy quotes, standalone headings, single-word openings, or leaked schema metadata unless the user explicitly asks for another format. Summary cleanup also strips accidental trailing `confidence` or `needs_review_reasons` blocks before storage. APA reference-list and in-text citation text are generated together. Reference-list text is generated deterministically from DOI/Crossref evidence whenever possible; `gpt-5.5` APA matching is used only when Crossref/DOI evidence is missing or ambiguous. `MEDUSA_OPENAI_COMBINE_DOCUMENT_INTELLIGENCE=true` restores the previous single structured `core_document_intelligence` Responses call for metadata, summary, APA candidate, and tag suggestions. `MEDUSA_OPENAI_PROMPT_CACHE_RETENTION=24h` configures prompt-cache retention hints keyed by document checksum for retries and Concordance reruns; Medusa hashes overlong cache keys to fit the Responses API 64-character limit and omits the retention hint when the installed OpenAI SDK does not expose that Responses parameter.

Page text normalization is local-first: `MEDUSA_OPENAI_PAGE_NORMALIZATION_MODE=auto` locally cleans normal pages and escalates only low-text or artifact-heavy pages, capped by `MEDUSA_OPENAI_PAGE_NORMALIZATION_AUTO_MAX_PAGES`. Auto mode sends page text only, not the full PDF per page. Set the mode to `always` only when you intentionally want the older all-pages OpenAI normalization behavior. Graphics are stored as cropped assets with labels/captions rather than converted into Markdown. If OpenAI is unavailable or a page-normalization request times out, Medusa falls back to local whitespace, hyphenation, and paragraph cleanup.

Reader compare mode shows authenticated rendered PDF pages and the current parsed page side by side. The compact Library detail preview renders only the focused PDF page, while expanded Reader mode gives the PDF preview, parsed text, and compare panes the available window-height frame below the document controls and tabs; PDF page previews render at 2.5x scale. The parsed page can be edited in place, saves as manual normalized text, rebuilds document search, and writes a `DocumentVersion` row with page-level before/after snapshots. The parsed-text pane repeats page navigation and Copy/Edit controls at the bottom, switching to Save/Cancel while editing. The editor tool strip includes Scrub, which removes the selected exact text from all parsed page text and shows the document-wide match count while text is highlighted. Expanded Compare mode lets full-document PDF scrolling drive page changes and keeps the text pane synchronized to the visible PDF page, while text-side scrolling only nudges the PDF within the current page so longer parsed text can be read to the bottom without auto-advancing. Scan Page runs a local page visual pass, then shows a review panel with page-map boxes, 300 DPI candidate thumbnails, individual selection, Keep selected, and Discard; keeping selected candidates is the step that replaces that page's stored figures and writes document history. Stored figure cards can be relabeled, given corrected captions/descriptions, or deleted; each correction rebuilds document search and writes history. History entries can be stepped through and restored with Restore as Current, which applies the chosen snapshot to the live searchable document while appending a new history row. Escape closes or collapses the active Medusa-owned popover, dialog, editor, composer, or expanded Reader surface, and Download Original uses Settings > Download Naming to render attachment filenames; the default template is `$title ($year)` and `.pdf` is implicit.

Raw text extraction is controlled separately in Settings. The Raw Text Extraction selector is grouped into Local options (Docling, Marker, PyMuPDF) and OpenAI model fallbacks. Settings has Save All controls at the top and bottom of the view so display, cache, runtime, accent, citation convention, and model preferences are saved together. The Preferences panel currently offers APA (7th Ed.) as the citation convention. Marker is the default preference and is installed in the backend/worker image; its model cache lives under `data/model-cache` through the Compose volume, so a first use may download local weights but later imports reuse them. PyMuPDF remains the built-in no-credential fallback when Marker is unavailable or times out.

Budget & Costs records and displays AI usage from completed and failed OpenAI Responses/embeddings calls and Gemini `generateContent` calls: provider, task, model, document/job context, token counts, cached input tokens where reported, output tokens, PDF/file context bytes, and recent errors. Dollar totals are estimates from Medusa's tracked model-pricing history using official provider token prices. OpenAI GPT usage is priced with `MEDUSA_OPENAI_PRICING_TIER` (`standard`, `batch`, `flex`, or `priority`), embeddings use their published input-token rate, and Google Gemini text usage uses Developer API paid-tier standard pricing. Unknown or unavailable models are counted as unpriced because model pricing and project access can change independently of the local app. Settings > Import Processing > Shared Model Defaults shows the active OpenAI pricing tier, when pricing was last refreshed, provides a Refresh Models & Pricing action, and warns when configured tier rows are missing or pricing is more than two days old. Refreshes update the existing active history row when prices are unchanged and add a new historical row only when a model's price changes, so usage can be costed against the price that applied when the call was recorded. Budget & Costs can group usage by model, task, document, calendar day, or calendar hour, with a cost trend line plus cost-by-model and token-by-task pie charts for the selected period.

Document Composition is available from the Library detail actions when a document is selected. Imports now write granular `DocumentCompositionRecord` rows for the staged cost estimate, second-pass local stages, synced model usage, processing warnings/errors, and manual edits. The Composition dialog shows the persisted estimate versus actual recorded model spend, a Cost Composition pie chart with dollar values, provider spend, local processing time, a React Flow pipeline chart with connected steps in import execution order, and a Processing Issues section when warnings or errors occurred. The pipeline chart includes OCR audit, page normalization, structured-table evidence, visual extraction/context, bibliography extraction, and the specific models active for downstream processing; later Concordance Runs append their capability/model-call nodes with Concordance labels. Older documents without composition rows show "not available." While imports are active, the reserved header progress control includes current known dollar spend so far.

Before broad Concordance starts, Settings estimates the selected scope and capabilities, including planned jobs, same-model no-ops, already queued work, current-version skips, unpriced routes, and estimated cloud spend. The document-level Concord button fetches the same estimate before confirmation. Concordance skips model-backed fields when document evidence or usage history shows the field already used the currently selected model, while changed model routes can still queue even if the capability version is otherwise current.

Async document work is started from the app shell, not only from the page-level component that owns the button. DOI, citation, summary, bibliography, and Concordance refresh actions immediately turn soft blue with their own icon spinning and a slim in-button progress bar, then the reserved header progress control follows active durable imports and background runs even if the user switches views. Page-local buttons still give a short green success blend or red result flash; failures also surface a concise error message.

Worker recovery:

```bash
MEDUSA_IMPORT_WORKER_CONCURRENCY=4
MEDUSA_WORKER_STALE_JOB_SECONDS=900
MEDUSA_DOCUMENT_CACHE_SIZE_MB=1024
```

Medusa defaults to four concurrent import jobs. The env var sets the startup default, and Settings lets the local user change the active preference without editing tracked files. Values above four are allowed but can generate many OpenAI calls and costs over a short period. Manual batch uploads are staged first; the worker only claims them after Process Uploads promotes staged rows into the queued pipeline.

Worker startup immediately requeues `running` import and Concordance jobs left by the previous worker process. This setting is the secondary guard for stale locks that remain while the worker is alive.

The document cache size defaults to 1,024 MB. It controls how many completed import PDFs are kept locally under `data/processing-cache` for Concordance and Accessory Summary work; originals are still written to GCS or local durable storage at upload time. Clearing staged uploads removes their managed processing-cache copies and staged original objects before deleting their queue-only records. Settings shows the current cache footprint rounded to the nearest MB. Settings > Download Naming controls suggested original-PDF download names with `$title`, `$year`, `$authors`, `$author`, and `$pages` tokens.

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

Full database backup and restore:

Use Utilities for the normal backup workflow. Backup Database shows a likely compressed size, then creates a `pg_dump` custom-format snapshot, compresses it with zstd, uploads it to the active GCS bucket under `GCS_PREFIX/backups`, and verifies the uploaded checksum. Restore Database is shown beside the GCS backup selector, requires confirmation, and restores from a listed GCS backup only; it always completes and verifies a fresh safety backup before applying the restore. Utilities also shows the count and total compressed size of all listed GCS backup dumps.

Legacy metadata JSON restore drill:

```bash
cd backend
python -m app.tools.restore_export /path/to/medusa-metadata.json
python -m app.tools.restore_export /path/to/medusa-metadata.json --apply
```

The restore command validates schema/safety flags, rejects secret-bearing keys, reports conflicts and skipped auth records, and parks restored queued/running jobs as `restored_paused` unless `--reactivate-jobs` is explicitly supplied.

## Safety Model

Imports are durable jobs stored in PostgreSQL. Manual uploads first create staged jobs that can be reviewed, added to by later batches, and released with Process Uploads; each processing step then records events and checkpoints, so stopping the app mid-import leaves work queued or resumable. Staged, queued, running, failed, cleared, and restored-paused document rows are queue/operations records only: they do not appear in Library lists, Library search, dashboard document counts, domain/tag document counts, project bibliographies, recommendations' existing-library matches, or Concordance scopes until processing finishes and the document becomes `ready`. PDF uploads are stored as-is; HTML and plain-text/Markdown uploads are parsed for source structure, converted locally into PDF mezzanine originals, and then stored through the same GCS/local paths. Upload source bytes are checksum-addressed for duplicate detection before processing.

Duplicate uploads are checked before staging. When an exact checksum match is found against a Library-visible document or an active/recoverable import row, the Import view asks whether to skip the duplicate, overwrite the matching document record, or import anyway as a separate document. Cleared/canceled queue-only rows are ignored so abandoned staged uploads do not block future imports. Library filters can also show exact checksum duplicates already in the collection.

Staged and queued upload rows show rough dollar estimates from stored page counts, the selected Import Processing preset, known model-pricing history, prior import usage exemplars by task/model when available, and prior estimate-vs-actual accuracy when Medusa has completed examples. The persisted estimate includes step-level metadata for local-only stages, pending OCR/visual-model integrations, capped page-normalization calls, shared metadata/summary/citation/tag/embedding models, and the selected preset snapshot. Import and Queue also show a rough grand total for the staged/queued upload set before processing starts.

If the worker/container stops while a job is already marked `running`, the next worker requeues it on startup and continues from the last durable checkpoint. In-flight documents may repeat the current step, and page normalization resumes from persisted page checkpoints when possible.

The Import page can release staged uploads with Process Uploads or discard all staged uploads with Clear Staged, which removes their queue-only document/job rows, managed processing-cache files, and staged original storage objects. The Import Queue can release staged uploads, retry failed imports in bulk, retry individual queued/failed/restored jobs, cancel individual staged/queued/failed/restored rows, and clear staged/queued/failed/restored rows into a terminal `cleared` state. Fresh running jobs are protected from manual retry, cancel, or clear to avoid racing an active worker.

Utilities > Database provides manual maintenance controls. Compact Database starts a visible background PostgreSQL `VACUUM (FULL, ANALYZE)` job where available, Optimize Database starts a visible background `ANALYZE` job to refresh table statistics, and Clear Import Cache removes terminal hidden import records, stale project-resource links, managed processing-cache files, and staged original objects that are already excluded from active Library and Queue surfaces. It does not clear Library-visible documents or staged/queued/running/failed/restored-paused import rows. Utilities polls maintenance status while long-running database work is active so the page shows elapsed time instead of holding a single opaque browser request. Utilities also shows container footprint stats from inside the backend runtime, including cgroup memory/CPU, process uptime, data-volume usage, path-level storage footprints, and Docker image/layer sizes when the Docker Engine socket has been deliberately mounted into the backend container. The same Container Footprint section lists runtime versions for HAProxy, Python, key backend packages, PostgreSQL client, zstd, curl, frontend Node.js, Vite, and the frontend build stamp so base-image and binary freshness are visible from the app. Below that, HAProxy Statistics reports the TLS endpoint, frontend/backend health, session totals, traffic, checks, and proxy errors from the internal HAProxy stats feed. Restart Backend terminates the backend process after the API response returns; the Compose backend service uses `restart: unless-stopped`, so Docker brings it back and the frontend polls `/api/health` until the backend is healthy again.

Release refreshes are host-agent compatible. The backend reads `data/deploy/release-status.json` and writes `data/deploy/release-request.json` when the user clicks the header `Upgrade Now` button. The server-side `scripts/medusa-release-agent.py` checks upstream git state, refuses dirty checkouts, fast-forwards only, rebuilds Compose with explicit build identity variables, and updates the status file. Template systemd units under `deploy/systemd/` can own the Compose stack and wire the release checker/apply watcher on a server such as carrot. The app itself does not run arbitrary git or Docker commands.

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

Utilities includes full database backup and restore controls. Backups are named with `YYYYMMDD-HHMMSS` plus the short hostname, compressed with zstd, uploaded to GCS, and checksum-verified after upload. The Backup Database control shows a likely backup size based on current PostgreSQL database size and the latest completed backup when available, Utilities shows the total size of all listed GCS backups, and recent backup/restore run history remains visible instead of only the newest row. Browser restore uses a selected GCS backup, asks for confirmation, is gated by a fresh verified safety backup, then applies with `pg_restore` and runs migrations. A full database restore may replace session rows, so the browser may need to sign in again afterward.

For portability, treat those PostgreSQL backups as the supported way to move the system of record between machines. Copying the repo or `data/` directory alone does not copy the Docker named database volume; direct database-directory portability requires an explicit bind mount and storage hardware suitable for PostgreSQL writes.

Utilities also keeps legacy metadata export links. The full metadata export captures research metadata, extracted text, organization state, notes, corrections, jobs, Concordance history, and a durable asset manifest. The storage manifest export lists original and derived asset URIs. These JSON exports intentionally omit API keys, service-account credentials, password hashes, and session tokens.

Metadata exports can be restored with the CLI restore tool. Restores are dry-run by default, preserve export IDs by default, skip password/session state, restore document/storage URI references, and park active job queues so a fresh worker does not unexpectedly reprocess restored history.
