# Medusa TODO

Last updated: 2026-06-19

This is the planned-work ledger for Medusa. Keep this file focused on work that is not done yet. Architectural rationale belongs in `docs/ARCHITECTURE.md`; this file is for actionable backlog items and acceptance notes.

## Highest Priority

- [ ] Implement exhaustive DOI/source-link resolution for APA citations.
  - Acceptance: citation refresh searches document metadata, extracted text, references, Crossref, Semantic Scholar, DOI.org, publisher pages, and targeted web evidence to locate a DOI whenever one exists; APA output favors DOI links; when no DOI can be verified, APA output uses the best direct stable source link, preferably a PDF or other static document; all evidence, attempted sources, conflicts, and confidence are recorded for Queue inspection.

- [ ] Add real low-text OCR fallback with Google Vision.
  - Acceptance: low-text/scanned PDF pages are detected, OCR is run only when needed, OCR text is stored per page, and processing remains resumable.

- [ ] Add robust citation verification beyond current Crossref basics.
  - Acceptance: DOI, Crossref, Semantic Scholar, publisher, PDF/static-source, and web evidence can be compared; uncertain conflicts create Queue candidates instead of overwriting trusted metadata.

- [ ] Add richer citation review evidence UI.
  - Acceptance: Queue shows source evidence side by side, supports partial field-level acceptance, and records which source supplied each accepted field.

## Document Processing And Intelligence

- [ ] Wire Docling and OpenAI raw extraction fallbacks.
  - Acceptance: Docling can be installed for the worker without requiring cloud credentials; the Raw Text Extraction Settings preference selects Docling, PyMuPDF, or an OpenAI fallback intentionally; unavailable local extractors record a clear processing event and fall back safely; imports and Concordance extraction refreshes both honor the selected engine without breaking page-level reader state.

- [ ] Integrate a local scholarly parser such as GROBID.
  - Acceptance: title, authors, affiliations, abstract, references, and section metadata can be extracted when available and stored with evidence.

- [ ] Add AI figure caption and gist enrichment.
  - Acceptance: extracted figure assets get AI-enriched captions/gists, confidence/evidence, and searchable text without overwriting imported labels/captions or user edits.

- [ ] Add Accessory Summaries.
  - Acceptance: users can define custom summary prompts, run them against selected documents or Concordance scopes, and each run uses the original PDF context plus the Settings-selected Accessory Summaries model without overwriting core summaries.

- [ ] Add richer table geometry and layout rendering.
  - Acceptance: table rows/cells/captions/page regions are stored as structured data, figure geometry can be rendered inline with parsed pages, and source regions can support future overlays/evidence views.

- [ ] Model richer table objects.
  - Acceptance: table rows/cells/captions/page regions are stored as structured data, while Markdown table text remains searchable.

- [ ] Add richer extraction fixtures.
  - Acceptance: tests cover two-column PDFs, multi-page tables, table-heavy papers, front matter before articles, scanned pages, vector charts/photos, bad metadata, obfuscated author emails, duplicates, and multi-author papers.

- [ ] Add semantic search and embedding refresh as a fuller Concordance capability.
  - Acceptance: embeddings are generated or refreshed for chunks/assets when configured, and search can combine lexical and semantic matches.

- [ ] Add image/figure gist search surfaces.
  - Acceptance: figure gists, captions, and image-derived descriptions participate in full-text and semantic search.

## Reader And Annotation Experience

- [ ] Add geometric PDF highlight overlays.
  - Acceptance: highlights can be created from selected PDF text/regions, persisted in `Annotation.geometry`, rendered on the page, and searched by body text.

- [ ] Add a more capable PDF reader.
  - Acceptance: page navigation, zoom, search-within-document, page thumbnails, and stable annotation overlays work inside the document pane.

- [ ] Add annotation editing.
  - Acceptance: existing annotations can be edited in place, not just created or deleted.

- [ ] Add reminder workflow for annotation/reminder kinds.
  - Acceptance: reminder annotations surface in Notes/Review or a reminder view with due dates.

## Library Organization And Search

- [ ] Normalize keyword/topic suggestion and display behavior.
  - Acceptance: keyword/topic dropdowns and lists render alphabetically by default; any non-alphabetical display order is an explicit, view-specific choice; import and Concordance keyword/topic extraction splits overly verbose compound phrases into useful primitives, such as `insider threat assessment` into `insider threat` and `threat assessment`, and `access control and cyber identity` into `access control` and `cyber identity`; deduplication clusters near-duplicates and favors primitive keywords such as `access control` while still allowing meaningfully distinct specific variants such as `access control lists` or `access control monitoring`.

- [ ] Add richer recommendation source/import management.
  - Acceptance: related-paper recommendations can be refreshed on a schedule or Concordance scope, source/provider failures are visible in Settings, downloads run as durable background fetch jobs instead of request-time fetches, and non-open recommendations can be triaged into a wishlist without pretending a PDF is available.

- [ ] Add arbitrary-filter Concordance scopes.
  - Acceptance: Concordance can run against the current filtered result set, not only whole library, document, domain, project, search text, or saved search.

- [ ] Add richer multi-condition filter builder.
  - Acceptance: saved searches can combine text, tags, domains, citation status, read status, priority, attributes, dates, and processing state.

- [ ] Add saved-search management improvements.
  - Acceptance: saved searches can be renamed, reordered, edited, duplicated, and used as durable library views.

- [ ] Add domain tree management.
  - Acceptance: domains can be nested, reordered, renamed, moved, colored, and soft-deleted from the UI.

- [ ] Add document-level BibTeX/RIS/CSL JSON copy/export controls.
  - Acceptance: individual document detail exposes citation formats beyond APA, matching project bibliography formatting.

- [ ] Add optional Zotero import/export.
  - Acceptance: Zotero libraries can be imported/exported through the citation model without weakening Medusa metadata evidence.

## Projects And Run Sheets

- [ ] Add project detail editing.
  - Acceptance: project name, description, due date, and status can be edited in the UI.

- [ ] Add project resource sorting and filtering.
  - Acceptance: run-sheet rows can be filtered by used/status/priority and sorted by title, priority, status, or added date.

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

- [ ] Add browser-based backup restore controls.
  - Acceptance: Settings can validate and dry-run a metadata export restore, show conflicts/skipped records, and require explicit confirmation before applying.

- [ ] Add backup scheduling/export command.
  - Acceptance: metadata export and storage manifest can be produced from CLI or scheduled job without using the browser.

- [ ] Add original object cleanup and restore workflow.
  - Acceptance: soft-deleted documents can be restored, and permanent deletion can optionally remove original/assets after confirmation.

- [ ] Add GCS manifest validation.
  - Acceptance: Medusa can check that every stored URI in Postgres exists in GCS/local storage and report missing objects.

- [x] Add OpenAI usage dashboard.
  - Acceptance: Budget shows recorded OpenAI Responses/embeddings calls across last-day, last-month, last-3-month, and all-time windows, including success/failure counts, token totals, cached input tokens, conservative known-model cost estimates, unpriced-call counts, PDF/file context bytes, task/model rollups, and recent errors from the durable `OpenAIUsageRecord` ledger.

- [ ] Add OCR cost/status dashboard coverage.
  - Acceptance: Settings shows queued/completed/failed OCR work, page counts, provider status, and recent OCR errors once OCR processing is wired into imports/Concordance.

- [ ] Replace FastAPI startup event with lifespan handler.
  - Acceptance: startup logic avoids current deprecation warnings while preserving admin bootstrap behavior.

- [ ] Add production-password guardrails.
  - Acceptance: default password use is visibly warned in UI and can be disabled through `.env`.

## Testing And QA

- [ ] Add Playwright smoke tests.
  - Acceptance: login, import defaults, library search, document correction, citation copy, Queue actions, project bibliography, backup export, annotations, and day/night modes are covered.

- [ ] Add import end-to-end tests with mocked GCS/OpenAI/OCR adapters.
  - Acceptance: upload through processed/searchable states is tested without real cloud calls.

- [ ] Add stop/start import-resume acceptance test.
  - Acceptance: stopping the worker mid-import and restarting resumes without duplicate records or lost files.

- [ ] Add visual regression checks for cockpit layouts.
  - Acceptance: Library, document detail, Import, Projects, Queue, Notes, and Settings are checked at desktop and mobile widths.
