# Second-Pass Document Processing

Last updated: 2026-06-21

This document is the implementation contract for Medusa's second-pass document
processing branch. It must be kept current as the branch evolves. Runtime code
should not be written before this document, `docs/ARCHITECTURE.md`, and
`TODO.md` describe the goals and acceptance checks for the work.

## Goals

Second-pass processing should make imported documents substantially more useful
without making routine imports expensive or fragile.

- Improve reader and search text by removing boilerplate, page furniture, and
  extraction artifacts that are not part of the article, chapter, or document
  body.
- Preserve scholarly structure: headings, sections, citations, equations,
  lists, captions, tables, and the relationship between text and visual assets.
- Extract all meaningful visual assets: figures, charts, plots, photos,
  diagrams, maps, scans, and table regions.
- Extract a document's own reference list into a dedicated Bibliography field
  when a references, bibliography, or works-cited section exists.
- Detect likely missed or incomplete assets instead of silently declaring a
  page complete.
- Make every new processing ability available at import time and retroactively
  through Concordance Runs.
- Keep the default cost model affordable by running deterministic local cleanup
  everywhere and using cheap model calls only for flagged pages or cropped
  regions.
- Preserve raw extraction, cleaned output, removed text, layout evidence, model
  evidence, and costs separately so the pipeline is auditable and reversible.

## Non-Goals

- Do not replace the durable staged-import workflow.
- Do not send every page or the whole PDF repeatedly to cloud models by default.
- Do not convert charts, diagrams, photos, or figure graphics into invented
  Markdown or prose inside page text.
- Do not silently overwrite manually corrected page text or metadata during
  Concordance.
- Do not make premium model analysis the normal import path.

## Success Criteria

- Balanced-mode imports produce cleaner body text for common scholarly PDFs:
  repeated headers/footers, page numbers, decorative separators, drop-cap
  artifacts, excess whitespace, broken bullets, line wraps, and front matter
  noise are removed or normalized.
- Each meaningful visual region is either extracted as a durable asset/table or
  recorded as a possible miss with page evidence.
- Figures and tables are linked to captions, nearby headings, surrounding text,
  and explicit mentions such as `Figure 2` or `Table 1` when available.
- Papers with a detected reference list store it in a separate
  Markdown-compatible `Bibliography` field while preserving visible italics
  when span-level PDF evidence exposes emphasis.
- New import steps have Settings rows with clear tooltips explaining what the
  step does and what it accomplishes.
- Import lets the user select a processing preset before staging files.
- Staged jobs preserve the selected preset snapshot so later Settings edits do
  not change queued work.
- Composition and processing events expose cleanup status, visual extraction
  status, warnings, model/provider choices, and costs.
- Existing documents can receive the same upgrades through Concordance.

## Default Modes And Presets

Medusa ships three built-in import-processing presets. Built-ins are read-only
but can be duplicated into editable user presets.

### Balanced

Balanced is the default for Settings and Import.

- Run deterministic cleanup on all pages.
- Run OCR only for low-text or scanned pages when credentials exist.
- Escalate page text normalization only for flagged pages.
- Cap flagged-page model cleanup at 6 pages or 15 percent of pages per
  document, whichever is larger.
- Use cropped visual-region calls only when local context is insufficient.
- Prefer cheaper task-specific OpenAI or Google models for cleanup and visual
  subtasks.

### Strict Local

- Run local extraction, deterministic cleanup, table detection, figure
  extraction, and visual coverage audit.
- Do not call cloud models for cleanup, visual gists, or asset classification.
- Permit local OCR only if a local provider is later added; Google Vision is
  disabled in this preset because it is a cloud call.

### Deep Review

- User-selected batches or Concordance scopes can use higher caps and stronger
  models.
- Whole-document or whole-PDF analysis remains explicit, not default.
- Premium models such as `gpt-5.5` or `gemini-2.5-pro` are reserved for this
  mode or for selected fallback work.

## Model Routing Rules

Model choice is task-specific. Settings owns the choices and Import snapshots
them onto staged work.

- Cheap text cleanup candidates: `gpt-5.4-mini` and
  `gemini-3.1-flash-lite`.
- Stronger text cleanup candidates: `gpt-5.4`, `gpt-5.2` when available and
  priced favorably, and `gemini-2.5-flash`.
- Cheap visual gist/classification candidates: `gemini-3.1-flash-lite` or an
  OpenAI mini-tier model selected in Settings.
- Stronger visual fallback candidates: `gemini-2.5-flash`, `gpt-5.4`, or
  `gpt-5.2` when available and priced favorably.
- Premium explicit-only candidates: `gpt-5.5` and `gemini-2.5-pro`.
- Model calls for visual work should use cropped page regions or cropped
  assets, not repeated whole-PDF context.
- Every cloud call must record provider, model, task, tokens, cached input
  tokens when available, file/context bytes, status, duration, error text, and
  cost estimate when pricing is known.

## Processing Pipeline

Second-pass processing extends the current import pipeline without weakening
staging, duplicate detection, storage, job durability, or queue visibility.

1. Stage upload, hash files, classify source format, resolve duplicates, store
   originals, create `ImportBatch`, `Document`, and staged `ImportJob` records.
2. Snapshot the selected processing preset and write it to the batch/job
   evidence before processing begins.
3. Extract raw text and layout locally. Marker remains the default extractor
   with PyMuPDF fallback.
4. Run `document_structure_cleanup`.
5. Run `ocr_fallback` only for low-text/scanned pages when the selected preset
   permits the configured provider.
6. Run page text normalization locally for clean pages and through capped model
   escalation for flagged pages.
7. Run `structured_tables` to preserve table text and store table geometry.
8. Run `visual_asset_extraction` with multi-pass local detection.
9. Run `visual_asset_context` to link assets/tables to captions, headings,
   nearby paragraphs, and explicit mentions.
10. Run a visual coverage audit and record warnings for likely missed or
    incomplete assets.
11. Run `bibliography_extraction` to detect reference-list sections, preserve
    Markdown italics where PDF span metadata allows it, and store the result on
    the document's `Bibliography` field with evidence.
12. Rebuild reading text, chunks, search text, and downstream metadata,
    summaries, citations, tags, embeddings, and Composition rows from the
    cleaned body text plus structured tables/assets.

## Text Cleanup Requirements

The structure cleanup stage should use layout statistics, repeated text, page
position, typography clues, and conservative heuristics before using models.

- Remove repeated running headers and footers.
- Remove page numbers and folio labels when they are page furniture.
- Remove decorative separators, text art, watermark fragments, and common
  copyright strips.
- Detect front matter and body start for covers, publisher pages, contents,
  prefaces, abstracts, chapters, appendices, references, and back matter.
- Normalize line wraps, hyphenation, word spacing, paragraph gaps, and excess
  blank lines.
- Preserve bullet lists as one item per line.
- Repair drop-cap first letters when geometry/text indicates a style choice.
- Preserve captions, section headings, citations, equations, labels, and table
  text.
- Retain removed text as auditable evidence but exclude it from reader body
  text, search body text, summaries, citations, tags, and recommendations.

## Visual Asset Requirements

Visual extraction must be multi-pass and coverage-oriented.

- Detect embedded raster images from PDF internals.
- Detect displayed image regions from page layout blocks.
- Detect vector-drawn charts, plots, diagrams, and maps through drawing
  clusters.
- Detect full-page and near-full-page scans.
- Detect table regions separately from non-table graphics.
- Expand crops enough to include axes, legends, labels, and complete visual
  bounds.
- Avoid duplicate overlapping crops and prefer the most complete region.
- Preserve or correct orientation using page rotation, PDF metadata, and
  rendered crop evidence.
- Store page number, bbox, page size, rotation, source type, extraction method,
  confidence, caption, label, nearby heading, surrounding text, explicit
  mentions, and crop-quality warnings.
- Run a coverage audit that flags unclaimed visual regions, likely clipped
  crops, duplicate crops, rotated crops, and likely missed charts/figures.

## Settings And Import UX

Settings gets a new `Import Processing` section. It should be a quiet, dense
pipeline table rather than a landing page.

Each step row includes:

- label
- enabled state when applicable
- model/provider control when applicable
- core parameter controls
- default value
- current preset value
- tooltip explaining exactly what the step does and what it accomplishes

Required configurable values:

- default import processing preset
- preset create, rename, duplicate, delete, and set-default actions
- cleanup mode
- second-pass emergency disable
- page cleanup escalation cap
- cheap text cleanup model
- stronger text cleanup fallback model
- OCR enabled/provider thresholds
- visual extraction enabled
- visual coverage audit enabled
- visual gist/context enabled
- cheap visual model
- stronger visual fallback model
- Deep Review caps

Import gets a compact `Processing preset` selector in the batch-defaults panel.
The selected preset affects files staged after the selection changes. The
selector shows a short quality/cost summary and defaults to the Settings
default preset, initially Balanced.

## Data Model And API Changes

Planned schema additions:

- import processing preset storage in preferences or dedicated preset rows
- preset id and preset snapshot on import batches/jobs
- layout blocks with page, text, bbox, kind, source, confidence, and metadata
- structured table records with page geometry, rows/cells, caption, and source
- visual asset candidates and audit warnings
- richer figure context and crop-quality metadata
- `Document.bibliography` as a Markdown-compatible extracted reference-list
  field separate from generated APA citations and project bibliographies

Planned API additions:

- preferences payload includes built-in and user presets, default preset id,
  import-processing step metadata, and tooltip descriptions
- preferences patch can save presets and default preset id
- import batch creation accepts processing preset id and/or preset snapshot
- import job output includes preset name, cleanup status, visual extraction
  status, and warning summary
- document detail exposes cleaned-text provenance, removed-boilerplate summary,
  structured tables, layout evidence, richer asset context, and Bibliography
- Composition exposes cleanup and visual extraction stages, warnings, and costs

## Concordance Behavior

Every second-pass capability must be import-time and retroactive.

- `document_structure_cleanup`: clean existing page text unless the page has
  manual `text_source`; manual pages are skipped or produce reviewable
  candidates.
- `ocr_fallback`: run only where pages remain low-text and provider settings
  allow it.
- `structured_tables`: model table rows/cells/geometry and preserve searchable
  Markdown text.
- `visual_asset_extraction`: refresh figures/assets idempotently and avoid
  duplicate rows on retry.
- `visual_asset_context`: enrich existing assets with captions, mentions,
  surrounding text, and searchable gists.
- `bibliography_extraction`: fill missing Bibliography fields from existing
  extracted pages/PDF layout evidence without overwriting manual edits unless
  forced through an explicit correction workflow.

Capability versions must be bumped whenever behavior changes so older
documents are discoverably out of date.

## Rollout Plan

1. Documentation-only commit.
2. Preset/settings data model and APIs.
3. Import preset selector and snapshotting.
4. Deterministic text cleanup engine with tests.
5. Structured table model and extraction tests.
6. Multi-pass visual asset extraction and coverage audit.
7. Asset context and cropped-region model routing.
8. Concordance integration and protection of manual edits.
9. Composition/evidence UI.
10. End-to-end mocked import tests and real smoke test.

## Rollback Plan

- Keep an emergency second-pass disable setting.
- Preserve current import staging, raw extraction, enrichment, search, and
  figure extraction enough that disabling second pass returns to current
  behavior.
- Keep raw extracted text unchanged so cleaned text can be regenerated.
- Store removed boilerplate and cleanup decisions as evidence rather than
  destructive deletion.
- Keep branch isolated until tests and smoke checks pass.

## Testing Strategy

- Settings tests for preset CRUD, default preset selection, built-in preset
  protection, Save All dirty state, and tooltip payloads.
- Import tests proving staged jobs snapshot presets and later Settings edits do
  not affect staged jobs.
- Cost-routing tests proving Balanced stays capped, Strict Local makes no cloud
  calls, and Deep Review is explicit.
- Text tests for header/footer removal, page-number removal, whitespace
  cleanup, drop-cap repair, bullet preservation, hyphenation, text-art
  suppression, and body-boundary detection.
- Asset tests for embedded images, displayed photos, vector charts, rotated
  pages, full-page scans, duplicate assets, incomplete crops, caption matching,
  multi-figure pages, and missing-asset warnings.
- Concordance tests proving old documents upgrade safely and manual edits are
  protected.
- End-to-end mocked import test verifying preset selection, clean reader text,
  removed-boilerplate evidence, searchable tables, complete visual assets,
  Composition records, and ready document status.

Final verification before merge:

```bash
backend/.venv/bin/pytest
npm --prefix frontend run build
curl -sS http://localhost:3737/api/health
```
