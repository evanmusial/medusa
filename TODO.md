# Medusa TODO

Last updated: 2026-06-18

This is the planned-work ledger for Medusa. Keep this file focused on work that is not done yet. Architectural rationale belongs in `docs/ARCHITECTURE.md`; this file is for actionable backlog items and acceptance notes.

## Highest Priority

- [ ] Implement exhaustive DOI/source-link resolution for APA citations.
  - Acceptance: citation refresh searches document metadata, extracted text, references, Crossref, Semantic Scholar, DOI.org, publisher pages, and targeted web evidence to locate a DOI whenever one exists; APA output favors DOI links; when no DOI can be verified, APA output uses the best direct stable source link, preferably a PDF or other static document; all evidence, attempted sources, conflicts, and confidence are recorded for Review Queue inspection.

- [ ] Add real low-text OCR fallback with Google Vision.
  - Acceptance: low-text/scanned PDF pages are detected, OCR is run only when needed, OCR text is stored per page, and processing remains resumable.

- [ ] Add robust citation verification beyond current Crossref basics.
  - Acceptance: DOI, Crossref, Semantic Scholar, publisher, PDF/static-source, and web evidence can be compared; uncertain conflicts create Review Queue candidates instead of overwriting trusted metadata.

- [ ] Add richer citation review evidence UI.
  - Acceptance: Review Queue shows source evidence side by side, supports partial field-level acceptance, and records which source supplied each accepted field.

## Document Processing And Intelligence

- [ ] Integrate a local scholarly parser such as GROBID.
  - Acceptance: title, authors, affiliations, abstract, references, and section metadata can be extracted when available and stored with evidence.

- [ ] Add AI figure caption and gist enrichment.
  - Acceptance: extracted figure assets get captions/gists, confidence/evidence, and searchable text without overwriting user edits.

- [ ] Add region-aware figure/table geometry.
  - Acceptance: figures and tables can be mapped back to page regions for future overlays and source evidence.

- [ ] Model richer table objects.
  - Acceptance: table rows/cells/captions/page regions are stored as structured data, while Markdown table text remains searchable.

- [ ] Add richer extraction fixtures.
  - Acceptance: tests cover two-column PDFs, multi-page tables, table-heavy papers, front matter before articles, scanned pages, bad metadata, duplicates, and multi-author papers.

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

- [ ] Add cost/status dashboard for OpenAI/OCR work.
  - Acceptance: Settings shows queued/completed/failed AI/OCR work, rough token/page counts, and recent errors.

- [ ] Replace FastAPI startup event with lifespan handler.
  - Acceptance: startup logic avoids current deprecation warnings while preserving admin bootstrap behavior.

- [ ] Add production-password guardrails.
  - Acceptance: default password use is visibly warned in UI and can be disabled through `.env`.

## Testing And QA

- [ ] Add Playwright smoke tests.
  - Acceptance: login, import defaults, library search, document correction, citation copy, Review Queue actions, project bibliography, backup export, annotations, and day/night modes are covered.

- [ ] Add import end-to-end tests with mocked GCS/OpenAI/OCR adapters.
  - Acceptance: upload through processed/searchable states is tested without real cloud calls.

- [ ] Add stop/start import-resume acceptance test.
  - Acceptance: stopping the worker mid-import and restarting resumes without duplicate records or lost files.

- [ ] Add visual regression checks for cockpit layouts.
  - Acceptance: Library, document detail, Import, Projects, Review Queue, Notes, and Settings are checked at desktop and mobile widths.
