# Portfolio Module

Portfolio is Medusa's workspace for user-authored or user-supplied research and education artifacts: drafts, assignments, research memos, rubrics, prompts, references, and feedback. It is intentionally adjacent to Library, not part of Library.

## User-Facing Contract

- Route: `/portfolio`
- Nav label: `Portfolio`
- Shortcut: `W`
- Nav placement: between Stashes and Queue
- Icon: Lucide `Briefcase`

The current implementation is a dense school-assignment workbench rather than an editor. It supports assignment creation, draft/version upload, labeled context material upload, generated preview, source download, Library-resource suggestions, structured AI assessment runs, metadata comparison between versions, tamper-evident audit status, and audited ZIP bundle export.

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
- `PortfolioMaterial`: supporting documents linked at item or version scope, with role, label, required-for-assessment flag, and notes. Current roles are `rubric`, `assignment`, `guide`, `reference`, `feedback`, `source`, and `other`.
- `PortfolioSuggestion`: cached Library or future external resource suggestion with relation family, score, status, and evidence.
- `PortfolioAssessmentRun`: assessment run metadata, selected model ids, material snapshot, status, summary, and cost/provenance metadata.
- `PortfolioAssessmentFinding`: assessment findings with category, severity, body, status, and evidence.
- `PortfolioAuditEvent`: append-only Portfolio audit ledger events with canonical JSON payloads, SHA-256 payload hashes, previous-event hashes, event hashes, Ed25519 signatures, public-key fingerprints, UTC occurrence times, and links to items, versions, materials, and assessment runs.
- `PortfolioAuditAnchor`: RFC 3161 timestamp-anchor proofs for Portfolio audit root hashes, including covered event range, TSA URL, raw timestamp response bytes as base64, parsed metadata, verification status, and verification errors.

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
- `POST /api/portfolio/{portfolio_item_id}/bundle`

Preview routes stream the generated PDF mezzanine inline. Source routes download the original uploaded source.

Bundle export builds and streams an audited ZIP with:

- `manifest.json` containing assignment metadata, version lineage, assessment ids, relative file paths, checksums, MIME types, and sizes.
- `versions/` containing every Portfolio-uploaded draft/source file plus generated preview/mezzanine files when distinct.
- `materials/` containing every uploaded rubric, assignment prompt, guide, reference, feedback, source, or other context file plus generated preview/mezzanine files when distinct.
- `assessments/` containing JSON and Markdown reports for every assessment run.
- `resources/` containing Library suggestion metadata, snippets, citations, and document ids. Library originals are not included unless the user uploaded them as Portfolio materials.
- `audit/` containing event-chain JSONL, public keys, timestamp-anchor proofs, and a verification summary.

## Assessment

Settings includes a model task named `Portfolio Assessment`. It defaults to Medusa's high-quality GPT default (`DEFAULT_GPT_MODEL`, currently `gpt-5.5`) unless Settings overrides the task model.

Each run snapshots the exact model ids and returns:

- `scorecard`: rubric criteria, point values when present, awarded points when supported, qualitative level, confidence, rationale, and evidence labels.
- `grade_estimate`: estimated grade/score, scale, confidence, and assumptions.
- `narrative_feedback`: strengths, concerns, missing evidence, and revision priorities.
- `findings`: category/severity/title/body/evidence rows for actionable review.
- `model_outputs` and `agreement`: per-model structured output and basic multi-model completion/grade-estimate comparison when multiple model ids are requested.

The prompt is evidence-constrained. It may use only the supplied draft text, uploaded Portfolio materials, Portfolio history/evidence, and Library/Recon evidence. If rubric points are absent, it must leave point totals null and use qualitative scoring rather than inventing a numeric scale.

## Audit And Timestamping

Every major Portfolio action appends a ledger event: item creation/update, draft upload, current-draft switch, material upload, resource refresh, assessment completion, and bundle export. Events are canonicalized as sorted JSON, hashed with SHA-256, chained to the prior event hash, and signed by a local Medusa Ed25519 key. The private key lives under ignored local data by default at `data/audit/portfolio-ed25519.key`; metadata exports and bundles include only public keys, fingerprints, signatures, hashes, and timestamp proofs.

RFC 3161 timestamp authority URLs are configured with `MEDUSA_AUDIT_TIMESTAMP_URLS`. If no TSA URL is configured, or if a TSA request fails, the audit chain remains locally valid and the UI reports `anchor_pending` or `anchor_failed`. Timestamp anchors are independent time evidence, not a promise of legal admissibility by themselves.

## Export And Restore

Metadata exports include Portfolio items, versions, version edges, materials, suggestions, assessment runs/findings, audit events, and audit anchors. The export safety contract still omits secrets, session tokens, password hashes, service-account credentials, and the Portfolio audit private key. Restore preserves lineage and current-version pointers when ids are preserved, maps links where possible when ids are remapped, and parks restored active Portfolio processing/assessment jobs as `restored_paused` by default.

## Roadmap

Portfolio-specific gaps and sequencing are tracked in `docs/PORTFOLIO_ROADMAP.md`. Keep `TODO.md` as the cross-feature work ledger and `docs/ARCHITECTURE.md` as the stable architecture record.
