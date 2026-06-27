# Portfolio Module

Portfolio is Medusa's workspace for user-authored or user-supplied research and education artifacts: drafts, assignments, research memos, rubrics, prompts, references, and feedback. It is intentionally adjacent to Library, not part of Library.

## User-Facing Contract

- Route: `/portfolio`
- Nav label: `Portfolio`
- Shortcut: `W`
- Nav placement: between Stashes and Queue
- Icon: Lucide `Briefcase`

The first implementation is a dense workbench rather than an editor. It supports item creation, version upload, material upload, generated preview, source download, Library-resource suggestions, baseline assessment runs, and metadata comparison between versions.

## Visibility Boundary

Portfolio files reuse the `documents` table and processing pipeline, but they do not become Library documents by default.

`Document.document_kind` values:

- `library`: normal Library document
- `portfolio_version`: hidden document backing an immutable Portfolio version
- `portfolio_material`: hidden document backing a rubric, prompt, reference, source, or feedback file

Library-visible filters require `document_kind == "library"` plus normal ready/undeleted state. Portfolio documents stay out of:

- Library lists and search
- Dashboard Library counts
- tag/domain document counts
- project bibliographies
- recommendation existing-library suppression
- duplicate scans
- default Concordance scopes

A future explicit include-Portfolio control can opt them into selected workflows.

## Data Model

Portfolio tables:

- `PortfolioItem`: the user-facing artifact container, with title, description, status, current version, organization ids, and metadata.
- `PortfolioVersion`: immutable uploaded version linked to a hidden `Document`, original source fields, generated-processing status, and per-version metadata.
- `PortfolioVersionEdge`: lineage between versions, initially `supersedes`.
- `PortfolioMaterial`: supporting documents linked at item or version scope, with role, label, required-for-assessment flag, and notes.
- `PortfolioSuggestion`: cached Library or future external resource suggestion with relation family, score, status, and evidence.
- `PortfolioAssessmentRun`: assessment run metadata, selected model ids, material snapshot, status, summary, and cost/provenance metadata.
- `PortfolioAssessmentFinding`: assessment findings with category, severity, body, status, and evidence.

## Processing

Portfolio accepts PDF, DOCX, RTF, TXT, and Markdown sources. PDF sources are stored as the preview/original object. Non-PDF sources are preserved under a Portfolio source key and converted locally into a PDF mezzanine for preview, text extraction, search, and model context.

Each upload creates:

- a hidden `Document`
- durable source storage evidence
- a local processing-cache PDF
- an `ImportBatch`
- a queued `ImportJob`
- processing events
- a persisted Composition estimate

Portfolio jobs are queued immediately from Portfolio controls and do not wait for the Import workspace's Process Uploads action.

## API

Current endpoints:

- `GET /api/portfolio`
- `POST /api/portfolio`
- `GET /api/portfolio/{portfolio_item_id}`
- `PATCH /api/portfolio/{portfolio_item_id}`
- `POST /api/portfolio/{portfolio_item_id}/versions`
- `POST /api/portfolio/{portfolio_item_id}/materials`
- `GET /api/portfolio/versions/{version_id}/preview`
- `GET /api/portfolio/versions/{version_id}/source`
- `GET /api/portfolio/materials/{material_id}/preview`
- `GET /api/portfolio/materials/{material_id}/source`
- `POST /api/portfolio/{portfolio_item_id}/suggestions/refresh`
- `POST /api/portfolio/{portfolio_item_id}/assessments`

Preview routes stream the generated PDF mezzanine inline. Source routes download the original uploaded source.

## Assessment

Settings includes a model task named `Portfolio Assessment`. The first implementation records selected-model provenance and local baseline findings for readiness, materials, rubric/prompt presence, resource suggestions, and extracted-text length. The data model is ready for richer multi-model LLM assessment, but deep rubric/reference scoring is a follow-up.

## Follow-Ups

- Improve DOCX/RTF fidelity beyond text-first parsing.
- Add external search-backed Portfolio resource suggestions.
- Add richer multi-model LLM assessment prompts, score normalization, and model comparison.
- Add Portfolio export/restore coverage.
- Add explicit include-Portfolio Concordance scopes.
- Add stronger visual smoke tests for `/portfolio`.
- Decide later whether Portfolio should gain editor-like interaction or stay source-upload centric.
