# Medusa Performance Roadmap

Last updated: 2026-06-26

This document maps future performance work for Medusa as the library grows from
hundreds of documents toward 10x and 50x current corpus size. It is intentionally
measurement-first: PostgreSQL remains the system of record and the first scaling
layer until benchmarks show that a cache, pub/sub layer, external search engine,
or other component solves a measured problem more cleanly.

## Current Baseline

The current performance pass added:

- `/api/documents/list`, a bounded slim Library list endpoint with total counts,
  pagination state, and a revision token.
- Frontend Library virtualization over 500-row result windows.
- Debounced search and a short idle stale window for document list data.
- Lean secondary-workspace document list fetches that skip duplicate badges and
  project membership when they are not needed.
- PostgreSQL full-text search over title, search text, APA reference text, and
  APA in-text citation, with title fallback matching.
- Persisted duplicate summary fields on `Document` so normal list reads do not
  recompute the duplicate graph.
- Batched dashboard/domain/tag counts in several hot paths.
- Request timing headers and slow API logging for `/api/*`.

Those changes address the first wave of slowdown: oversized payloads, repeated
enrichment, frontend over-rendering, and missing query shape separation.

## Guiding Principles

- Measure before caching. Add a cache only after knowing the endpoint, query,
  payload, render, or provider call that is hot.
- Prefer bounded responses. No workspace should need the whole corpus unless the
  user explicitly starts an export, broad maintenance task, or Concordance run.
- Keep PostgreSQL authoritative. Derived caches and read models can make reads
  cheap, but the canonical metadata, jobs, evidence, and corrections remain in
  PostgreSQL.
- Use read models for stable derived facts. Counts, snippets, duplicate labels,
  search vectors, and row display fields are good candidates when they are
  expensive to rebuild on every request.
- Preserve local/no-credential fallback. Any optional Valkey, external search,
  or provider cache should degrade to PostgreSQL-backed behavior.
- Keep correctness visible. Stale counts, hidden staged imports, soft-deleted
  documents, duplicate false positives, and user-corrected metadata are all
  product correctness issues, not just implementation details.

## Measurement Plan

Before adding major performance machinery, create repeatable measurements.

### Scale fixtures

Build or seed representative fixtures for:

- 1x: current live corpus shape.
- 10x: enough documents, pages, tags, domains, projects, notes, figures,
  recommendations, usage rows, and processing events to stress ordinary use.
- 50x: a heavier stress fixture with realistic skew, including a few very large
  documents, many singleton/low-use tags, deep domains, large projects, and
  older job/event history.

Fixture data should preserve Medusa's visibility rules:

- Ready documents are visible in Library, search, domains, tags, projects,
  recommendations, and Concordance scopes.
- Staged, queued, running, failed, cleared, and restored-paused import rows stay
  out of those Library/research surfaces.
- Soft-deleted documents and notes remain excluded from active surfaces.

### Endpoint probes

Capture p50, p95, p99, response bytes, SQL count, SQL time, total request time,
and error rate for at least:

- `/api/dashboard`
- `/api/documents/list` with no filters
- `/api/documents/list` with text search
- `/api/documents/list` with domain, tag, read, priority, citation, and duplicate filters
- `/api/documents/{id}`
- `/api/domains`
- `/api/tags`
- `/api/projects`
- `/api/notes`
- `/api/review`
- `/api/imports/jobs`
- `/api/concordance/runs` and `/api/concordance/jobs`
- `/api/documents/duplicates/scan`
- `/api/documents/{id}/recommendations`
- PDF page image and original-PDF preview routes

### Database evidence

For slow endpoints, save:

- `EXPLAIN (ANALYZE, BUFFERS)` for the main query shapes.
- Row estimates versus actual rows.
- Whether indexes are used or bypassed.
- Sort/hash memory behavior.
- Top queries from `pg_stat_statements` once enabled.
- Autovacuum/analyze timing for large import runs.

### Frontend evidence

Capture:

- React render time for Library list, detail pane, Related modal, Projects,
  Domains, Tags, Finances, and Composition.
- Bundle chunk size and first-load cost.
- Main-thread time while scrolling Library and opening document detail.
- Network payload sizes per workspace.
- Whether background refetches produce visible layout shifts.

## Performance Budgets

Use these as starting targets on the 10x fixture, then adjust with real hardware
measurements:

- Dashboard: under 100 ms backend time when idle.
- Library list, no search: under 150 ms backend time, under 250 ms total local
  request time.
- Library list, text search: under 300 ms backend time for common terms.
- Domain/tag/project inventory: under 250 ms backend time.
- Document detail open: under 300 ms backend time excluding PDF page rendering.
- Library scroll: no visible row jank on ordinary desktop hardware.
- Active-work polling: cheap enough to run during imports without competing
  with worker writes.

The 50x fixture can have looser interactive budgets, but the UI should still
stay bounded, nonblocking, and honest about progress.

## Near-Term Fixes

These are the next likely high-yield changes that do not require a new service.

### Keyset pagination for Library

Offset pagination is acceptable for the first bounded list, but deep offsets get
more expensive as the corpus grows. Add cursor pagination for stable sorts:

- Title sort cursor: `title_sort`, `title`, `id`.
- Search rank cursor: rank, title sort, `id`.
- Updated-time cursor for future recent-work views.

Keep offset support only for compatibility or shallow page controls. The UI can
still show "Browsing 501-1000 of N" while using a cursor internally.

### Smaller row payloads

Library rows still include enough content to render summaries and chips. Future
payload trimming options:

- Store and return a precomputed plain-text `summary_excerpt`.
- Return tag/domain/project display names only where row rendering needs them.
- Fetch rich Markdown summaries only in detail, Reader, Related, or explicit
  preview expansion.
- Keep row author display as a precomputed short string while preserving full
  structured authors in document detail.

### Conditional requests and cache validators

Use the `revision` token from `/api/documents/list` more fully:

- Add ETag or `If-None-Match` behavior for list windows.
- Return `304 Not Modified` for unchanged list pages.
- Carry separate revisions for list membership, list row display fields, and
  detail-only fields when useful.

### Fine-grained frontend invalidation

Current invalidations are intentionally safe. Tighten them over time:

- Patch cached list rows after title, priority, read status, citation status,
  no-DOI, tag, domain, project, and trash operations when the changed document is
  already in the cached window.
- Invalidate totals only when a change affects membership or counts.
- Avoid invalidating every document-family query when only detail-only evidence
  changed.
- Cancel stale search requests when the user types a newer query.

### Route-level code splitting

The frontend build now warns near the large-chunk threshold. Split heavy surfaces
behind dynamic imports:

- Composition and React Flow.
- Finances charts.
- Settings model/pricing panels.
- Related modal.
- PDF/Reader helpers if separable.

The goal is faster initial Library load without reducing the rich workbench
experience once a user opens a heavy surface.

## PostgreSQL And Data-Model Enhancements

### Stored search vector

The current GIN expression index should be replaced or supplemented with a
stored/search-maintained vector when benchmarking shows value:

- `Document.search_vector` with weighted title, authors, year, DOI, tags,
  domains, APA citation, bibliography, notes, annotations, figures, and body
  text.
- Higher weights for title, DOI, authors, tags, and domains.
- Lower weights for long body text.
- Rebuild through import, document edits, tag/domain changes, notes, annotation
  changes, figure edits, and Concordance search-index capability.

This makes ranking and snippets more predictable and keeps query expressions
simple.

### Search read model

If `Document` becomes too wide or too join-heavy, introduce a
`DocumentSearchRecord` or equivalent read model:

- One row per Library-visible document.
- Contains document id, visibility status, title sort key, weighted search
  vector, snippet source text, filter columns, and display excerpts.
- Updated by import completion, document edits, organization changes, notes,
  annotations, figure updates, and Concordance runs.
- Querying this table returns IDs and rank first; detail rows are fetched only
  for the requested page.

This keeps search independent from rich document detail loading.

### Aggregate read models

For 10x and 50x scale, repeated count queries may dominate workspaces. Consider:

- `DomainDocumentStats`: direct count and subtree count for active Library
  documents.
- `TagDocumentStats`: active document count, candidate/canonical breakdown, and
  stale assessment counts.
- `ProjectDocumentStats`: item count, used count, status breakdown.
- `LibraryHealthStats`: missing DOI, unverified citation, no summary, no tags,
  no domains, missing figures, stale capabilities.

Update these through explicit write paths and repair them through a maintenance
action that recomputes from canonical rows.

### Index review candidates

Benchmark before adding, but likely candidates include:

- Partial title sort index for Library-visible documents.
- Composite partial indexes for common filters:
  `read_status`, `priority`, `citation_status`, `duplicate_count`, and title
  sort under the Library-visible predicate.
- Reverse and composite join indexes for `document_tags`, `document_domains`,
  `ProjectItem`, notes, and annotations.
- GIN indexes for JSONB only where queries actually filter JSONB evidence.
- Time indexes for append-only event/history tables used by recent-work views.

Avoid speculative indexes on every column; each index slows writes and imports.

### Append-only table management

As imports and Concordance runs accumulate, append-heavy tables can outgrow
interactive needs:

- `ProcessingEvent`
- `OpenAIUsageRecord`
- `DocumentCompositionRecord`
- `BackupRun`
- `DocumentVersion`
- `DocumentTagAssessment`

Future options:

- Recent-window indexes for UI views.
- Archive/cold filters in default endpoints.
- Time partitioning for high-volume event or usage tables.
- Summaries for dashboard and status surfaces.

Do not partition early unless benchmarks show table size or vacuum cost is a
real bottleneck.

### Database maintenance and statistics

Keep building around PostgreSQL health:

- Enable and expose `pg_stat_statements` if acceptable for the local runtime.
- Add a Utilities panel for top slow queries, rows scanned, and last analyze.
- Run `ANALYZE` after large imports and large tag/domain maintenance jobs.
- Tune autovacuum thresholds for append-heavy tables if dead tuples accumulate.
- Track database size by table and index in Utilities.
- Consider PgBouncer only if connection churn or multi-process scaling becomes
  measurable.

## Frontend Enhancements

### Library UX under pagination

The current page model is safe, but bulk workflows need careful semantics:

- Make "select visible page" distinct from future "select all matching results."
- If "select all matching" is added, execute bulk operations server-side against
  a saved filter/search token, not by loading all rows into the browser.
- Preserve selected document focus across page changes when possible.
- Prefetch the next/previous page after the current page settles.

### Avoid row-level Markdown cost

Markdown rendering in every visible row is richer than a plain excerpt. If row
render time shows up in profiling:

- Return a sanitized text excerpt for list rows.
- Reserve Markdown rendering for detail, Reader, summaries, citations, and
  expanded previews.
- Keep row height stable even when excerpts are missing or short.

### Browser-side performance marks

Add lightweight measurements for:

- Search input to list response displayed.
- List response received to rows painted.
- Document click to detail displayed.
- Related modal open to first content displayed.
- Settings/Finances/Composition first open time.

These can remain console/dev-only initially, then graduate into a local
debug/status panel.

## Worker And Processing Throughput

### Worker backpressure

Import concurrency is configurable, but future tuning should consider:

- Active database write pressure.
- CPU-heavy extraction/rendering load.
- Provider rate limits and timeouts.
- Disk/cache pressure.
- Current foreground API latency.

The worker can eventually reduce or increase slots dynamically rather than
using a fixed integer in all conditions.

### Batch writes

Profile import paths for per-row commits or repeated refreshes:

- Batch insert pages, chunks, figures, processing events, and composition rows
  where safe.
- Keep checkpoints durable, but avoid committing every tiny local sub-step when
  a batch transaction is safe.
- Use bulk updates for Concordance search-index rebuilds.

### Progress summaries

The UI should not have to scan large event lists to know progress:

- Keep per-job progress fields current on `ImportJob` and `ConcordanceJob`.
- Store compact batch/run progress summaries.
- Use events for audit detail, not as the primary polling source.

## Related, Stashes, And Provider Work

Related-paper discovery can become expensive at scale because it combines local
context with external provider calls. Future fixes:

- Cache provider lookup results by DOI, normalized title, OpenAlex ID, Semantic
  Scholar ID, Crossref DOI, and query string with evidence timestamps.
- Add provider cooldown/rate-limit state so repeated refreshes do not hammer a
  failing provider.
- Make recommendation downloads durable background jobs before fetching PDFs.
- Add a recommendation read model for sorted display rows and known-item status.
- Recompute already-known matching from normalized DOI/title evidence through a
  bounded local query instead of scanning all recommendation rows.
- Add provider-failure visibility in Settings or Activity.

Valkey could help provider cooldowns and short-lived rate-limit counters later,
but provider evidence and cached bibliographic metadata should remain in
PostgreSQL.

## Asset And PDF Performance

PDF preview and visual assets have different bottlenecks from metadata search:

- Cache rendered page images by document id, page, render scale, source object
  version, and theme-independent parameters.
- Return cache validators for page images and figure thumbnails.
- Generate smaller thumbnails for list/card surfaces instead of serving full
  figure crops everywhere.
- Keep original PDF streaming authenticated and avoid public GCS objects.
- Consider background pre-rendering for the first page of newly imported
  documents if PDF preview startup becomes noticeable.

## Valkey Decision Notes

Valkey is a good candidate when the bottleneck is ephemeral, shared across
processes, frequently invalidated, or naturally pub/sub. It is not a replacement
for Medusa's durable database.

Good Valkey candidates:

- Active-work pub/sub so browser sessions can receive import, Concordance,
  backup, and future Activity updates without polling.
- Short-lived hot aggregate caches for dashboard/domain/tag/project counts after
  benchmarks show PostgreSQL count queries dominate.
- Provider rate-limit and cooldown counters.
- Distributed locks and request coalescing for expensive refreshes, such as
  "only one Related refresh for this document at a time."
- Read-through caches for expensive, stable, small payloads such as model option
  catalogs, provider metadata lookups, or status summaries.
- Debounce/invalidation channels when multiple backend or worker processes run.

Poor Valkey candidates:

- System-of-record metadata, jobs, correction history, evidence, or auth state.
- Primary full-text search index.
- Large document/page text blobs.
- Long-lived recommendation evidence that must survive restarts and backups.
- Whole Library result pages whose invalidation would be complex and fragile.
- Anything that must be restored from a PostgreSQL backup.

Adoption criteria:

- A benchmark names the endpoint or operation that is too slow.
- PostgreSQL query shape, indexes, read models, and payload trimming have been
  tried or rejected with evidence.
- Cache invalidation rules are clear and testable.
- The app still boots and works without Valkey.
- Backups do not need Valkey data for correctness.
- Metrics show hit rate, miss cost, memory use, eviction, and stale-read risk.

Implementation shape if adopted:

- Add a `valkey` Compose service and optional `VALKEY_URL`.
- Keep a no-Valkey fallback path.
- Prefix keys by environment and schema/cache version.
- Use short TTLs unless invalidation is proven.
- Centralize cache key construction and invalidation.
- Expose cache status in Utilities.
- Clear or version caches on migrations that affect cached payloads.

## External Search Engine Decision Notes

An external search engine is a larger move than Valkey. Consider it only if
PostgreSQL FTS cannot satisfy quality or latency requirements after stored
vectors, weighted ranking, snippets, and read-model separation.

Possible triggers:

- Need typo-tolerant, faceted, interactive search across tens or hundreds of
  thousands of documents and many millions of chunks.
- Need richer snippets/highlighting than PostgreSQL can provide comfortably.
- Need separate indexing of figure gists, table cells, notes, recommendations,
  and chunks with mixed ranking models.

PostgreSQL should remain authoritative even if an external search index is
introduced. Reindexing must be Concordance-compatible and repairable from the
database.

## Prioritized Roadmap

### Phase 0: Measure and guard

- Add a benchmark seed/probe script for 1x, 10x, and 50x fixtures.
- Enable or document `pg_stat_statements` for local performance diagnosis.
- Record endpoint timing snapshots before each major optimization.
- Add frontend performance marks for Library search, row paint, and detail open.
- Add regression checks for hidden import rows staying out of Library/search.

### Phase 1: Keep the current architecture fast

- Add keyset pagination for `/api/documents/list`.
- Add precomputed row excerpts and author display strings.
- Add conditional request support for list windows.
- Split heavy frontend chunks.
- Tighten React Query invalidation after common document mutations.
- Review and add only benchmark-backed indexes.

### Phase 2: Read models and aggregate tables

- Add stored search vector or a dedicated document search read model.
- Add aggregate stats tables for domain, tag, project, and Library health
  counts.
- Add repair/rebuild actions for read models.
- Add recent-window summaries for append-only event and usage surfaces.

### Phase 3: Optional Valkey

- Add Valkey only for a measured workload with clear invalidation and fallback.
- Start with pub/sub or provider cooldowns before caching core Library results.
- Add Utilities cache status and metrics.
- Keep every cache disposable.

### Phase 4: Larger search evolution

- Reassess PostgreSQL FTS quality and latency at 50x.
- Add semantic search over chunks/assets when the embedding strategy is chosen.
- Consider an external search index only if PostgreSQL plus read models no
  longer meets quality or latency goals.

## Verification Checklist For Performance Changes

Every meaningful performance change should include the narrowest relevant set:

- Baseline and after timings for affected endpoints.
- SQL count and SQL time comparison.
- Payload size comparison when API shape changes.
- `EXPLAIN (ANALYZE, BUFFERS)` for query/index changes.
- Backend tests for visibility, filtering, counts, and stale-cache safety.
- Frontend build for API/type changes.
- Live health check after runtime changes.
- Architecture/TODO updates when the change affects API contracts, persistence,
  runtime services, or performance strategy.
