# Medusa TODO

Last updated: 2026-06-23

This is the planned-work ledger for Medusa. Keep this file focused on work that is not done yet. Architectural rationale belongs in `docs/ARCHITECTURE.md`; this file is for actionable backlog items and acceptance notes.

## Highest Priority

- [ ] Implement exhaustive DOI/source-link resolution for APA citations.
  - Acceptance: build on the current DOI regex plus Crossref DOI/title/author/year baseline by searching document metadata, extracted text, references, Semantic Scholar, DOI.org, publisher pages, and targeted web evidence to locate a DOI whenever one exists; APA output favors DOI links; when no DOI can be verified, APA output uses the best direct stable source link, preferably a PDF or other static document; all evidence, attempted sources, conflicts, and confidence are recorded for Queue inspection.

- [ ] Add real low-text OCR fallback with Google Vision.
  - Acceptance: low-text/scanned PDF pages are detected, OCR is run only when needed, OCR text is stored per page, and processing remains resumable.

- [ ] Add robust citation verification beyond current Crossref basics.
  - Acceptance: DOI, Crossref, Semantic Scholar, DOI.org, publisher, PDF/static-source, and web evidence can be compared field by field; uncertain conflicts create Queue candidates instead of overwriting trusted metadata.

- [ ] Add richer citation review evidence UI.
  - Acceptance: Queue shows source evidence side by side, supports partial field-level acceptance, and records which source supplied each accepted field.

## Document Processing And Intelligence

- [ ] Implement second-pass import processing on `codex/second-pass-document-processing`.
  - Acceptance: `docs/SECOND_PASS_DOCUMENT_PROCESSING.md`, `docs/ARCHITECTURE.md`, and this TODO ledger are committed before runtime code begins; the branch keeps second-pass work isolated; built-in Balanced/Strict Local/Deep Review presets exist; an emergency disable path can return imports to the current pipeline; final verification includes backend tests, frontend build, and app health.

- [x] Add Settings Import Processing presets and step controls.
  - Acceptance: Settings has an Import Processing section with every import step, enabled state where applicable, model/provider controls where applicable, core parameters, sensible defaults, and tooltips explaining exactly what happens and what each step accomplishes; built-in presets are read-only but duplicable; user presets can be created, renamed, duplicated, edited, deleted, and set as default; Save All persists presets, default preset, caps, thresholds, OCR settings, cleanup toggles, and visual settings.

- [ ] Add Import preset selection and durable preset snapshotting.
  - Acceptance: Import has a compact Processing preset selector in batch defaults; Balanced is selected by default from Settings; staged batches/jobs store the selected preset id and preset snapshot; later Settings edits do not affect already-staged work; staged/processing rows and Composition show which preset was used.
  - Partial: Import has the Processing preset selector, uses the Settings default, snapshots the selected preset onto batch/job/document evidence, shows preset names in staged/processing rows, and persists preset-aware step-level cost estimate metadata for staged jobs. Remaining work is an explicit Composition display for the preset snapshot and stronger tests around later Settings edits not changing already-staged jobs.

- [ ] Add deterministic document structure cleanup.
  - Acceptance: imports and Concordance can remove or normalize repeated headers/footers, page numbers, watermarks, decorative text art, front matter noise, excess whitespace, broken line wraps, hyphenation, bullets, and drop-cap styling artifacts while preserving headings, captions, citations, equations, lists, tables, and body text; removed text is kept as evidence but excluded from reader/search/enrichment body text; manual page edits are not silently overwritten.
  - Partial: import and Concordance run deterministic cleanup, preserve removed boilerplate evidence, protect manual page text during Concordance, and feed cleaned text into normalization/search. Remaining work is broader fixture coverage and stronger handling for body-boundary detection, hyphenation, watermarks, and edge-case scholarly layouts.

- [x] Extract source-document bibliographies into a dedicated field.
  - Acceptance: imports and Concordance detect references, bibliography, or works-cited sections; `Document.bibliography` stores the extracted reference list separately from generated APA citation text and project bibliographies; Markdown-compatible italics are preserved when PDF span metadata exposes emphasis; document detail displays and allows editing the Bibliography field; search, export, restore, and history include it.

- [ ] Add structured table extraction and persistence.
  - Acceptance: table rows/cells/captions/page regions are stored as structured data; Markdown table text remains searchable; tables can link to nearby headings, captions, and explicit `Table N` mentions; imports and Concordance are idempotent and retry-safe.
  - Partial: cleanup records table-like blocks in metadata evidence and the Settings flow reflects that this is evidence-only today. Remaining work is first-class table rows/cells/captions/page-region persistence and table-context linking.

- [ ] Add multi-pass visual asset extraction and coverage audit.
  - Acceptance: embedded images, displayed image regions, vector charts/plots/diagrams, photos, maps, full-page scans, and table regions are detected; crops include complete axes, legends, labels, and visual bounds when possible; duplicate/overlapping crops are reconciled; page rotation/orientation is preserved or corrected; every meaningful visual region is either extracted or flagged with an audit warning.
  - Partial: local extraction covers embedded images, page image regions, and vector drawing clusters with captions, orientation metadata, durable assets, and a basic no-assets-found warning. Remaining work is robust full-page scan/table-region coverage, duplicate/incomplete crop audit, complete axes/legend expansion, and missed-region warnings.

- [ ] Add visual asset context and affordable visual model routing.
  - Acceptance: figures/tables link to captions, nearby headings, surrounding paragraphs, and explicit mentions such as `Figure 2`; searchable gists come from captions/local context first; cropped-region model calls use cheaper OpenAI/Google models when local context is insufficient; premium visual/document analysis requires Deep Review or explicit Concordance scope; every cloud call records provider/model/task/tokens/file bytes/status/duration/cost.
  - Partial: local figure context links captions, nearby text, and explicit figure mentions; Settings stores visual model-routing preferences; staged import estimates mark visual model routes as pending rather than charging for calls that do not yet run. Remaining work is cropped-region model calls, visual gists beyond local context, premium gating enforcement, and usage/cost records for visual model calls.

- [ ] Wire second-pass capabilities into Concordance.
  - Acceptance: `document_structure_cleanup`, `bibliography_extraction`, `visual_asset_extraction`, `visual_asset_context`, `structured_tables`, and `ocr_fallback` are versioned Concordance capabilities; old documents can be upgraded without re-upload; jobs are durable, resumable, idempotent, and visible through events/progress; manual page text is skipped or turned into reviewable candidates unless explicit replacement is requested.
  - Partial: the listed capabilities exist and route to current cleanup, bibliography, visual extraction, visual context, structured-table evidence, and OCR eligibility audit handlers. Concordance now estimates scoped run cost before queuing, reports planned/same-model no-op/current/already-queued work, and skips model-backed fields when document evidence or usage history already matches the selected model. Remaining work is real OCR execution, first-class structured-table persistence, stronger idempotency tests for visual/table runs, and broader progress/evidence UI for each capability.

- [ ] Design and implement Recon for corpus-grounded research inquiries.
  - Acceptance: add a Recon workspace between Projects and Tags; inquiries store scope, question/instructions, selected model, run mode, run history, answers, evidence, usage, and cost; scopes support whole library, domains, projects, saved searches/views, and eventually selected documents; the Start Research action uses Medusa's durable async progress convention with cost/time preview; Quick Answer uses retrieval over the selected corpus, Broad Sweep inspects every scoped document at least lightly, and Exhaustive is an explicit deep mode rather than the default; answers cite exact document/page/chunk evidence and can be re-run when the question, model, scope, or corpus changes. Planning notes live in `docs/RECON.md`.

- [ ] Evaluate alternate core document-intelligence providers and cheaper GPT models.
  - Acceptance: representative already-processed papers are compared side by side across the current routed GPT baseline, cheaper GPT options, Gemini, and Claude for metadata, summary, APA fallback, and tag suggestions; quality gaps, failure modes, latency, and recorded cost are documented before changing defaults.

- [ ] Extend provider abstraction beyond OpenAI/Gemini.
  - Acceptance: Anthropic and local-model calls can be configured without committing credentials; every cloud call records provider, endpoint, model, task, token/file context where available, status, latency, and errors; Budget & Costs distinguishes provider costs and marks unknown pricing explicitly.

- [ ] Add discounted async processing for non-urgent Concordance refreshes.
  - Acceptance: large library refreshes can opt into discounted batch/flex-style provider modes where available, remain resumable through durable Concordance jobs, and clearly show delayed completion expectations before the run starts.

- [ ] Wire Docling and OpenAI raw extraction fallbacks.
  - Acceptance: Docling can be installed for the worker without requiring cloud credentials; the Raw Text Extraction Settings preference selects Docling, PyMuPDF, or an OpenAI fallback intentionally; unavailable local extractors record a clear processing event and fall back safely; imports and Concordance extraction refreshes both honor the selected engine without breaking page-level reader state.

- [ ] Integrate a local scholarly parser such as GROBID.
  - Acceptance: title, authors, affiliations, abstract, references, and section metadata can be extracted when available and stored with evidence.

- [ ] Add AI figure caption and gist enrichment.
  - Acceptance: extracted figure assets get AI-enriched captions/gists, confidence/evidence, and searchable text without overwriting imported labels/captions or user edits.

- [ ] Extend Accessory Summaries beyond current-document runs.
  - Acceptance: the current Library detail Accessory Summary flow can also run one prompt against selected documents, saved searches, or Concordance scopes, with durable per-document summary rows and the same Settings-selected default model behavior.

- [ ] Add richer table geometry and layout rendering.
  - Acceptance: table rows/cells/captions/page regions are stored as structured data, figure geometry can be rendered inline with parsed pages, and source regions can support future overlays/evidence views.

- [ ] Model richer table objects.
  - Acceptance: table rows/cells/captions/page regions are stored as structured data, while Markdown table text remains searchable.

- [ ] Add richer extraction fixtures.
  - Acceptance: tests cover two-column PDFs, multi-page tables, table-heavy papers, front matter before articles, scanned pages, vector charts/photos, bad metadata, obfuscated author emails, duplicates, and multi-author papers.

- [ ] Add richer HTML import rendering and asset capture.
  - Acceptance: HTML imports can optionally preserve local/remote images, useful CSS layout cues, tables, and source URLs in the generated PDF mezzanine and extraction evidence without weakening the current text-first, no-credential fallback.

- [ ] Add semantic search and embedding refresh as a fuller Concordance capability.
  - Acceptance: embeddings are generated or refreshed for chunks/assets when configured, and search can combine lexical and semantic matches.

- [ ] Evaluate local text chunk encoding before replacing OpenAI embeddings.
  - Acceptance: BGE-M3 or a comparable local embedding model is benchmarked against the current OpenAI embedding path on Medusa search queries; vector dimensions, runtime footprint, indexing speed, retrieval quality, and Concordance reindex behavior are documented before changing the default.

- [ ] Add image/figure gist search surfaces.
  - Acceptance: figure gists, captions, and image-derived descriptions participate in full-text and semantic search.

## Activity, Notes, And Research Workflows

- [ ] Add a unified Activity and Work Ledger.
  - Acceptance: Activity gives one durable, searchable place to inspect imports, Concordance Runs, citation refreshes, Accessory Summaries, recommendation fetches/downloads, backups/restores, OCR, embeddings, future Recon runs, and maintenance jobs; rows use common status language for staged, queued, running, paused, blocked, failed, retryable, complete, and cleared work; lanes or filters distinguish interactive work, imports, maintenance, cloud/model work, backups, and research runs; row actions support retry, pause/resume where safe, cancel, open result/source, and inspect details; each detail view shows processing events, model/provider calls, warnings, errors, retries, duration, rough/known cost, and next available action without weakening Queue's import/review workflows.

- [ ] Fully build out Notes for documents, topics, and ideas.
  - Acceptance: Notes supports standalone notes for topics, concepts, questions, ideas, and thesis/research thinking as well as notes attached to one or more documents; a note can link to documents, pages, annotations, figures, tables, projects, domains, tags, citations, or saved searches without requiring a document link; notes have title, body, type, status, optional due/reminder fields, and project/domain/tag organization; document detail shows linked notes and can create/link notes in context; the Notes workspace supports search, filters, backlinks, link management, soft delete/restore, and export/restore coverage; document-linked notes continue to contribute to document search while standalone topic/idea notes are searchable from Notes and global search.

- [ ] Add a Corpus Health dashboard.
  - Acceptance: Corpus Health summarizes documents missing DOI/source links, verified citation, authors/year/pages, summary, tags, domains, projects, OCR, figures/tables, embeddings, or current capability versions; it groups failed, partial, stale, and low-confidence processing states by cause; it surfaces tag/domain/project hygiene issues; each issue opens the relevant filtered Library, Queue, Tags, Settings, or Concordance action; broad repair actions provide scope, time, and cost previews before queuing work.

## Reader And Annotation Experience

- [ ] Add geometric PDF highlight overlays.
  - Acceptance: highlights can be created from selected PDF text/regions, persisted in `Annotation.geometry`, rendered on the page, and searched by body text.

- [ ] Add a more capable PDF reader.
  - Acceptance: page navigation, zoom, search-within-document, page thumbnails, and stable annotation overlays work inside the document pane.

- [ ] Redesign Library detail annotation creation.
  - Acceptance: the inline annotation composer stays out of the Library summary/detail flow until annotation capture has a quieter pane-aware UI for page, kind, color, note body, and eventual geometry selection.

- [ ] Add annotation editing.
  - Acceptance: existing annotations can be edited in place, not just created or deleted.

- [ ] Add reminder workflow for annotation/reminder kinds.
  - Acceptance: reminder annotations surface in Notes/Review or a reminder view with due dates.

## Library Organization And Search

- [ ] Add tag Delete workflow.
  - Acceptance: Tags view can delete unused or selected tags only after confirmation, safely remove document links when requested, and record any document tag changes in `DocumentVersion` history.
  - Partial: Optimize now uses the same Settings-selected Tag Suggestions model as import tag creation plus deeper deterministic governance analysis to produce larger reviewable merge, orphaned-tag cleanup, relationship, status, and pruning plans. Broad scopes cap the LLM call to a ranked high-yield subset while deterministic cleanup still reviews the full scope. Approved merges and document-assignment pruning run through audited document-history paths; true zero-link orphan tags can be alias-merged into useful used tags or pruned entirely through a guarded approval path. The plan pane can approve individual suggestions or batch-approve all current suggestions while showing top progress feedback during plan generation and bulk apply, and reporting stale skipped actions.

- [x] Normalize tag suggestion and display behavior.
  - Acceptance: tag dropdowns and lists render alphabetically by default; any non-alphabetical display order is an explicit, view-specific choice; import and Concordance tag extraction splits overly verbose compound phrases into useful primitives, such as `insider threat assessment` into `insider threat` and `threat assessment`, and `access control and cyber identity` into `access control` and `cyber identity`; deduplication clusters near-duplicates and favors primitive tags such as `access control` while still allowing meaningfully distinct specific variants such as `access control lists` or `access control monitoring`.
  - Completed: Tags are now user-facing flat labels; legacy keyword/topic kind values are normalized to `tag`, the Settings task is labeled Tag Suggestions, the Tags view no longer exposes a kind column, the Tags table supports shift-click range selection across visible sorted/filtered rows, merged tag names are remembered as aliases, tag prompts prefer an existing-tag manifest, import and Concordance run tag candidates through existing-first/not-existing-only three-axis governance scoring, import tag attachment is capped at five total tags and one brand-new candidate tag per document, low-value and near-existing candidates are recorded without creating new labels, strong new concepts become candidate tags only after stricter relevance/novelty scoring, semantic covered-by checks reduce duplicate creation, Optimize honors the same Tag Suggestions model preference used for import tag creation, can flag zero-use and singleton tags for larger merge/status cleanup, orphan pruning, or assignment pruning plans even when no model merge candidate exists, Optimize supports batch approval of all current suggestions with visible in-pane progress while the bulk request runs, broad `summary_topics` Concordance tag updates remain additive, and document-level Tag Refresh can explicitly replace a document's tag assignments through the import-style governance scorer. The original method notes live in `docs/TAG_GOVERNANCE.md`.

- [ ] Expand Related Documents into a diverse discovery and acquisition workflow.
  - Acceptance: Related hides library-held, active-import, staged-import, and already-stashed candidates from the main list by default while preserving an Already Known audit view; duplicate suppression uses DOI equality first and strong normalized-title/year/author evidence second; results are grouped or filterable by relation family such as closest, newer, foundational, methods, contrasting, open PDF, reference material, and diverse set; ranking balances relevance with diversity across authors, years, venues, methods, source types, domains, and relation types; evidence records preserve provider, relation, DOI/source URL, matched references, abstract snippets, open-PDF evidence, and duplicate-suppression reason; refreshes can run on a schedule or Concordance scope; source/provider failures are visible in Settings or Activity; open-PDF downloads run as durable background jobs; useful non-open recommendations can be moved into an acquisition wishlist without pretending a PDF is available.
  - Partial: recommendation refresh now enriches OpenAlex/Semantic Scholar/Crossref candidates with Unpaywall and arXiv open-PDF availability, resets previously failed candidates when a refreshed match is seen, exposes manual Google Scholar search links, and renders the Library detail overlay as a Discover / Already Known / All workflow. Discover hides library-held, active-import, queued-import, and DOI-wishlisted rows by default; Already Known shows the suppression reason. Rows carry relation-family metadata, reason chips, evidence payloads, diversity scores, and known status in `raw_metadata.recommendations_v2`; filters cover diverse, closest, newer, foundational, methods, contrasting, open PDF, and reference material; default ranking balances relevance with diversity across authors, years, venues, providers, and relation families; DOI Stashes now serve as the acquisition wishlist action from recommendations. Remaining work is scheduled/Concordance-scope refreshes, a centralized Settings/Activity provider-failure surface beyond processing-event payloads, durable background download jobs before PDF fetch, and project/domain-aware expansion.

- [ ] Add arbitrary-filter Concordance scopes.
  - Acceptance: Concordance can run against the current filtered result set, not only whole library, document, domain, project, search text, or saved search.

- [ ] Add richer multi-condition filter builder.
  - Acceptance: saved searches can combine text, tags, domains, citation status, read status, priority, attributes, dates, and processing state.

- [ ] Add saved-search management improvements.
  - Acceptance: saved searches can be renamed, reordered, edited, duplicated, and used as durable library views.

- [x] Add domain tree management.
  - Acceptance: domains can be nested, reordered, renamed, moved, colored, and soft-deleted from the UI.

- [ ] Add document-level BibTeX/RIS/CSL JSON copy/export controls.
  - Acceptance: individual document detail exposes citation formats beyond APA, matching project bibliography formatting.

- [ ] Add citation conventions beyond APA 7.
  - Acceptance: Settings > Preferences expands the persisted citation convention radio group beyond the current APA (7th Ed.) option; document citation refreshes, project bibliographies, exports, and copy controls all honor the selected convention; Concordance can refresh older generated citation text when the convention changes.

- [ ] Add optional Zotero import/export.
  - Acceptance: Zotero libraries can be imported/exported through the citation model without weakening Medusa metadata evidence.

## Projects And Run Sheets

- [ ] Add project detail editing.
  - Acceptance: project name, description, due date, and status can be edited in the UI.

- [ ] Add project resource sorting and filtering.
  - Acceptance: run-sheet rows can be filtered by used/status/priority and sorted by title, priority, status, or added date.

- [ ] Let project resources be categorized into Domains.
  - Acceptance: items in a project run sheet can be assigned to existing Domains from the project workspace, those domain assignments are persisted on the underlying library documents, and project resource rows can be grouped or filtered by Domain.

- [ ] Add bibliography file exports.
  - Acceptance: APA/BibTeX/RIS/CSL JSON outputs can be downloaded as files, not only copied from the UI.

- [ ] Add project-level notes and milestones.
  - Acceptance: project notes and milestone/reminder items appear in the project workspace and metadata export.

## Metadata Correction And History

- [ ] Add fuller metadata correction history/diff viewer.
  - Acceptance: `DocumentVersion` snapshots can be compared field by field in the UI.

- [ ] Add imported metadata conflict review.
  - Acceptance: conflicting import/AI/Crossref/user metadata candidates are visible and can be accepted field by field.

- [ ] Add metadata correction provenance.
  - Acceptance: the app distinguishes user edits, importer output, AI output, citation verifier output, and Concordance updates.

## Operations, Safety, And Portability

- [x] Add staged upload processing with rough cost preview.
  - Acceptance: batch uploads create durable staged import jobs that can be added to across drops; staged/unfinished document rows stay queue-only and are excluded from Library lists/search, dashboard document counts, tag/domain counts, project bibliographies, recommendation existing-library matches, and Concordance scopes until processing completes; Import and Queue show rough per-row and grand-total dollar estimates from page count, prior usage exemplars, and prior estimate-vs-actual calibration when available; Process Uploads releases staged jobs to the worker queue; Import Clear Staged hard-deletes staged-only upload records and removes their managed cache/original files before processing; cancel/clear can park other queue rows before processing; Composition persists the original per-document estimate and compares it to actual import spend; the worker runs PostgreSQL `VACUUM (ANALYZE)` after a released import queue drains.

- [x] Add browser-based full database backup and restore controls.
  - Acceptance: Settings can start a full PostgreSQL backup to GCS, show backup/restore phase progress in the header, list GCS backups and their total size for restore, require confirmation before restore, and require a fresh verified pre-restore backup before applying any restore.

- [ ] Add backup scheduling, retention, and drill automation.
  - Acceptance: full database backups can run on a schedule, old GCS backups can be pruned by a visible retention policy, and a dry restore drill can validate the latest backup without replacing the live database.

- [ ] Add original object cleanup and restore workflow.
  - Acceptance: soft-deleted documents can be restored, and permanent deletion can optionally remove original/assets after confirmation.

- [ ] Add GCS manifest validation.
  - Acceptance: Medusa can check that every stored URI in Postgres exists in GCS/local storage and report missing objects.

- [x] Add Settings-managed GCS bucket and Google service-account upload.
  - Acceptance: Settings shows the active bucket, can save it for future backend/worker operations, accepts a service-account JSON upload, stores the key outside tracked files with restrictive permissions, displays the service account name/project without exposing private key material, and uses the managed key for GCS, Google Vision, and Gemini when available.

- [x] Add AI usage dashboard.
  - Acceptance: Budget & Costs shows recorded OpenAI Responses/embeddings calls and Gemini `generateContent` calls across last-day, last-month, last-3-month, and all-time windows, including success/failure counts, token totals, cached input tokens when available, conservative known-model cost estimates, unpriced-call counts, PDF/file context bytes, cost trend lines, cost/token pie charts, model/task/document/calendar-day/calendar-hour rollups, and recent errors from the durable `OpenAIUsageRecord` ledger.

- [x] Add per-document Cost Composition and pipeline provenance.
  - Acceptance: imports record local stage durations, synced LLM/embedding costs, provider/model/method details, errata, and manual edit markers in durable composition rows; Library exposes a Composition modal with a dollar pie chart, provider breakdown, local processing time, and left-to-right pipeline; active import progress shows known spend so far; older documents without rows report composition as not available.

- [ ] Add OCR cost/status dashboard coverage.
  - Acceptance: Settings shows queued/completed/failed OCR work, page counts, provider status, and recent OCR errors once OCR processing is wired into imports/Concordance.

- [ ] Replace FastAPI startup event with lifespan handler.
  - Acceptance: startup logic avoids current deprecation warnings while preserving admin bootstrap behavior.

- [ ] Add production-password guardrails.
  - Acceptance: default password use is visibly warned in UI and can be disabled through `.env`.

## Testing And QA

- [ ] Add Playwright smoke tests.
  - Acceptance: login, import defaults, library search, document correction, citation copy, Queue actions, project bibliography, backup/restore controls, annotations, and day/night modes are covered.

- [ ] Add import end-to-end tests with mocked GCS/OpenAI/OCR adapters.
  - Acceptance: upload through processed/searchable states is tested without real cloud calls.

- [ ] Add stop/start import-resume acceptance test.
  - Acceptance: stopping the worker mid-import and restarting resumes without duplicate records or lost files.

- [ ] Add visual regression checks for cockpit layouts.
  - Acceptance: Library, document detail, Import, Projects, Queue, Notes, and Settings are checked at desktop and mobile widths.
