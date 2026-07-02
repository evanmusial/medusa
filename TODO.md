# Medusa TODO

Last updated: 2026-07-01

This is the planned-work ledger for Medusa. Keep this file focused on work that is not done yet. Architectural rationale belongs in `docs/ARCHITECTURE.md`; this file is for actionable backlog items and acceptance notes.

## Highest Priority

- [ ] Add real low-text OCR fallback with Google Vision.
  - Acceptance: low-text/scanned PDF pages are detected, OCR is run only when needed, OCR text is stored per page, and processing remains resumable.
  - Partial: bibliography extraction now records symbol-heavy unreadable text pages with `ocr_recommended=true` when a PDF has a corrupt but non-empty text layer, and can use visual OCR as a tail-page rescue when PDF span/page-text bibliography extraction finds nothing. Google Vision is tried when available, with Tesseract as the backend image's local fallback. Remaining work is real OCR execution for whole-page low-text and corrupt-text-layer page text, plus persistence of rescued OCR page text.

- [ ] Add manual Reader region nomination for missed figures and tables.
  - Acceptance: Reader PDF/Scan Page offers an Add Region or Draw Region mode where the user can draw one or more rough bounding boxes on a rendered PDF page, label each region as table/figure/chart/photo/diagram, optionally provide a label and description, preview the exact crop, and keep or discard each candidate. Kept regions create durable figure/table extraction records with page geometry, searchable captions/descriptions, document history, and safe retry semantics; the flow must support multiple regions on one page and work as a rescue path when automatic table/visual extraction misses subtle or mostly text-based tables.

- [ ] Add robust citation verification beyond current Crossref basics.
  - Acceptance: compare the already persisted DOI/source-link resolver evidence, Crossref metadata, publisher/static-source evidence, model metadata, and user-corrected fields field by field; conflicting title, author, year, publication, DOI, source URL, page, volume/issue, or article-number evidence creates Queue candidates instead of overwriting trusted metadata. DOI/source-link discovery provider plumbing is complete; this item is about verification policy, conflict adjudication, and safe partial acceptance.

- [ ] Add richer citation review evidence UI.
  - Acceptance: Queue renders `doi_source_resolution`, `doi_discovery`, `source_link_resolution`, Crossref, AI, publisher/static-source, and user/manual evidence side by side; shows selected/conflicting DOI and source-link candidates with confidence and attempted-source details; supports partial field-level acceptance for citation metadata; and records which source supplied each accepted field.

## Document Processing And Intelligence

- [ ] Add a richer Publication workspace and provider-evidence review UI.
  - Acceptance: publication rows can be inspected outside the document detail pane, show aliases, identifiers, provider evidence, conflicts, and linked ready documents, and support review/merge/cleanup of duplicate publication identities without automatic metadata overwrite.

- [ ] Extend Slipstream remote processing beyond the v1 lease/result foundation.
  - Acceptance: remote clients can run the same configured import and Concordance capability set as local workers, including capability-specific result bundle schemas, derived asset uploads with checksum validation, central scoped provider-call proxying for any model-backed step, per-call usage/cost attribution, richer client health/rate-limit surfaces, and end-to-end UI smoke coverage for Settings, Queue, Status, import completion, Concordance completion, failure recovery, and lease cancellation.
  - Partial: Slipstream v1 now has one-time enrollment tokens with server-enforced capability/capacity limits, Ed25519 signed polling, nonce/timestamp replay protection, registered clients, active lease quorum over `(job_type, job_id)`, shared local/remote claim coordination, heartbeat expiry/requeue, stale active-lease repair when a job is no longer running, artifact download, event/fail/result endpoints, Settings client/lease controls, Queue assignment labels, a bundled concurrent import-preprocess runner, a local Docker Compose worker profile for a 4-slot laptop worker, and a default-disabled Cloud Run worker-pool profile with Settings enablement/concurrency/flavor controls, generated `gcloud` commands, Secret Manager-backed client state, runtime cost estimates, and scale-to-zero guardrails. Remote import preprocessing applies page/search/composition evidence and returns the job to the central queue at `normalizing_pages`; Medusa still owns enrichment, model calls, storage, citations, tags, indexing, and final completion. Remaining work is richer portable runners, full Concordance remote execution, lease-scoped provider-call proxying, asset bundle validation/storage beyond document/page/capability manifests, per-call remote model usage attribution, automatic Cloud Run scaling execution, idle pool cost event attribution, a lean Cloud Run worker image that avoids full Marker/Torch/CUDA weight when not needed, and broader integration smoke coverage.

- [x] Show current execution location and next stage in Queue rows.
  - Acceptance: each import and Concordance queue row distinguishes where work is running now from the pipeline stage it is currently in. The location label should explicitly identify the execution venue, such as `Local worker`, `Slipstream: {hostname/client name}`, `Cloud Run: {pool/client name}`, or `Queued for central worker`, and should show unassigned/eligible states when no worker owns the row yet. Rows also show the next planned stage/action so states like `normalizing_pages` clearly read as already past remote raw extraction and waiting for central normalization/enrichment. The Queue should keep this compact and scannable while exposing enough detail to explain why an online remote worker is polling but not eligible to claim the row.
  - Completed: import and Concordance job APIs now return derived `execution_location` and `next_stage` labels from active lease metadata plus current pipeline state; Queue import rows display `Execution` and `Next` detail; Activity import and Concordance rows reuse the same labels.

- [ ] Implement second-pass import processing on `codex/second-pass-document-processing`.
  - Acceptance: `docs/SECOND_PASS_DOCUMENT_PROCESSING.md`, `docs/ARCHITECTURE.md`, and this TODO ledger are committed before runtime code begins; the branch keeps second-pass work isolated; built-in Balanced/Strict Local/Deep Review presets exist; an emergency disable path can return imports to the current pipeline; final verification includes backend tests, frontend build, and app health.

- [x] Add Settings Import Processing presets and step controls.
  - Acceptance: Settings has an Import Processing section with every import step, enabled state where applicable, model/provider controls where applicable, core parameters, sensible defaults, and tooltips explaining exactly what happens and what each step accomplishes; built-in presets are read-only but duplicable; user presets can be created, renamed, duplicated, edited, deleted, and set as default; Save All persists presets, default preset, caps, thresholds, OCR settings, cleanup toggles, and visual settings.

- [ ] Add Import preset selection and durable preset snapshotting.
  - Acceptance: Import has a compact Processing preset selector in batch defaults; Balanced is selected by default from Settings; staged batches/jobs store the selected preset id and preset snapshot; later Settings edits do not affect already-staged work; staged/processing rows and Composition show which preset was used.
  - Partial: Import has the Processing preset selector, uses the Settings default, snapshots the selected preset onto batch/job/document evidence, shows preset names in staged/processing rows, and persists preset-aware step-level cost estimate metadata for staged jobs. Remaining work is an explicit Composition display for the preset snapshot and stronger tests around later Settings edits not changing already-staged jobs.

- [ ] Add deterministic document structure cleanup.
  - Acceptance: imports and Concordance can remove or normalize repeated headers/footers, page numbers, watermarks, decorative text art, front matter noise, excess whitespace, broken line wraps, hyphenation, bullets, and drop-cap styling artifacts while preserving headings, captions, citations, equations, lists, tables, and body text; removed text is kept as evidence but excluded from reader/search/enrichment body text; manual page edits are not silently overwritten.
  - Partial: import and Concordance run deterministic cleanup, preserve removed boilerplate evidence, protect manual page text during Concordance, feed cleaned text into normalization/search, and page-text normalization v4 handles first-page publisher front matter where article-info/abstract regions sit above the introduction in separate visual bands. Remaining work is broader fixture coverage and stronger handling for body-boundary detection, hyphenation, persistent watermarks, and edge-case scholarly layouts.

- [x] Extract source-document bibliographies into a dedicated field.
  - Acceptance: imports and Concordance detect references, bibliography, or works-cited sections; `Document.bibliography` stores the extracted reference list separately from generated APA citation text and project bibliographies; Markdown-compatible italics are preserved when PDF span metadata exposes emphasis; document detail displays and allows editing, copying, and explicitly refreshing the Bibliography field; search, export, restore, and history include it.
  - Completed: bibliography extraction now rejects publisher reference-count front matter such as `References: this document contains references to N other documents` and method-section wording such as `Reference List Search` or `References cited`; PDF-span extraction orders strong non-marker two-column bibliography pages by detected column before section scoring, preserves native PDF line order on marker-heavy numbered reference pages, skips subscription footers, IEEE permission footers, and known running headers inside references, and recognizes organization starts such as `Kroll. (2014)` and `United States Army (2010)`; bracketed reference lists keep their marker style so wrapped numeric page/DOI continuations do not become extra sources; forced Bibliography Refresh clears stale machine-extracted bibliography text when current extraction returns `not_found`, while preserving user-supplied bibliography text; forced refresh preserves an existing bibliography of at least three entries when fresh extraction would reduce it and records `rejected_regression_existing_bibliography`; forced refresh applies separator-insensitive deterministic APA-order sorting before model cleanup, allows model cleanup for extracted lists up to 300 entries and 120,000 characters, rejects model cleanup output that reduces the detected entry count, drops visible coauthors, or adds duplicate entries, strips missing-page placeholders such as `n/a`, records explicit skip/rejection evidence for larger or unsafe cleanup results, and surfaces skipped/rejected cleanup status in the Bibliography area.
  - Completed: bibliography extraction can render the tail pages and run visual OCR as a last-resort reference-list rescue when normal PDF span and parsed-page extraction return `not_found`; OCR errors are recorded as extraction evidence, and the document detail/Reader flow shows a styled alert when Bibliography Refresh completes without finding references.
  - Completed: document detail/Reader Bibliography now has a focused Markdown editor with bold/italic controls and Cmd/Ctrl+B or Cmd/Ctrl+I shortcuts; users can manually mark a Bibliography verified, and verified Bibliographies require confirmation before edit or refresh. Confirmed edits/refreshes clear verification until the user verifies again.
  - Completed: DOI, APA Reference List, and APA In-Text Citation fields can also be manually marked verified; verified DOI/APA fields require confirmation before edit, No DOI marking, or citation refresh, and confirmed changes clear only the affected field verification until set again.

- [ ] Add an explicit very-large Bibliography Cleanup override.
  - Acceptance: the Bibliography area already warns when extraction stayed complete but model cleanup was skipped or rejected; remaining work is letting the user run a one-time over-cap cleanup for that document after seeing estimated cost/risk, and the resulting evidence records the override, cap, detected entry count, detected characters, selected model, and whether cleanup completed, failed, or fell back.

- [ ] Add structured table extraction and persistence.
  - Acceptance: table rows/cells/captions/page regions are stored as structured data; Markdown table text remains searchable; tables can link to nearby headings, captions, and explicit `Table N` mentions; imports and Concordance are idempotent and retry-safe.
  - Partial: cleanup records table-like blocks in metadata evidence and the Settings flow reflects that this is evidence-only today. Remaining work is first-class table rows/cells/captions/page-region persistence and table-context linking.

- [ ] Add multi-pass visual asset extraction and coverage audit.
  - Acceptance: embedded images, displayed image regions, vector charts/plots/diagrams, photos, maps, full-page scans, and table regions are detected; crops include complete axes, legends, labels, and visual bounds when possible; duplicate/overlapping crops are reconciled; page rotation/orientation is preserved or corrected; every meaningful visual region is either extracted or flagged with an audit warning.
  - Partial: local extraction covers embedded images, page image regions, and vector drawing clusters with captions, orientation metadata, durable assets, inline parsed-text figure markers, a basic no-assets-found warning, Reader one-page Scan Page rescue that preserves other pages and records evidence, and visual asset extraction v3 suppresses uncaptained first-page publisher furniture so journal mastheads/logos/update badges do not become research figures. Remaining work is robust full-page scan/table-region coverage, durable user-drawn visual hints/bounding boxes, duplicate/incomplete crop audit, complete axes/legend expansion, and missed-region warnings.

- [ ] Add visual asset context and affordable visual model routing.
  - Acceptance: figures/tables link to captions, nearby headings, surrounding paragraphs, and explicit mentions such as `Figure 2`; searchable gists come from captions/local context first; cropped-region model calls use cheaper OpenAI/Google models when local context is insufficient; premium visual/document analysis requires Deep Review or explicit Concordance scope; every cloud call records provider/model/task/tokens/file bytes/status/duration/cost.
  - Partial: local figure context links captions, nearby text, and explicit figure mentions; Settings stores visual model-routing preferences; staged import estimates mark visual model routes as pending rather than charging for calls that do not yet run. Remaining work is cropped-region model calls, visual gists beyond local context, premium gating enforcement, and usage/cost records for visual model calls.

- [ ] Wire second-pass capabilities into Concordance.
  - Acceptance: `document_structure_cleanup`, `bibliography_extraction`, `formula_capture`, `visual_asset_extraction`, `visual_asset_context`, `structured_tables`, and `ocr_fallback` are versioned Concordance capabilities; old documents can be upgraded without re-upload; jobs are durable, resumable, idempotent, and visible through events/progress; manual page text is skipped or turned into reviewable candidates unless explicit replacement is requested.
  - Partial: the listed capabilities exist and route to current cleanup, bibliography, manual formula capture, visual extraction, visual context, structured-table evidence, and OCR eligibility audit handlers. Concordance now estimates scoped run cost before queuing, reports planned/same-model no-op/current/already-queued work, skips model-backed fields when document evidence or usage history already matches the selected model, exposes document-level Formula Capture from the preview/Reader action row, renders captured LaTeX formulas inside parsed document text read mode, and lets forced Bibliography Refresh clear stale machine-extracted bibliography output when the current extractor cannot support it. Remaining work is real OCR execution, first-class structured-table persistence, stronger idempotency tests for visual/table runs, dedicated formula review/display beyond rendered parsed text/evidence, and broader progress/evidence UI for each capability.

- [ ] Deepen Recon for corpus-grounded research inquiries.
  - Acceptance: add a Recon workspace between Projects and Tags; inquiries store scope, question/instructions, selected model, run mode, run history, answers, evidence, usage, and cost; scopes support whole library, domains, projects, saved searches/views, and eventually selected documents; the Start Research action uses Medusa's durable async progress convention with cost/time preview; Quick Answer uses retrieval over the selected corpus, Broad Sweep inspects every scoped document at least lightly, and Exhaustive is an explicit deep mode rather than the default; answers cite exact document/page/chunk evidence and can be re-run when the question, model, scope, or corpus changes. Planning notes live in `docs/RECON.md`.
  - Partial: Recon V1 now has durable inquiry/run/evidence/answer tables, `/recon`, Library/domain/project/saved-search scopes, manual estimates/runs/cancel, Source Finder, Quick Answer, retrieval-backed Broad Sweep/Exhaustive warnings, optional pgvector ranking, a `recon_inquiry` model task, Portfolio Find Resources integration, Portfolio Assessment evidence injection, and focused tests. Remaining work is worker-backed Broad Sweep/Exhaustive map-reduce with resumability/cancellation, selected-document and passage-seeded entry points, negative relevance persistence for full coverage questions, stale-run detection, Notes/Projects promotion, and richer active-work/corpus-health surfaces.

- [ ] Evaluate alternate core document-intelligence providers and cheaper GPT models.
  - Acceptance: representative already-processed papers are compared side by side across the current routed GPT baseline, cheaper GPT options, Gemini, and Claude for metadata, summary, APA fallback, and tag suggestions; quality gaps, failure modes, latency, and recorded cost are documented before changing defaults.

- [ ] Extend provider abstraction beyond OpenAI/Gemini.
  - Acceptance: Anthropic and local-model calls can be configured without committing credentials; every cloud call records provider, endpoint, model, task, token/file context where available, status, latency, and errors; Finances distinguishes provider costs and marks unknown pricing explicitly.

- [ ] Add discounted async processing for non-urgent Concordance refreshes.
  - Acceptance: large library refreshes can opt into discounted batch/flex-style provider modes where available, remain resumable through durable Concordance jobs, and clearly show delayed completion expectations before the run starts.

- [ ] Wire Docling and OpenAI raw extraction fallbacks.
  - Acceptance: Docling can be installed for the worker without requiring cloud credentials; the Raw Text Extraction Settings preference selects Docling, PyMuPDF, or an OpenAI fallback intentionally; unavailable local extractors record a clear processing event and fall back safely; imports and Concordance extraction refreshes both honor the selected engine without breaking page-level reader state.

- [ ] Integrate a local scholarly parser such as GROBID.
  - Acceptance: title, authors, affiliations, abstract, references, and section metadata can be extracted when available and stored with evidence.

- [ ] Add AI figure caption and gist enrichment.
  - Acceptance: extracted figure assets get AI-enriched captions/gists, confidence/evidence, and searchable text without overwriting imported labels/captions or user edits.

- [ ] Extend Inquests beyond current-document runs.
  - Acceptance: the current Library detail Inquest flow can also run one prompt against selected documents, saved searches, or Concordance scopes, with durable per-document answer rows and the same Settings-selected default model behavior.

- [ ] Add richer table geometry and layout rendering.
  - Acceptance: table rows/cells/captions/page regions are stored as structured data, figure geometry can be rendered inline with parsed pages, and source regions can support future overlays/evidence views.
  - Partial: extracted figures now sync private Markdown image markers into parsed page text and render inline in Reader Text with full-asset clickthrough. Remaining work is structured table geometry, source-region overlays/evidence views, and first-class table rendering.

- [ ] Model richer table objects.
  - Acceptance: table rows/cells/captions/page regions are stored as structured data, while Markdown table text remains searchable.

- [ ] Add richer extraction fixtures.
  - Acceptance: tests cover two-column PDFs, multi-page tables, table-heavy papers, front matter before articles, scanned pages, vector charts/photos, bad metadata, obfuscated author emails, duplicates, and multi-author papers.

- [ ] Add richer HTML import rendering and asset capture.
  - Acceptance: HTML imports can optionally preserve local/remote images, useful CSS layout cues, tables, and source URLs in the generated PDF mezzanine and extraction evidence without weakening the current text-first, no-credential fallback.

- [ ] Deepen semantic search and embedding refresh.
  - Acceptance: embeddings are generated or refreshed for chunks/assets when configured, and search can combine lexical and semantic matches.
  - Partial: Recon retrieval now blends lexical scoring with optional pgvector chunk similarity when a query embedding can be generated, and Concordance `search_index` v4 fills missing text chunk embeddings for older imports. Remaining work is broader semantic search UI, asset/figure embeddings, stale/outdated embedding detection, Corpus Health coverage reporting, and local embedding model evaluation.

- [ ] Evaluate local text chunk encoding before replacing OpenAI embeddings.
  - Acceptance: BGE-M3 or a comparable local embedding model is benchmarked against the current OpenAI embedding path on Medusa search queries; vector dimensions, runtime footprint, indexing speed, retrieval quality, and Concordance reindex behavior are documented before changing the default.

- [ ] Add image/figure gist search surfaces.
  - Acceptance: figure gists, captions, and image-derived descriptions participate in full-text and semantic search.

## Portfolio

Roadmap: `docs/PORTFOLIO_ROADMAP.md`.

- [ ] Improve Portfolio DOCX/RTF fidelity.
  - Acceptance: DOCX and RTF Portfolio uploads preserve useful headings, lists, tables, emphasis, page breaks, and source provenance in the generated PDF/text mezzanine beyond the current text-first parser; unavailable conversion tools produce clear processing events and retry-safe failure state.

- [ ] Add external search-backed Portfolio resource suggestions.
  - Acceptance: Find Resources combines local Library semantic/search matches with bounded external scholarly/web evidence, stores source/provider/evidence metadata in `PortfolioSuggestion`, and clearly separates Library-held, queued/imported, and external-only suggestions.
  - Partial: local Library suggestions now reuse Recon retrieval and store retrieved evidence snippets/page metadata on `PortfolioSuggestion`; external scholarly/web paths remain future work.

- [ ] Calibrate Portfolio assessment against real school rubrics.
  - Acceptance: Portfolio Assessment has fixture coverage for point-based rubrics, qualitative rubrics, assignment guides, instructor feedback, and multiple model outputs; UI shows clear grade assumptions, evidence labels, scorecard rows, revision priorities, and model agreement/disagreement without overwriting prior runs.
  - Partial: Portfolio Assessment now returns structured scorecards, grade estimates, narrative feedback, revision priorities, per-model outputs, and agreement metadata using the current high-quality default model or Settings override. Remaining work is real-rubric calibration, deeper exact evidence labels, and cost/provenance UI polish.

- [ ] Add Portfolio bundle/restore operational drills.
  - Acceptance: automated fixtures export a Portfolio bundle and metadata backup, restore into a clean database, verify all versions/materials/assessments/audit proofs round-trip, confirm private signing keys are absent, and confirm active Portfolio jobs remain parked unless explicitly reactivated.
  - Partial: Portfolio bundle export now includes source/version/material files, generated previews, assessment reports, resource metadata, checksums, manifests, public keys, audit chain JSONL, timestamp-anchor proofs, and verification summary. Metadata export/restore includes Portfolio and audit rows while omitting private signing keys.

- [ ] Add explicit include-Portfolio Concordance scopes.
  - Acceptance: Concordance can target Portfolio versions/materials only when the user explicitly chooses Portfolio, selected Portfolio items, or selected versions; default Library scopes remain Library-only.

- [ ] Decide whether Portfolio needs editor-like interaction.
  - Acceptance: after real use, either keep Portfolio source-upload centric or design a limited editor/review layer with clear non-goals, history behavior, and assessment integration.

## Activity, Notes, And Research Workflows

- [ ] Add a unified Activity and Work Ledger.
  - Acceptance: Activity gives one durable, searchable place to inspect imports, Concordance Runs, citation refreshes, Inquests, recommendation fetches/downloads, backups/restores, OCR, embeddings, future Recon runs, and maintenance jobs; rows use common status language for staged, queued, running, paused, blocked, failed, retryable, complete, and cleared work; lanes or filters distinguish interactive work, imports, maintenance, cloud/model work, backups, and research runs; row actions support retry, pause/resume where safe, cancel, open result/source, and inspect details; each detail view shows processing events, model/provider calls, warnings, errors, retries, duration, rough/known cost, and next available action without weakening Queue's import/review workflows.
  - Partial: `/activity` now provides a first-pass lane-filtered Work Ledger over existing import batches, import jobs, Concordance runs/jobs, backup/restore runs, and citation-review candidates, with progress/timestamps/status/action links back to the owning surfaces. Remaining work is a durable cross-work ledger model, search, richer detail drawers, recommendation downloads, Inquest/OCR/embedding/provider-failure rows, and safe row-level retry/pause/resume/cancel actions where the underlying workflow supports them.

- [ ] Fully build out Notes for documents, topics, and ideas.
  - Acceptance: Notes supports standalone notes for topics, concepts, questions, ideas, and thesis/research thinking as well as notes attached to one or more documents; a note can link to documents, pages, annotations, figures, tables, projects, domains, tags, citations, or saved searches without requiring a document link; notes have title, body, type, status, optional due/reminder fields, and project/domain/tag organization; document detail shows linked notes and can create/link notes in context; the Notes workspace supports search, filters, backlinks, link management, soft delete/restore, and export/restore coverage; document-linked notes continue to contribute to document search while standalone topic/idea notes are searchable from Notes and global search; when this is ready for the main cockpit again, restore the horizontal Notes button with the BookOpen icon and `N` shortcut.

- [ ] Add a Corpus Health dashboard.
  - Acceptance: Corpus Health summarizes documents missing DOI/source links, verified citation, authors/year/pages, summary, tags, domains, projects, OCR, figures/tables, embeddings, or current capability versions; it groups failed, partial, stale, and low-confidence processing states by cause; it surfaces tag/domain/project hygiene issues; each issue opens the relevant filtered Library, Queue, Tags, Settings, or Concordance action; broad repair actions provide scope, time, and cost previews before queuing work.
  - Partial: `/health` now summarizes DOI evidence gaps, citation review, missing summaries, missing author/year identity, unfiled domains, untagged documents, project use, duplicate candidates, failed import/Concordance work, and latest unresolved backup/restore failures from existing document/job APIs, with sampled document shortcuts and document-backed issue cards that open Library using a visible `Health` result filter. Remaining work is first-class capability freshness, OCR/figure/table/embedding coverage, saved health views, richer failure grouping, and scoped repair queues with cost/time previews.

## Reader And Annotation Experience

- [x] Restore the withdrawn annotation UI as a complete Reader workflow.
  - Acceptance: Library and Reader do not show annotation lists, empty states, or controls until users can create, edit, delete, and search page-aware annotations from selected parsed text or an explicit note composer with kind, color, page, and body controls.
  - Completed: Reader Notes now expose a page-aware annotation composer below the Reader, capture optional selected parsed-text quote evidence, support kind/color/page/body fields, filter/search annotations, jump back to an annotation page, edit annotations inline, delete annotations, and refresh document search through the existing annotation API.

- [ ] Add geometric PDF highlight overlays.
  - Acceptance: highlights can be created from selected PDF text/regions, persisted in `Annotation.geometry`, rendered on the page, and searched by body text.

- [ ] Add a more capable PDF reader.
  - Acceptance: page navigation, zoom, search-within-document, page thumbnails, and stable annotation overlays work inside the document pane.
  - Partial: parsed-text Reader search now counts case-insensitive matches across pages, jumps previous/next by matching page, and highlights matches on the current read-mode page. Remaining work is PDF-native search/zoom, page thumbnails, and stable annotation overlays.

- [x] Redesign Library detail annotation creation.
  - Acceptance: the inline annotation composer stays out of the Library summary/detail flow until annotation capture has a quieter pane-aware UI for page, kind, color, note body, and eventual geometry selection.
  - Completed: annotation creation now lives in the Reader Notes section below the active Reader surface instead of the Library summary/detail metadata flow.

- [x] Add annotation editing.
  - Acceptance: existing annotations can be edited in place, not just created or deleted.
  - Completed: Reader Notes rows can edit body, kind, color, and page in place.

- [ ] Add reminder workflow for annotation/reminder kinds.
  - Acceptance: reminder annotations surface in Notes/Review or a reminder view with due dates.

## Library Organization And Search

- [x] Add robust duplicate detection, review, and resolution.
  - Acceptance: Library has a left-pane duplicate scan action; duplicate matching uses SHA-256, MD5, DOI, case-insensitive normalized titles, and supporting metadata; duplicate documents are labeled in Library rows and Reader/detail mode; duplicate review shows side-by-side recency and identity details; choosing which document to keep removes the unkept duplicate from active Library/search without destroying files or history; marking a pair as different keeps both documents and removes the Duplicate label from that pair; import-time duplicate checks use the same matching basis; Utilities can backfill MD5 hashes for existing documents by hydrating originals through the document cache.
  - Completed: `Document.checksum_md5` is persisted with an Alembic migration, imports and stash/recommendation download paths write MD5, `/api/documents/duplicates/scan`, `/api/documents/duplicates/resolve`, and `/api/documents/duplicates/dismiss` power the Library review dialog, duplicate row/detail labels include match basis, false-positive pair dismissals suppress future Library duplicate labels, and `/api/utilities/document-hashes/backfill` computes missing MD5 hashes from cache or durable storage.

- [ ] Add optional duplicate metadata merge during resolution.
  - Acceptance: before hiding the unkept duplicate, the review dialog can selectively copy newer DOI/citation/summary/tags/domains/notes/project links or other non-conflicting metadata onto the kept document with `DocumentVersion` history and a clear before/after preview.

- [ ] Add tag Delete workflow.
  - Acceptance: Tags view can delete unused or selected tags only after confirmation, safely remove document links when requested, and record any document tag changes in `DocumentVersion` history.
  - Partial: Optimize now uses the same Settings-selected Tag Suggestions model as import tag creation plus deeper deterministic governance analysis to produce larger reviewable merge, orphaned-tag cleanup, relationship, status, and pruning plans. Broad scopes cap the LLM call to a ranked high-yield subset while deterministic cleanup still reviews the full scope. Approved merges and document-assignment pruning run through audited document-history paths; true zero-link orphan tags can be alias-merged into useful used tags or pruned entirely through a guarded approval path. The plan pane can approve individual suggestions or batch-approve all current suggestions while showing top progress feedback during plan generation and bulk apply, and reporting stale skipped actions.

- [x] Normalize tag suggestion and display behavior.
  - Acceptance: tag dropdowns and lists render alphabetically by default; any non-alphabetical display order is an explicit, view-specific choice; import and Concordance tag extraction splits overly verbose compound phrases into useful primitives, such as `insider threat assessment` into `insider threat` and `threat assessment`, and `access control and cyber identity` into `access control` and `cyber identity`; deduplication clusters near-duplicates and favors primitive tags such as `access control` while still allowing meaningfully distinct specific variants such as `access control lists` or `access control monitoring`.
  - Completed: Tags are now user-facing flat labels; legacy keyword/topic kind values are normalized to `tag`, the Settings task is labeled Tag Suggestions, the Tags view no longer exposes a kind column, the Tags table supports shift-click range selection across visible sorted/filtered rows, merged tag names are remembered as aliases, tag prompts prefer an existing-tag manifest, import and Concordance run tag candidates through existing-first/not-existing-only three-axis governance scoring, import tag attachment is capped at five total tags and one brand-new candidate tag per document, low-value and near-existing candidates are recorded without creating new labels, strong new concepts become candidate tags only after stricter relevance/novelty scoring, semantic covered-by checks reduce duplicate creation, Optimize honors the same Tag Suggestions model preference used for import tag creation, can flag zero-use and singleton tags for larger merge/status cleanup, orphan pruning, or assignment pruning plans even when no model merge candidate exists, Optimize supports batch approval of all current suggestions with visible in-pane progress while the bulk request runs, broad `summary_topics` Concordance tag updates remain additive, and document-level Tag Refresh can explicitly replace a document's tag assignments through the import-style governance scorer. The original method notes live in `docs/TAG_GOVERNANCE.md`.

- [ ] Expand Related Documents into a diverse discovery and acquisition workflow.
  - Acceptance: Related hides library-held, active-import, staged-import, and already-stashed candidates from the main list by default while preserving an Already Known audit view; duplicate suppression uses DOI equality first and strong normalized-title/year/author evidence second; results are grouped or filterable by relation family such as closest, newer, foundational, methods, contrasting, open PDF, reference material, and diverse set; ranking balances relevance with diversity across authors, years, venues, methods, source types, domains, and relation types; evidence records preserve provider, relation, DOI/source URL, matched references, abstract snippets, open-PDF evidence, and duplicate-suppression reason; refreshes can run on a schedule or Concordance scope; source/provider failures are visible in Settings or Activity; open-PDF downloads run as durable background jobs; useful non-open recommendations can be moved into an acquisition wishlist without pretending a PDF is available.
  - Partial: recommendation refresh now uses bounded OpenAlex/Semantic Scholar/Crossref title/topic/evidence search for ready documents even when DOI/bibliography is missing, enriches candidates with Unpaywall and arXiv open-PDF availability, parses stored `Document.bibliography` reference entries into local DOI/title/source-url candidates, expands discovery through top project/domain/tag context-neighbor documents and their bibliographies/provider lookups, resets previously failed candidates when a refreshed match is seen, exposes manual Google Scholar search links, and renders the Library detail Related modal as a Discover / Already Known / All workflow. Discover hides library-held, active-import, queued-import, and already-stashed rows by default; Already Known shows the suppression reason. Rows carry relation-family metadata, reason chips, evidence payloads, query strings, context sources/scores, diversity scores, and known status in `raw_metadata.recommendations_v2`; filters cover diverse, closest, newer, foundational, methods, contrasting, open PDF, and reference material; default ranking balances relevance with diversity across authors, years, venues, providers, relation families, scholarly query evidence, and Medusa research-neighborhood context; DOI Stashes now serve as the Stash/Wishlist action from recommendations. The modal now separates provider-discovered/search-discovered/context-derived Other Related Articles from Bibliography Sources, keeps raw extracted source citation text visible, attaches enriched recommendation actions to parsed bibliography references, and allows title-only or bibliography-only documents to refresh related candidates. The Stashes workspace is now a DOI-backed Acquisition Stashes workbench with Wishlist, Open PDF, Queued, In Library, and All lanes, explicit Needs PDF/Open PDF lead states, source-document/source-evidence links, and no queued PDF for non-open wishlisted leads. Remaining work is scheduled/Concordance-scope refreshes, a centralized Settings/Activity provider-failure surface beyond processing-event payloads, durable background download jobs before PDF fetch, no-DOI acquisition wishlist records with richer priority/status/notes, and later semantic/embedding quality improvements.
  - Remaining detailed notes:
    - Concordance and scheduling: add `recommendations` as a normal Concordance capability for whole library, selected documents, current search, saved search, domain, and project scopes; record per-document completion/version state; make refreshes retry-safe and skip documents without viable title/DOI/bibliography/context signals; add an optional scheduled refresh policy that avoids repeatedly hammering providers.
    - Provider visibility: promote provider/query/context errors from per-document processing-event payloads into a Settings or Activity view showing provider enabled state, last successful refresh, last error, rate-limit hints, candidate counts, and affected document counts.
    - Acquisition jobs: replace direct open-PDF fetches with durable background download/import jobs that expose queued/running/failed/complete state, retry, cancellation, byte limits, MIME/type checks, duplicate decisions, and source evidence before handing the PDF to the normal import pipeline.
    - Acquisition wishlist: extend the DOI-backed Wishlist lane with first-class wishlist records for strong metadata-only recommendations when no DOI is available; include editable priority/status, source document, reason chips, source URL, manual lookup links, notes, and later imported/matched resolution.
    - Quality tuning: evaluate ranking against real library examples; tune query/context/provider weights, MMR diversity penalties, title/year/author duplicate thresholds, bibliography-vs-search balance, and over-broad title-only query suppression.
    - Semantic relatedness: add embedding-assisted candidate scoring once enough stable candidate/evidence data exists; use document summaries, titles, abstracts, tags/domains, and citation contexts without allowing embeddings to override DOI/title duplicate safety.
    - Evidence UX: make "why this paper" inspectable from the row, including source query, context-neighbor seed document, matched bibliography line, provider relation, DOI/open-PDF evidence, duplicate suppression basis, and whether the candidate was found through source document evidence or neighborhood expansion.
    - Evaluation harness: add repeatable fixtures or a small curated corpus for recommendation-quality regression tests, including DOI-rich papers, title-only documents, bibliography-only documents, context-neighbor discovery, already-known suppression, and no-open-PDF wishlist candidates.

- [ ] Add arbitrary-filter Concordance scopes.
  - Acceptance: Concordance can run against the current filtered result set, not only whole library, document, domain, project, search text, or saved search.

- [ ] Add richer multi-condition filter builder.
  - Acceptance: saved searches can combine text, tags, domains, citation status, read status, priority, attributes, dates, and processing state.

- [ ] Validate Valkey cache behavior at 10x and 50x scale.
  - Acceptance: seed or synthesize representative document/tag/domain/project data at 10x and 50x current corpus size; capture `/api/documents/list`, `/api/documents`, `/api/dashboard`, `/api/domains`, `/api/tags`, search, duplicate-scan, and active-work polling timings with SQL counts and `X-Medusa-Cache` headers; compare the current Valkey read-through layer against PostgreSQL index/query/read-model/materialized-table options; keep Valkey only for workloads it serves better than PostgreSQL.
  - Completed: Medusa now has an optional internal Valkey service, durable `cache_revisions`, cached hot response families, manual Refresh Cache, manual Hydrate Cache from live PostgreSQL data, app-configurable Valkey memory limits, Status/profile cache telemetry, and a Status-page Valkey resource monitor.
  - Notes: detailed phases, endpoint budgets, PostgreSQL/read-model candidates, frontend/runtime improvements, asset/provider considerations, and Valkey/external-search decision criteria live in `docs/PERFORMANCE_ROADMAP.md`.

- [ ] Add saved-search management improvements.
  - Acceptance: saved searches can be renamed, reordered, edited, duplicated, and used as durable library views.
  - Partial: Library saved searches can now be renamed inline, duplicated, overwritten with the current Library query/filters, deleted after confirmation, applied from the sidebar, and opened from the command palette. Remaining work is drag/drop or explicit sort-order management and a stronger "durable view" mode that can make a saved search feel like a first-class workspace.

- [x] Add domain tree management.
  - Acceptance: domains can be nested, reordered, renamed, moved, described, associated with tags, colored, and soft-deleted from the UI.

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

- [x] Add Utilities Bulk Intake for large duplicate-safe imports.
  - Acceptance: Utilities accepts many PDF, HTML, Markdown, or plain-text files, checks every file through import duplicate detection, shows all Library/Queue matches and repeated-drop files without Import-page preview truncation, and stages only non-duplicate files into the normal staged import queue.

- [x] Add browser-based full database backup and restore controls.
  - Acceptance: Settings can start a full PostgreSQL backup to GCS, show backup/restore phase progress in the header, list GCS backups and their total size for restore, require confirmation before restore, and require a fresh verified pre-restore backup before applying any restore.

- [x] Add host-agent release refresh for portable server deployments.
  - Acceptance: the backend reads an ignored release-status file, writes an ignored upgrade-request file after authenticated user approval, the header shows a compact accent-colored `Upgrade Now` action with a non-refresh icon when a newer release or newer running build is available, reload confirms with an unsaved-edits warning, and a host-side script can check upstream git state, refuse dirty checkouts, fast-forward only, rebuild Compose with explicit build identity, and verify backend health plus the app shell before release completion.

- [x] Add twice-weekly dependency update plan.
  - Acceptance: once Renovate is enabled for the repo, dependency update tooling checks Docker Compose images, Dockerfile base images, backend Python packages, and frontend npm packages twice weekly; critical security updates can bypass the normal window; runtime image PRs keep explicit tags, are not auto-merged, and preserve the invariant that HAProxy is the only host-published service on `3737` while Valkey remains private to backend/worker.
  - Completed: root `renovate.json` schedules Tuesday/Friday checks, and `docs/DEPENDENCY_UPDATE_PLAN.md` documents the activation prerequisite, Valkey-specific review checklist, verification commands, published-port invariant, and rollback path.

- [x] Add idle-gated maintenance builds with a mandatory backup gate.
  - Acceptance: the host release agent supports scheduled Tuesday/Friday maintenance plus on-demand app requests, classifies already-merged safe dependency updates separately from approval-required changes, waits for idle sessions and active-work blockers, creates and verifies a full GCS PostgreSQL backup before any Compose rebuild/runtime refresh, reports Docker/Compose versions without auto-updating the host engine, and exposes maintenance status/actions in Utilities and Status.
  - Completed: `scripts/medusa-release-agent.py auto-maintenance`, backend backup/readiness CLIs, session heartbeat tracking, maintenance release-status fields, Utilities/Status controls, HAProxy maintenance copy, and systemd maintenance timer/path templates are implemented.

- [x] Make Utilities database maintenance visible during long runs.
  - Acceptance: Compact Database and Optimize Database start backend-owned maintenance work, return immediately, report active operation/detail/elapsed time through database maintenance status, prevent overlapping maintenance operations, and keep the Utilities page responsive while PostgreSQL runs `VACUUM (FULL, ANALYZE)` or `ANALYZE`.

- [x] Add systemd templates for portable server operation.
  - Acceptance: the repo includes a `medusa.service` template for the Docker Compose app stack plus release checker/apply units, and portable deployment docs describe enabling them on a server checkout such as carrot.

- [ ] Add backup scheduling, retention, and drill automation.
  - Acceptance: full database backups can run on a schedule, old GCS backups can be pruned by a visible retention policy, and a dry restore drill can validate the latest backup without replacing the live database.

- [ ] Add original object cleanup and restore workflow.
  - Acceptance: soft-deleted documents can be restored, and permanent deletion can optionally remove original/assets after confirmation.
  - Completed: Library selection and detail/Reader Trash actions move ready Library documents to soft-deleted Trash with history/composition audit while preserving originals and stored assets.

- [ ] Persist page-preview images as durable assets for CDN delivery.
  - Acceptance: import or Concordance can generate versioned page-preview PNG assets into GCS/local storage, store their `DocumentPage.image_uri` values, serve them through the asset CDN redirect path when configured, and invalidate/delete stale preview assets when source pages are replaced or permanently removed.

- [ ] Add automatic renewal and expiry monitoring for the asset CDN certificate.
  - Acceptance: `assets.medusa.evan.engineer` certificate renewal is automated or operationally checked well before the current `medusa-assets-cert-20260702b` managed certificate's 90-day expiry window; renewal status is visible in operational docs/status surfaces; failures alert the user before there is any risk of serving expired CDN TLS.

- [ ] Add GCS manifest validation.
  - Acceptance: Medusa can check that every stored URI in Postgres exists in GCS/local storage and report missing objects.

- [x] Add Settings-managed GCS bucket and Google service-account upload.
  - Acceptance: Settings shows the active bucket, can save it for future backend/worker operations, accepts a service-account JSON upload, stores the key outside tracked files with restrictive permissions, displays the service account name/project without exposing private key material, and uses the managed key for GCS, Google Vision, and Gemini when available.

- [x] Add AI usage dashboard.
  - Acceptance: Finances shows recorded OpenAI Responses/embeddings calls and Gemini `generateContent` calls across last-day, last-month, last-3-month, and all-time windows, including success/failure counts, token totals, cached input tokens when available, conservative known-model cost estimates, unpriced-call counts, PDF/file context bytes, cost trend lines, cost/token pie charts, model/task/document/calendar-day/calendar-hour rollups, and recent errors from the durable `OpenAIUsageRecord` ledger.

- [x] Add per-document Cost Composition and pipeline provenance.
  - Acceptance: imports record local stage durations, synced LLM/embedding costs, provider/model/method details, errata, and manual edit markers in durable composition rows; Library exposes a Composition modal with a dollar pie chart, provider breakdown, local processing time, and left-to-right pipeline; active import progress shows known spend so far; older documents without rows report composition as not available.

- [ ] Add OCR cost/status dashboard coverage.
  - Acceptance: Settings shows queued/completed/failed OCR work, page counts, provider status, and recent OCR errors once OCR processing is wired into imports/Concordance.

- [ ] Replace FastAPI startup event with lifespan handler.
  - Acceptance: startup logic avoids current deprecation warnings while preserving admin bootstrap behavior.

- [ ] Add production-password guardrails.
  - Acceptance: default password use is visibly warned in UI and can be disabled through `.env`.
  - Partial: Settings > Account now rotates the live login email/password after current-password verification, password changes revoke other sessions, the login form no longer prefills the default password, and passwords are stored as PostgreSQL `users.password_hash` values seeded only on first account creation. Remaining work is the visible default-password warning/control.

- [x] Add account two-factor authentication.
  - Acceptance: Settings > Account can generate an authenticator-app setup key after current-password verification, require a current TOTP code before enabling, store the TOTP secret and hashed one-time recovery codes on the user row, require a TOTP or recovery code during login when enabled, consume recovery codes after use, and disable 2FA only after current-password plus second-factor verification.

## Testing And QA

- [ ] Add Playwright smoke tests.
  - Acceptance: login, import defaults, library search, document correction, citation copy, Queue actions, project bibliography, backup/restore controls, annotations, and day/night modes are covered.

- [ ] Add import end-to-end tests with mocked GCS/OpenAI/OCR adapters.
  - Acceptance: upload through processed/searchable states is tested without real cloud calls.

- [ ] Add stop/start import-resume acceptance test.
  - Acceptance: stopping the worker mid-import and restarting resumes without duplicate records or lost files.

- [ ] Add visual regression checks for cockpit layouts.
  - Acceptance: Library, document detail, Import, Projects, Queue, Notes, and Settings are checked at desktop and mobile widths.
