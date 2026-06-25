# Medusa Design And Architecture Record

Last updated: 2026-06-25

This is the living record of Medusa's product, design, and architecture decisions. Future Codex sessions should read this before changing the app and update it when decisions change. Details matter here because Medusa is meant to become a long-lived research system, not a one-off prototype.

## Product Intent

Medusa stands for **Metadata-Enhanced Document Understanding, Search, and Analysis**. It is a local-first research document clearinghouse that should help organize, search, read, annotate, summarize, cite, and reuse research documents across domains of knowledge and project-specific run sheets.

The product is optimized for one primary user on a trusted local network. It still requires password login because HAProxy exposes the app on LAN-accessible HTTPS port `3737`.

Core workflows:

- Stage batch uploads of academic PDFs, HTML documents, plain-text/Markdown files, and textbook excerpts before explicitly releasing them into import processing.
- Preserve original files and process them into searchable metadata, text, summaries, cropped graphic assets, figures, formulas, and citation candidates.
- Run Concordance Runs to bring already-imported documents up to the current extraction, enrichment, citation, tagging, OCR, formula-capture, search, and asset feature set.
- Preserve document layout semantics during processing where they affect meaning, especially two-column articles, tables, and figure/photo/chart placement.
- Organize documents by nested domains, flat tags, read priority, custom attributes, and projects.
- Discover DOI-based related papers for completed documents, enrich open-PDF availability through lawful scholarly resolvers, suppress already-known recommendations from the default discovery list while preserving an audit view, classify relation families, stash useful DOIs for later PDF follow-up, and queue open-PDF recommendations through the normal import pipeline.
- Keep ambiguous metadata and citations visible in Queue instead of pretending uncertain output is verified.
- Build project run sheets with resource status and exportable APA/BibTeX/RIS/CSL bibliographies.

## Design System Direction

Medusa should feel like a serious research cockpit: dense, calm, polished, and fast to scan.

Typography should reserve compact, heavier treatment for controls, interaction chips, and button-adjacent metadata. Section subtitles, metric labels, table headers, usage ledgers, and ordinary panel copy should use sentence/title case or source text casing with moderate weight so repeated operational surfaces remain readable. Normal UI text should not drop below 12px; smaller treatment should be avoided unless it is icon-only-adjacent decoration that remains legible under browser zoom.

Workspace navigation and ordinary action buttons share the same regular-weight control typography so commands do not read smaller, bolder, or visually weaker than the main Library/Domains/Projects navigation. Navigation keeps a generous hit area, while ordinary action buttons use leaner padding and a 38px control height so dense work surfaces do not feel puffy.

Domain references in dropdowns, picker lists, checklists, chips, saved-search summaries, note links, Settings scopes, and other non-tree lists should render the full hierarchy path such as `Parent / Child / Topic`; dedicated tree views may use indentation, quiet connector elbows, and the selected path detail.

Current UI architecture:

- Fixed top header with the Medusa emblem, global search, a reserved active-work progress control, optional release upgrade action, icon-only Status action, theme toggle, and session action. The active-work slot keeps its width while idle so the header does not jump when imports, Concordance, citation refresh work, or release prompts start, but it must shrink and ellipsize before it can collide with the global search field under browser zoom. The release action appears as a compact accent-colored `Upgrade Now` button to the left of the day/night theme switch when a host-side status check reports newer pushed code or when the running server build is newer than the browser bundle. The icon-only Status action opens `/status`, showing the Medusa acronym plus version, commit hash, uptime, memory and disk footprints, database size, runtime versions, proxy state, and storage path details from existing authenticated status APIs. Starting an upgrade warns that unsaved edits will be discarded, locks the initiating browser tab behind a release progress overlay, waits for the host agent to report completion and for `/api/health` to answer, then reloads into the new browser bundle before returning control to the user.
- The app shell treats idle resource use as a first-class UX constraint. Header and navigation badges come from compact dashboard counts instead of whole-list polling, heavy workspace datasets are fetched only when their workspace is visible, and fast polling is reserved for active imports, Concordance, backups, or release upgrades.
- Horizontal work navigation replaces the old left sidebar: Library, Domains, Projects, Tags, Queue, Notes, Import, Stashes, Budget & Costs, Utilities, and Settings are laid out left-to-right in the former dashboard-metric strip, styled as quiet no-background links with Settings pushed to the far right. Each top-level workspace has a canonical browser path (`/library`, `/domains`, `/projects`, `/tags`, `/queue`, `/notes`, `/import`, `/stashes`, `/budget`, `/utilities`, and `/settings`) so pages can be bookmarked, opened in a new tab, and restored on refresh. The Status page has its own bookmarkable `/status` path but is reached from the top-right icon rather than the horizontal work navigation. Document focus links use `/documents/{document_id}` and open Library with that document selected in the detail pane; `/document/{document_id}` is accepted as a compatibility alias. Top navigation assigns single-letter shortcuts when focus is not inside an editable control: `L` Library, `D` Domains, `P` Projects, `T` Tags, `Q` Queue, `N` Notes, `I` Import, `A` Stashes, `B` Budget & Costs, `U` Utilities, and `S` Settings; top-nav tooltips show the shortcut on a second line.
- Main Library view uses a tri-pane layout:
  - Resizable left filter pane for domains, tags, smart filters, saved searches, and a Title Cleanup utility under the Domains tree. The pane has a content-aware minimum so select controls and their affordances remain visible. Library document rows can be dragged onto left-pane domain rows to add that domain assignment, with dashed ready states, hover/release feedback, and assigned-state indicators. Title Cleanup trims leading/trailing title whitespace and collapses repeated title whitespace across active documents, using the same async button feedback treatment as Refresh and Concord actions.
  - Center dense document results with selected-document bulk edit controls. Results render alphabetically by title ascending, and the default Library document query returns the full filtered active result set so the row count matches the navigation Library count instead of silently stopping at a page-size cap. Library filter and bulk dropdowns use compact searchable custom pickers with Enter-to-select/toggle behavior, capped visible option lists, fixed floating menus that do not resize or scroll-shift panes, and stable trigger widths so background refreshes do not shift the toolbar. Domain and Project bulk controls are multi-selects; when exactly one document is selected, they reflect and edit that document's existing memberships. Tags can be typed and added to the pending bulk selection from the picker. The selected-document Concordance button above the list is intentionally removed for now; document-level and Settings Concordance entry points remain. Document rows use visible-but-quiet alternate shading when enabled, true black/white title text by theme, first-paragraph inline summary excerpts, fixed aligned byline columns for page count, publication year, and author list, and a fixed metadata column that stays quiet for normal states. Library list rows omit normal `Ready`, `Verified`, `Normal`, and `Low` badges; they show only elevated priority, duplicates, non-ready/non-verified states, and a quiet `No DOI` chip when no DOI is recorded.
  - Resizable right document detail/correction pane for authenticated original PDF preview, normalized one-page parsed text reading and editing, color-tinted domain chips listed before inline alphabetical TAGS chips with remove controls, a separate domain Assign picker row that lists all domains with counts, an end-of-list add field, and a Tag Refresh action, DOI Copy/Edit/Refresh controls, APA Reference List and APA In-Text Citation sections, generated Summary Copy/Edit/Refresh controls, Bibliography Copy/Refresh controls, Accessory Summaries, existing annotations, extracted figures with relabel/description correction and delete controls, attributes, complete edit history with version stepping and Restore as Current, evidence, and Composition. Clicking Edit for document metadata reveals the correction form and focuses the Title field. DOI keeps its compact value-chip styling; DOI Refresh queues citation refresh so DOI/Crossref discovery can run even when no DOI is currently stored, and Edit lets the user provide a DOI manually. Citation sections show Copy, Edit, Refresh, and compact model/provenance controls that display the model name or `user provided` without repeating field-label text. Summary Edit uses Markdown-oriented rich-text controls for bold, italic, underline, bullet/numbered lists, indentation, and formatting removal while preserving line breaks; Summary Refresh queues a summary-only Concordance run using the selected Summary model. Bibliography Refresh queues a forced document-scoped `bibliography_extraction` Concordance run so the current source reference list can be re-extracted from parsed pages/PDF evidence on demand, then the selected Bibliography Cleanup model formats it as APA-sorted Markdown sources, one per line, with personal authors inverted to `Surname, Initials.`, entries sorted by first-author surname, and intelligent grouping and italics preserved; broad unforced Concordance still protects existing bibliography text from silent overwrite. Tag Refresh queues a forced `tag_refresh` Concordance job for the current document, confirms that existing tag assignments will be removed, then reruns import-style Tag Suggestions and governance with existing-tag reuse before creating any new candidate. Default generated document summaries and Accessory Summaries are prompted as complete-sentence technical paragraphs written at a graduate academic level suitable for a master's-degree reader that begin with the paper's broad facts and purpose, provide key findings and concrete facts early, avoid starting sentences with prepositions, then summarize main points, ideas, methods, findings, and concepts without bold, italics, bullets, em dashes, fancy quotes, standalone headings, single-word openings, or leaked schema metadata unless the user explicitly asks for another format. Accessory Summaries are user-prompted focused summaries queued as durable worker jobs and displayed inline with optional titles. Composition opens as a near-fullscreen modal with a compact left summary rail for persisted estimate-vs-actual cost comparison, import cost composition, provider spend, local processing time, and processing issues, plus a larger right-side React Flow pipeline workspace whose connected nodes follow import execution order. The normal desktop layout should avoid whole-modal vertical scrolling by spreading content horizontally and reserving most of the available area for the pipeline; narrow viewports may stack and scroll as a fallback. The pipeline includes second-pass import stages such as OCR audit, page normalization, structured-table evidence, visual extraction/context, bibliography extraction, and downstream model work with the models/preset active at processing time; later Concordance Runs append their own capability and model-call nodes instead of being folded into the original import path. Library annotation creation controls are deferred pending a quieter pane-aware redesign.
- Library Reader mode can expand the selected document to the whole lower work area while preserving document controls, PDF/Text/Compare tabs, citation actions, the annotation list, and metadata sections. Expanded Reader dedicates the first visible frame to the document header, action row, tabs, and active PDF/Text/Compare surface so the PDF preview and parsed-text editor fill the remaining window height before metadata sections continue below. In the normal detail pane, document preview actions are grouped as Reader/Edit/Link, then Related/Composition/Concord/Formulas, then Download Original/Open Original; in expanded Reader mode the same actions sit on one row with the far-right Close control preserved. The Formulas action queues only the manual `formula_capture` Concordance capability for the open document. Escape closes the expanded Reader when no smaller Medusa-owned popover, dialog, menu, tooltip, or expanded editor/composer is active; those smaller surfaces close or collapse first. Download Original streams the authenticated PDF as an attachment with a filename rendered from the Settings Download Naming template. The compact detail-pane PDF preview renders only the focused page so it stays a preview rather than a full-document scroll strip. Expanded Compare mode shows authenticated rendered PDF page images beside the extracted page text editor. Full-document PDF scrolling remains the authoritative way to move quickly through pages and updates the parsed page from the visible PDF position; text-side synchronized scrolling is bounded to the current PDF page so a parsed page with more text height than the rendered PDF can still be read to the bottom without causing an automatic page advance. Page previews render at 2.5x scale. The PDF preview footer includes a page-number field and Scan Page action that runs a local one-page visual pass for figures, tables, graphs, photos, diagrams, and other visual assets; the field follows Medusa's expanded rendered-page scroll surface, and manually committing the field jumps the preview to that page. Scan Page returns review candidates without mutating the document, displays page-map boxes plus 300 DPI candidate thumbnails, supports multiple candidates on the same page, and only replaces that page's stored figure rows when the user chooses Keep selected; Discard clears candidates without changing figures. Stored figures remain user-correctable after extraction: the detail pane can patch figure labels, captions, and searchable gists or delete extractions, rebuilding document search and recording history/composition entries. Open Original remains the native authenticated PDF route for browser PDF controls. Parsed-text reading keeps page navigation and Copy/Edit controls at the top and bottom of the text pane; Markdown-looking pipe tables render as quiet scrollable tables in read mode, and recognized LaTeX formula delimiters render as math while Copy/Edit preserves the underlying normalized text. While editing, the bottom strip switches to Save/Cancel. Text edit mode has a below-editor tool strip whose first action is Scrub; when text is selected, Scrub counts exact matches across the document and removes that string from all normalized page text as one audited edit.
- Completed DOI-bearing documents and documents with extracted source Bibliographies expose a Library detail Related modal that uses most of the viewport instead of a compact popover. The modal loads any cached related papers and, when empty, automatically refreshes from scholarly metadata services and locally parsed bibliography references. Stored `Document.bibliography` entries can seed DOI/title candidates with raw reference evidence, then run through the same enrichment, ranking, duplicate-suppression, and stash/import flow as provider candidates. Recommendations default to Discover / Diverse, which hides library-held, active-import, queued-import, and already-stashed DOI candidates while preserving Already Known and All audit views. Relation filters cover Diverse, Closest, Newer, Foundational, Methods, Contrasting, Open PDF, and Reference Material. The modal groups provider-discovered non-bibliography results as Other Related Articles and the source document's extracted reference list as Bibliography Sources; bibliography sources keep their raw citation text visible and attach enriched recommendation actions when a source has been parsed into a recommendation row. Recommendation rows show title, DOI, venue, year, source, short abstract/description, compact evidence chips, known-item suppression reason when applicable, and open-PDF availability without card backgrounds. Row actions sit below the item text and support copying just the DOI, copying the title, copying source bibliography text, stashing the DOI in Stashes, opening the source, opening a manual Google Scholar search in a new tab, and queueing selected or all discovery open PDFs for import.
- Stashes view lists saved related-paper DOIs as sortable rows. Each row can copy the DOI, copy the paper title and then open the DOI at Sci-Hub in a new user-opened window by appending the DOI to `https://sci-hub.box/`, resolve and import an open-PDF copy through DOI metadata sources, upload a PDF through an Upload PDF button, or use a compact dashed "Drag PDF Here To Upload" target. Uploads and resolver-backed DOI imports create normal import batch/job records immediately, and successfully imported stashes can be removed from the list. Stashes are also marked imported/removable when any ready Library document has a matching normalized DOI, high-confidence title match, or both, even if that document arrived through another import path.
- Import view centers drag/drop staging for PDF, HTML, and plain-text/Markdown files plus a batch-defaults intake panel for optional label, priority, read status, domains, tags, projects, and the selected import-processing preset. Domains, tags, and projects use searchable chip pickers with restrained inline creation so bulk uploads can be organized before files are dropped. Non-PDF uploads are parsed for source semantics, converted locally to PDF, and stored as PDF mezzanine originals so preview/download/storage paths stay uniform. The processing preset defaults to Balanced from Settings, can be changed before staging files, and is snapshotted onto the batch/job so later Settings edits do not change queued work.
- Import view also provides active drop-target feedback, duplicate-decision handling, live staged/processing job rows, persisted rough per-file dollar estimates, a staged/queued grand-total estimate, a Process Uploads button that releases all staged rows into the worker-claimed import pipeline, and a Clear Staged button that discards staged uploads before processing by deleting their queue-only document/job records plus managed cache/original storage objects. Staged estimates use the selected Import Processing preset snapshot, known model-pricing history, prior import usage exemplars when available, and prior estimate-vs-actual calibration. Estimate metadata records step-level local/pending/model-backed components so capped page normalization, shared metadata/summary/citation/tag/embedding work, local cleanup/bibliography/visual extraction, and pending OCR/visual model routes are distinguishable. Staged rows are durable queue records, but their document rows are not Library-visible until processing completes: they must not appear in Library lists/search, dashboard document counts, domain/tag document counts, project bibliographies, recommendation existing-library matches, or Concordance scopes. Rows shade left-to-right with per-file progress while showing bold status, an animated processing/import glyph near the status when work is active, current model, known or rough spend, row retry when recoverable, and a horizontally separated row Cancel action for staged/queued/failed/restored work. Import > Processing orders visible rows active-first so running jobs and their progress details stay visible during large batches, then shows failed/restored, queued, staged, and recent completed rows. Completed rows stay visible briefly, then disappear from that panel after 15 seconds while remaining durable backend history.
- The reserved header active-work control shows import progress first when imports are active, including current known dollar spend so far, otherwise active Concordance/citation background work. It is visually hidden when no work is active, keeps its wider layout slot reserved, and clicking it opens Queue.
- Domains view is the domain-tree management surface. It provides a searchable alphabetized tree, top-level or nested domain creation, selected-domain editing for name, parent, description, tag associations, and color, child creation, soft delete with confirmation, a direct list of documents assigned to the selected domain, and deterministic suggested filing candidates from the library. Parent domain rows display direct document count first and descendant document count in parentheses, for example `0 (5)`, so direct filing and child-folder totals remain distinct. Suggestions use domain tags/name/description against document tags/title/summary/citation text and must exclude documents already assigned to the selected domain or any descendant domain. Domain descriptions and associated tags are domain-level classification hints for filing suggestions; they do not silently expand assigned-document search text. The Domain Tags editor suggests existing tags from the selected domain description and the tags attached to suggested filing documents, but adding those suggestions remains user-approved and draft-only until the domain is saved. The same tag picker accepts pasted comma/semicolon/newline-separated tag lists, maps exact normalized names to existing tags where possible, and shows matched, skipped, and unmatched values for approval before updating the draft. Top-level domains and every nested sibling group are displayed alphabetically by name.
- Projects view supports project creation, run-sheet resource management, status/priority/used tracking, project notes, and bibliography generation, with run-sheet controls constrained to their pane so long document titles cannot spill into bibliography controls. Bibliography generation controls live in the Bibliography panel, all-sources and used-only generation actions stay side by side, and APA output renders Markdown italics on a white full-width bibliography surface while BibTeX/RIS/CSL JSON remain preformatted.
- Tags view supports tag management as a sortable, searchable table with document counts, governance status, row selection, shift-click range selection across the current visible sorted/filtered rows, and a left-aligned operation toolbar for Clear Selection, Rename, Merge, Delete, and Optimize. User-facing tags are flattened: keyword/topic distinctions are not exposed in the Tags view, import defaults, or document panes. Rename works for exactly one selected tag. Merge is enabled for two or more selected tags, displays the selected count in the button label, and opens a confirmation dialog where the user chooses a selected tag to keep or enters a different merged tag name. Merges remember normalized source tag names as aliases for the kept tag so future import, Concordance, manual, and bulk tag-name creation resolves old merged labels to the current canonical tag instead of recreating deleted source tags. Optimize opens a right-side governance plan pane and uses the same Settings-selected Tag Suggestions model that import uses for tag creation, plus deterministic analysis, to review the selected tags, or the currently visible filtered tag list when nothing is selected. The pane shows a top progress strip with model, scope, and elapsed time while the synchronous plan request is building. It returns deeper cleanup plans with strict primary merge suggestions, looser single-document cleanup merges, orphaned zero-link tag merge/prune suggestions, semantic relationship suggestions, candidate/canonical status suggestions, and weak document-tag assignment pruning suggestions with rationale, confidence, model label, source tag counts, and affected-document counts. Broad scopes larger than the 300-tag model inventory cap skip the model planner and return a local deterministic governance plan with a local broad-scope plan summary indicator. If the model planner is unavailable or fails on narrower scopes, Optimize still returns deterministic local governance suggestions and marks the plan summary with a model-planner fallback indicator instead of failing the whole request. Optimize is intentionally allowed to flag low-use and legacy singleton tags for downgrade, retirement, merge, or pruning because older imports created many canonical one-document labels before governance scoring existed. It should still return governance actions for scopes made only of zero-use and one-use tags even when no merge candidate exists: true zero-link orphan tags should merge into a useful used tag when deterministic variant/prefix/semantic checks find a strong target, otherwise they are prune-entirely candidates; one-use candidates without durable evidence are retire candidates; one-use canonicals are downgrade candidates unless low-value or near-duplicate enough to retire; and singleton assignments without scoring history are prune-review candidates. No optimization is applied until the user approves a suggestion. The plan pane supports individual approvals and an Approve All action for the current plan; batch approval applies merges first, then orphan prunes, semantic relationships, status changes, and assignment pruning, shows a top in-pane progress strip while the bulk request is running, and reports stale skipped actions when earlier merges remove tags referenced later in the plan. Approved merge suggestions call the normal audited merge endpoint; approved orphan pruning deletes a tag only when it has no document links at all; approved assignment pruning removes one document-tag link with `DocumentVersion` history; approved relationships and status changes teach future import scoring without silently rewriting documents. The general Delete toolbar control remains reserved pending broader implementation.
- Queue shows staged/queued/running/failed/restored import jobs with the same shaded per-job progress rows, current model, known or rough spend, stage detail, animated status-side processing glyph when active, right-aligned retry slot, and spaced row Cancel action used by Import > Processing. Queue bulk actions include Process Uploads, Retry Failed, Clear, and Clear Failed, and the header shows the rough staged/queued upload total. Cancel and Clear park staged, queued, failed, and restored-paused import rows as `cleared` but leave fresh running worker locks alone; failed recommendation download rows that happened before a document exists remain visible until canceled/cleared but cannot be retried because there is no stored document to reprocess. Citation cards use the owning document title, source/provenance chips, a constrained citation preview, and attached accept/reject actions so long titles and provider labels cannot collide.
- Notes view supports notes/reminders attached to documents, domains, projects, or the general library.
- Budget & Costs exposes AI usage exploration with last-day, last-month, last-3-months, and all-time windows in a constrained analytics workbench rather than a full-monitor spreadsheet. It uses a command strip for period/metric/group controls, compact metric tiles, a cost trend line over calendar day/hour rollups, cost-by-model and token-by-task pie charts, a tightly columned rollup table, and a recent-call ledger panel. Model, task, document, calendar-day, and calendar-hour rollups remain available when usage records include model/document data. Utilities exposes a Database section for authenticated maintenance actions: Compact Database runs PostgreSQL `VACUUM (FULL, ANALYZE)` to reclaim database space where possible, Optimize Database runs `ANALYZE` to refresh table statistics, and Clear Import Cache removes terminal hidden import rows plus stale project-resource links that are excluded from Library and Queue active surfaces. The Clear Import Cache button shows the current hidden import-document count. Utilities also exposes full database backup/restore controls, legacy metadata JSON/storage-manifest export links, a Container Footprint section backed by `/api/utilities/container/status`, reporting backend-container cgroup memory/CPU, service uptime, process/thread counts, data-volume disk usage, path-level footprints for Medusa-managed storage directories, runtime versions for HAProxy/backend/frontend binaries and packages, and Docker image/layer sizes when the Docker Engine socket has been deliberately mounted into the backend container. Compose does not mount the Docker socket by default because even a read-only socket bind grants the backend process broad host Docker control. Below it, HAProxy Statistics reads `/api/utilities/haproxy/status` and reports the HTTPS endpoint, frontend/backend status, sessions, traffic, health-check detail, and proxy error totals from HAProxy's internal CSV stats feed. The Container Footprint section can restart the backend container through `/api/utilities/container/restart`: the endpoint schedules a backend process termination after returning, the Compose backend service has `restart: unless-stopped`, and the frontend polls `/api/health` until the backend is healthy again. Settings exposes preferences, citation convention selection, Library alternate-row shading, day/night accent color controls, Download Naming for original-PDF attachment filenames, import-processing presets, preset-specific model routing, shared raw extraction/document-analysis model defaults, model-pricing refresh status and stale-pricing warning, GCS bucket configuration, managed Google service-account upload/status, document cache budget controls, and Concordance controls. Import Processing settings must show each pipeline step with an enabled state where applicable, the actual route and model/provider used by the selected preset, core parameters, sensible defaults, and a tooltip explaining exactly what happens and what the step accomplishes. Shared model defaults live inside Import Processing so users can see how Balanced, Strict Local, Deep Review, or a custom preset combines preset-specific model routes with global metadata, summary, citation, tag, normalization, raw extraction, manual formula-capture, and embedding defaults. Settings places Save All controls at both the top and bottom of the view, and each Save All action persists all preference groups together; uploaded service-account JSON and model-pricing refreshes are saved through their own authenticated actions. Navigating away from dirty Settings through Medusa's internal navigation asks whether to save first; accepting runs the same Save All operation before leaving.
- Full database backup and restore are browser-driven from Utilities, including a one-row GCS backup selector plus Restore Database action, a total-size readout for all listed GCS backup dumps, and a recent backup/restore history list so prior runs remain visible after a new backup completes. Browser restore uses selected GCS backups only and requires confirmation before queuing; legacy metadata restore remains CLI-first: dry-run by default, explicit `--apply`, and intended for JSON export drills or partial fresh-database recovery.

Visual decisions:

- The header brand uses the user-provided transparent Medusa emblem SVG plus a large lowercase `medusa` wordmark in Century Schoolbook Bold, falling back to compatible local serif faces. The emblem is borderless and sized to visually match the wordmark height. Hovering or focusing the emblem/wordmark shows the acronym expansion: "Metadata-Enhanced Document Understanding, Search, and Analysis."
- The header brand lockup should have restrained, generous top/bottom padding plus modest side padding so the emblem and wordmark breathe without turning the header into a hero element.
- The browser page title is lowercase `medusa` at rest and becomes `medusa (local)`, `medusa (local: IP)`, or `medusa (remote: IP)` after startup/runtime location detection, depending on how the page is opened.
- The browser title stays lowercase and contextual: top-level workspaces render as `medusa | Workspace`, selected documents render as `medusa | DOCUMENT_TITLE`, selected projects as `medusa | PROJECT_TITLE`, and equivalent management surfaces use the current selected domain/tag when available.
- The top header does not display a build/version stamp. The login panel shows the frontend build stamp under the form in muted text, and both Status and Utilities report the same stamp in runtime metadata so the running UI can be identified without developer tools. The stamp uses `YYYYMMDD (HASH)`. `MEDUSA_BUILD_VERSION` can explicitly set the full stamp for server releases; otherwise `MEDUSA_BUILD_DATE` and `MEDUSA_BUILD_HASH` can override the parts, and local builds use the current date plus a build-content hash when those values are blank.
- The emblem source remains black with transparency; night mode inverts it with CSS so the glyph reads light while keeping the transparent background intact. The same SVG is used as the browser favicon.
- The primary navigation should not consume a persistent left rail. Top-level destinations belong in the quiet horizontal work navigation so the research panes can use the full application width.
- Day mode uses cool white surfaces, slightly darker gray backgrounds/borders for contrast, ink text, restrained blue primary actions, teal success, amber warnings.
- Night mode uses charcoal surfaces, high-contrast text, blue/teal accents, and soft borders.
- Avoid loud gradients, marketing-style hero layouts, decorative blobs, or oversized display typography inside the work surface.
- Use icons for actions and navigation where they improve scanning.
- Standard action buttons use restrained rounded rectangles with icon-left labels, blue filled primary actions, and very light secondary actions with visible blue-gray borders. Buttons should size to their content by default rather than stretching across grid panels unless a narrow responsive layout explicitly needs full width.
- Settings fillable fields use white input surfaces against the softer Settings panel background so editable controls are visually distinct from status text, read-only fields, and action buttons. Numeric preference rows should avoid duplicating the current input value as a separate bold label-side summary. Settings section icons sit left-aligned above their header text instead of floating at the right edge of the section title row.
- Buttons that start background jobs should show a soft blue in-flight state with the button's own icon spinning and a slim in-button progress bar while work is active. On success, they should blend to green over 0.20 seconds, hold green for 0.5 seconds, then fade back to their normal button color over 0.2 seconds. Failures still flash red with a concise error popover.
- Interactive controls use app-styled delayed tooltips rather than native browser title bubbles. Buttons, action links, dropdowns, checkboxes, and free-text inputs should explain the action or edit they perform after a two-second hover; disabled controls should keep the action explanation and add the specific reason the control is unavailable.
- Top-level navigation and lightweight status should read as quiet text on the work-surface background, not as button-like cards.
- Keep cards for framed tools or repeated items; do not nest cards.
- Keep cockpit spacing dense and practical; panes should prioritize scanning and repeated work over airy presentation.

## Architecture Snapshot

Runtime shape:

- `frontend`: React + TypeScript + Vite, served internally on port `3737`.
- `backend`: FastAPI API on internal port `8000`.
- `worker`: Python durable import processor.
- `db`: PostgreSQL with `pgvector`.
- `haproxy`: TLS terminator and redirect/proxy on host port `3737`, with internal stats on `8404`.
- `docker-compose.yml` wires all services and exposes only HAProxy on `3737`.
- Backend and worker startup initialize PostgreSQL through Alembic migrations before normal app workflows open.

Data storage:

- PostgreSQL is the system of record.
- Alembic is the schema migration system for PostgreSQL. SQLite tests still use SQLAlchemy metadata creation for fast isolated test schemas.
- Durable originals are checksum-addressed. PDF uploads use the uploaded PDF checksum. HTML and plain-text/Markdown uploads use the uploaded source-byte checksum for duplicate detection and storage addressing, then store a generated PDF mezzanine as the durable original object. Current storage keys use `documents/<first-two-sha256-chars>/<sha256>/<original-filename>` under the configured prefix.
- GCS is the intended original-object store when a saved Settings GCS bucket or `GCS_BUCKET` and Google credentials are configured.
- Local filesystem storage under `data/originals` is the fallback so the app can boot and import without cloud credentials.
- Hand-managed GCS service-account files live locally under ignored `data/secrets`; Compose mounts that directory read-only at `/app/data/secrets`. Settings-managed service-account uploads are written under ignored `data/managed-secrets` with restrictive file permissions and are preferred by GCS, Google Vision, and Gemini/Vertex calls. Google integrations use explicit service-account JSON credentials; routine container runtime no longer mounts or relies on host gcloud ADC.
- The GCS service account needs object-level create/read/list/delete access for the configured bucket and prefix. `storage.buckets.get` is useful for diagnostics, object upload requires `storage.objects.create`, and backup verification is recorded in manifest objects so `storage.objects.update` is not required.
- Processing/document cache lives under `data/processing-cache`, is ignored by git, and keeps local PDF copies for staged/queued/running/failed work plus recently completed imports within the configured document cache budget. For HTML/text imports, this cache contains the generated PDF mezzanine. Clearing staged uploads removes their managed cache files before deleting the staged queue records.
- Default Compose stores PostgreSQL in Docker's `medusa-postgres` named volume, not under the repo's `data/` tree. The repo plus `data/` can travel together for originals, local cache, managed secrets, and model weights, but the live database only travels through backup/restore or an explicit portable Compose override that bind-mounts the database directory to suitable external storage.

Backend modules:

- `backend/app/main.py`: FastAPI app, auth, CRUD/search/import/project/review APIs, DOI stash APIs, and stash-to-import upload handling.
- `backend/app/database.py`: database engine, session scope, Alembic startup migration runner, and SQLite/test metadata fallback.
- `backend/app/models.py`: ORM entities and relationships.
- `backend/app/worker.py`: long-running durable job loop.
- `backend/app/services/storage.py`: GCS/local storage adapter that resolves the saved GCS bucket and explicit Google service-account credentials before falling back to local storage.
- `backend/app/services/analysis_models.py`: canonical raw extraction/document-analysis task registry, default model ids, OpenAI/Google model option lists, grouped option metadata, and task descriptions used by Settings.
- `backend/app/services/document_cache.py`: bounded local PDF cache registration, lookup, storage rehydration, and pruning.
- `backend/app/services/import_sources.py`: upload source classification, HTML/plain-text semantic parsing, and local PDF mezzanine rendering.
- `backend/app/services/extraction.py`: layout-aware PDF text extraction, deterministic page text cleanup, table normalization, and chunking.
- `backend/app/services/ai.py`: OpenAI Responses API document-intelligence extraction, Gemini text-generation routing for selected Gemini models through uploaded service-account Vertex credentials or the Developer API key fallback, PDF-file context for citation-critical OpenAI metadata, routed text-only summary/tag-suggestion calls, compact APA fallback calls for uncertain citations, tag-optimization suggestion calls, optional legacy combined metadata/summary/APA/tag-suggestion calls, page text normalization calls with bounded fallback, embedding adapter, and call-site usage instrumentation.
- `backend/app/services/openai_usage.py`: durable AI usage recorder, model-pricing history maintainer, and Budget & Costs/Settings rollup builder for OpenAI/Gemini token/file-context counts and conservative estimated costs by task, model, document, calendar day/hour, import job, and Concordance job.
- `backend/app/services/composition.py`: per-document import composition ledger helpers, cost summarization, provider rollups, local duration rollups, processing issue tracking, pipeline chart data construction, and active-import cost estimation.
- `backend/app/services/ocr.py`: Google Vision adapter placeholder.
- `backend/app/services/processing.py`: import processing orchestration.
- `backend/app/services/preferences.py`: DB-backed local preferences such as import worker concurrency, Library alternate-row shading, accent colors, Download Naming templates, saved GCS bucket, managed Google service-account status, document cache size, document-analysis model selections, and model-pricing status payloads for Settings.
- `backend/app/services/google_credentials.py`: service-account JSON validation, secure managed-key storage under ignored data paths, and scoped Google credential loading.
- `backend/app/services/concordance.py`: retroactive capability registry, run creation, and Concordance job processing.
- `backend/app/services/figures.py`: embedded PDF figure extraction, durable asset storage, and figure row creation.
- `backend/app/services/exports.py`: authenticated metadata export and durable storage manifest builders.
- `backend/app/services/backups.py`: full PostgreSQL backup/restore orchestration, `pg_dump`/`pg_restore` subprocess handling, zstd compression/decompression, GCS backup object listing/upload/download, checksum verification, and restore safety backup gating.
- `backend/app/services/restore.py`: metadata export validation, dry-run planning, and fresh-database restore logic.
- `backend/app/services/citations.py`: APA/BibTeX/RIS/CSL formatting utilities.
- `backend/app/services/verifier.py`: Crossref lookup, Semantic Scholar/title-search DOI discovery, targeted title web-search DOI fallback, and verification helpers.
- `backend/app/services/recommendations.py`: DOI normalization, OpenAlex/Semantic Scholar/Crossref related-paper adapters, Unpaywall/arXiv open-PDF availability enrichment, recommendation caching/matching, and open-PDF recommendation import queueing.
- `backend/app/services/runtime_location.py`: startup/runtime IPv4 detection and page-title context classification for local, LAN, and remote access.
- `backend/app/tools/restore_export.py`: CLI entry point for validating, planning, and applying metadata restores.

Frontend modules:

- `frontend/src/App.tsx`: current full application shell and views.
- `frontend/src/lib/api.ts`: API client.
- `frontend/src/types.ts`: shared frontend response types.
- `frontend/src/styles.css`: design system tokens, layout, and responsive rules.

Frontend async-work contract:

- The app shell owns user-visible progress for durable Concordance work. Page controls start runs through a shell-level `startConcordanceRun` helper so the request is recorded in shell state before the API call returns.
- The shell reconciles local "starting" jobs with `/api/concordance/runs` and `/api/concordance/jobs` polling data, then renders active work in the reserved header progress slot while work is starting, queued, or running.
- Header progress shows imports first when imports are active, otherwise the first active Concordance/citation background run or an active-count summary. It is hidden but width-preserving when idle and opens Queue when clicked.
- Page-level controls still own their local disabled state, soft blue in-flight button/icon/progress treatment, and transient result flash. Completion blends through green; a failed start or failed watched job flashes red and shows a concise popover error.
- The Library DOI and citation Refresh actions queue a forced `citation_refresh` Concordance Run for the current document. DOI Refresh remains available when DOI is missing so stored text and Crossref/title evidence can be searched; APA Reference List and APA In-Text Citation buttons start the same durable refresh because both citation surfaces are generated from the same citation metadata/model preference. Summary Refresh queues a forced `summary_refresh` Concordance Run for the current document and uses only the selected Summary model. Tag Refresh queues a forced `tag_refresh` Concordance Run for the current document and uses only the selected Tag Suggestions model plus the import-style tag governance scorer. If the user stays on the document pane, the button-level watcher can flash completion/failure; success flashes fade quickly while error flashes remain visible longer. If the user navigates away, the app shell still follows the durable run and displays terminal state.
- Settings, selected-document batch Concordance, and document-level Concordance controls use the same shell-owned starter so navigation away from those pages does not abandon UI reconciliation.
- Import jobs remain represented by Queue rows and the header active-work progress control because their progress is already dashboard-backed; retry, bulk retry, and clear controls use the same transient button-feedback convention.
- Accessory Summary creation writes a durable queued row and then relies on the worker plus selected-document polling to show queued/running/complete/failed state inline in the detail pane. The Summarize button uses the same transient in-flight/success/error treatment as Concordance and citation refreshes while the new row is being queued and tracked.
- Recommendation refresh/download actions are not full Concordance runs today, but their buttons follow the same local success/error feedback convention until recommendation downloads become durable background fetch jobs.

## Data Model

Current core entities:

- `User`, `SessionToken`
- `AppPreference`: local DB-backed operational preferences such as import worker concurrency, Library alternate-row shading, day/night accent colors, Download Naming templates, saved GCS bucket, service-account display metadata/path, document-analysis model choices, and document cache size. Service-account private key material is stored only on disk under ignored managed-secret paths, not in PostgreSQL.
- `Domain`: nestable knowledge hierarchy.
- `Tag`: flat library label. The legacy `kind` column is retained for compatibility but normalized to `tag`; keyword/topic distinctions from extraction are flattened into the tag namespace. Alembic revision `20260620_0013` normalizes existing rows. Tag API responses include an active-document count for management views.
- `TagAlias`: normalized source label remembered from tag merges. The alias points at the current canonical `Tag` so later AI tag suggestions, Concordance refreshes, manual correction tags, bulk tag names, and tag creation resolve an old merged label to the kept tag. Aliases are moved forward when their target tag is merged again.
- `SavedSearch`: named query and filter presets for repeated research views and Concordance scopes.
- `Domain`: nested knowledge organization nodes with name, parent, description, color, sort order, document links, associated tags, and soft delete. Domain tags reuse the flat `Tag` vocabulary through `domain_tags` so future domain-filing suggestions can compare document tags/summaries against domain descriptions and tag metadata. The API enforces no parent cycles, rejects duplicate active sibling names, rebuilds affected document search text when a domain rename changes searchable domain text, records document history for domain rename/delete effects, detaches deleted domains from documents and notes, and moves deleted-domain children up one level.
- `Document`: canonical research object and processing/search state, including generated citation text and the source document's extracted Markdown-compatible `Bibliography` reference-list field when available.
- `DocumentVersion`: metadata correction/history snapshots.
- `DocumentCapability`: per-document completion state for versioned import/concordance capabilities.
- `OpenAIUsageRecord`: per-call OpenAI Responses/embeddings/Gemini usage ledger with document/job/run context, model, task, token counts, cached input tokens, PDF/file-context bytes, status, and recent error text.
- `ModelPricingRecord`: model-pricing history for OpenAI and Google models with provider, model, pricing tier/basis, per-million token rates, optional long-context/Gemini over-200k rates, source URL, observed/check timestamps, and `superseded_at` for price changes. Refreshes update `last_checked_at` on unchanged active prices and create a new historical row only when the rate signature changes.
- `DocumentCompositionRecord`: per-document provenance and cost ledger for imports, Concordance Runs, and edits. Rows record persisted pre-processing cost estimates, second-pass local/import stages, Concordance capability stages, synced model/embedding usage costs, provider/model/method, status, stage ordering, processing warnings/errors, and pipeline metadata. Estimate rows can seed fallback pipeline nodes for configured steps that did not yet have an actual runtime row, while later Concordance rows carry run/job ids in metadata so Composition can append those runs chronologically. The optional `usage_record_id` links back to the raw AI usage row when available.
- `BackupRun`: durable full database backup/restore progress rows with kind, reason, status, phase, progress, GCS object URI, zstd dump checksum, restore source metadata, safety-backup linkage, and error/completion timestamps.
- `DocumentRecommendation`: cached DOI/title-based related-paper recommendations for a source document, including provider/relation evidence, DOI, title, authors, venue, description, open PDF/source URLs, existing-library/import matches, and import status.
- `DoiStash`: saved DOI follow-up rows for related-paper recommendations, including optional title/source evidence, source recommendation/document links, import job/document links, upload filename, status, and soft-delete state.
- `DocumentAccessorySummary`: user-prompted focused summaries owned by a document, with prompt, optional title, selected model, generated Markdown body, status/attempt/lock fields, completion timestamp, and model/evidence metadata.
- `DocumentPage`: raw extracted per-page text, normalized reader text, source, low-text flags, and optional page image URI; the document detail API exposes these pages for the full-text reader.
- `TextChunk`: chunked full text and optional embedding vector.
- `Figure`: extracted figure, chart, photo, and diagram crops with durable asset URIs, page geometry, user-correctable labels, captions, searchable gists, and extraction-scope metadata such as document import or Reader page scan.
- Second-pass state: import-processing presets currently live in `AppPreference`, import batches/jobs/documents snapshot the selected preset in evidence, `Document.bibliography` stores extracted source reference lists, `metadata_evidence.formula_capture` stores manual Concordance LaTeX formula evidence, and `Figure` rows store local visual crops with geometry, labels, captions, source kind, orientation metadata, extraction scope, and local context. Reader page scans append `metadata_evidence.visual_page_scans` entries and processing events so targeted visual rescue attempts remain auditable. Remaining planned entities include layout blocks, first-class structured table rows/cells, durable visual hints/bounding boxes, visual asset candidates, visual audit warnings, and richer figure context/crop-quality records so raw extraction, cleaned body text, removed boilerplate, source reference lists, formula evidence, and derived visual assets can be inspected or regenerated independently.
- `Annotation`: page-aware highlights/notes with color, body, soft delete, and reserved geometry for future PDF overlays.
- `Note`: document/domain/project notes and reminders.
- `AttributeDefinition`, `DocumentAttributeValue`: custom per-document attributes.
- `Project`, `ProjectItem`, `ProjectBibliography`: run sheets, resource status/priority/used tracking, project notes, and citation exports.
- `ImportBatch`, `ImportJob`, `ProcessingEvent`: durable import bookkeeping.
- `ConcordanceRun`, `ConcordanceJob`: durable retroactive upgrade bookkeeping.
- `CitationCandidate`: reviewable citation/metadata candidates.

Important modeling decisions:

- Documents are soft-deleted via `deleted_at`.
- Duplicate detection starts with SHA-256 checksum, but checksum is not unique in the data model because the user can deliberately import an exact duplicate.
- Import duplicate decisions are explicit: skip duplicates, overwrite an existing matching document, or import anyway as a separate document.
- Library views surface exact checksum duplicates with duplicate counts and a duplicate-status filter.
- Citation status is explicit, with `needs_review` as the safe uncertain state.
- Accepted citation candidates apply their metadata/citation to the document, set citation status to `verified`, and create a `DocumentVersion` audit snapshot.
- Metadata evidence is stored as JSON so extraction, Crossref, OpenAI, and future sources can be audited.
- AI usage accounting is stored separately from document metadata in `OpenAIUsageRecord` so cost/debug history survives metadata correction and can include failed calls. The ledger records usage reported by OpenAI and Gemini calls, and future OpenAI rows snapshot the configured pricing tier in usage metadata. Budget & Costs estimates dollars from `ModelPricingRecord` history when available, falling back to the current official-pricing table for the configured `MEDUSA_OPENAI_PRICING_TIER` (`standard`, `batch`, `flex`, or `priority`) plus OpenAI embedding and Gemini Developer API text prices. Usage cost lookup resolves model aliases and timestamp-matches each call to the price row active when the call happened; unknown or unavailable models remain unpriced, and token counts stay the durable source of truth because model pricing, billing tier, regional uplift, discounts, and project access can change outside the app. `DocumentCompositionRecord` is the document-facing provenance layer over that ledger: it preserves the staged cost estimate, actual import pipeline, and stage/model composition later Concordance logic can inspect before deciding whether a document already satisfies a capability/model requirement.
- Author records in `Document.authors` use JSON objects with `given`, `family`, `affiliation`, and `email` when visible. Import and Concordance GPT prompts should normalize semi-obfuscated email forms such as `someone{at}university{dot}edu`, `someone [at] university [dot] edu`, and `someone at university dot edu` into `someone@university.edu`; emails must not be inferred when absent.
- Title-only citation evidence must pass a strong normalized-title match before it is stored as Crossref evidence.
- Crossref evidence may fill missing citation fields such as authors, year, venue, DOI, publisher, and source URL; it should not silently overwrite existing user-corrected fields.
- When AI metadata, local text DOI regex, and Crossref title lookup do not find a DOI, import and `citation_refresh` try Semantic Scholar title lookup and then an enabled targeted `"paper title" DOI` static web-search fallback. Strong title support is required before the found DOI is stored under `Document.metadata_evidence["doi_discovery"]`; the citation path then retries Crossref by that DOI.
- The broader DOI discovery strategy should prefer free, structured metadata services before generic web search. Candidate sources include Crossref REST and Crossref Simple Text Query for reference-string matching, OpenAlex works search and DOI lookups, Semantic Scholar Graph API title/DOI lookups, DataCite Public API for DataCite-registered works and datasets, OpenCitations Meta for DOI/PMID/OpenAlex-linked bibliographic metadata, and PubMed/Europe PMC for biomedical title/PMID/PMCID/DOI matching. DOI.org/content-negotiation and Registration Agency checks are useful after a candidate DOI is found; Unpaywall is useful for open-PDF/source-link enrichment after DOI discovery rather than as a title-to-DOI matcher. Generic targeted web search remains the last fallback and must store compact evidence only.
- APA citations should favor DOI links whenever a DOI can be located and verified. If no DOI can be verified, the citation should prefer a direct stable source link, ideally a PDF or other static document, over a transient search or generic landing page.
- Citation and metadata text from Crossref, OpenAI, PDFs, or user review candidates should be normalized for display and exports, including decoding HTML entities such as `&amp;`, `&quot;`, and numeric character references into their actual characters. `Document.apa_citation` stores the APA Reference List entry; `Document.apa_in_text_citation` stores the APA parenthetical in-text citation. Each has model and source fields so the UI can show the generating model or `user provided` after manual override.
- Recommendation matching prefers normalized DOI equality and falls back only to high-confidence title matches with strong normalized title similarity plus year and/or author support except for exact-title matches. Recommendations may be cached from multiple providers; source/provider evidence is retained so a candidate can be inspected later.
- Recommendation v2 metadata is stored under `DocumentRecommendation.raw_metadata.recommendations_v2` so cached rows can carry relation family, reason chips, known status, hidden reason, diversity score, evidence URL/DOI/PDF fields, and duplicate-suppression basis without a migration-heavy successor table. The listing service recomputes this metadata when rows are loaded so old cached rows and newly staged/stashed/library-matched items stay in agreement. The default ranking uses a maximum-marginal-relevance style pass that balances provider score and open-PDF/DOI availability with diversity across authors, years, venues, providers, and relation families.
- Recommendation and stash DOI imports do not create a parallel processing path. When an open PDF URL is available from a lawful scholarly metadata source or resolver, the download endpoint creates normal `ImportBatch` and `ImportJob` records, stores the PDF through the configured storage adapter, and lets the worker process it like any other PDF. Relatedness currently comes from OpenAlex, Semantic Scholar, Crossref, and locally parsed stored Bibliography references; open-PDF availability can be enriched from Unpaywall and arXiv before recommendations are cached. Bibliography entries are parsed into DOI/title/source-url candidates with raw reference evidence, then pass through the same enrichment, existing-library matching, ranking, and stash/import handling as provider candidates. Provider refresh failures and bibliography seed counts are recorded in the `recommendations_refreshed` processing event payload. Stash Import DOI uses the same enabled DOI metadata and open-PDF resolver sources, records resolver evidence on the queued document, and does not automate downloads from user-opened external lookup pages. Google Scholar is exposed only as a user-opened search link, not an automated scraper, because its search surfaces are not treated as a programmatic recommendation/download source. Recommendations without open PDF URLs remain metadata-only candidates and can be stashed through DOI Stashes.
- DOI stashes are a durable follow-up list for recommendation DOIs that the user wants to revisit later. Stashing is DOI-unique and soft-deleted rows are reactivated on repeat stash. Uploading a PDF from a stash creates the same `ImportBatch`, `Document`, `ImportJob`, cache, storage, and duplicate-skip records as the normal import path, with the stash DOI/source evidence copied onto the queued document. Stash listing syncs completed import-job status and independently imported ready documents by normalized DOI and high-confidence title match so matched rows show as imported and can be removed without deleting the Library document.
- Full-text search data is stored on `Document.search_text`; chunk embeddings live on `TextChunk.embedding`.
- Search and reader copy prefer `DocumentPage.normalized_text` when present and fall back to raw extracted `DocumentPage.text`.
- Manual extracted-text edits persist to `DocumentPage.normalized_text` with `text_source="manual"`, rebuild document search immediately, and record page-level before/after snapshots in `DocumentVersion`.
- Reader Scrub removes the selected exact text from every page's reader/search text, promotes affected pages to manual normalized text, rebuilds search, and records one `DocumentVersion` row with the scrub text, match count, and page-level before/after snapshots.
- Document annotations contribute their body text to `Document.search_text`; deleted annotations are excluded from active document detail and search rebuilds.
- Processing capabilities are versioned so Medusa can tell which documents need a Concordance Run.
- `DocumentVersion` is the complete document edit/audit ledger for user-facing document changes. Manual metadata edits, citation acceptance, import overwrites, extracted-text cleanup, Scrub actions, history restores, and Concordance cleanup that changes document/page fields must write before/after snapshots rather than silently replacing title, authors, citations, page text, tags, domains, attributes, or other mutable document fields.
- Library Title Cleanup is an audited bulk document mutation. It normalizes active document titles by trimming leading/trailing whitespace and collapsing repeated whitespace to one space, rebuilds document search text for changed documents, and writes `DocumentVersion` plus composition history for each changed title.
- Tag rename and merge operations are user-facing document changes. They update document tag relationships, rebuild affected document search text, and append a `DocumentVersion` snapshot for each affected document with before/after tag state plus operation metadata such as old/new tag names, selected source tag ids, target tag id, removed tag ids, and remembered alias names. Tag Merge also writes `TagAlias` rows for selected source names and retargets aliases from tags being removed, preserving transitive canonicalization. Tags also carry governance status (`canonical`, `candidate`, `retired`, or `blocked`), optional definition/use/avoid guidance, and metadata used by import scoring. `TagRelationship` stores approved semantic relationships such as `covered_by`, `broader`, `narrower`, `related`, and `cluster_peer`. `DocumentTagAssessment` records per-document tag scoring decisions with document relevance, library fit, novelty value, overall score, decision, rationale, and import/Concordance job context. Tag Optimize is suggestion-only: it records AI usage for the taxonomy review but does not mutate tags or documents until a user approves a merge, status, relationship, assignment-pruning, or orphan-pruning suggestion. Orphan pruning is a guarded tag-row delete path for tags with no `document_tags` links at all; it nulls historical `DocumentTagAssessment.tag_id` references while preserving candidate-name evidence.
- Restore as Current is the history-undo contract. Restoring a selected version applies the version's restorable document and page snapshots to the live document, rebuilds search, and appends a new `DocumentVersion` row that references the restored version instead of mutating or deleting older history.

## Processing Pipeline

Current import path:

1. User uploads one or more PDFs, HTML documents, or plain-text/Markdown files through `/api/imports/batches`.
2. Frontend calls `/api/imports/duplicates` to classify supported source formats, hash the proposed upload source bytes, and detect exact checksum matches against Library-visible documents, active/recoverable import rows, and files within the same drop. Cleared/canceled queue-only rows are not duplicate sources.
3. If duplicates are found, the user chooses skip, overwrite, or import anyway before `/api/imports/batches` stages the batch.
4. The upload request includes current batch defaults: optional label, domain IDs, tag IDs, project IDs, priority, read status, and attributes.
5. Backend applies the duplicate strategy. Skip creates a completed `duplicate_skipped` job, overwrite reuses and reprocesses the selected existing document record, and import-anyway creates another document with the same checksum.
6. Backend applies batch defaults to each imported document and creates project run-sheet items for selected projects.
7. PDF uploads are stored as-is. HTML and plain-text/Markdown uploads are parsed from the raw source for semantic cues such as title/headline/heading/paragraph/list structure, rendered locally with PyMuPDF into a PDF mezzanine, and recorded with source checksum/provenance plus generated-PDF checksum in `Document.metadata_evidence["source_import"]`.
8. The durable original object written to GCS/local storage is always a PDF: either the uploaded PDF or the generated PDF mezzanine for non-PDF sources.
9. A document-specific local PDF cache copy is saved under `data/processing-cache` and recorded as `document_cache_path`; the original has already been written to GCS/local storage before cache policy applies.
10. `Document`, `ImportBatch`, and staged `ImportJob` records are committed. Each staged document stores an estimated page count and a persisted rough dollar estimate when available so the UI can show pre-processing cost and Composition can later compare the estimate with actual import spend. These pre-import `Document` rows are operational queue records only; they are excluded from Library lists/search, dashboard document counts, domain/tag counts, project bibliographies, recommendation existing-library checks, and Concordance document scopes until processing completes and `Document.processing_status` becomes `ready`.
11. The user presses Process Uploads to promote all staged import jobs to `queued`; worker claims queued jobs and moves them through extraction, enrichment, indexing, and completion. Import processing defaults to 4 concurrent jobs from one worker process and can be changed to any positive value in Settings.
12. Raw PDF text/layout extraction is a Settings-selectable task for PDF-origin documents. The default preference is local Marker, with Docling and PyMuPDF also listed under Local and enabled OpenAI models listed as cloud fallback choices. Marker is installed in the backend/worker image, but its downloaded model weights are stored under the mounted `data/model-cache` path rather than baked into the image. The first Marker run on a machine/cache may download weights; later imports reuse that cache. PyMuPDF remains the bundled no-credential fallback when Marker is unavailable or times out. Docling remains listed as a planned local extractor option until its runtime is wired. HTML/plain-text imports use the parsed source-page text as the first extraction surface instead of re-deriving text from the generated PDF mezzanine.
13. Two-column pages should read down the left column before crossing to the right column, while full-width headers/sections remain in vertical order.
14. Detected tables are converted to Markdown and included in page text so table content is searchable and available to metadata/summarization.
15. Extracted, normalized, chunked, and assembled search text is sanitized before persistence so PDF control bytes such as NUL cannot break PostgreSQL `TEXT` writes or retry loops.
16. Page text is normalized into standard readable paragraph flow. The default mode is local-first `MEDUSA_OPENAI_PAGE_NORMALIZATION_MODE=auto`: normal pages use deterministic cleanup, while low-text or artifact-heavy pages may escalate to the Settings-selected Text on Pages model up to `MEDUSA_OPENAI_PAGE_NORMALIZATION_AUTO_MAX_PAGES` per document. Auto mode sends extracted page text only and does not attach the original PDF per page. `always` restores the older all-pages OpenAI path and may include PDF context when `MEDUSA_OPENAI_SEND_PDF=true`; `never` keeps page normalization fully local. The normalizer must preserve wording/order, headings, labels, captions, citations, equations, lists, tables, and logical flow without summarizing graphics or converting charts/photos/diagrams into Markdown. Page-normalization requests use `MEDUSA_OPENAI_PAGE_NORMALIZATION_TIMEOUT_SECONDS` and fall back locally on timeout/error. Manual reader edits and Scrub cleanup use the same normalized text surface, mark affected pages as manual, rebuild search, and create history snapshots.
17. PDF figure/photo/chart assets are extracted with PyMuPDF as 300 DPI cropped page graphics. Embedded raster images, page image blocks, and vector-drawn graphic clusters are stored through the configured storage adapter and recorded as `Figure` rows with page number, crop geometry, source kind, extraction scope, label, and nearby caption when available. Captions and labels such as `Figure 1.` remain text anchors in normalized page text; the actual graphic remains an asset instead of Markdown. Reader page scans reuse the same local extractor against one selected page and first return selectable review candidates with inline thumbnails and page-map geometry. Keeping selected candidates replaces only that page's figure rows, preserves all other pages, rebuilds document search, and records metadata evidence plus a processing event/history entry; discarding the review leaves the document unchanged. Stored figures can later be relabeled, given corrected captions/descriptions, or deleted as audited manual corrections; each change rebuilds search and records `DocumentVersion` history.
18. Normalized text is chunked for search/embedding, falling back to raw extracted text when needed.
19. OpenAI metadata extraction runs only when `OPENAI_API_KEY` exists; otherwise a low-confidence review record is produced. Metadata extraction asks for visible authors, affiliations, and normalized contact emails and stores them in `Document.authors`.
20. Extraction and async document-intelligence work are split into Settings-selectable tasks: Raw Text Extraction, Metadata, Summary, APA Citation Matching, Tag Suggestions, Text on Pages (Normalization), Bibliography Cleanup, Formula Capture, Text Chunk Encoding, and Accessory Summaries. The compatible internal key for Tag Suggestions remains `keywords_topics`, but persisted output is flattened into tags. Metadata and APA fallback matching default to `OPENAI_MODEL=gpt-5.5`; Summary defaults to `gpt-5.4`; Tag Suggestions defaults to `gpt-5.4-mini`; Bibliography Cleanup defaults to `gpt-5.4-nano` and is used for forced/ad hoc Bibliography Refresh rather than default import; Formula Capture defaults to `gpt-5.4` and is manual-only through Concordance; Accessory Summaries defaults to `gpt-5.4`; Text Chunk Encoding defaults to `OPENAI_EMBEDDING_MODEL` and offers `text-embedding-3-small`, `text-embedding-3-large`, and `text-embedding-ada-002`.
21. By default, document intelligence is routed by task. Metadata extraction may send the original PDF as a Responses API file input when `MEDUSA_OPENAI_SEND_PDF=true` and the file is below `MEDUSA_OPENAI_PDF_FILE_MAX_MB`; summary and tag extraction use extracted text only. `MEDUSA_OPENAI_COMBINE_DOCUMENT_INTELLIGENCE=true` is an opt-in legacy mode that runs Metadata, Summary, APA Citation Matching, and Tag Suggestions as one structured `core_document_intelligence` Responses call using the Metadata model selection.
22. Tag Suggestions output is treated as candidate evidence and then scored by tag governance before tags are attached. The scorer is existing-first, not existing-only: it checks alias memory, governance status, optional definitions, library counts, approved relationships, deterministic lexical similarity, optional cached embedding similarity, near-existing matches, and semantic covered-by matches. Each candidate is scored on document relevance, library fit, and novelty value using title/summary/body support. Strong covered-by or close-match candidates reuse the existing tag; low-value form/generic labels are skipped; near-existing but ambiguous candidates are recorded without creating a new tag. Import may attach at most five scored tags per document and may create at most one new `candidate` tag, and new tags require stronger relevance/novelty thresholds than reused tags. Weak or redundant candidates are recorded but not attached. Import and Concordance both persist `DocumentTagAssessment` rows and document metadata evidence for these decisions.
23. OpenAI Responses calls pass stable prompt-cache keys derived from the document checksum, hashing overlong keys to fit the Responses API 64-character limit, and use `MEDUSA_OPENAI_PROMPT_CACHE_RETENTION` when configured and supported by the installed OpenAI SDK; if that SDK does not expose a retention parameter, Medusa omits the retention hint instead of failing the import. Concordance reruns hydrate original PDFs from the local document cache or durable storage when a task needs PDF context.
24. Each OpenAI Responses, embeddings, or Gemini request records a durable `OpenAIUsageRecord` when usage data is available, including task/model, provider, import, Concordance, or Accessory Summary context, token counts, cached input tokens, PDF/file-context bytes, and failure status. Settings reads `/api/openai/usage` to show totals, task/model rollups, recent calls, and model-pricing status; `/api/model-pricing/refresh` stores the latest enabled model prices and only appends history on price changes. Import queue cost previews model rough per-document cost from page count plus prior import usage exemplars by task/model, falling back to broader task/library rates and then to a conservative per-page default when there is not enough history. When prior documents have both persisted estimates and actual composition costs, Medusa applies a bounded actual-to-estimate calibration factor to future staged-upload estimates.
25. During imports, `DocumentCompositionRecord` rows are written for the staged cost estimate, each local stage, and synced per-call AI usage rows. Rows record stage order, method/model/provider, high-precision known dollar cost, local duration, tokens, status, processing warnings/errors, and pipeline metadata. Estimate rows are not counted as actual provider spend; Composition displays them separately as estimate-vs-actual comparison. Actual provider spend must include every priced usage item, including sub-cent and sub-micro-dollar embedding calls, and the Composition summary can recover current pricing from linked raw usage records when older composition rows rounded tiny costs to zero. Local stages that only have a configured cloud fallback, such as local-first page normalization, must display as local work unless a separate provider usage record shows that the model was actually called. Older documents without rows intentionally show Composition as not available.
26. Stored `rich_summary` text must begin with the semantic substance of the summary itself, not a standalone heading such as `Summary`, `Overview`, `Abstract`, `Synopsis`, or similar, and not with a single-word opener. The AI prompts also request complete-sentence default summaries as technical plain-text paragraphs written at a graduate academic level suitable for a master's-degree reader: the first paragraph states the paper's broad facts and purpose, key findings and concrete facts appear early, sentences avoid starting with prepositions, and subsequent paragraphs summarize the main points, ideas, methods, findings, and concepts without bold, italics, bullets, em dashes, fancy quotes, leaked schema metadata, confidence labels, or review-reason trailers unless the user explicitly asks for another format. Import/Concordance cleanup strips standalone first-line headings and accidental trailing `confidence` or `needs_review_reasons` blocks before persistence.
27. DOI is discovered from AI metadata, local DOI regex over extracted text, Crossref DOI/title lookup with optional first-author and publication-year constraints, Semantic Scholar title lookup, and then the enabled targeted `"paper title" DOI` static web-search fallback. If Crossref evidence is available, missing citation fields are filled from that evidence without overwriting existing values. Title-search DOI evidence is stored on document metadata before Crossref is retried by the found DOI.
28. APA Reference List and APA In-Text Citation text are generated together from the same citation metadata and Settings-selected APA Citation Matching model preference. Reference-list text is generated deterministically from Crossref/document metadata when DOI/Crossref evidence is available. It is marked `verified` only when enough metadata exists and DOI/Crossref evidence is present.
29. When DOI/Crossref cannot verify the citation, Medusa asks the Settings-selected APA Citation Matching model, defaulting to `gpt-5.5`, to generate/check APA Reference List and parenthetical in-text candidates from compact metadata and extracted-text excerpts without attaching the PDF. The result remains `needs_review` unless later verified or accepted.
30. Uncertain citations create `CitationCandidate` review records.
31. Successful jobs retain their local PDF cache copy up to the configured Document Cache Size. Budget pruning deletes oldest non-active cache files and leaves GCS/local original storage untouched.

Second-pass processing status:

1. The first branch deliverable is documentation: `docs/SECOND_PASS_DOCUMENT_PROCESSING.md`, this architecture record, and `TODO.md` define the work before runtime code begins.
2. Import staging records the selected processing preset id and a snapshot of the preset values. Built-in presets are Balanced, Strict Local, and Deep Review. Balanced is the default for Settings and Import.
3. `document_structure_cleanup` runs after raw extraction and before page normalization, chunking, enrichment, search, and asset-context work. It removes repeated headers/footers, page numbers, watermarks, decorative text art, front matter noise, excess whitespace, broken line wraps, bullet/list artifacts, and drop-cap styling artifacts while preserving meaningful body text, headings, captions, citations, equations, lists, and tables. Removed text is retained as evidence but excluded from body search/enrichment.
4. `ocr_fallback` currently audits low-text/scanned page eligibility and records pending-provider evidence. Google Vision is the intended first cloud OCR provider, but OCR execution is not yet wired into the page extraction retry loop.
5. Page normalization stays local for clean pages. Balanced mode escalates only flagged pages to cheap task-specific OpenAI or Google models, capped at 6 pages or 15 percent of pages per document, whichever is larger. Full-PDF or every-page cloud analysis is reserved for explicit Deep Review work.
6. `structured_tables` currently records table-like cleanup evidence in document metadata. First-class table rows/cells, captions, page regions, and source geometry remain planned.
7. `visual_asset_extraction` now runs local extraction for embedded raster images, displayed page-image regions, and vector drawing clusters, recording durable 300 DPI crops with page geometry, source kind, orientation, captions, and basic warnings. Exhaustive full-page scan/table-region coverage, duplicate/incomplete crop audit, and complete axes/legend expansion remain planned.
8. `visual_asset_context` links figures to labels, captions, nearby text, and explicit references such as `Figure 2` today. Cropped-region model calls, searchable visual gists, premium gating, and per-call visual usage/cost records remain planned.
9. `bibliography_extraction` detects References, Bibliography, and Works Cited sections and stores the paper's own reference list in `Document.bibliography` as one newline-delimited source per entry. Import-time extraction remains local by default: it removes numeric/bracketed entry prefixes, folds blank-line gaps and list-marker continuations back into the current reference, and uses PDF span metadata when available so visible italics in the reference list can be preserved as Markdown emphasis. Forced/ad hoc Bibliography Refresh then applies the Settings-selected Bibliography Cleanup model, defaulting to `gpt-5.4-nano`, to make APA-style source grouping, personal-author inversion, first-author-surname sorting, and Markdown italics paramount while still forbidding invented bibliographic fields.
10. `formula_capture` is a manual-only Concordance refinement pass. It uses the Settings-selected Formula Capture model, defaulting to `gpt-5.4`, with extracted page text and original PDF file context when the configured OpenAI PDF-file setting permits it. It captures visible equations and mathematical expressions as LaTeX/MathJax-compatible source in `metadata_evidence.formula_capture`, makes formulas searchable, appends a clearly marked Formula capture block to non-manual parsed page text, and protects pages with `text_source="manual"` from silent overwrite.
11. Composition records second-pass stages, warnings, model/provider choices, local duration, token/file-context usage, and costs where rows and usage data exist. A more explicit preset-snapshot display and richer second-pass warning surfaces remain planned.

Durability decisions:

- Jobs are database-backed and step-oriented.
- Manual batch uploads start as staged import jobs. Staged jobs already have stored originals, cache paths, duplicate decisions, batch defaults, page-count estimates, processing events, and document rows, but workers do not claim them until Process Uploads promotes them to `queued`. Those document rows are not considered library documents until they finish processing; only ready/complete/restored document statuses are eligible for Library, search, dashboard/document counts, project bibliography, recommendation, and Concordance scopes. The Import page Clear Staged action hard-deletes staged-only upload documents/jobs and removes their managed cache files and staged originals from GCS or local storage; if a staged job unexpectedly shares a document with other import history, Medusa falls back to clearing the job without deleting the shared document.
- Processing events are appended for auditability.
- The app must tolerate stop/start without losing queued jobs.
- Worker startup immediately requeues `running` imports and Concordance jobs from the previous worker process. Worker claims also use `locked_at` and `MEDUSA_WORKER_STALE_JOB_SECONDS` as a stale-lock recovery guard.
- The worker keeps an in-process set of active import job IDs so parallel import slots do not reclaim each other's long-running jobs as stale. Restart recovery still requeues interrupted jobs because that in-memory set disappears with the worker process.
- Import jobs checkpoint visible steps before long phases (`extracting`, `normalizing_pages`, `normalizing_page_<n>`, `extracting_figures`, `enriching`, `indexing`, `cleaning_cache`) so Queue does not appear frozen at `stored` during real processing. `/api/imports/jobs` returns queue-like work first plus recent history so active older jobs from large batches are not hidden behind newer queued rows.
- Container shutdown is intentionally restart-safe rather than interrupt-perfect: in-flight import threads may be terminated with the container, and the next worker startup requeues those `running` rows. The current document may repeat its current step to preserve correctness. Page normalization commits each completed page and resumes from persisted normalized pages when possible.
- Import processors should stay idempotent where possible and avoid duplicating pages/chunks when a step reruns.
- Completed jobs may keep local PDF cache copies in `data/processing-cache` within the configured budget. Originals are retained in GCS or the configured local fallback store regardless of cache pruning.
- Failed jobs may keep their processing-cache copy to support retry and debugging and are protected from budget pruning while still active/recoverable.
- After a released import queue drains and there are no queued/running import jobs left, the worker runs PostgreSQL `VACUUM (ANALYZE)` across all tables when Postgres is the active backend. Staged jobs do not count as active import processing for this drain check.

## Concordance Runs

Concordance Runs are retroactive upgrade jobs for the library. They bring already-imported documents into agreement with the current Medusa feature set without requiring re-upload.

Implemented foundation:

- `DocumentCapability` records document-level capability completion state.
- `ConcordanceRun` records scope, requested capability keys, status, and progress counters.
- `ConcordanceJob` records document/capability work items with target version, attempts, errors, and completion state.
- The worker processes import jobs first, up to the configured import concurrency preference, then Concordance jobs from the same durable database queue pattern.
- The frontend app shell tracks started Concordance runs independently from the page that launched them and reconciles progress from run/job polling so navigation does not hide accepted work.
- Settings includes a Concordance panel that can estimate and start scoped runs while displaying current capability/run/job status.
- The document detail pane estimates a current-document Concordance Run before asking the user to confirm the run, while button-scoped refresh actions can target a single capability directly.

Current first capabilities:

- `page_text_normalization` v3: conforms raw extracted page text into standard readable paragraph flow using OpenAI when configured and local cleanup as a fallback; it preserves headings, labels, captions, citations, equations, lists, tables, and reading flow across columns/graphics without converting graphics to Markdown. Concordance reruns use the original PDF context when available.
- `search_index` v3: rebuilds `Document.search_text` from title, authors, visible author contact emails, abstract, summary, extracted Bibliography, APA reference-list and in-text citations, normalized pages, figure labels/captions/gists, notes, custom attributes, tags, and domains.
- `citation_refresh` v4: regenerates Markdown APA 7 reference-list text and APA parenthetical in-text text from DOI/Crossref evidence first, fills missing fields, can discover a missing DOI through Semantic Scholar title lookup or targeted `"paper title" DOI` static web-search evidence before retrying Crossref, records citation model/provenance, and uses compact GPT-5.5 APA fallback only when evidence cannot verify the citation; uncertain output stays in Queue for citation review.
- `summary_refresh` v1: button-scoped capability used by document Summary Refresh. It regenerates only the main `rich_summary` using the selected Summary model, records usage with task key `summary`, rebuilds document search when the summary changes, and keeps broader metadata/tag extraction out of one-off summary refreshes. It is accepted by the Concordance API for explicit Summary Refresh requests but is not included in default all-capability Concordance selections.
- `tag_refresh` v1: button-scoped capability used by document Tag Refresh. It runs only the selected Tag Suggestions model against the current document text, fails before mutating tags when the model route is unavailable, removes the document's current tag links, applies the same existing-first import tag governance scorer, rebuilds search, records `DocumentVersion` history, and is accepted by the Concordance API for explicit document refresh requests but is not included in default all-capability Concordance selections.
- `summary_topics` v8: uses the configured AI adapter to fill missing metadata, visible author contacts, default paragraph-style summaries, and flattened tag suggestions without overwriting user-corrected identity metadata. The default path routes metadata through the high-quality model, summaries through GPT-5.4 text-only calls, and tag extraction through GPT-5.4-mini text-only calls. Tag extraction receives a compact sorted manifest of existing canonical/candidate tags and is instructed to prefer exact existing tags when they fit. Suggested tag names resolve through remembered merge aliases, then pass through the aggressive tag-governance scorer for existing-first/not-existing-only, three-axis relevance/fit/novelty scoring, optional embedding similarity, cluster-aware checks, low-value suppression, near-existing reuse/blocking, semantic covered-by reuse, and strict attachment caps before creating or attaching tags. Concordance `summary_topics` is additive for tags: it may attach newly scored tags but must not evict tags already on the document. Weak assignment removal remains an explicit Optimize pruning approval. Legacy combined `core_document_intelligence` remains opt-in.
- `bibliography_extraction` v1: extracts the source document's own reference list into the `Bibliography` field when a references/bibliography/works-cited section is present, normalizes it as one source per line without numeric/bracketed source prefixes, and preserves Markdown italics when PDF span evidence exposes emphasis. Concordance fills missing bibliographies and protects user-edited values from silent overwrite except for explicit forced document-level Bibliography Refresh requests, which also run the selected Bibliography Cleanup model to produce APA-sorted Markdown entries with personal authors inverted, entries sorted by first-author surname, and intelligent grouping.
- `formula_capture` v1: manual refinement capability that captures visible formulas as page-scoped LaTeX evidence using the selected Formula Capture model. It appears in the Concordance capability picker but is not preselected with the ordinary broad maintenance set and is excluded from backend default capability selection when no keys are supplied. It can also be invoked directly from the open document's preview or expanded Reader action row through a Formulas button that queues only this capability. It appends searchable formula notes to non-manual parsed page text and stores all returned formula entries in document evidence; read-mode parsed text renders recognized LaTeX delimiters as math while edit/copy surfaces preserve source text. Manually edited pages are protected and counted instead of being overwritten.
- `visual_asset_extraction` v2: extracts 300 DPI rendered page-image and vector graphic crops plus embedded-image fallbacks into durable storage and attaches them to document records with geometry, labels, captions, source kind, orientation, and audit warnings. Visible page-image crops are rendered from the page before raw embedded bytes are used so PDF color-space, mask, and decode instructions are preserved. The legacy `figure_assets` capability key remains accepted for older queued jobs.
- `visual_asset_context` v1: enriches extracted assets with caption, heading, nearby paragraph, and explicit mention context without requiring whole-PDF cloud calls.
- `recommendations` v1: refreshes DOI/title related-paper recommendations from OpenAlex, Semantic Scholar, Crossref, and locally parsed stored Bibliography references, enriches open-PDF availability from Unpaywall/arXiv when configured, marks already-present library matches, exposes manual Google Scholar search links, and caches provider/reference evidence without importing full text automatically.

Use Concordance Runs when adding or improving:

- second-pass document cleanup, visual asset extraction, visual asset context, structured tables, formula capture, and OCR fallback
- tag extraction
- layout extraction, OCR, table handling, or figure extraction
- citation verification or formatting
- summaries, aspect-specific summaries, attributes, or notes-derived indexes
- embeddings, full-text search fields, image gists, or other search surfaces

Expected behavior:

- New features must define how they run at import time and how they apply to existing documents.
- Runs should be triggerable for the whole library, selected documents, a domain/subdomain, a project, a saved search, or a filtered result set.
- Current UI supports whole-library, current document, current search text, domain, and project scopes. The API supports selected-document runs through `scope_type="documents"` with document ids.
- Saved-search scopes use `SavedSearch` rows so repeated research views can be upgraded retroactively without re-entering filters.
- Capability versions should be recorded per document or per derived artifact so the app can find missing/outdated work.
- Concordance jobs must be durable, resumable, idempotent, and visible through processing events/progress.
- A run should avoid overwriting user-corrected metadata unless explicitly requested or unless it records a reviewable candidate.
- Before a Concordance Run is queued, Medusa estimates the selected scope/capability cost from current model pricing, page counts, and model routes, and reports planned jobs, same-model no-ops, already queued work, current-version skips, and unpriced routes.
- Model-backed Concordance fields should be no-ops when the document already has successful output for the currently selected model. Capability version alone does not suppress a rerun when the selected model route has changed; same-model history from document fields, metadata evidence, and `OpenAIUsageRecord` is the stronger cost-control signal.
- Ambiguous or low-confidence output should go to Queue for citation review rather than silently replacing trusted data.
- Model changes in Settings affect new work; older documents should be refreshed through Concordance when their derived analysis needs to match the newly selected model set.
- Second-pass Concordance capabilities must protect manually edited page text. Pages with `text_source="manual"` should be skipped, produce reviewable cleanup candidates, or require explicit replacement rather than being silently overwritten.

## Security And Operations

Authentication:

- Single-user password login.
- Session cookies are HTTP-only and backed by hashed session tokens in PostgreSQL.
- Default dev credentials exist only so a fresh local stack is usable. Real use should set `MEDUSA_PASSWORD` in `.env`.
- `MEDUSA_ADMIN_EMAIL` and `MEDUSA_PASSWORD` seed the first admin account only. Once the user row exists, the live login email and password are PostgreSQL account state, and Settings > Account is the supported in-app rotation path.
- Account credential changes require the current password. Password changes hash the new password and revoke other active sessions while preserving the browser session that made the change.

Secrets:

- `.env` is ignored.
- `.env.example` documents expected variables.
- Google service-account JSON files are ignored under `data/secrets`.
- Settings can upload a Google service-account JSON key into ignored `data/managed-secrets/google-service-account.json`; Medusa writes the managed directory as `0700` and the key as `0600` where the host filesystem supports POSIX modes. PostgreSQL stores only display metadata and the managed path, never the private key JSON.
- GCS service accounts must be able to create original PDFs and extracted assets, read them back for preview/export/reprocessing, and delete temporary smoke-test objects when verifying credentials.
- Do not track API keys, service-account JSON, or generated data.

Network:

- The app listens externally on HTTPS port `3737` through the HAProxy service.
- HAProxy terminates TLS for `medusa.home.musial.io`, redirects plain HTTP requests on the same port to `https://medusa.home.musial.io:3737`, and proxies to the internal frontend service on `frontend:3737`.
- Backend, worker, database, frontend, and HAProxy stats are internal Docker services.

Operational settings:

- The active GCS bucket can be saved from Settings as an `AppPreference`. If no saved bucket exists, Medusa falls back to `GCS_BUCKET`; saving an empty bucket intentionally disables GCS and leaves local storage as the active backend.
- Uploaded Google service-account JSON is preferred for GCS, Google Vision, and Gemini calls. Gemini uses the service account through Vertex AI with `GOOGLE_CLOUD_PROJECT` or the JSON `project_id` and `GOOGLE_CLOUD_LOCATION` defaulting to `global`; when no managed JSON is available, Gemini can still use the existing Developer API key fallback.
- `MEDUSA_IMPORT_WORKER_CONCURRENCY` sets the startup default for concurrent import processing. The built-in default is 4, and Settings accepts any positive value while warning that higher values can create a burst of OpenAI calls and cost.
- `MEDUSA_DOCUMENT_CACHE_SIZE_MB` sets the startup default for the bounded local document cache. The built-in default is 1,024 MB, and Settings can change the active value without affecting GCS/local original storage writes. Settings also displays the current `data/processing-cache` footprint rounded to the nearest MB through `/api/document-cache/status`.
- `MEDUSA_RAW_TEXT_EXTRACTION_TIMEOUT_SECONDS` bounds local raw extraction tools such as Marker before falling back or failing the current extraction attempt.
- `MEDUSA_CITATION_TITLE_WEB_SEARCH` controls the targeted `"paper title" DOI` static web-search fallback used by import and citation refresh when local text, Crossref title matching, and Semantic Scholar title lookup do not find a DOI; `MEDUSA_CITATION_TITLE_WEB_SEARCH_TIMEOUT_SECONDS` bounds that request. The fallback stores compact DOI evidence instead of full search pages.
- `MEDUSA_OPENAI_PAGE_NORMALIZATION_MODE` controls page-normalization spend. `auto` is the default local-first mode; `always` sends every page through the configured OpenAI page-normalization model; `never` keeps page normalization local. `MEDUSA_OPENAI_PAGE_NORMALIZATION_AUTO_MAX_PAGES` caps auto-mode cloud escalations per document.
- Docker sets `HOME`, `XDG_CACHE_HOME`, `HF_HOME`, `TORCH_HOME`, and `MPLCONFIGDIR` under `/app/data` so local ML model downloads survive container recreation through the existing `./data:/app/data` volume instead of entering the image. The backend image also installs PostgreSQL 16 client tools plus `zstd` so `pg_dump`, `pg_restore`, and zstd compression match the PostgreSQL 16 server used by Compose.
- HAProxy certificate material lives in ignored local files at `data/haproxy/fullchain.pem` and `data/haproxy/privatekey.pem`. Compose combines them into a runtime PEM inside the HAProxy container; certificate private keys must never be committed. `MEDUSA_PUBLIC_HOST` defaults to `medusa.home.musial.io`, `MEDUSA_ALLOWED_HOSTS` allows that host through the Vite frontend server, and `MEDUSA_HAPROXY_STATS_URL` defaults to the internal `http://haproxy:8404/stats;csv` feed used by Utilities.
- HAProxy and the Vite API proxy use five-minute client/server timeouts so intentionally synchronous long-running API calls, especially Tags Optimize plan generation over broad tag scopes, can finish while the UI progress strip remains visible.
- The active import concurrency, citation convention, Library alternate-row shading preference, accent color preferences, Download Naming template, saved GCS bucket, managed service-account display/path metadata, document cache size, and model selections are stored in PostgreSQL through `AppPreference` and can be changed in Settings without editing `.env`; private credential JSON remains outside PostgreSQL and outside exports.
- Portable deployment logic must distinguish repository data from database data: `./data` bind mounts application files and caches, while the default `medusa-postgres` volume remains host-local Docker state. Moving to another machine should restore a full PostgreSQL dump; running directly from removable media should require a separate Compose override and a reliability warning for slow or flash-style storage.
- Release detection is file-backed so the web backend does not need host Docker or git control. `MEDUSA_RELEASE_STATUS_PATH` defaults to `/app/data/deploy/release-status.json`, and `MEDUSA_RELEASE_REQUEST_PATH` defaults to `/app/data/deploy/release-request.json`. A host-side release agent such as `scripts/medusa-release-agent.py` owns `git fetch`, fast-forward-only merge, Compose rebuild/restart, and health verification. The backend reads the status file and writes a request file when an authenticated user clicks `Upgrade Now`; server systemd units can own the Compose stack, refresh release status on a timer, and consume upgrade-request files outside the container. The signed-in frontend performs lightweight release-status checks on a short idle cadence so newly available upgrades appear promptly, then treats an accepted upgrade request as a blocking release transaction: it polls release status through restart gaps, verifies `/api/health` after the agent reports completion, and reloads the browser when the server is running a newer build than the current bundle.

Safe deletion:

- Documents use soft delete. Original object cleanup is intentionally not automatic yet.
- Original PDFs are served through authenticated `/api/documents/{document_id}/original` responses and should not require public GCS objects. Adding `download=1` returns an attachment whose filename is rendered from the local Download Naming preference; the `.pdf` extension is implicit. The in-app Reader preview renders individual pages through authenticated `/api/documents/{document_id}/pages/{page_number}/image` PNG responses so page-scoped controls can track scroll position and later support geometry hints without depending on browser PDF plugin internals.
- Parsed pages are served as part of authenticated `/api/documents/{document_id}` detail responses for the in-app full-text reader.
- Full database backup/restore routes are authenticated and tracked through `BackupRun`. A manual backup creates a PostgreSQL custom-format dump with `pg_dump`, compresses it with `zstd`, uploads it under `<GCS_PREFIX>/backups/` in the saved/active GCS bucket, then downloads/streams the uploaded object to validate its SHA-256 checksum before marking the run complete.
- Backup object names use `medusa-postgres-YYYYMMDD-HHMMSS-<short-hostname>.dump.zst`; a sibling `.manifest.json` records backup id, object key, GCS URI, compressed size, source database size, SHA-256, hostname, compression/dump format, database identity without password, selected non-secret runtime settings, and safety flags.
- The reserved header active-work control includes backup and restore progress. Backup phases are `initializing`, `dumping`, `compressing`, `uploading`, `verifying`, and `complete`/`failed`; restore phases include `safety_backup`, `fetching`, `checking`, `restoring`, `migrating`, and terminal state.
- `/api/backups/estimate` reports the current PostgreSQL database size and a likely compressed backup size, using the latest completed backup's compression ratio when a manifest has source database size. `/api/backups/gcs` lists all available GCS `.dump.zst` artifacts from the backup folder using manifests and object metadata; Utilities sums those rows to show the total remote backup footprint. `/api/backups/database` starts a new full backup. `/api/restores/database` starts restore from a selected GCS backup. `/api/restores/database/upload` remains an authenticated API recovery hook but is not exposed in the normal Utilities UI.
- Every restore must first create a new full pre-restore safety backup and verify its upload/checksum before the target dump is fetched, checked, decompressed, and applied. Restore uses `pg_restore --clean --if-exists --no-owner --no-privileges`, then runs Alembic migrations so older dumps can be brought to the current schema. The Utilities UI asks for confirmation before creating a restore run. A full database restore can replace session rows, so the browser may need to sign in again after restore.
- Full database backups are true PostgreSQL snapshots and therefore include auth tables such as password hashes and session rows. API keys and service-account JSON are not stored in PostgreSQL and are not written into backup manifests; managed Google key files remain in ignored local data paths and must exist on the restored machine for GCS/Google integrations.
- Full database backup/restore is the supported portability path for the system of record. Copying the repo, `data/originals`, or `data/processing-cache` without a database dump is not a complete library move.
- Legacy backup/export routes are authenticated and intentionally omit API keys, service-account credentials, password hashes, and session tokens.
- `/api/exports/metadata` returns full metadata JSON with organization state, extracted text, notes, correction history, jobs, Concordance history, and an embedded storage manifest.
- `/api/exports/storage-manifest` returns the durable original/page/figure asset URI manifest by itself.
- `/api/openai/usage` returns authenticated usage totals, task/model rollups, recent OpenAI/Gemini call records, pricing status, the active OpenAI pricing tier, and estimated costs for a requested period (`last_day`, `last_month`, `last_3_months`, or `all_time`). Unknown models are counted as unpriced rather than guessed.
- `/api/model-pricing/refresh` records the current enabled OpenAI tier-specific and Google standard-pricing snapshot into `ModelPricingRecord`, updating unchanged rows' `last_checked_at` and appending a new row only when a model price changes. Settings warns when the configured tier's rows are missing or the latest active pricing check is more than two days old.
- `/api/utilities/database/status` reports database-maintenance counts for Utilities, including the hidden import cache count used by the Clear Import Cache button, plus any active or last completed database maintenance operation. `/api/utilities/database/compact` starts PostgreSQL `VACUUM (FULL, ANALYZE)` as a backend-owned background maintenance operation through an autocommit connection and returns immediately with `status: running`; `/api/utilities/database/optimize` does the same for PostgreSQL `ANALYZE`. Utilities polls status while those operations are active and shows elapsed time/detail rather than holding a single long browser request. `/api/utilities/import-cache/clear` removes hidden terminal import document rows, their terminal import jobs, stale `ProjectItem` links, managed processing-cache files, and staged original objects where deletion is available. It must not remove Library-visible documents or staged/queued/running/failed/restored-paused import rows. `/api/utilities/container/status` includes a runtime-version inventory for HAProxy, backend Python/package/system binaries, frontend Node/Vite, the frontend build stamp, and optional current-backend Docker image/layer sizing when `MEDUSA_DOCKER_SOCKET_PATH` points at a mounted Docker Engine socket. `/api/utilities/haproxy/status` returns authenticated HAProxy stats derived from the internal CSV feed and degrades to an unavailable status when the backend is not running inside the Compose deployment.
- `/api/release/status` returns authenticated release status from the host-agent status file plus current runtime identity. `/api/release/upgrade` writes an authenticated upgrade request file when a newer upstream release is available and the host agent marked apply as available. If the server is already on a newer build than the browser bundle, the same status response tells the frontend to reload instead of requesting another deploy; the initiating upgrade flow keeps the UI blocked until that reload can happen after release completion and a passing health check.
- Metadata restore is available through `python -m app.tools.restore_export /path/to/medusa-metadata.json`.
- Restore dry-runs validate schema/safety flags, reject secret-bearing keys, report conflicts, summarize embedded storage-manifest counts, and make no writes.
- Restore applies preserve export IDs by default, restore research metadata and storage URI references, skip auth credentials/session state, and do not restore text-chunk embeddings because metadata exports intentionally omit vector values.
- Restored queued/running import and Concordance jobs are parked as `restored_paused` by default so a worker cannot accidentally replay old backup state. `--reactivate-jobs` exists for deliberate maintenance use.

Verification baseline:

- `backend/.venv/bin/pytest`
- `npm --prefix frontend run build`
- `curl -sS http://localhost:3737/api/health`
- Optional: authenticated dashboard and smoke PDF upload when import behavior changes.

## Current Gaps And Intended Next Moves

Known gaps:

- Alembic initial migration is implemented; future schema changes should add migration revisions instead of relying on metadata-only creation.
- Concordance Run foundation and scoped UI controls are implemented; arbitrary-filter scopes beyond saved searches are still future work.
- Concordance capability coverage is still early; OCR, figure caption/gist enrichment, richer layout upgrades, and arbitrary-filter scope need follow-up implementation.
- OCR path is adapter-ready but not integrated into the page extraction retry loop.
- GROBID/local scholarly parser is not wired yet.
- DOI/source-link resolution is not exhaustive yet. Citation refresh now expands beyond current DOI regex plus Crossref DOI/title/author/year matching to Semantic Scholar title lookup and targeted title web-search DOI evidence, but Crossref Simple Text Query/reference-string matching, OpenAlex, DataCite, OpenCitations Meta, PubMed/Europe PMC, DOI.org/Registration Agency checks, publisher pages, richer source-link selection, and field-level evidence comparison remain future work.
- Anthropic provider routes and local embedding defaults are not wired yet. Gemini text-generation routes are wired through Vertex AI or the Developer API for text-only document-intelligence calls, with provider usage accounting in the existing AI usage ledger. Broader provider abstraction and local embedding evaluation remain future work.
- Figure extraction stores embedded images, rendered page-image crops, and vector graphic crops with local captions/context; AI figure caption/gist enrichment, exhaustive visual audit, and region-aware table geometry are still future work.
- Table extraction is basic Markdown normalization; richer table objects/cell geometry are not modeled yet.
- Original PDF preview/open is implemented through authenticated routes, and normalized parsed page text is available in a one-page reader with page arrows. Geometric text selection/highlight overlay remains future work.
- Saved searches, smart filters, and bulk edit controls are implemented; richer multi-condition filter builders are still future work.
- Metadata correction UI exists for core identity fields, citation status, read/priority state, tags, domains, summaries, custom attributes, and reader text cleanup. Correction history is captured as `DocumentVersion` snapshots and can be restored as the current document state; a fuller field-by-field diff viewer is still future work.
- Notes/reminders exist, but the Notes workspace is not yet a full research-notes system for standalone topics, ideas, concepts, backlinks, and many-to-many document/source links.
- Queue, header progress, backup progress, Budget & Costs, and Composition each expose slices of background work, but there is not yet a unified Activity and Work Ledger across imports, Concordance, recommendations, backups, OCR, embeddings, research runs, and maintenance jobs.
- Related-paper recommendations are present, but they are not yet a durable diverse discovery/acquisition workflow with default already-known suppression, relation-family ranking, provider failure visibility, background downloads, and acquisition wishlist triage.
- Library health issues are currently spread across Library, Queue, Settings, Tags, Composition, and Concordance instead of summarized in a Corpus Health dashboard.
- Auth is single-user only; no roles or sharing model.
- Full database backup/restore is implemented as authenticated Utilities controls backed by GCS, zstd, checksum verification, and mandatory pre-restore safety backups. Legacy metadata JSON exports remain available, and scheduled backup drills/retention policy remain future work.
- Accessory Summaries are implemented for current-document Library detail runs. Batch Accessory Summary prompts across selected documents, saved searches, or Concordance scopes remain future work.

High-value next steps:

- Wire OCR fallback for low-text pages with Google Vision.
- Add exhaustive DOI/source-link resolution, robust citation verification beyond Crossref basics, and richer field-level evidence review.
- Add arbitrary-filter scopes and richer saved-search management for Concordance Runs.
- Add provider abstraction and usage accounting for Gemini, Anthropic, and local embedding routes before changing non-OpenAI defaults.
- Build richer history review/diff UI for manual corrections and imported metadata candidates.
- Add AI figure caption/gist enrichment and include figure gists in richer semantic search.
- Evaluate local BGE-M3 or comparable embeddings against the current OpenAI embedding path.
- Extend Accessory Summaries to selected-document, saved-search, and Concordance-style scoped runs.
- Add richer layout fixtures for two-column PDFs, multi-page tables, and table-heavy papers.
- Add real PDF viewer with highlights/notes.
- Add geometric PDF highlight overlays on top of the current annotation records.
- Add richer multi-condition filter builders.
- Add a unified Activity and Work Ledger for all durable background work.
- Build out Notes into a document-linked and standalone topic/idea research-notes workspace.
- Expand Related into a diverse discovery and acquisition workflow with already-known suppression and wishlist triage.
- Add a Corpus Health dashboard for missing metadata, stale capabilities, failed work, and repair entry points.
- Add scheduled full-database backup drills and retention controls.
- Add Playwright smoke tests for login, import, library search, citation copy, project bibliography, and day/night modes.

## Decision Log

### 2026-06-25: Targeted title-search DOI discovery

Decision: Add Semantic Scholar title DOI lookup and a targeted `"paper title" DOI` static web-search fallback to import enrichment and `citation_refresh`.

Why: Some papers do not expose a DOI in the PDF text and are not recovered by Crossref title search, but the DOI is easy to locate from exact-title search-result evidence. The app should use that evidence before falling back to uncertain APA model output.

Consequences:

- Missing-DOI imports and DOI Refresh first try local text, Crossref, Semantic Scholar title lookup, then targeted title web-search evidence before giving up.
- Strong title support is required before a DOI from web-search text is accepted, and compact evidence is stored in `Document.metadata_evidence["doi_discovery"]`.
- The found DOI is fed back through the existing Crossref and APA citation path rather than creating a separate citation formatter.
- Full exhaustive DOI verification remains future work for Crossref Simple Text Query/reference-string matching, OpenAlex, DataCite, OpenCitations Meta, PubMed/Europe PMC, DOI.org/Registration Agency checks, publisher pages, source-link fallback selection, and field-level evidence comparison.

### 2026-06-25: Host-agent release refresh for portable servers

Decision: Add a file-backed release status and upgrade-request contract for portable server deployments such as carrot.

Why: Medusa should be able to show that newer code has been pushed and offer an authenticated `Upgrade Now` action without giving the web backend broad host control. The server needs a narrow boundary between browser consent, backend state, and host-owned git/Docker operations.

Consequences:

- The app reads `data/deploy/release-status.json` and writes `data/deploy/release-request.json`; both live under ignored runtime data.
- A host-side release agent checks upstream git state, blocks dirty checkouts, fast-forwards only, rebuilds Compose with explicit build identity variables, verifies `/api/health`, and updates the status file.
- The header button appears to the left of the theme toggle, uses the active accent color, uses a Rocket icon rather than Refresh, and confirms before browser reload with an unsaved-edits warning.
- Database portability remains the full PostgreSQL backup/restore workflow; copying `data/` preserves secrets/caches/local originals but not the default Docker named Postgres volume.

### 2026-06-24: Move backup and restore controls to Utilities

Decision: Move the browser-facing full database backup/restore panel and legacy export links from Settings into Utilities.

Why: Backup, restore, and metadata/export drills are operational maintenance actions. Utilities already owns database maintenance, container/runtime inspection, HAProxy status, and restart controls, while Settings should stay focused on saved preferences, credentials, model routing, storage defaults, and Concordance configuration.

Consequences:

- Utilities now shows Database Backup & Restore alongside database maintenance and runtime operations.
- The backup/restore routes, `BackupRun` records, GCS listing, estimate refresh, checksum validation, header progress, and safety-backup gate are unchanged.
- Settings no longer owns backup/restore-specific polling or action state.

### 2026-06-23: Promote Activity, Research Notes, Related Discovery, and Corpus Health

Decision: Promote the Activity and Work Ledger, expanded Notes, richer Related Documents discovery, and Corpus Health ideas into the planned backlog.

Why: These features strengthen Medusa as a dogfood research cockpit before adding more writing-adjacent surfaces. The Notes direction should absorb the earlier Evidence Notebook idea by building a fuller Notes workspace for both document-linked evidence and standalone topic or idea notes that can link to documents.

Consequences:

- Activity should become the unified inspection surface for durable background work while preserving Queue's import/review responsibilities.
- Notes should support standalone topic/idea notes, many-to-many links to documents and research objects, backlinks, search, filtering, reminders, export/restore, and document-detail integration.
- Related should evolve from a simple DOI recommendation list into durable diverse discovery with default already-known suppression, relation-family ranking, provider evidence, background downloads, and acquisition wishlist handling.
- Corpus Health should summarize missing/stale/failed library quality issues and link directly to filtered review or scoped repair actions.

### 2026-06-22: Document tag refresh replaces assignments through import governance

Decision: Add a Library detail Tag Refresh action backed by a button-scoped `tag_refresh` Concordance capability.

Why: The user needs a document-level way to discard stale tag assignments and regenerate tags with the same existing-first process used during import, so near-duplicate tags are not created when an existing canonical or candidate tag already suffices.

Consequences:

- Tag Refresh removes only the selected document's tag links, not the tag rows themselves, then runs the selected Tag Suggestions model and the existing import tag-governance scorer.
- Existing tags, merge aliases, semantic relationships, low-value suppression, near-existing blocking, attachment caps, and the one-new-candidate limit all apply to refreshed documents exactly as they do during import.
- The refresh fails before mutating tag links when the selected Tag Suggestions route is not configured.
- The action rebuilds document search and records `DocumentVersion` history with before/after tag snapshots.
- General `summary_topics` Concordance remains additive for tags so whole-library or broad-scope Concordance does not silently strip manual organization.

### 2026-06-21: Documented second-pass document processing branch

Decision: Develop the import-quality second pass on `codex/second-pass-document-processing`, with documentation as the first branch deliverable before runtime code begins.

Why: The work touches import staging, processing presets, Settings, model routing, text cleanup, OCR, structured tables, visual asset extraction, Concordance, Composition, and tests. Keeping it on its own branch preserves the current import path while the quality and cost model are proven.

Consequences:

- `docs/SECOND_PASS_DOCUMENT_PROCESSING.md` is the branch contract for goals, non-goals, success criteria, default modes, model routing, pipeline order, Settings/Import UX, data/API changes, Concordance behavior, rollout, rollback, and tests.
- Balanced is the default processing preset; Strict Local and Deep Review are built-in alternatives. User-created presets can combine models, caps, thresholds, OCR settings, cleanup toggles, and visual settings.
- Every new import step that is configurable must appear in Settings with a clear tooltip that explains what the step does and what it accomplishes.
- Import must snapshot the selected preset onto staged batches/jobs so later Settings edits do not change queued work.
- New second-pass capabilities must be implemented both at import time and retroactively through Concordance Runs while protecting user-edited text from silent overwrite, unless the product decision for that capability explicitly marks it manual-only. Formula Capture is one such manual-only Concordance refinement and must not be wired into normal imports by default.

### 2026-06-17: V1 scaffold

Decision: Build Medusa as a Dockerized local-first web app with React/Vite frontend, FastAPI backend, worker service, and PostgreSQL/pgvector database.

Why: The app needs reliable metadata/search/jobs beyond SQLite, and the user wants safe stop/start behavior on a laptop with LAN access.

Consequences:

- Docker Compose is the default run path.
- Port `3737` belongs to the frontend.
- Durable processing state lives in Postgres.
- GCS/OpenAI/Vision are optional credentials at boot but first-class integration points.

### 2026-06-17: Citation accuracy policy

Decision: Generate APA immediately when possible, but mark citations `verified` only when enough metadata exists and DOI/Crossref evidence is available. Otherwise use `needs_review`.

Why: Completely accurate citations are a product requirement. Review is safer than silently promoting uncertain model output.

Consequences:

- Queue citation review is a core workflow, not an error state.
- Citation candidates store evidence and confidence.

### 2026-06-17: Quiet cockpit design

Decision: Use a dense cockpit layout with restrained blue/teal/amber status colors and day/night themes.

Why: The app is for repeated research work, not marketing. It should prioritize scanning, comparison, and repeated action.

Consequences:

- Avoid hero pages, decorative gradients, and loud color.
- Prefer stable panes, tables/lists, compact buttons, and evidence panels.

### 2026-06-17: Codex architecture record

Decision: Add `AGENTS.md` and this architecture record as required context for future Codex sessions.

Why: Medusa will evolve through many iterations. A durable design and architecture memory prevents accidental drift and makes future revisions faster.

Consequences:

- Future material changes should update this file in the same change.
- `AGENTS.md` instructs Codex to read this file before architectural/design work.

### 2026-06-17: Layout-aware extraction

Decision: Treat two-column pages and tables as first-class import concerns. Extract pages from layout blocks, detect column clusters, read columns in scholarly article order, and normalize detected tables into Markdown.

Why: Academic PDFs often use two columns and dense tables. Naive text extraction can interleave columns or flatten tables into unusable text, damaging search, summaries, citation inference, and later question answering.

Consequences:

- `backend/app/services/extraction.py` owns reading-order heuristics and table Markdown conversion.
- Search and AI enrichment receive table text as structured Markdown inside page text.
- Future extraction upgrades should preserve or improve this contract rather than reverting to raw `page.get_text("text")`.

### 2026-06-18: Bounded processing/document cache

Decision: `data/processing-cache` is managed local working storage and a bounded document cache. Successful jobs retain cache copies until the configured Document Cache Size budget prunes older non-active files.

Why: Originals still belong in GCS or the configured local fallback store, but keeping recent imported PDFs locally makes Concordance and Accessory Summary runs faster and less dependent on immediate storage reads.

Consequences:

- Queued/running/failed jobs retain cache files and are protected from budget pruning while recoverable.
- Completed jobs remove `local_cache_path`, retain `document_cache_path` when the file remains cached, and record budget checks in processing events.
- Cache pruning does not affect GCS/local original storage writes at upload time.
- Concordance can rehydrate a missing local cache copy from the original object URI when needed.

### 2026-06-17: Conservative title-only citation evidence

Decision: Keep DOI Crossref lookups, but require title-only Crossref candidates to pass a strong normalized-title similarity threshold before storing them as evidence.

Why: Short or synthetic titles can produce plausible-looking but wrong Crossref matches. Evidence attached to a document should help review, not pollute it.

Consequences:

- Title-only matches below the threshold are ignored.
- Verified citation status still requires enough metadata plus DOI or accepted Crossref evidence.

### 2026-06-18: Crossref fills missing citation fields

Decision: Use trusted Crossref evidence to fill blank citation metadata fields during import and Concordance citation refresh.

Why: OpenAI extraction may be unavailable, and local PDF text extraction can miss authors/year/venue even when Crossref has already matched the exact title or DOI. Storing Crossref evidence without using it leaves documents stuck with incomplete APA strings such as `(n.d.). Title.`

Consequences:

- Crossref evidence can fill missing authors, publication year, venue, publisher, DOI, and source URL.
- Existing document fields are left intact to avoid silently overwriting user-corrected metadata.
- Citation refresh can use already-stored Crossref evidence when a live lookup is unavailable.
- Broader conflict comparison and field-level review remain future work.

### 2026-06-18: Normalized page text reader

Decision: Store normalized page text separately from raw PDF extraction and make the parsed-text reader show one readable page at a time with explicit previous/next navigation.

Why: Raw PDF extraction preserves layout artifacts that are useful for debugging but poor for reading. Medusa needs contiguous paragraph flow that follows the original document order without odd spacing, while still preserving raw extraction evidence for reprocessing and comparison.

Consequences:

- `DocumentPage.normalized_text` is the preferred reader/search text; `DocumentPage.text` remains the raw extraction fallback.
- Import jobs normalize page text after layout extraction. OpenAI performs the conforming pass when configured; deterministic cleanup handles whitespace, spaced letters, hyphenated wraps, and paragraph joins when OpenAI is unavailable.
- `page_text_normalization` is a Concordance capability so older imports can be upgraded without re-uploading.
- `search_index` is versioned to v2 because it now prefers normalized page text.
- The document detail text reader displays a single page with visible arrow controls, page counter, page note action, and full-text copy.

### 2026-06-18: Navigation and batch workbench controls

Decision: Replace the left navigation rail with quiet horizontal work navigation, reserve header space for active-work progress, and expose Concordance Runs from selected rows in the document list.

Why: The cockpit should be dense without making passive information look clickable. The research panes need the full available width, and selected-document workflows should support both metadata edits and retroactive processing.

Consequences:

- Primary navigation renders left-to-right above the work surface, with Settings pushed to the far right and no persistent left rail.
- The active-work progress control lives in a reserved header slot to the left of build/version/theme/session controls, so it can appear without shifting those controls.
- The Library bulk toolbar can queue a `documents`-scoped Concordance Run for selected document ids after a custom confirmation dialog warns that model settings can make the run costly.
- The existing Settings Concordance panel remains the place for whole-library, saved-search, domain, and project scoped runs.

### 2026-06-18: Header and bulk tag refinement

Decision: Simplify the header wordmark, align global search with the default Library document-list pane, darken light-mode button outlines, and allow bulk custom tag nomination.

Why: The brand should read as a polished mark rather than a labeled placeholder, the search field should visually belong to the center work pane, and bulk tagging needs to support both known taxonomy terms and newly nominated terms without leaving the document list.

Consequences:

- The `Research Library` subtitle is removed from the header/login brand lockup.
- The Medusa emblem is borderless and larger; the `medusa` serif wordmark is scaled to the emblem height.
- The topbar's default grid offset aligns the global search with the Library middle pane at default pane widths.
- Light-mode secondary/icon button borders use a darker neutral token for better visibility.
- The Library bulk tag selector sorts existing tags alphabetically and includes a custom tag input that creates/applies the new tag through bulk update.

### 2026-06-18: Reader mode and Markdown citation surfaces

Decision: Add an expanded Library Reader mode, render summary/citation fields as controlled Markdown, and expose document-level citation refresh as a live, disabled-while-running action.

Why: The right detail pane is useful for preview and correction, but serious reading needs the full lower work area while keeping controls nearby. APA citations and scientific summaries also need formatting, especially italics and structured summaries, without forcing the user to read raw Markdown syntax.

Consequences:

- The Library filter pane minimum is raised and enforced through persisted pane clamping so select arrows and control text cannot be collapsed out of view.
- Document rows include a short rendered Markdown summary preview instead of leaving summary text as one large undifferentiated paragraph.
- `rich_summary`, `bibliography`, `apa_citation`, and `apa_in_text_citation` remain Markdown-compatible database fields.
- OpenAI extraction prompts now request complete-sentence technical paragraph summaries written at a graduate academic level suitable for a master's-degree reader, with openings that begin with the paper's broad facts and purpose, place key findings and concrete facts early, avoid starting sentences with prepositions, avoid single-word openers or standalone headings, and avoid bold, italics, bullets, em dashes, and fancy quotes unless the user explicitly asks for another format.
- APA formatter output uses Markdown italics for APA publication elements and Crossref volume/issue/page fields when available.
- The document detail and expanded Reader surfaces include APA Reference List and APA In-Text Citation Copy/Edit/Refresh controls. Refresh queues a forced `citation_refresh` Concordance Run for that document and disables while a matching queued/running job exists.
- `citation_refresh` is currently versioned to v4 so existing imports can be conformed through Concordance Runs.

### 2026-06-18: DOI-first citation links

Decision: Make exhaustive DOI discovery the next citation-verification priority. APA citations should prefer DOI links when a DOI can be located; if no DOI is available, use the best direct stable source link, preferably a PDF or other static document.

Why: Citation accuracy includes retrievability. A correct-looking APA string is not enough if Medusa could have found the DOI or a more durable source link with deeper evidence gathering.

Consequences:

- Citation refresh should become more exhaustive than the current DOI regex plus Crossref DOI/title/author/year matching.
- DOI discovery should continue beyond the current document metadata, extracted text, Crossref, Semantic Scholar title lookup, and targeted web evidence path by inspecting references plus free/open metadata sources such as Crossref Simple Text Query, OpenAlex, DataCite, OpenCitations Meta, PubMed/Europe PMC, DOI.org/Registration Agency checks, and publisher pages.
- Every attempted source, conflict, and fallback source-link choice should be recorded as evidence for Queue inspection.
- DOI links should win over source URLs in APA output; stable PDF/static-source URLs are acceptable only when DOI resolution fails.

### 2026-06-19: Cost-routed document intelligence and DOI-first APA

Decision: Route document-intelligence work by task cost and quality risk. Keep citation-critical Metadata and APA fallback matching on `gpt-5.5`, default Summary and Accessory Summaries to `gpt-5.4`, default Tag Suggestions to `gpt-5.4-mini`, default ad hoc Bibliography Cleanup to `gpt-5.4-nano`, and use DOI/Crossref evidence to generate APA citations deterministically before asking GPT for citation fallback judgment.

Why: APA correctness is brittle and citation verification should be evidence-backed, while summaries and organization tags are lower-risk and reviewable. DOI/Crossref metadata can often provide the reference for free once title, authors, year, or DOI are known. GPT should not regenerate what trusted citation metadata can format deterministically.

Consequences:

- `.env` should hold the private API key and `OPENAI_MODEL=gpt-5.5` as the startup default.
- Settings exposes ten extraction/analysis model controls inside Import Processing as shared defaults: Raw Text Extraction, Metadata, Summary, APA Citation Matching, Tag Suggestions, Text on Pages (Normalization), Bibliography Cleanup, Formula Capture, Text Chunk Encoding, and Accessory Summaries.
- Raw Text Extraction uses grouped Settings options: Local includes Docling, Marker, and PyMuPDF with Marker as the default preference; OpenAI includes the enabled GPT model options for cloud fallback choices. Marker is installed in the worker image and uses the mounted `data/model-cache` path for downloaded weights. PyMuPDF remains the built-in fallback; Docling remains a listed local option until its runtime is wired.
- Text on Pages (Normalization) is local-first by default. `MEDUSA_OPENAI_PAGE_NORMALIZATION_MODE=auto` escalates only low-text or artifact-heavy pages, sends extracted page text without repeated PDF file context, and caps escalations per document. Use `always` only for intentional all-pages cloud normalization.
- Metadata, Summary, APA Citation Matching, Tag Suggestions, Text on Pages (Normalization), Bibliography Cleanup, Formula Capture, and Accessory Summaries are GPT/Responses tasks. Metadata and APA Citation Matching remain the high-quality citation path; Summary, Formula Capture, and Accessory Summaries default to `gpt-5.4`; Tag Suggestions defaults to `gpt-5.4-mini`; Bibliography Cleanup defaults to `gpt-5.4-nano` and is only used for user-triggered refresh, not import-time source bibliography extraction; Formula Capture is likewise manual-only through Concordance; Text Chunk Encoding remains the embeddings endpoint and defaults to `OPENAI_EMBEDDING_MODEL`.
- `MEDUSA_OPENAI_SEND_PDF=true` enables Responses API file input for original PDFs below `MEDUSA_OPENAI_PDF_FILE_MAX_MB`.
- `MEDUSA_OPENAI_COMBINE_DOCUMENT_INTELLIGENCE=false` is the default routed mode. Setting it to `true` restores the previous single-call `core_document_intelligence` mode for metadata, summary, APA candidate, and tag suggestions, but that mode cannot use separate cheaper models for summary/tags.
- `MEDUSA_OPENAI_PROMPT_CACHE_RETENTION=24h` adds OpenAI prompt-cache retention hints keyed by document checksum for retries and Concordance reruns when the installed SDK supports the Responses retention parameter; otherwise Medusa sends the cache key only. Overlong cache keys are hashed to satisfy the Responses API 64-character key limit.
- DOI regex extraction plus Crossref DOI/title/author/year matching runs before GPT APA fallback. Crossref-backed citations are formatted locally and can be verified; GPT APA fallback uses compact metadata/excerpts without PDF context and remains a reviewable candidate.
- `citation_refresh` was raised to v4 after the DOI-first APA work to include APA in-text citation generation and citation model/provenance tracking; `summary_topics` is v8 for routed summaries, routed tag extraction, tag-governance scoring, and updated model evidence.

### 2026-06-20: Flat tag namespace and Optimize plan pane

Decision: Collapse the user-facing keyword/topic distinction into one Tag namespace and make tag optimization a right-side review pane rather than an immediate mutation.

Why: Keywords, topics, and tags were carrying the same organizational meaning in different columns and labels. The user should not need to choose a kind, and AI cleanup must be inspectable before it rewrites a library taxonomy.

Consequences:

- The Tags view, document detail pane, Library filters, Import defaults, bulk edit controls, exports, restore, search, and Optimize source-tag chips all treat tags as flat labels sorted alphabetically unless a specific view intentionally chooses another order.
- The `tags.kind` column remains only for compatibility with older rows and exports; migration `20260620_0013` normalizes existing values to `tag`, and new/imported/restored tags are written as `tag`.
- Merged tag names are retained in `tag_aliases` as canonicalization aliases. Import and Concordance tag suggestions, manual tag-name edits, bulk tag names, and tag creation consult those aliases before creating rows, and aliases move forward if their target tag is later merged again.
- The Settings model task is labeled Tag Suggestions. The internal key remains `keywords_topics` so older preferences and usage rows continue to resolve, but model output is flattened before it reaches user-facing tag lists. Import and Concordance tag prompts include a compact existing-tag manifest and ask the model to scan that inventory before proposing new labels, while still allowing genuinely missing concepts to become new tag candidates after governance scoring.
- Optimize opens a persistent right-side governance plan pane that displays the reviewed scope, model, rationale, confidence, source tag counts, status/health summary, and server-computed affected-document counts. Suggestions are approval-only. Optimize uses the same saved Tag Suggestions model preference that import uses for tag creation, defaulting to `gpt-5.4-mini`; when the user selects a stronger model such as `gpt-5.4`, import tag creation and Optimize use that model together. The prompt asks for a thorough cleanup pass rather than a small sample, with larger strict and singleton suggestion limits. Broad scopes send the model a ranked high-yield subset of low-count tags, likely broader targets, variant groups, prefix families, and long covered labels so the slow LLM request stays bounded; deterministic review still evaluates the full selected/visible scope. The backend supplements model merges with deeper deterministic review candidates for singular/plural variants, existing broader-prefix targets, repeated two-word prefixes among single-document tags, orphaned zero-link tag merge/prune decisions, semantic relationships, candidate status changes, and weak assignment pruning.
- Approving an Optimize suggestion runs the normal audited merge endpoint, which adds or preserves the target/new tag on every affected document before removing source tags and recording `DocumentVersion` history.
- Optimize suggestions expose Approve Merge, Merge Into, and Dismiss actions. Merge Into asks for a custom target name; if that normalized name already exists, the UI requires confirmation and the backend merges into the existing tag rather than creating a duplicate.

### 2026-06-20: Tag governance scoring and Optimize workbench

Decision: Adopt the tag-governance methods captured in `docs/TAG_GOVERNANCE.md`: embedding-aware hybrid similarity, LLM candidate extraction, library-aware scoring, cluster-aware review, existing-first/not-existing-only behavior, three-axis relevance/fit/novelty scoring, and semantic covered-by checks during import and Concordance.

Why: The library had roughly 200 documents and almost 3,000 tags, with too many documents drifting toward broad miscellaneous labels. The system needs to reduce noisy tag creation and weak assignments without blocking genuinely new concepts.

Consequences:

- Tag Suggestions output is candidate evidence. Import and Concordance pass topics/keywords through a deterministic governance scorer before attachment.
- Existing tags are preferred when aliases, exact matches, semantic similarity, or covered-by checks indicate they are a fair fit. New concepts still become tags when relevance and novelty are strong enough, but import-created new tags start as `candidate`.
- Each candidate is recorded in `DocumentTagAssessment` with document relevance, library fit, novelty value, overall score, decision, rationale, and job context. Document metadata evidence stores a compact summary of the tag-governance pass.
- Tags now have governance status plus optional definition/use/avoid guidance. Approved semantic relationships live in `TagRelationship`; alias memory remains in `TagAlias`.
- Optimize remains the user-in-the-loop workbench. It now surfaces merge suggestions, single-document cleanup merges, relationship approvals, candidate status changes, and weak-assignment pruning. Merges and pruning are audited document mutations; relationships and status changes teach future scoring without silently rewriting documents.

### 2026-06-20: Aggressive tag admission control

Decision: Tighten import-time tag admission and expand Optimize review for legacy singleton canonical tags.

Why: The live library still had thousands of tags after merge-oriented optimization, with most of the excess coming from canonical one-document labels. Import cannot keep treating every plausible keyword as a useful taxonomy term.

Consequences:

- Import and Concordance still record tag candidates for evidence, but import attachment is capped at five total tags and one brand-new candidate tag per document.
- New tags require stronger document relevance and novelty than reused tags. Low-value form/generic labels are skipped, and near-existing candidates are reused or recorded as not attached instead of creating another label.
- The scorer uses title/summary/body relevance, existing alias memory, active tag search, optional embedding similarity, semantic covered-by checks, and close-match thresholds before allowing new tag creation.
- Optimize can now suggest downgrading, retiring, merging, or pruning low-use tags even when the selected scope has no model-proposed merge candidates. True zero-link orphan tags are deterministic cleanup candidates: merge them into a useful used tag when variant, broader-prefix, or high-similarity checks find a target; otherwise prune the unused tag row entirely. One-use candidates are retire candidates when they have no durable score evidence or weak evidence; one-use canonicals are downgrade candidates until repeated use proves durable value; singleton assignments without scoring history can be pruned by explicit approval. These remain user-approved operations, not automatic cleanup. Broad scopes may now produce several hundred suggested actions so the user can clean more than a small batch per run.
- Optimize plans can be applied suggestion-by-suggestion or through Approve All. Batch approval is not all-or-nothing: it applies still-valid actions in merge, orphan-prune, relationship, status, assignment-prune order, shows a top progress strip with the planned action/document-reference count while the request is in flight, and reports stale skipped suggestions caused by earlier merges or prior user changes.

### 2026-06-20: Staged uploads with rough cost preview

Decision: Manual batch uploads stage durable import jobs first, show rough per-file and grand-total dollar estimates, and require the user to press Process Uploads before workers can claim the jobs.

Why: Large upload batches can create bursts of model calls. The user should be able to keep adding PDFs across batches, inspect rough cost before processing starts, and then release the whole staged set intentionally.

Consequences:

- `/api/imports/batches` still stores originals, writes cache copies, applies duplicate decisions/defaults, and commits `Document`, `ImportBatch`, and `ImportJob` rows, but new manual import jobs use status `staged` and current step `staged`.
- `/api/imports/jobs/process-staged` promotes all staged import jobs to `queued`, records a processing event, and sets document processing status so the worker can claim them through the existing import pipeline.
- Import and Queue surfaces include Process Uploads controls. Import also includes Clear Staged for bulk discard of staged-only uploads and their managed cache/original files. Staged rows can be canceled/cleared before processing; retry remains reserved for failed/restored/stale work.
- Staged and other unfinished import document rows stay queue-only. Library document queries, search filters, direct document detail routes, dashboard document/review counts, tag/domain counts, project bibliographies, recommendation existing-library matching, and Concordance scopes use the shared imported-document visibility rule and exclude `staged`, `queued`, `running`, `failed`, `cleared`, and `restored_paused` rows.
- Queue cost previews use stored page counts plus recorded import usage exemplars by task/model when available, then task-level/library-level fallbacks, then a conservative per-page default. Each staged document persists its rough estimate as a `DocumentCompositionRecord` with record kind `estimate`; Composition compares that estimate to actual model/embedding spend once the import records usage. Future queue estimates apply a bounded calibration factor derived from prior persisted-estimate versus actual-cost pairs.
- The header active-work progress does not treat staged jobs as active imports; Queue navigation still counts them as attention-worthy work.
- When a released import queue drains, the worker runs PostgreSQL `VACUUM (ANALYZE)` across all tables. Staged jobs waiting for a future Process Uploads click do not prevent that post-drain optimization.

### 2026-06-20: Bookmarkable workspace URLs

Decision: Give every top-level workspace a canonical browser path while keeping the existing single-page app shell and Settings save-before-leaving guard.

Why: Research work should be resumable from bookmarks, browser refreshes, and copied links. Top-level navigation should behave like real page navigation without introducing a louder routing framework or losing durable app-shell state.

Consequences:

- The quiet horizontal navigation renders as links to `/library`, `/domains`, `/projects`, `/tags`, `/queue`, `/notes`, `/import`, `/stashes`, `/budget`, `/utilities`, and `/settings`.
- Document focus renders as `/documents/{document_id}` and selects that document in Library; `/document/{document_id}` is accepted and normalized to the canonical plural route.
- Plain clicks use in-app navigation and push browser history; modifier-clicks and copied links use the normal anchor URL.
- Document row title areas are links, document browsing pushes history entries, and the detail pane exposes a Copy Link action for the focused document.
- Direct loads, refreshes, and Back/Forward derive the active workspace and document focus from the URL. `/` maps to Library and is normalized to `/library` once the shell loads.
- Leaving dirty Settings through navigation or browser history keeps the same save prompt used by internal page changes.

### 2026-06-20: Settings citation convention and summary output polish

Decision: Persist a Settings citation convention preference, keep APA 7 as the only current convention, and tighten the default generated-summary contract across canonical summaries and Accessory Summaries.

Why: Citation format is a library-level preference that will eventually need choices, but the current product should expose only the implemented convention. Generated summaries should read like technical prose by default, not like formatted outlines, and document controls should use consistent Refresh language for durable background work.

Consequences:

- Settings > Preferences stores `citation_convention` as an `AppPreference`; the current radio group has one enabled option, APA (7th Ed.), represented internally as `apa_7`.
- Future citation conventions must extend the same preference, API schema, citation generation/formatting paths, and bibliography/export surfaces rather than adding one-off UI controls.
- The Settings opening Runtime, Storage, and AI overview tiles are removed; Settings now starts directly with operational panels. Settings section icons sit left-aligned above section header text.
- DOI, APA citation, and Summary document actions use Refresh wording because they queue durable Concordance-backed refresh work.
- Citation provenance labels display the model name or `user provided` without prepending repetitive labels such as APA Citation Matching.
- The shared summary prompt hint applies to document summaries and Accessory Summaries. Defaults are technical plain-text paragraphs with complete sentences, a graduate academic level suitable for a master's-degree reader, key findings and concrete facts early, no sentence starts with prepositions, no standalone Summary/Overview-style opening, no single-word opener, no bold, italics, bullets, em dashes, fancy quotes, or decorative Markdown unless the user explicitly asks for another format.
- Import and Concordance summary persistence strips standalone first-line summary headings and accidental trailing schema metadata blocks before storing `rich_summary`.

### 2026-06-20: PDF mezzanine for HTML and text imports

Decision: Accept HTML and plain-text/Markdown uploads through the normal Import workflow, parse their raw source semantics for reader/search text, and store a locally generated PDF as the durable original object.

Why: Medusa's preview, storage, cache, OpenAI file-context, and download paths already assume PDF as the universal document surface. HTML and text still carry useful structure before rendering, especially titles, headings, paragraphs, list items, and captions, so source parsing should feed extraction rather than treating the generated PDF as the only truth.

Consequences:

- Duplicate detection for non-PDF uploads uses the uploaded source-byte SHA-256, while `metadata_evidence["source_import"]["mezzanine"]` stores the generated PDF checksum, filename, size, format, and renderer.
- GCS/local original storage and `data/processing-cache` receive PDF bytes for every document, including non-PDF imports.
- Worker extraction uses persisted parsed source pages for HTML/text imports and compacts full parsed-page text out of metadata after `DocumentPage` rows are written.
- Current HTML rendering is semantic text-first and does not preserve remote images, full CSS layout, or interactive content. Richer HTML asset capture can be added later without changing the PDF mezzanine contract.

### 2026-06-19: Accessory Summaries

Decision: Add current-document Accessory Summaries as durable document-owned rows, generated by the worker from a user prompt and Settings-selected model.

Why: Focused research questions should not overwrite the canonical document summary. They need their own prompt, model, body, title, evidence, status, and retry surface so arbitrary topic summaries remain auditable and cost-visible.

Consequences:

- `DocumentAccessorySummary` stores prompt, optional title, selected model, generated summary, evidence, status, attempts, lock time, and completion time.
- `/api/documents/{document_id}/accessory-summaries` queues a row; `/api/accessory-summaries/{summary_id}` saves optional titles.
- The worker processes queued Accessory Summaries after imports and Concordance jobs, requeues interrupted running rows on startup, and marks failed rows with visible errors.
- Accessory Summary OpenAI calls use task key `accessory_summaries`, record Budget & Costs usage, may include original PDF file context when configured and under size limits, and use prompt-cache keys derived from document checksum plus summary id.
- Completed Accessory Summaries contribute title, prompt, and body text to document search.
- Metadata exports include Accessory Summaries as document children; restored queued/running rows are parked unless restore is explicitly allowed to reactivate jobs.

### 2026-06-19: Reader History Restore And Scrub

Decision: Add Library/Reader history undo through `DocumentVersion` snapshots and name the restore action Restore as Current instead of Accession To Main. Add a reader text-edit tool strip whose first action, Scrub, removes selected exact text from all parsed page text and shows the current document-wide match count.

Why: Cleanup often involves papers with front matter, copyright lines, or repeated extraction artifacts. The user needs fast bulk removal without losing auditability, and history restore should be understandable as applying an older state to the current searchable document while preserving every prior version.

Consequences:

- `/api/documents/{document_id}/versions/{version_id}/restore` applies restorable document/page snapshots and creates a new `DocumentVersion` pointing back to the restored version.
- `/api/documents/{document_id}/pages/scrub` removes exact selected text from every page's reader/search text, sets affected pages to manual normalized text, rebuilds search, and records one audited history row with match counts and page snapshots.
- The History UI supports newer/older stepping, previewing the selected version, and Restore as Current. Richer field-by-field diffs remain future work.
- Scrub counts exact matches in the current reader text selection and disables when there is no selected text or no matches.

### 2026-06-18: Task-level model controls and PDF-context enrichment

Decision: Use task-level model controls in Settings, default Raw Text Extraction to local Marker, and include original PDF file input when configured and size-safe.

Why: Import and Concordance jobs already run asynchronously, so Medusa can afford high-quality models for the tasks that need them, while the user may want cheaper/faster models for lower-risk tasks. Extracted text is useful, but original PDFs may preserve layout, figures, page images, and front-matter boundaries that improve extraction.

### 2026-06-17: Local GCS credential mounting

Decision: Keep GCS service-account JSON files under ignored `data/secrets` and mount that directory read-only into backend and worker containers.

Why: Medusa needs real GCS access locally, but credentials must never be committed. A repo-local ignored path is easier to move and reason about than binding a Desktop-specific absolute path.

Consequences:

- `.env` points `GOOGLE_APPLICATION_CREDENTIALS` at `/app/data/secrets/<key>.json`.
- `docker-compose.yml` mounts `./data/secrets:/app/data/secrets:ro`.
- GCS IAM should include `storage.objects.create`, `storage.objects.get`, `storage.objects.list`, and `storage.objects.delete` for normal app operation. Backup verification is stored in sidecar manifest objects and the database rather than by patching object metadata, so `storage.objects.update` is not required.
- Future credential rotations should replace the local JSON file and update ignored `.env` if the filename changes.

### 2026-06-17: Concordance Runs for retroactive feature upgrades

Decision: Call retroactive library upgrade jobs **Concordance Runs**.

Why: Medusa will gain document-intelligence features over time, and old imports must not be stranded on older extraction/search/citation/tagging behavior. "Concordance" has scholarly resonance and captures the goal: bringing the library back into agreement with the current system.

Consequences:

- New document-processing features should define both import-time behavior and Concordance behavior.
- Capability versions are needed so Medusa can identify stale or missing derived artifacts.
- Concordance Runs should be durable jobs with review-safe output, progress events, retry semantics, and filters for whole-library, domain, project, saved-search, and selected-document scopes.

### 2026-06-17: Immediate import drop target

Decision: The Import dropzone should start uploads as soon as supported document files are dropped or selected, and the whole drop panel should visibly switch into an active acceptance state while files are dragged over it.

Why: Import is a high-frequency workflow. The target should feel physically obvious and should not require a second confirmation click after the user drops files in the right place.

Consequences:

- The entire dropzone surface, including the icon area, is the file target.
- Priority and read-status controls define defaults for the immediate batch.
- The UI must show an unmistakable drag-over state before drop and live upload/submission status after drop.

### 2026-06-17: Modular resizable panes

Decision: Make the main cockpit panes modular and resizable with draggable splitters. Persist user-adjusted widths locally in the browser.

Why: Research work shifts between browsing, triage, metadata review, and reading. Fixed panes force the user into one layout, while resizable panes let the interface adapt to the current task without introducing separate modes.

Consequences:

- The Library filter pane and Library detail pane should be resizable on desktop.
- Splitters should remain subtle, keyboard-accessible, and visually consistent with the quiet cockpit style.
- Small screens should collapse to a single-column layout and hide drag splitters.
- Default spacing should stay dense enough for research scanning, with stable dimensions so text and controls do not jump while resizing.

### 2026-06-17: Concordance Run foundation

Decision: Implement Concordance Runs as first-class durable database jobs with a versioned capability registry, document-level completion state, worker processing, and a Settings control panel.

Why: Medusa will gain extraction, citation, OCR, search, and AI features over time. Existing imports need a trustworthy way to receive those features without re-uploading files or relying on one-off maintenance scripts.

Consequences:

- New document-intelligence features should add or update a capability definition and define both import-time and Concordance behavior.
- The worker now drains import jobs before Concordance jobs so new uploads stay responsive.
- The first implemented capabilities are `search_index`, `citation_refresh`, and `summary_topics`.
- Whole-library Concordance can run from Settings now; narrower scope controls are a near-term UX follow-up.

### 2026-06-18: Correction pane and scoped Concordance controls

Decision: Make the document detail pane editable and extend Concordance controls to targeted scopes.

Why: Imported scholarly metadata will sometimes be wrong, and the user needs to correct titles, authors, DOI, tags, domains, priorities, summaries, and custom attributes without leaving the reading/browsing surface. Concordance also needs to be useful on the subset currently under review, not only the whole library.

Consequences:

- Manual corrections write `DocumentVersion` snapshots with changed fields and before/after metadata.
- Citation-affecting corrections regenerate APA Reference List and APA In-Text Citation text unless the user explicitly edits that citation field.
- The detail pane can run Concordance for the current document.
- Settings can run Concordance for the library, current document, current search text, a domain, or a project.
- Future work should add a richer correction-history diff viewer and arbitrary-filter Concordance scopes beyond saved searches.

### 2026-06-18: Saved searches, notes, and bulk edit

Decision: Add saved searches, smart filter controls, library bulk edit, and a notes/reminders workbench.

Why: Medusa needs to support repeated research triage, not just one-off browsing. The user should be able to save a current view, return to it, bulk assign priorities/tags/domains, and keep notes or reminders attached to documents, domains, projects, or the library.

Consequences:

- `SavedSearch` stores a named query plus filter JSON and can be used as a Concordance scope.
- The Library filter pane owns saved-search creation/application/deletion and filter selection.
- The document list supports selecting visible documents and applying read status, priority, tag, and domain updates.
- Notes and reminders have CRUD APIs and a dedicated Notes workbench.
- Document-linked notes contribute to document search text.

### 2026-06-18: Figure asset extraction

Decision: Extract embedded PDF images into durable storage during import and expose them through authenticated figure asset routes.

Why: Research documents often carry meaning in figures, diagrams, scans, and embedded images. Keeping figure assets addressable lets Medusa later generate image gists, support figure-aware search, and preview extracted media without relying on the original PDF renderer.

Consequences:

- Import processing now runs a figure extraction step before metadata enrichment while the processing-cache PDF is still available.
- `Figure` rows store page number, label, basic extraction gist, and durable asset URI.
- Figure assets use storage keys under `figures/<first-two-sha256-chars>/<sha256>/...`.
- `visual_asset_extraction` and `visual_asset_context` are Concordance capabilities so older documents can be upgraded from their durable original object without re-upload; legacy `figure_assets` requests are treated as a compatibility alias.
- Visible PDF image blocks are stored from 300 DPI rendered page crops when available; raw embedded image bytes are only a fallback when no usable page crop can be rendered.
- The detail pane shows extracted figure thumbnails through `/api/figures/{id}/asset`.

### 2026-06-18: Metadata backup and storage manifest exports

Decision: Add authenticated JSON exports for Medusa metadata and durable storage manifests.

Why: Medusa is meant to be safe to stop, restart, move, and back up. A metadata export gives the user a portable record of the library's research organization and processing state without copying credentials or relying on direct database access.

Consequences:

- Utilities now includes backup/export controls for full metadata and the asset manifest.
- `backend/app/services/exports.py` owns export construction so future restore tooling can share the schema.
- Metadata exports include documents, extracted text, tags, domains, annotations, notes, attributes, correction history, projects, jobs, Concordance state, citation candidates, and storage URI references.
- Exports intentionally omit service-account credentials, API keys, password hashes, and session tokens.
- JSON metadata restore later became the CLI `restore_export` workflow; full disaster recovery is handled by the 2026-06-19 PostgreSQL backup/restore workflow.

### 2026-06-19: Full database backup and restore through GCS

Decision: Add browser-driven full PostgreSQL backup and restore backed by GCS, zstd compression, checksum verification, visible header progress, and mandatory pre-restore safety backups.

Why: Metadata JSON exports are useful for inspection and partial recovery, but they are not a complete local-first disaster-recovery path. Medusa's system of record is PostgreSQL, so a reversible restore workflow should snapshot the whole database and make the safety backup impossible to skip.

Consequences:

- `BackupRun` rows track manual backups, pre-restore safety backups, and restore runs with status, phase, progress, GCS object details, checksums, source metadata, and errors.
- Manual backup phases are `initializing`, `dumping`, `compressing`, `uploading`, and `verifying`; the header active-work slot shows those phases and percent progress next to import/Concordance work.
- Backups use `pg_dump --format=custom`, zstd compression, object names shaped like `medusa-postgres-YYYYMMDD-HHMMSS-<short-hostname>.dump.zst`, and sibling JSON manifests under `<GCS_PREFIX>/backups/`. Utilities shows a likely next-backup size under the Backup Database button, a GCS backups status tile with the count and total compressed size of all listed dump backups, and the ten most recent backup/restore runs; the estimate uses `pg_database_size(current_database())` and, after a completed backup exists, scales by the latest recorded compressed-size/source-database-size ratio.
- Upload verification computes a SHA-256 over the local compressed file, uploads it to GCS, then reads the uploaded object back and compares the checksum before completion.
- Restore from the browser UI uses a selected GCS backup, asks for confirmation, and always creates and verifies a fresh full GCS backup first. Only after that safety backup is complete does Medusa fetch/check/decompress the selected dump, apply it with `pg_restore --clean --if-exists`, and run migrations.
- Full database dumps include auth tables because they are complete database snapshots; API keys and service-account JSON remain outside PostgreSQL and outside backup manifests.
- The old authenticated metadata JSON and storage manifest downloads remain as legacy inspection/export tools at the bottom of Settings, while the primary Backup Database and Restore Database controls now use the full database workflow.

### 2026-06-20: Portable storage boundary

Decision: Keep the default Compose database on the Docker-managed `medusa-postgres` named volume, and document backup/restore as the supported way to move Medusa's PostgreSQL system of record between hosts.

Why: The repo's `./data` bind mount is useful for local originals, processing cache, managed secrets, model weights, and other application files, but PostgreSQL has stricter durability and fsync expectations than an ordinary portable folder. A casual USB flash drive is acceptable for carrying exports and backup artifacts, but it is not a good default live database target.

Consequences:

- Moving the checkout plus `data/` is not a complete library move unless a full database backup is restored on the destination.
- A future portable mode should be an explicit Compose override that bind-mounts PostgreSQL onto a reliable external SSD and makes the storage tradeoff visible to the user.
- Backup/restore, metadata export, and storage-manifest language must keep separating database state, durable original assets, caches, and secrets.

### 2026-06-18: Project run-sheet management

Decision: Turn Projects into editable run sheets with project resource rows, status, priority, used/not-used tracking, notes, and all-sources or used-only bibliography generation.

Why: Projects are the bridge between the library and an actual paper, assignment, or research task. The user needs to track which resources are candidates, being read, used, or rejected and then generate a bibliography from the exact subset that made it into the work.

Consequences:

- Project detail APIs now expose `ProjectItem` rows with linked document summaries.
- The Projects view can add library documents to a project, edit each row's status/priority/used flag/note, remove resources, and generate APA/BibTeX/RIS/CSL JSON bibliographies.
- Bibliography generation accepts a used-only mode so the final source list can exclude candidates that were not used.
- Future project work should add richer sorting/filtering, due-date/status editing, and export buttons for bibliography files.

### 2026-06-18: Actionable citation review

Decision: Add Queue actions to accept or reject citation candidates.

Why: A queue that only displays uncertainty still leaves metadata work stranded. Citation review needs a direct path to promote evidence-backed metadata into the document or dismiss bad candidates.

Consequences:

- Accepting a candidate updates the document fields represented by candidate metadata, applies candidate APA Reference List text, refreshes the APA In-Text Citation from the accepted metadata, marks the document citation as `verified`, refreshes search text, and writes a `DocumentVersion` history record.
- Rejecting a candidate changes only the candidate status and removes it from the active citation review queue.
- Future review work should show richer side-by-side evidence and support partial field-level acceptance.

### 2026-06-18: Authenticated PDF preview and annotations

Decision: Serve original PDFs through an authenticated document route and add document annotations/highlights to the detail pane.

Why: Medusa needs to support reading and marking documents, not just cataloging metadata around them. Originals should remain private in GCS/local storage while still being previewable in the app.

Consequences:

- `/api/documents/{document_id}/original` streams the durable original object through the storage adapter with inline content disposition.
- The detail pane embeds the original PDF and provides an open-in-new-tab control.
- `Annotation` rows are now exposed through CRUD endpoints and included in document detail.
- Annotation body text contributes to document search, and soft-deleted annotations are excluded from active detail/search rebuilds.
- Existing annotation rows remain exposed in the detail pane, but the earlier inline Library annotation composer is deferred pending a quieter pane-aware redesign for page, kind, color, note body, and eventual geometric overlay selection using the existing `geometry` field.

### 2026-06-18: Parsed full-text reader

Decision: Expose extracted `DocumentPage` rows through the document detail API and add a PDF/Text reader switch in the document pane.

Why: Original PDFs need to remain viewable, but parsed scholarly text also deserves a clean reading surface for review and search validation.

Consequences:

- `/api/documents/{document_id}` includes page text, source, low-text flags, and page image URI references.
- The document pane can switch between the authenticated original PDF and parsed page text.
- Reader annotation creation actions are deferred with the broader Library annotation-capture redesign; existing page-aware annotation records remain searchable and can later map onto geometric overlays.
- Low-text pages are visible in the reader, giving the future Google Vision OCR path an obvious review surface.

### 2026-06-18: Alembic migrations

Decision: Add Alembic as the PostgreSQL schema migration system and run migrations during backend/worker startup.

Why: Medusa's schema is broad enough that metadata-only creation is risky. Migrations give future changes an ordered, reviewable upgrade path while keeping existing local data intact.

Consequences:

- `backend/alembic.ini`, `backend/alembic/env.py`, and the initial schema revision are now included in the backend image.
- `init_db()` runs Alembic for PostgreSQL and keeps SQLAlchemy metadata creation as the SQLite/test fallback.
- Backend and worker startup serialize PostgreSQL Alembic upgrades with a Postgres advisory lock so simultaneous container starts do not race on the same migration.
- The initial migration is idempotent for existing local PostgreSQL databases by creating current tables and supporting indexes only when missing.
- Future model changes must include an Alembic revision and corresponding tests or smoke verification.

### 2026-06-18: Import throughput and active-work progress

Decision: Add DB-backed import worker concurrency preferences, default concurrent imports to four per worker process while allowing higher user-selected values, and show active import progress in the persistent active-work progress surface.

Why: Large batches should keep moving without requiring multiple worker containers, while the user still needs a quiet, persistent signal that queued/importing documents are making progress outside the Import view.

Consequences:

- `/api/preferences` exposes active import worker, citation convention, day/night accent, document cache size, model task registry, grouped model options, and selected model preferences. Settings saves user changes as `AppPreference`.
- The worker claims multiple import jobs up to the current preference, keeps Concordance work behind active imports, and excludes in-process import IDs from stale recovery claims.
- Import page normalization records and commits per-page checkpoint events so slow OpenAI page-normalization calls are visible as `normalizing_page_<n>` rather than a single opaque extraction step. On restart, already-normalized pages are reused when possible and missing pages are processed again.
- `/api/imports/jobs/{job_id}/rescue` can requeue failed/restored import jobs and running jobs whose worker lock is stale. Fresh running jobs are rejected to avoid racing an active worker thread.
- `/api/dashboard` includes import queued/running counts plus active batch progress totals, active step, and elapsed seconds so the header active-work control can render progress without scanning the recent job list.
- The active-work progress control is visually hidden when no imports or background runs are queued/running but keeps its reserved header slot.

### 2026-06-19: Shell-owned async progress and action feedback

Decision: Move Concordance-starting UI through an app-shell starter and render active durable async work in the reserved header progress control, while keeping local button-level in-flight, success, and error feedback for immediate action visibility.

Why: A user can start small-looking work, such as an APA citation refresh, then switch views. The backend should still finish the durable job, and the UI should make it obvious that Medusa received the request, is processing it, and eventually completed or failed.

Consequences:

- Citation Refresh queues a forced `citation_refresh` Concordance Run for both APA citation surfaces instead of relying on a page-local request lifecycle.
- The app shell records a local "starting" job immediately, reconciles it with persisted Concordance run/job state, and displays starting/queued/running status in the header active-work control.
- Page-local controls can unmount without losing the shell's progress/error display. If the originating page remains mounted, its button can still flash completion/failure from the watched job.
- Buttons that start async work use the same restrained feedback language: soft blue plus a spinning in-button icon and slim progress bar while work is in flight, a timed green success blend on completion, red plus a short error popover for failure, then a fade back to the normal button color.
- Import progress shares the header active-work control because imports already have dashboard-backed progress, while import requeue buttons use the same transient feedback convention.
- Recommendation refresh/download buttons use the same local feedback convention until recommendation downloads become durable background fetch jobs.

### 2026-06-19: Project controls stay inside their pane

Decision: Constrain the Projects add-resource select/button row to the project-detail pane and clip panel overflow so long native select option labels cannot visually intrude into the Bibliography panel.

Why: Project run sheets can contain many long scholarly titles. Native select controls can carry awkward intrinsic widths, and a tight three-pane workspace must not let controls overlap adjacent bibliography actions.

Consequences:

- The project add-resource row uses bounded flexible sizing and wraps/stacks at small widths.
- Project, detail, and bibliography panels hide overflow at their edges rather than allowing one pane's controls to spill into another.
- Future Project controls should be checked at desktop and narrow breakpoints before assuming native select/button intrinsic sizes are safe.

### 2026-06-20: Project bibliography surface

Decision: Keep project bibliography generation controls inside the Bibliography panel and render APA bibliography output as rich Markdown on a white full-width document surface.

Why: All-sources and used-only generation are bibliography actions, not run-sheet resource actions. APA reference lists also need visible formatting such as italics, while export formats such as BibTeX, RIS, and CSL JSON should stay preformatted for copying.

Consequences:

- The Bibliography panel owns All sources, Used only, Copy, format tabs, and output display.
- All sources and Used only sit side by side in a dedicated generation row so they do not stack in the project header.
- APA output renders Markdown italics as formatted text on a paper-white surface that fills the bibliography area; BibTeX, RIS, and CSL JSON remain preformatted text.

### 2026-06-21: Model pricing history and Settings refresh

Decision: Store model pricing in `ModelPricingRecord` history and expose pricing tier, freshness, plus a Refresh Models & Pricing action alongside the model defaults in Settings > Import Processing.

Why: Budget & Costs and document Composition need clean cost accounting even when provider prices change. Daily checks should not create duplicate history rows, but true price changes must leave an auditable old/new price boundary.

Consequences:

- Settings shows the active OpenAI pricing tier, latest local pricing refresh timestamp, the source snapshot date, a Refresh Models & Pricing button using the standard async button animation, and a warning when the configured tier rows are missing or pricing has not been refreshed in more than two days.
- Refreshing stores current enabled OpenAI GPT prices for the configured tier, OpenAI embedding prices, and Google Gemini standard paid-tier token prices. It updates `last_checked_at` for unchanged prices and inserts a new active row only when the rate signature changes, setting `superseded_at` on the prior row.
- Budget & Costs, active import spend, import cost exemplars, and Composition sync cost each usage record against the historical price row active at the usage timestamp and pricing tier, with the current official pricing table for the configured tier as fallback when no database history exists yet.
- Google text model options remain limited to non-preview, non-shutdown models. Current Google pricing covers Gemini 3.1 Flash-Lite and the Gemini 2.5 Pro/Flash/Flash-Lite family; legacy Gemini 2.0 and unsupported `gemini-3.5-flash` values are not built-in current options.

### 2026-06-19: APA reference-list and in-text citation surfaces

Decision: Split the Library detail citation display into `APA Reference List` and `APA In-Text Citation` sections, with separate Copy/Edit controls and shared Refresh behavior.

Why: Research writing needs both the reference-list entry and the parenthetical in-text form. They should be visibly distinct but generated from the same evidence/model preference so they do not drift.

Consequences:

- `Document.apa_citation` remains the Markdown-compatible reference-list entry. `Document.apa_in_text_citation` stores the parenthetical in-text citation.
- Each citation has stored model/source provenance. The UI displays the model name when model/generated provenance is present and `user provided` after a manual override.
- Inline citation edits PATCH only the edited field and create normal `DocumentVersion` history. User edits do not silently mark the paired citation as user-provided.
- `citation_refresh` v4 refreshes both citation fields together and records the selected APA Citation Matching model, even when trusted Crossref metadata lets Medusa format the reference-list citation deterministically.
- Existing populated APA reference-list citations are backfilled as generated by `gpt-5.5`; their in-text citations are derived from stored authors/year where possible.

### 2026-06-19: Gemini model options and AI cost rollups

Decision: Add Google Gemini text-generation models as a provider group in Settings > Import Processing shared model defaults and record Gemini `generateContent` calls in the existing AI usage ledger.

Why: Medusa needs model/method preferences that can compare OpenAI and Google choices without hiding cost. The user may choose Gemini for summaries, metadata, page normalization, APA fallback checks, and Accessory Summaries, and those calls must remain visible in Budget & Costs by task, model, document, and time.

Consequences:

- `data/secrets/gemini.env` is the preferred ignored local secret file for `GEMINI_API_KEY`; backend and worker also honor direct `GEMINI_API_KEY` environment configuration.
- Settings-managed Google service-account JSON is preferred over `GEMINI_API_KEY` for Gemini model calls and routes through Vertex AI using the saved key plus `GOOGLE_CLOUD_PROJECT`/JSON `project_id` and `GOOGLE_CLOUD_LOCATION`.
- Settings > Import Processing shared model defaults group compatible text-generation choices under OpenAI and Google, and exclude Gemini model ids containing `preview` plus deprecated/shutdown Gemini defaults from the Google group. Current built-in Google options include Gemini 3.1 Flash-Lite, Gemini 2.5 Pro, Gemini 2.5 Flash, Gemini 2.5 Flash-Lite, and stable latest aliases that resolve to those priced families.
- Gemini text-generation calls use Vertex AI `generateContent` when managed service-account credentials are available, otherwise the Developer API `generateContent` route with `GEMINI_API_KEY`; both paths use extracted text only. Original PDF file attachment remains an OpenAI Responses path until Gemini PDF-context handling is explicitly wired and verified.
- Budget & Costs records Gemini calls with provider `google` in the existing `OpenAIUsageRecord` table, estimates known Gemini text-model costs from model-pricing history or the local pricing fallback, and leaves unknown/ambiguous models unpriced.
- Budget & Costs rollups now include model, task, document, calendar day, and calendar hour views so expensive documents or time windows can be isolated.

### 2026-06-19: Settings-managed GCS and Google service account

Decision: Let Settings save the active GCS bucket and upload a Google service-account JSON key for managed Google credentials.

Why: Medusa should not require editing `.env` or relying on pass-through gcloud/ADC credentials for routine GCS, Vision, and Gemini work once the user has supplied a service account.

Consequences:

- `/api/preferences` exposes the active GCS bucket, whether it has been saved, and a non-secret service-account status summary. `PATCH /api/preferences` saves the bucket through `AppPreference`.
- `/api/preferences/google-service-account` accepts an authenticated JSON upload, validates that it is a service-account key, stores it under ignored `data/managed-secrets` with restrictive permissions, and stores only display/path metadata in PostgreSQL.
- Storage, Google Vision, and Gemini prefer the managed JSON. Gemini uses Vertex AI with the JSON/project configuration when service-account credentials are available and keeps the Developer API key path as the no-managed-key fallback.
- Metadata exports include the saved bucket because it is not secret, but do not include the uploaded JSON or service-account metadata that would trip restore secret guards.

### 2026-06-19: Document Cost Composition and pipeline provenance

Decision: Add a document-facing composition ledger and Library Composition modal for imports.

Why: Budget & Costs answers broad spend questions, but a research document also needs provenance: exactly which local stages and cloud models generated it, how long import work took, which provider/model costs contributed dollars, and which warnings, errors, or edits happened afterward. Concordance can later use this same ledger to avoid reprocessing documents already generated with a specific capability and model.

Consequences:

- Imports write `DocumentCompositionRecord` rows for local stages, synced AI usage, warnings/errors, and manual citation/metadata edits.
- `/api/documents/{document_id}/composition` summarizes those rows into cost entries, provider spend, local duration entries, pipeline chart steps, and processing issues. Cost entries and provider spend are priced usage, not visual guesses: sub-cent model or embedding calls remain listed and included in totals, while local stages only show configured fallback models when the model actually has a provider usage row. If no rows exist, the endpoint returns `available=false`.
- The Library detail pane has a Composition button beside Edit/Concord/Reader/Related. It opens a centered modal with a Cost Composition pie chart, total known dollar cost, total import duration, provider breakdown, local time, processing issues, and a multi-row React Flow pipeline chart with contained stage nodes.
- The header active-work progress slot is wider and includes current known import spend while imports are queued/running.
- Metadata exports include composition rows; restore preserves their costs/tokens/stage metadata and clears raw usage-record pointers when usage rows are not part of the export.

### 2026-06-19: Composition Pipeline Chart

Decision: Render the Composition pipeline with `@xyflow/react` instead of custom flex boxes, and rename visible Errata language to Processing Issues.

Why: Pipeline provenance needs a real graph surface that can fit, pan, and zoom without text bleeding between stages. "Errata" was too opaque and incorrectly suggested publication corrections rather than import warnings or errors.

Consequences:

- The Composition modal uses read-only React Flow nodes and custom arrowed edges that draw a visible stroke from each source node border into the next target node border. React Flow handles are hidden anchor points, not visible connection controls. Pipeline steps remain ordered by import stage and same-stage task execution rather than alphabetic model names.
- Processing Issues is reserved for warnings/errors; completed manual edits remain in the composition ledger but are not listed as issues.
- The API field remains `errata` for compatibility, but product copy should use Processing Issues unless the backend contract is revised.

### 2026-06-19: DOI stashes for related-paper follow-up

Decision: Make DOI stashes a first-class database-backed workflow with a top-level Stashes view, while keeping Related recommendations visually quiet and auto-refreshing by default.

Why: Related-paper discovery often produces useful DOI targets before the PDF is immediately available. The user needs a durable follow-up list that survives navigation and lets a later PDF upload join the normal import queue without re-entering metadata.

Consequences:

- Related recommendations default to Hide Existing, auto-refresh when an eligible document has no cached rows, and keep row actions below the recommendation text so titles, venues, and descriptions have horizontal space.
- `DoiStash` rows are unique by normalized DOI, can be reactivated after soft delete, and keep recommendation/source evidence plus import job/document pointers.
- Stashes view lists saved DOIs with local sorting, per-row DOI copy, manual Sci-Hub DOI links in a new window that first copy the paper title, resolver-backed Import DOI, Upload PDF, and compact dashed drag target controls.
- Stash uploads create normal import batches, documents, storage writes, cache records, import jobs, duplicate-skip events, and queue progress. Once the import job completes, a duplicate match is accepted as already imported, or a ready Library document matches by DOI/title, the stash can be removed from the active list.
