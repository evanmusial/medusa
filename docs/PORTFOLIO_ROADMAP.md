# Portfolio Roadmap

Portfolio is Medusa's workspace for user-authored research and education documents, now centered on school-assignment iteration: assignment title/brief, draft versions, labeled context materials, Library resources, structured AI assessment, and tamper-evident bundle export.

This roadmap tracks the gaps that should be filled after real use begins. Keep tactical task tracking in `TODO.md`; keep stable architecture and product contracts in `docs/ARCHITECTURE.md`; use this document for Portfolio-specific sequencing and acceptance notes.

## Current Baseline

- `/portfolio` is a first-class workspace between Stashes and Queue.
- Portfolio accepts PDF, DOCX, RTF, TXT, and Markdown version/material uploads.
- Uploaded source files are preserved, while generated PDF/text mezzanines support preview, extraction, search text, and model context.
- Portfolio versions and materials reuse hidden `Document` rows with `document_kind` values outside normal Library visibility.
- `PortfolioVersionEdge` preserves version ancestry, with `supersedes` as the first relation.
- Materials can attach rubrics, assignment prompts, guides, references, feedback, source material, or other context at item or version scope.
- Find Resources currently uses local Library text/search evidence.
- Assessments create local baseline findings plus model-backed rubric scorecards, narrative feedback, grade estimates, revision priorities, per-model outputs, and agreement metadata when multiple models are requested.
- Portfolio audit events are canonicalized, SHA-256 hash-chained, signed with a local Ed25519 key, and optionally anchored through RFC 3161 timestamp authorities.
- Portfolio bundle export streams an audited ZIP with source files, generated previews, assessment reports, resource metadata, manifests/checksums, public keys, event-chain JSONL, timestamp-anchor proofs, and verification summary.
- Metadata export/restore includes Portfolio rows and audit proofs while omitting private signing keys.

## Near-Term Gaps

### Better DOCX And RTF Fidelity

Current DOCX/RTF handling is text-first. It is good enough for preservation and search, but not yet good enough for high-quality previews or layout-sensitive assessment.

Acceptance:

- DOCX extraction preserves useful headings, ordered and unordered lists, tables, emphasis, page breaks, and source provenance.
- RTF extraction preserves headings, lists, basic emphasis, and readable paragraph boundaries.
- If a high-fidelity local conversion tool is unavailable, Portfolio records a clear processing event and retry-safe failure or degraded-mode state.
- The generated mezzanine keeps enough evidence to explain assessment findings that rely on document structure.

### External Resource Suggestions

Current resource suggestions come from local Library evidence only. Portfolio should eventually combine Library matches with bounded external scholarly and web evidence.

Acceptance:

- Find Resources returns separate groups for Library-held, queued/imported, and external-only suggestions.
- External suggestions store provider, URL/DOI, title, authors, publication/source, confidence score, and evidence snippet metadata in `PortfolioSuggestion`.
- External lookup is bounded, cancellable or retryable, and visible through processing events or an activity surface.
- Existing Library documents remain the preferred source when they clearly match the Portfolio topic.

### Rich Portfolio Assessment Refinements

The core structured assessment path now exists. Remaining work is about calibration, comparison quality, and deeper evidence linking after real school use.

Acceptance:

- Assessment calibration is tested against real rubrics with point totals, qualitative-only rubrics, and instructor feedback.
- Findings cite exact material/version labels and page/snippet evidence where extraction supports it.
- Multi-model comparison summarizes agreement/disagreement beyond completion counts and grade-estimate snapshots.
- Runs expose usage/cost provenance in the UI beside selected model ids.
- Assessment preserves old findings and lets future UI filter by run, model, category, severity, and status.

## Mid-Term Gaps

### Bundle Export Polish And Restore Drills

Portfolio data now round-trips through Medusa metadata export/restore and has a ZIP bundle endpoint. Remaining work is operational hardening.

Acceptance:

- Add fixture-based restore drills that export a Portfolio item, restore into a clean database, and verify lineage, material scope, current-version pointer, audit chain verification, and parked active jobs.
- Add large-bundle streaming tests so very large draft/material files do not require excessive memory.
- Add a bundle manifest post-processing convention for recording the final ZIP SHA-256 without invalidating the ZIP hash itself.
- Keep secret-bearing fields rejected or omitted using the same safety rules as the rest of Medusa exports.

### Explicit Portfolio Concordance Scopes

Portfolio documents must remain excluded from default Library Concordance runs, but the user should be able to opt into Portfolio-specific upgrade work.

Acceptance:

- Concordance can target all Portfolio items, selected Portfolio items, selected versions, selected materials, or the current Portfolio view.
- The UI makes Portfolio inclusion explicit and never silently broadens Library scopes.
- Capability state distinguishes Library documents, Portfolio versions, and Portfolio materials.
- Reprocessing keeps version lineage intact and does not collapse historical evidence.

### Stronger UI And Integration Smoke Coverage

The first implementation has build and backend tests. The module needs focused UI smoke coverage as the surface grows.

Acceptance:

- Smoke tests verify nav placement, `/portfolio` routing, item creation, version upload, material upload, resource refresh, assessment creation, preview/source links, and responsive pane behavior.
- Tests cover empty, processing, ready, failed, and multi-version states.
- Portfolio controls do not shift or overlap on common laptop and tablet viewport sizes.

## Later Product Questions

### Editor-Like Interaction

Portfolio is currently source-upload centric. After real use, decide whether it should remain that way or add limited editor/review capabilities.

Decision criteria:

- Users need lightweight review comments, annotations, or revision planning inside Portfolio rather than in external tools.
- Version lineage remains clear if edits are made in-app.
- Assessment and comparison can use editor-created evidence without turning Portfolio into a full document editor.
- The UI stays quiet and work-focused rather than becoming a general writing suite.

Possible outcomes:

- Keep Portfolio upload-centric and invest in assessment/comparison.
- Add a small review layer for notes, tasks, and assessment responses.
- Add limited structured editing for short Markdown/TXT artifacts only.

## Open Design Threads

- Whether Portfolio should support rubric templates separate from uploaded rubric files.
- Whether assessment findings should be promoted into project tasks, notes, or annotations.
- Whether Portfolio suggestions should support one-click import into Library, one-click stash, or both.
- Whether version comparison should grow from metadata comparison into rendered diff, text diff, or assessment-delta views.
- Whether Portfolio should expose a public/shareable export bundle for a project, class, grant, or research package.
