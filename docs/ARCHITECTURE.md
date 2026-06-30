# Medusa Design And Architecture Record

Last updated: 2026-06-30

This is the living record of Medusa's product, design, and architecture decisions. Future Codex sessions should read this before changing the app and update it when decisions change. Details matter here because Medusa is meant to become a long-lived research system, not a one-off prototype.

## Product Intent

Medusa stands for **Metadata-Enhanced Document Understanding, Search, and Analysis**. It is a local-first research document clearinghouse that should help organize, search, read, annotate, summarize, cite, and reuse research documents across domains of knowledge and project-specific run sheets.

The product is optimized for one primary user on a trusted local network. It still requires password login by default because HAProxy exposes the app on LAN-accessible HTTPS port `3737`; the live password is stored as a database hash after first boot, and the account can require authenticator-app two-factor authentication. An explicit local convenience flag, `MEDUSA_LOCAL_AUTO_LOGIN=true`, may be used only on single-user local instances to mint a normal admin session automatically when the browser has no valid cookie; it bypasses password and two-factor prompts and must stay disabled on LAN/public deployments.

Core workflows:

- Stage batch uploads of academic PDFs, HTML documents, plain-text/Markdown files, and textbook excerpts before explicitly releasing them into import processing.
- Preserve original files and process them into searchable metadata, text, summaries, cropped graphic assets, figures, formulas, and citation candidates.
- Run Concordance Runs to bring already-imported documents up to the current extraction, enrichment, citation, tagging, OCR, formula-capture, search, and asset feature set.
- Preserve document layout semantics during processing where they affect meaning, especially two-column articles, tables, and figure/photo/chart placement.
- Organize documents by nested domains, flat tags, read priority, custom attributes, and projects.
- Discover DOI-based related papers for completed documents, enrich open-PDF availability through lawful scholarly resolvers, suppress already-known recommendations from the default discovery list while preserving an audit view, classify relation families, stash useful DOIs for later PDF follow-up, and queue open-PDF recommendations through the normal import pipeline.
- Keep ambiguous metadata and citations visible in Queue instead of pretending uncertain output is verified.
- Build project run sheets with resource status and exportable APA/BibTeX/RIS/CSL bibliographies.
- Keep a separate Portfolio workspace for user-authored research, education, drafts, rubrics, references, and feedback files, preserving source/version lineage while letting Library documents and external evidence inform suggestions and assessments.
- Ask corpus-grounded Recon inquiries across the visible Library, domains, projects, or saved searches, storing durable runs, answers, evidence, and cost estimates that can later feed Portfolio research support.

## Design System Direction

Medusa should feel like a serious research cockpit: dense, calm, polished, and fast to scan.

Typography should reserve compact, heavier treatment for controls, interaction chips, and button-adjacent metadata. Section subtitles, metric labels, table headers, usage ledgers, and ordinary panel copy should use sentence/title case or source text casing with moderate weight so repeated operational surfaces remain readable. Normal UI text should not drop below 12px; smaller treatment should be avoided unless it is icon-only-adjacent decoration that remains legible under browser zoom.

Workspace navigation and ordinary action buttons share the same regular-weight control typography so commands do not read smaller, bolder, or visually weaker than the main Library/Domains/Projects navigation. Navigation keeps a generous hit area, while ordinary action buttons use tight padding and a 34px control height so dense work surfaces stay crisp.

Domain references in dropdowns, picker lists, checklists, chips, saved-search summaries, note links, Settings scopes, and other non-tree lists should render the full hierarchy path such as `Parent / Child / Topic`; dedicated tree views may use indentation, quiet connector elbows, and the selected path detail.

Confirmations, destructive-action checks, and informational acknowledgement prompts are Medusa-owned modal dialogs, not native browser/OS confirm or alert boxes. They use the quiet panel surface, explicit icon-and-text action buttons, layered Escape handling, and a darkened backdrop that keeps the underlying cockpit visible but inactive while the choice is pending.

Current UI architecture:

- Fixed top header with the Medusa emblem, a capped-width global search field with a right-side clear action that exits filtered search mode by clearing the query, a reserved active-work progress control, optional release upgrade action, icon-only Status action, and a far-right user options menu. The user menu exposes Valkey cache usage/hit-rate status with a mini utilization graph, Refresh Cache, Hydrate Cache, a discoverable Quick Switcher entry, a browser-local Continue list for recently viewed documents, a Release History section above Day/Night mode, Settings, and Sign out, replacing the former dedicated logout and theme icons. Refresh Cache and Hydrate Cache show an animated full-row in-flight fill plus `1%` through `100%` copy in the menu row, and the same shell-owned action state is mirrored in the header active-work progress slot so cache work remains visible after the menu closes. Release History opens the bookmarkable `/release-history` page and shows host-agent-recorded applied main releases with date/time, commit hash, and concise feature-change notes. The app-wide command palette opens with `Cmd K`/`Ctrl K` and can jump to workspaces, Release History, recently viewed documents, saved searches, and common shell actions such as clearing search or cache refresh/hydration without adding a second navigation rail. The active-work slot keeps its width while idle so the header does not jump when imports, Concordance, citation refresh work, cache refresh/hydration, or release prompts start, but it must shrink and ellipsize before it can collide with the capped global search field under browser zoom. The release action appears as the same compact accent-colored `Upgrade Now` button when a host-side status check reports newer pushed code, and switches to `Reload Now` whenever the server is already running a newer build than the current browser bundle. Same-hash runtime refreshes do not prompt because the embedded browser build stamp still matches the server. The icon-only Status action opens `/status` and has a quick hover summary for uptime, memory, database, and active work; the full page shows build/version identity with the short commit hash, uptime, memory and disk footprints, database size, Valkey cache state, runtime versions, proxy state, storage path details, backend image identity, hot-route p95 timings, active queue age/depth, database relation footprints, and storage-footprint splits from existing authenticated status APIs. Its final section is Library Fun Stats: visible-library document/page/figure counts, bibliography reference totals, parsed and indexed word/character counts, author/DOI/citation coverage, project-source use, notes, annotations, domains, and tags. Docker image/layer sizing remains optional when the Docker Engine socket is deliberately mounted; without that socket, the Status and Utilities backend-image cards fall back to the backend base-image identity reported by runtime inventory and state that layer sizing is disabled. Starting an upgrade warns that unsaved edits will be discarded, locks the initiating browser tab behind a release progress overlay, waits for the host agent to report completion and for both `/api/health` and the exact app shell route to answer through the public proxy, then reloads into the new browser bundle before returning control. If a browser is already stale when the user clicks `Reload Now`, the same health and app-shell checks run before the cache-busting reload begins. The React startup screen uses the Medusa emblem, clear upgrade/reload/restart copy, and a subtle activity indicator while startup health retries are still running.
- The area below the fixed header uses the primary panel background as the workspace canvas instead of a gray moat around floating cards. Workspaces should read as open continuous surfaces rather than boxed panels: resize gutters act as slim draggable dividers with hover/focus feedback and double-click reset, top-level pane borders are avoided, and internal grouping uses light section rhythm, subtle row separators, and active/hover states instead of nested thin outlines. Library, Settings, Domains, Projects, Recon, Tags, Portfolio, Queue, Finances, Utilities, and Status share this open-canvas direction while preserving framed repeated rows, dialogs, and genuinely bounded tools where boundaries aid scanning.
- The app shell treats idle resource use as a first-class UX constraint. Header and navigation badges come from compact dashboard counts instead of whole-list polling, heavy workspace datasets are fetched only when their workspace is visible, search input waits briefly before refetching document results, idle document-list results stay fresh briefly to avoid redundant view-switch fetches, and fast polling is reserved for active imports, Concordance, backups, cache refresh/hydration, or release upgrades. The Library uses `/api/documents/list` result windows with total counts, a 50-row default, Settings-persisted page sizes with suggested values of 25/50/100/150/200/250/500 and arbitrary whole-number sizes of 10 or greater, and virtualized rows instead of rendering the full corpus in the browser by default. List responses are deliberately slim and omit heavy full-text, bibliography, and citation blobs from row queries; secondary workspaces can still use the shared document-list API without Library-only enrichments such as duplicate badges and project membership when they only need a lean all-document reference set.
- Horizontal work navigation replaces the old left sidebar: Library, Domains, Projects, Recon, Tags, Stashes, Portfolio, Queue, Activity, Health, Import, Finances, and Utilities are laid out left-to-right in the former dashboard-metric strip and styled as quiet no-background links. Settings remains a canonical `/settings` workspace, but it is reached from the far-right user options menu rather than duplicated in the horizontal work navigation. Release History is a canonical `/release-history` workspace reached from the user menu and command palette rather than the horizontal work navigation. Notes remains an implemented `/notes` workspace route, but its horizontal button and `N` shortcut are hidden until the fuller Notes backlog item is ready for the main cockpit again. Each top-level workspace has a canonical browser path (`/library`, `/domains`, `/projects`, `/recon`, `/tags`, `/stashes`, `/portfolio`, `/queue`, `/activity`, `/health`, `/notes`, `/import`, `/budget`, `/utilities`, `/release-history`, and `/settings`) so pages can be bookmarked, opened in a new tab, and restored on refresh. The Status page has its own bookmarkable `/status` path but is reached from the top-right icon rather than the horizontal work navigation. Document focus links use `/documents/{document_id}` and open Library with that document selected in the detail pane; the paged Library list anchors to the result window containing that document and scrolls the highlighted row into view. `/documents/{document_id}/reader` opens the same document in expanded Reader mode, and leaving Reader restores the selected row's list position instead of resetting the visible page. `/document/{document_id}`, `/documents/{document_id}/detail`, and `/reader/{document_id}` are accepted as compatibility aliases and normalized to the canonical document paths. Top navigation assigns single-letter shortcuts when focus is not inside an editable control: `L` Library, `D` Domains, `P` Projects, `R` Recon, `T` Tags, `A` Stashes, `W` Portfolio, `Q` Queue, `Y` Activity, `H` Health, `I` Import, `B` Finances, and `U` Utilities; top-nav tooltips show the shortcut on a second line.
- Main Library view uses a tri-pane layout:
  - Resizable left filter pane for domains, tags, smart filters, saved searches, selected-document bulk edit controls, and document hygiene utilities under the Domains tree. Saved searches can be applied, renamed inline, duplicated, overwritten with the current Library query/filter scope, and deleted after confirmation; custom ordering and first-class durable workspace views remain future work. The pane has a content-aware minimum so select controls and their affordances remain visible, and the whole filter pane can be collapsed from its heading when the user wants a wider reading/listing surface. Collapsed-filter mode hides the pane and its resize divider, then gives the recovered width to the center list and right preview pane with the preview pane receiving the larger proportional share; a compact toolbar control restores the filters. When one or more documents are selected, non-destructive bulk controls for read status, priority, tags, domains, and projects appear in this pane; confirmation-gated Trash remains in the result header. The bottom Keywords cloud ranks the most common tags in the current Library result rows and each chip applies or clears that tag filter so the left pane supports iterative drill-down. Library document rows can be dragged onto left-pane domain rows to add that domain assignment, with dashed ready states, hover/release feedback, and assigned-state indicators. Title Cleanup trims leading/trailing title whitespace and collapses repeated title whitespace across active documents, using the same async button feedback treatment as Refresh and Concord actions. Find Duplicates scans active Library documents with the duplicate-matching service, opens a side-by-side review dialog for each pair, shows match basis plus created/updated/history recency details, and lets the user choose which document remains visible or mark the pair as different documents. Resolving a duplicate soft-deletes the unkept document, preserves file/history data, and records duplicate-resolution evidence and `DocumentVersion` history on both records. Marking a pair different preserves both documents and records false-positive duplicate evidence so future scans, filters, row badges, and detail badges ignore that pair.
  - Center dense document results with a stable result/selection count, selected-document Trash action, sort control, and pagination controls. Results default to title ascending when no search rank is active, can also sort by publication date/newest first or page count/largest first, are fetched from `/api/documents/list` in a 50-row default page size, and show the total matching document/page counts plus previous/next controls so the row count remains honest without loading the whole corpus into React by default. The result label shows Browsing copy when nothing is selected and `X selected of YYY` when selection is active. Pagination uses previous/next arrow buttons and an explicit current/total page count computed from the list endpoint totals; arrows disable while a requested page window is still loading so placeholder data cannot select the wrong row. Settings persists the preferred Library page size; the control suggests 25, 50, 100, 150, 200, 250, and 500 rows while accepting any whole number 10 or greater. Active global search and Library filters are repeated as compact removable chips above the result rows, with a Clear All action, so scoped result sets are visible even when the left filter pane is not the user's focus. The mounted row set is virtualized with density-aware fixed row heights and explicit alternate-row parity so large pages do not make scrolling or rendering proportional to the full result size. Library density is a user preference: `Comfortable` is the current/default spacing, `Compact` tightens rows for fast scanning, and `Reading` gives excerpts more room for browsing. The actual summary excerpt length and matching virtual row height also respond to the measured list viewport width and height, preserving the current laptop-sized clamp while giving roomy and expansive desktop layouts additional summary lines. Library filter and bulk dropdowns use compact searchable custom pickers with Enter-to-select/toggle behavior, capped visible option lists, fixed floating menus that do not resize or scroll-shift panes, and stable trigger widths so background refreshes do not shift the toolbar. Domain and Project bulk controls are multi-selects; when exactly one document is selected, they reflect and edit that document's existing memberships. Tags can be typed and added to the pending bulk selection from the picker. A confirmation-gated Trash action in the selected-document toolbar moves selected ready Library documents to soft-deleted Trash while preserving originals, assets, history, and composition audit records. Locked documents cannot be bulk edited, dragged onto domains, or moved to Trash until unlocked. The selected-document Concordance button above the list is intentionally removed for now; document-level and Settings Concordance entry points remain. Document rows use visible-but-quiet alternate shading when enabled, true black/white title text by theme with the publication year appended as a normal-weight `(YYYY)`, first-paragraph inline summary excerpts, fixed aligned byline columns for page count, nonzero figure count, and author list, and a fixed metadata column that stays quiet for normal states. Library list rows omit normal `Ready`, `Verified`, `Normal`, and `Low` badges; they show only elevated priority, persisted duplicate summary badges refreshed by duplicate scan/resolve/dismiss actions, non-ready/non-verified states, and a quiet `No DOI` chip only when the document has been explicitly flagged as confirmed to have no DOI.
- Resizable right document detail/correction pane for authenticated original PDF preview, normalized one-page parsed text reading and editing, color-tinted domain chips listed before inline alphabetical TAGS chips with remove controls, a separate domain Assign picker row that lists all domains with counts, an end-of-list add field, and a Tag Refresh action, DOI Copy/Edit/Refresh/Verify/No DOI controls, APA Reference List and APA In-Text Citation Copy/Edit/Refresh/Verify sections, generated Summary Copy/Edit/Refresh/Validate controls, Bibliography Copy/Edit/Refresh/Verify controls, Inquests, extracted figures with relabel/description correction and delete controls, attributes, compact history rows with version stepping and Restore as Current, evidence, Composition, a lock toggle before Trash, and a single-document Trash control. The detail/Reader top identity strip is sticky and user-configurable from Settings; Title and Authors are sticky by default, with optional Year, DOI, Priority, and status chips. Preview actions are grouped by purpose: Reader/Close Reader plus compact icon-only Edit, Link, Download Original, and Lock controls; Ask, Related, Composition, Concord, and Formulas as document work actions; and confirmation-gated Trash as the destructive action. `Open Original` is intentionally omitted because authenticated Download Original and in-app PDF preview cover the durable original access paths without another competing button. Detail responses keep history row metadata, changed-field chips, restorable flags, and preview hints lightweight; full before/after `DocumentVersion` snapshots remain stored server-side and are used by the restore endpoint rather than being sent on every document click. Clicking Edit for document metadata reveals the correction form and focuses the Title field. DOI keeps its compact value-chip styling; DOI Refresh queues citation refresh so DOI/Crossref discovery can run even when no DOI is currently stored, Edit lets the user provide a DOI manually, and No DOI records a manual metadata-evidence flag without storing a placeholder DOI string. Citation sections show Copy, Edit, Refresh, Verify, compact model/provenance controls that display the model name or `user provided` without repeating field-label text, and Markdown-backed rich editors with bold/italic/remove-format controls plus Cmd/Ctrl-B/I shortcuts in edit mode, so formatting can be typed visually while saving back to Markdown. Summary Edit uses Markdown-oriented rich-text controls for bold, italic, underline, bullet/numbered lists, indentation, and formatting removal while preserving line breaks; Summary Refresh queues a summary-only Concordance run using the selected Summary model; Summary Validate records the current text as the validated exemplar, protects it from unconfirmed edit/refresh replacement, and long summaries with more than four paragraphs repeat their generated time above and below the rendered text. Bibliography shows the relative generation time when extraction provenance is available, supports the same Markdown-backed rich editor with bold/italic formatting and keyboard shortcuts in both the focused Bibliography editor and full correction form, and can be manually marked verified even when empty to affirm that the source document provides no reference list. Verified DOI, APA citation, Bibliography, and Summary validation state is stored in document metadata evidence with the verifying/validating user, timestamp, accepted value state or summary digest, and whether an accepted Bibliography value was empty; editing or refreshing verified DOI/APA/Bibliography data or validated Summary text requires confirmation, and confirmed edits/refreshes remove the affected verified or validated state until it is set again. Bibliography Refresh queues a forced document-scoped `bibliography_extraction` Concordance run so the current source reference list can be re-extracted from parsed pages/PDF evidence on demand, then the selected Bibliography Cleanup model formats it as APA-sorted Markdown sources, one per line, conforming to the selected reference/source style, with cited work titles in sentence case, journal/proceedings/container titles in title case, personal authors inverted to `Surname, Initials.`, entries sorted by first-author surname, and intelligent grouping and italics preserved; broad unforced Concordance still protects existing bibliography text from silent overwrite. Tag Refresh queues a forced `tag_refresh` Concordance job for the current document, confirms that existing tag assignments will be removed, then reruns import-style Tag Suggestions and governance with existing-tag reuse before creating any new candidate. Default generated document summaries and Inquest answers are prompted as complete-sentence technical paragraphs written at a graduate academic level suitable for a master's-degree reader that open with the document's substantive claim, problem, method, finding, or conceptual contribution instead of author/year/medium/source-title framing; they cover original ideas or concepts, subject-matter areas, research questions raised, conclusions or novel insights, surprising or counterintuitive results when present, academic context, main takeaways near the end, and adjacent research areas or related topics worth pursuing for continued reading, without bold, italics, bullets, em dashes, fancy quotes, standalone headings, single-word openings, or leaked schema metadata unless the user explicitly asks for another format. Inquests are user-prompted document questions that try inline model answers, fall back to durable worker jobs on timeout, and display saved answers inline with optional titles. Composition opens as a near-fullscreen modal with a compact left summary rail for persisted estimate-vs-actual cost comparison, import cost composition, provider spend, local processing time, and processing issues, plus a larger right-side React Flow pipeline workspace whose connected nodes follow import execution order. The normal desktop layout should avoid whole-modal vertical scrolling by spreading content horizontally and reserving most of the available area for the pipeline; narrow viewports may stack and scroll as a fallback. The pipeline includes second-pass import stages such as OCR audit, page normalization, structured-table evidence, visual extraction/context, bibliography extraction, and downstream model work with the models/preset active at processing time; later Concordance Runs append their own capability and model-call nodes instead of being folded into the original import path.
  - APA Reference List, APA In-Text Citation, document Bibliography, Related bibliography-source rows, and generated project APA bibliography copy actions write both semantic `text/html` and `text/plain` clipboard data. Rich-paste targets such as Word, email, and other rich text editors receive `<em>`, `<strong>`, `<u>`, `<code>`, and paragraph markup without Medusa font styling, while plain-text paste targets receive readable text with Markdown markers stripped.
  - Single-document refresh starts and completions update the selected detail and patch cached visible row data without invalidating the paged Library list, forcing focus, or resetting the current Library result page; imports remain the active-work class that can repoll the Library list because they add or reveal rows.
- Library detail and expanded Reader include a Replace action for in-place source replacement. Replace accepts the normal import source formats, stores the uploaded file as the new durable original on the same document record, clears source-derived metadata, parsed text, citations, summaries, bibliographies, figures, tags, custom attributes, and live page-specific annotations, and immediately queues a normal import job for that document id. The replacement keeps domains, project links, priority, read state, `DocumentVersion` history, processing events, prior Composition/cost rows, and an explicit previous/new accession snapshot so costs, logs, and accession history survive the source swap. Locked documents must be unlocked before replacement.
- Library Reader mode can expand the selected document to the whole lower work area while preserving document controls, PDF/Text/Compare tabs, citation actions, and metadata sections. Expanded Reader dedicates the first visible frame to the sticky document identity strip, action row, tabs, and active PDF/Text/Compare surface so the PDF preview and parsed-text editor fill the remaining window height before metadata sections continue below. The normal `Reader` action becomes `Close Reader` while expanded and returns to the normal Library panes. Preview actions are grouped by purpose: Reader/Close Reader plus compact icon-only Edit, Link, and Download Original controls; Ask, Related, Composition, Concord, and Formulas as document work actions; and confirmation-gated Trash as the destructive action. `Open Original` is intentionally omitted because authenticated Download Original and in-app PDF preview cover durable original access without another competing button. PDF/Text/Compare are compact tab-like buttons sized to their content rather than stretched across the whole expanded Reader width. The Formulas action queues only the manual `formula_capture` Concordance capability for the open document. Escape closes the expanded Reader when no smaller Medusa-owned popover, dialog, menu, tooltip, or expanded editor/composer is active; those smaller surfaces close or collapse first. Download Original streams the authenticated PDF as an attachment with a filename rendered from the Settings Download Naming template. The compact detail-pane PDF preview renders only the focused page so it stays a preview rather than a full-document scroll strip. Expanded Compare mode shows authenticated rendered PDF page images beside the extracted page text editor. Full-document PDF scrolling remains the authoritative way to move quickly through pages and updates the parsed page from the visible PDF position; text-side synchronized scrolling is bounded to the current PDF page so a parsed page with more text height than the rendered PDF can still be read to the bottom without causing an automatic page advance. Page previews render at 2.5x scale. The PDF preview footer includes a page-number field and Scan Page action that runs a local one-page visual pass for figures, tables, graphs, photos, diagrams, and other visual assets; the field follows Medusa's expanded rendered-page scroll surface, and manually committing the field jumps the preview to that page. Scan Page returns review candidates without mutating the document, displays page-map boxes plus 300 DPI candidate thumbnails, supports multiple candidates on the same page, and only replaces that page's stored figure rows when the user chooses Keep selected; Discard clears candidates without changing figures. Stored figures remain user-correctable after extraction: the detail pane can patch figure labels, captions, and searchable gists or delete extractions, rebuilding document search and recording history/composition entries. Parsed-text reading keeps a compact search control plus page navigation and Copy/Edit controls at the top and bottom of the text pane. Reader search is case-insensitive over parsed page text, reports total matches and matching-page position, jumps previous/next across matching pages, and highlights current-page matches in read mode without changing stored text. Reader Notes below the reader are backed by `Annotation` rows: the composer captures kind, color, page, body, and optional selected parsed-text quote evidence; rows can be searched, jumped back to their page, edited inline, or deleted, with annotation body text included in document search. Markdown-looking pipe tables render as quiet scrollable tables in read mode, and recognized LaTeX formula delimiters render as math while Copy/Edit preserves the underlying normalized text. While editing, the bottom strip switches to Save/Cancel. Text edit mode has a below-editor tool strip whose first action is Scrub; when text is selected, Scrub counts exact matches across the document and removes that string from all normalized page text as one audited edit.
- Authenticated PDF page-image preview URLs include a document-content version derived from the current checksum and page count. The backend only grants long-lived browser caching when that version matches the active original so replacement imports cannot reuse stale page PNGs for the same document ID.
- Completed ready documents expose a Library detail Related modal that uses most of the viewport instead of a compact popover. The modal loads any cached related papers and, when empty, automatically refreshes from bounded scholarly metadata search, DOI/reference-graph services when DOI exists, locally parsed bibliography references, and the source document's project/domain/tag research neighborhood. Ready documents no longer require a DOI or extracted bibliography before Related can try discovery; a searchable title plus any available abstract, summary, tags, domains, DOI, or bibliography can seed title/topic/evidence queries. Stored `Document.bibliography` entries can seed DOI/title candidates with raw reference evidence; bibliographies and provider results from top context-neighbor documents can also seed additional leads when those neighbors share projects, domains, tags, authors, or nearby publication years. These candidates run through the same enrichment, ranking, duplicate-suppression, and stash/import flow as provider candidates, with query/context evidence preserved as recommendation chips and metadata. Recommendations default to Discover / Diverse, which hides library-held, active-import, queued-import, and already-stashed DOI candidates while preserving Already Known and All audit views. Relation filters cover Diverse, Closest, Newer, Foundational, Methods, Contrasting, Open PDF, and Reference Material. The modal groups provider-discovered, search-discovered, and context-derived non-bibliography results as Other Related Articles and the source document's extracted reference list as Bibliography Sources; bibliography sources keep their raw citation text visible and attach enriched recommendation actions when a source has been parsed into a recommendation row. Recommendation rows show title, DOI, venue, year, source, short abstract/description, compact evidence chips, known-item suppression reason when applicable, and open-PDF availability without card backgrounds. Row actions sit below the item text and support copying just the DOI, copying the title, copying source bibliography text, stashing open-PDF DOI leads, wishlisting non-open DOI leads in Stashes without queueing a PDF, opening the source, opening a manual Google Scholar search in a new tab, and queueing selected or all discovery open PDFs for import.
- Stashes view is the DOI-backed acquisition workbench. It lists saved related-paper DOIs as sortable bibliographic rows with title, authors, year, venue, abstract/description, source, and page count when Medusa knows it, and defaults to a Wishlist lane for active stashes that lack open-PDF evidence. Additional lanes show Open PDF leads, queued/running stash imports, already-matched Library items, and All stashes. Recommendation-created stashes snapshot recommendation metadata; hand-entered DOI stashes use enabled public DOI metadata services such as OpenAlex, Semantic Scholar, and Crossref to fill missing bibliographic fields. Each row can copy the DOI, copy the paper title and then open the DOI at Sci-Hub in a new user-opened window by appending the DOI to `https://sci-hub.box/`, open saved source/open-PDF evidence, jump back to the source Library document that produced the recommendation, resolve and import an open-PDF copy through DOI metadata sources, upload a PDF through an Upload PDF button, or use a compact dashed "Drag PDF Here To Upload" target. Uploads and resolver-backed DOI imports create normal import batch/job records immediately, and successfully imported stashes can be removed from the list. Stashes are also marked imported/removable when any ready Library document has a matching normalized DOI, high-confidence title match, or both, even if that document arrived through another import path; matched rows expose a Library link for validation and a Delete Stash action that removes only the stash record, not the imported document. A separate no-DOI acquisition wishlist entity remains future work.
- Import view centers drag/drop staging for PDF, HTML, and plain-text/Markdown files plus a batch-defaults intake panel for optional label, priority, read status, domains, tags, projects, and the selected import-processing preset. Domains, tags, and projects use searchable chip pickers with restrained inline creation so bulk uploads can be organized before files are dropped. Non-PDF uploads are parsed for source semantics, converted locally to PDF, and stored as PDF mezzanine originals so preview/download/storage paths stay uniform. The processing preset defaults to Balanced from Settings, can be changed before staging files, and is snapshotted onto the batch/job so later Settings edits do not change queued work.
- Import view also provides active drop-target feedback, duplicate-decision handling, live staged/processing job rows, persisted rough per-file dollar estimates, a staged/queued grand-total estimate, a Process Uploads button that releases all staged rows into the worker-claimed import pipeline, and a Clear Staged button that discards staged uploads before processing by deleting their queue-only document/job records plus managed cache/original storage objects. Duplicate preflight and staging prepare the same import-source profile, store MD5 for the durable stored original, and compare SHA-256, MD5, normalized DOI, case-insensitive normalized title, authors, publication year, journal, publisher, source URL, and close page count against active Library/queue rows and the current drop. Staged estimates use the selected Import Processing preset snapshot, known model-pricing history, prior import usage exemplars when available, and prior estimate-vs-actual calibration. Estimate metadata records step-level local/pending/model-backed components so capped page normalization, shared metadata/summary/citation/tag/embedding work, local cleanup/bibliography/visual extraction, and pending OCR/visual model routes are distinguishable. Staged rows are durable queue records, but their document rows are not Library-visible until processing completes: they must not appear in Library lists/search, dashboard document counts, domain/tag document counts, project bibliographies, recommendation existing-library matches, or Concordance scopes. Rows shade left-to-right with per-file progress while showing bold status, an animated processing/import glyph near the status when work is active, current model, known or rough spend, row retry when recoverable, and a horizontally separated row Cancel action for staged/queued/failed/restored work. Import > Processing orders visible rows active-first so running jobs and their progress details stay visible during large batches, then shows failed/restored, queued, staged, and recent completed rows. Completed rows stay visible briefly, then disappear from that panel after 15 seconds while remaining durable backend history. Utilities > Ingestion History reads `/api/utilities/ingestion-history`, derives batch audit rows from `ImportBatch`, `ImportJob`, `ProcessingEvent`, usage, and composition-ledger records, and shows label, status, file counts, total size, preset, time taken, estimate, actual cost, and cost per processed document.
- The reserved header active-work control shows import progress first when imports are active, including imported/total count, percentage, ETA in minutes, current stage, and current known dollar spend so far, otherwise active Concordance/citation/Inquest background work. When more than one non-import background unit is active, the header uses an aggregate active count, progress percentage, and finished/total detail instead of showing the first one-job run as if it were the whole queue. When import work completes, the header shows the latest recently completed batch's actual cost as transient top-chrome feedback until the browser user dismisses it or it ages out; restored or older completion history stays in the operational history views instead of resurfacing in the header, and dismissing the latest completion does not rotate older completed batches back into the header. Recent failed OpenAI/Gemini usage rows surface through a separate shell-level alert with task, model, document/source, error text, estimated cost when known, and an Open Finances shortcut; the alert remains visible until dismissed or opened so provider failures do not stay hidden in the Finances ledger. The active-work control is visually hidden when no work is active or retained completion notice exists, keeps its wider layout slot reserved, and clicking it opens Queue.
- Domains view is the domain-tree management surface. It provides a searchable alphabetized tree, top-level or nested domain creation, selected-domain editing for name, parent, description, tag associations, and color, child creation, soft delete with confirmation, a direct list of documents assigned to the selected domain, and deterministic suggested filing candidates from the library. Parent domain rows display direct document count first and descendant document count in parentheses, for example `0 (5)`, so direct filing and child-folder totals remain distinct. Suggestions use domain tags/name/description against document tags/title/summary/citation text and must exclude documents already assigned to the selected domain or any descendant domain. Domain descriptions and associated tags are domain-level classification hints for filing suggestions; they do not silently expand assigned-document search text. The Domain Tags editor suggests existing tags from the selected domain description and the tags attached to suggested filing documents, but adding those suggestions remains user-approved and draft-only until the domain is saved. The same tag picker accepts pasted comma/semicolon/newline-separated tag lists, maps exact normalized names to existing tags where possible, and shows matched, skipped, and unmatched values for approval before updating the draft. Top-level domains and every nested sibling group are displayed alphabetically by name.
- Projects view supports project creation, run-sheet resource management, status/priority/used tracking, project notes, and bibliography generation, with run-sheet controls constrained to their pane so long document titles cannot spill into bibliography controls. Bibliography generation controls live in the Bibliography panel, all-sources and used-only generation actions stay side by side, and APA output renders Markdown italics on a white full-width bibliography surface while BibTeX/RIS/CSL JSON remain preformatted.
- Recon is the corpus inquiry workspace at `/recon`, placed between Projects and Tags. It uses a dense three-pane cockpit: inquiry list and editor, answer/run surface, and evidence panel. Inquiries store title, question, instructions, scope, default mode, selected model, status, and run history. V1 scopes include the visible Library, one domain, one project, or one saved search; default Library scopes exclude hidden Portfolio version/material rows. V1 modes are Source Finder, Quick Answer, Broad Sweep, and Exhaustive. Source Finder returns ranked source evidence first; Quick Answer synthesizes only from stored evidence; Broad Sweep and Exhaustive are explicit but currently retrieval-backed with warnings until deeper worker-backed per-document passes land. Answers may cite only stored `ReconEvidence`; weak support should be reported as weak rather than inflated into authority. Estimate and Run actions are manual and user-triggered.
- Tags view supports tag management as a sortable, searchable table with document counts, governance status, row selection, shift-click range selection across the current visible sorted/filtered rows, and a left-aligned operation toolbar for Clear Selection, Rename, Merge, Delete, and Optimize. User-facing tags are flattened: keyword/topic distinctions are not exposed in the Tags view, import defaults, or document panes. Rename works for exactly one selected tag. Merge is enabled for two or more selected tags, displays the selected count in the button label, and opens a confirmation dialog where the user chooses a selected tag to keep or enters a different merged tag name. Merges remember normalized source tag names as aliases for the kept tag so future import, Concordance, manual, and bulk tag-name creation resolves old merged labels to the current canonical tag instead of recreating deleted source tags. Optimize opens a right-side governance plan pane and uses the same Settings-selected Tag Suggestions model that import uses for tag creation, plus deterministic analysis, to review the selected tags, or the currently visible filtered tag list when nothing is selected. The pane shows a top progress strip with model, scope, and elapsed time while the synchronous plan request is building. It returns deeper cleanup plans with strict primary merge suggestions, looser single-document cleanup merges, orphaned zero-link tag merge/prune suggestions, semantic relationship suggestions, candidate/canonical status suggestions, and weak document-tag assignment pruning suggestions with rationale, confidence, model label, source tag counts, and affected-document counts. Broad scopes larger than the 300-tag model inventory cap skip the model planner and return a local deterministic governance plan with a local broad-scope plan summary indicator. If the model planner is unavailable or fails on narrower scopes, Optimize still returns deterministic local governance suggestions and marks the plan summary with a model-planner fallback indicator instead of failing the whole request. Optimize is intentionally allowed to flag low-use and legacy singleton tags for downgrade, retirement, merge, or pruning because older imports created many canonical one-document labels before governance scoring existed. It should still return governance actions for scopes made only of zero-use and one-use tags even when no merge candidate exists: true zero-link orphan tags should merge into a useful used tag when deterministic variant/prefix/semantic checks find a strong target, otherwise they are prune-entirely candidates; one-use candidates without durable evidence are retire candidates; one-use canonicals are downgrade candidates unless low-value or near-duplicate enough to retire; and singleton assignments without scoring history are prune-review candidates. No optimization is applied until the user approves a suggestion. The plan pane supports individual approvals and an Approve All action for the current plan; batch approval applies merges first, then orphan prunes, semantic relationships, status changes, and assignment pruning, shows a top in-pane progress strip while the bulk request is running, and reports stale skipped actions when earlier merges remove tags referenced later in the plan. Approved merge suggestions call the normal audited merge endpoint; approved orphan pruning deletes a tag only when it has no document links at all; approved assignment pruning removes one document-tag link with `DocumentVersion` history; approved relationships and status changes teach future import scoring without silently rewriting documents. The general Delete toolbar control remains reserved pending broader implementation.
- Queue shows staged/queued/running/failed/restored import jobs with the same shaded per-job progress rows, current model, known or rough spend, stage detail, animated status-side processing glyph when active, right-aligned retry slot, and spaced row Cancel action used by Import > Processing. Import and Queue both show a compact latest import receipt from ingestion history with file counts, failed count, actual spend, estimate comparison, cost per document, preset, duration, and storage size so completed batches remain understandable after the header completion notice is gone. Queue bulk actions include Process Uploads, Retry Failed, Clear, and Clear Failed, and the header shows the rough staged/queued upload total. Cancel and Clear park staged, queued, failed, and restored-paused import rows as `cleared` but leave fresh running worker locks alone; failed recommendation download rows that happened before a document exists remain visible until canceled/cleared but cannot be retried because there is no stored document to reprocess. Citation cards use the owning document title, source/provenance chips, a constrained citation preview, and attached accept/reject actions so long titles and provider labels cannot collide.
- Activity is an initial unified Work Ledger surface at `/activity`. It aggregates existing durable records from import batches, import jobs, Concordance runs, non-complete Concordance jobs, backup/restore runs, and citation review candidates into lane filters for All, Imports, Concordance, Backups, and Review. Rows share concise status pills, timestamps, progress bars where available, and navigation actions back to Queue, Import, Utilities, Settings, or the source document. The top Active count and navigation badge use dashboard-backed active-work totals, including import jobs, Concordance jobs, Inquests, and active backup/restore rows, so counts keep updating even when a particular durable work type does not yet have a detailed Activity row. Failed rows remain visible even when normal recent-row caps would otherwise push them out of the ledger. This first pass is intentionally an aggregation layer over existing APIs; a future durable cross-work ledger table should add recommendation downloads, OCR/embedding details, provider-failure rollups, pause/resume/cancel semantics, and deeper event/model-call drilldown.
- Health is the Corpus Health workspace at `/health`. It reads a dedicated library snapshot with duplicate/project detail and summarizes DOI evidence gaps, citation review, missing summaries, missing author/year identity fields, unfiled domains, untagged documents, documents not yet used in projects, duplicate candidates, failed import/Concordance work, and latest unresolved backup/restore failures. Historical backup/restore failures stay visible in Activity, but a newer successful run in the same backup or restore group clears the Health warning. Document-backed issue cards open Library with a visible `Health` result chip backed by `/api/documents/list?health_status=...`, so sampled cards and the destination list use the same review scopes. Each issue card shows counts, sampled affected documents, and repair entry points back to Library filters, Queue/Activity, Domains, Tags, Projects, Settings, or the individual document. This first pass intentionally uses existing document and job APIs; future Corpus Health work should add first-class capability freshness, OCR/figure/table/embedding coverage, saved health views, and scoped repair queues with cost/time previews.
- Settings includes a quiet Slipstream panel for enablement status, one-time enrollment tokens, registered clients, capability/capacity metadata, last check-in, active leases, and disable/revoke/cancel controls. Queue rows show whether a running job is assigned to Local worker or `Slipstream: client-name`, with lease heartbeat/expiry metadata available from the row payload.
- Notes view supports notes/reminders attached to documents, domains, projects, or the general library.
- Finances exposes AI usage exploration with last-day, last-month, last-3-months, and all-time windows in a full-width analytics workbench that keeps text at the ordinary Library scale and reserves heavier type for headings and key values. It uses a command strip for period/metric/group controls, compact metric tiles, a cost trend line over calendar day/hour rollups, cost-by-model and token-by-task pie charts, a tightly columned rollup table, and a recent-call ledger panel. Model, task, document, calendar-day, and calendar-hour rollups remain available when usage records include model/document data. Utilities exposes Bulk Intake for duplicate-safe large imports: the module accepts many PDF, HTML, Markdown, or plain-text files, checks the whole set through `/api/imports/duplicates`, shows every existing Library/Queue match and every repeated file in the drop, and stages only files with no duplicate match through the normal staged import queue using `/api/imports/batches` with duplicate skipping. Utilities also exposes a Database section for authenticated maintenance actions: Compact Database runs PostgreSQL `VACUUM (FULL, ANALYZE)` to reclaim database space where possible, Optimize Database runs `ANALYZE` to refresh table statistics, Backfill Document Hashes hydrates missing originals into the document cache and writes missing `Document.checksum_md5` values, and Clear Import Cache removes terminal hidden import rows plus stale project-resource links that are excluded from Library and Queue active surfaces. The Clear Import Cache button shows the current hidden import-document count, while Backfill Document Hashes shows the current active-document MD5-missing count. Utilities also exposes full database backup/restore controls, legacy metadata JSON/storage-manifest export links, a backup-size trend graph that fills its available horizontal span, a Container Footprint section backed by `/api/utilities/container/status`, reporting backend-container cgroup memory/CPU, service uptime, process/thread counts, data-volume disk usage, path-level footprints for Medusa-managed storage directories, runtime versions for HAProxy/backend/frontend binaries and packages, and Docker image/layer sizes when the Docker Engine socket has been deliberately mounted into the backend container. Compose does not mount the Docker socket by default because even a read-only socket bind grants the backend process broad host Docker control. Below it, HAProxy Statistics reads `/api/utilities/haproxy/status` and reports the HTTPS endpoint, frontend/backend status, sessions, traffic, health-check detail, and proxy error totals from HAProxy's internal CSV stats feed. The Container Footprint section can restart the backend container through `/api/utilities/container/restart`: the endpoint schedules a backend process termination after returning, the Compose backend service has `restart: unless-stopped`, and the frontend polls `/api/health` until the backend is healthy again. Settings exposes preferences, citation convention selection, Library alternate-row shading, Library density, configurable sticky document fields, day/night accent color controls, Download Naming for original-PDF attachment filenames, import-processing presets, preset-specific model routing, shared raw extraction/document-analysis model defaults, model-pricing refresh status and stale-pricing warning, GCS bucket configuration, managed Google service-account upload/status, document cache budget controls, and Concordance controls. Import Processing settings must show each pipeline step with an enabled state where applicable, the actual route and model/provider used by the selected preset, core parameters, sensible defaults, and a tooltip explaining exactly what happens and what the step accomplishes. Shared model defaults live inside Import Processing so users can see how Balanced, Strict Local, Deep Review, or a custom preset combines preset-specific model routes with global metadata, summary, citation, tag, normalization, raw extraction, manual formula-capture, and embedding defaults. Settings places Save All controls at both the top and bottom of the view, and each Save All action persists all preference groups together; uploaded service-account JSON and model-pricing refreshes are saved through their own authenticated actions. Navigating away from dirty Settings through Medusa's internal navigation asks whether to save first; accepting runs the same Save All operation before leaving.
- Full database backup and restore are browser-driven from Utilities, including a one-row backup selector plus Restore Database action, a total-size readout for all listed backup dumps, and a recent backup/restore history list so prior runs remain visible after a new backup completes. Browser restore uses selected local backups by default and requires confirmation before queuing; legacy metadata restore remains CLI-first: dry-run by default, explicit `--apply`, and intended for JSON export drills or partial fresh-database recovery.

Visual decisions:

- The header brand uses the user-provided cropped transparent Medusa emblem PNG plus a large lowercase `medusa` wordmark in Century Schoolbook Bold, falling back to compatible local serif faces. The emblem is borderless and sized to visually match the wordmark height. Hovering or focusing the emblem/wordmark shows the acronym expansion: "Metadata-Enhanced Document Understanding, Search, and Analysis."
- The header brand lockup should have restrained, generous top/bottom padding plus modest side padding so the emblem and wordmark breathe without turning the header into a hero element.
- The browser page title is lowercase `medusa` at rest and becomes `medusa (local)`, `medusa (local: IP)`, or `medusa (remote: IP)` after startup/runtime location detection, depending on how the page is opened.
- The browser title stays lowercase and contextual: top-level workspaces render as `medusa | Workspace`, selected documents render as `medusa | DOCUMENT_TITLE`, selected projects as `medusa | PROJECT_TITLE`, and equivalent management surfaces use the current selected domain/tag when available.
- The top header does not display a build/version stamp. The login panel shows the frontend build stamp under the form in muted text, and both Status and Utilities report the same stamp in runtime metadata so the running UI can be identified without developer tools. The stamp uses `YYYYMMDD (HASH)`. `MEDUSA_BUILD_VERSION` can explicitly set the full stamp for server releases; otherwise `MEDUSA_BUILD_DATE` and `MEDUSA_BUILD_HASH` can override the parts, and local builds use the current date plus a build-content hash when those values are blank.
- The emblem asset set includes a black transparent PNG for day mode and favicon default plus a white transparent PNG for night mode and dark-scheme favicon use. The startup/loading screen and HAProxy maintenance page use the same cropped mark.
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
- Optional Slipstream clients: remote Python processes registered with the central app that poll over HTTPS for leased import or Concordance work; they do not expose inbound ports and never connect directly to PostgreSQL.
- `db`: PostgreSQL with `pgvector`.
- `valkey`: internal Valkey cache service using the Redis protocol, no host port, no persistence, bounded by `MEDUSA_VALKEY_MAXMEMORY` at startup, `allkeys-lru` eviction, and attached only to the private backend/worker cache network. The default memory cap is 8 GB, and Settings > Preferences can save and apply a different Valkey Memory Limit to the running service.
- `haproxy`: TLS terminator and redirect/proxy on host port `3737`, with internal stats on `8404`.
- Optional `metrics-exporter`: backend-image Prometheus text exposition sidecar on internal port `43737`, added only through `docker-compose.metrics.yml`, exposed publicly through HAProxy TLS on `MEDUSA_METRICS_BIND_IP`, and protected by a bearer token. It reads a Valkey-backed heavy metrics snapshot, live Valkey and HAProxy stats, a private backend snapshot endpoint, and optionally the Docker Engine Unix socket when deliberately mounted.
- `docker-compose.yml` wires the application services and exposes only HAProxy on host port `3737`; Valkey is not attached to the public-facing proxy/frontend path and has no published host port. The metrics overlay is the only planned host-published exception, and should bind only to the monitoring interface/IP rather than `0.0.0.0`.
- Backend and worker startup initialize PostgreSQL through Alembic migrations before normal app workflows open. Backend startup also schedules a background Valkey cache hydration by default after the saved Valkey memory limit has been applied.
- Dependency freshness is managed through root `renovate.json` plus `docs/DEPENDENCY_UPDATE_PLAN.md`: Renovate checks Docker, backend, and frontend dependency surfaces twice weekly, while critical security updates can be handled immediately. A host-side maintenance lane can also run Tuesday/Friday during the quiet `03:00-06:00 America/Indiana/Indianapolis` window for already-merged safe updates and same-tag image refreshes. Routine restarts, rebuilds, safe app updates, and same-tag image refreshes do not require a database backup. The host agent requires a fresh full PostgreSQL backup only when the classified change touches database schema or persistence, backup/restore tooling, runtime container definitions, non-patch backend runtime dependencies, or major underlying program versions such as PostgreSQL/pgvector. Runtime image updates must preserve explicit tags, the Valkey private cache network, and the invariant that base application Compose publishes only HAProxy on host port `3737`; the optional metrics overlay may additionally publish the bearer-protected metrics sidecar on the configured monitoring bind IP and port. Docker Engine and Compose plugin updates are report-only recommendations outside Medusa automation.

Data storage:

- PostgreSQL is the system of record.
- Valkey is a derived response-cache and operational-counter layer only. It stores rebuildable API payloads and status/counter data, not source-of-truth documents, search indexes, jobs, correction history, auth state, or evidence. Valkey is internal-only, not exported, and not backed up. Cache keys include durable PostgreSQL `cache_revisions` rows so relevant writes and manual refreshes make old Valkey payloads unreachable even if old keys remain until TTL/LRU pruning. Startup and manual cache hydration fill the current revision's derived API payloads from live PostgreSQL data, including organization/status/dashboard payloads, deterministic Library pages, saved-search pages, and visible document details that fit the payload and memory caps; hydration does not create a second durable data model. `MEDUSA_CACHE_STARTUP_HYDRATE=true` is the default, `MEDUSA_CACHE_HYDRATE_MAX_DOCUMENTS=0` means all visible Library document details, and `MEDUSA_CACHE_HYDRATE_PAGE_SIZE` controls list-page hydration windows. The Valkey memory cap defaults to 8 GB and is configurable from Settings, which persists the value and applies it through Valkey's runtime configuration path when reachable.
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
- `backend/app/services/openai_usage.py`: durable AI usage recorder, model-pricing history maintainer, and Finances/Settings rollup builder for OpenAI/Gemini token/file-context counts and conservative estimated costs by task, model, document, calendar day/hour, import job, and Concordance job.
- `backend/app/services/composition.py`: per-document import composition ledger helpers, cost summarization, provider rollups, local duration rollups, processing issue tracking, pipeline chart data construction, and active-import cost estimation.
- `backend/app/services/ocr.py`: Google Vision adapter placeholder.
- `backend/app/services/processing.py`: import processing orchestration.
- `backend/app/services/preferences.py`: DB-backed local preferences such as import worker concurrency, Library alternate-row shading, accent colors, Download Naming templates, saved GCS bucket, managed Google service-account status, document cache size, document-analysis model selections, and model-pricing status payloads for Settings.
- `backend/app/services/google_credentials.py`: service-account JSON validation, secure managed-key storage under ignored data paths, and scoped Google credential loading.
- `backend/app/services/concordance.py`: retroactive capability registry, run creation, and Concordance job processing.
- `backend/app/services/slipstream.py`: remote-processing enrollment, request-signature verification, lease coordination shared by local and remote workers, artifact access, heartbeat/expiry, and result-application helpers.
- `backend/app/services/figures.py`: embedded PDF figure extraction, durable asset storage, and figure row creation.
- `backend/app/services/exports.py`: authenticated metadata export and durable storage manifest builders.
- `backend/app/services/backups.py`: full PostgreSQL backup/restore orchestration, `pg_dump`/`pg_restore` subprocess handling, zstd compression/decompression, local backup artifact listing/storage, optional explicitly enabled GCS backup object listing/upload/download, checksum verification, and restore safety backup gating.
- `backend/app/services/cache.py`: Valkey/NullCache response-cache adapter, durable cache-revision helpers, SQLAlchemy revision-bump hooks, cache status payloads, route/cache-family counters, and storage/database/queue footprint rollups for Status.
- `backend/app/services/restore.py`: metadata export validation, dry-run planning, and fresh-database restore logic.
- `backend/app/services/citations.py`: APA/BibTeX/RIS/CSL formatting utilities.
- `backend/app/services/verifier.py`: Crossref lookup, Semantic Scholar/title-search DOI discovery, targeted title web-search DOI fallback, and verification helpers.
- `backend/app/services/recommendations.py`: DOI normalization, OpenAlex/Semantic Scholar/Crossref related-paper adapters, Unpaywall/arXiv open-PDF availability enrichment, recommendation caching/matching, and open-PDF recommendation import queueing.
- `backend/app/services/search.py`: document search-text rebuild helpers and the shared Library/Concordance search filter that uses PostgreSQL full-text search when available.
- `backend/app/services/performance.py`: request-scoped SQL timing counters installed on the SQLAlchemy engine for lightweight API performance headers and slow-request logs.
- `backend/app/services/runtime_location.py`: startup/runtime IPv4 detection and page-title context classification for local, LAN, and remote access.
- `backend/app/tools/restore_export.py`: CLI entry point for validating, planning, and applying metadata restores.
- `backend/app/slipstream/client.py`: basic outbound-polling Slipstream client entry point that registers with an enrollment token, stores its Ed25519 private key in ignored local data, downloads leased artifacts, and submits manifest-based results.

Frontend modules:

- `frontend/src/App.tsx`: current full application shell and views.
- `frontend/src/lib/api.ts`: API client.
- `frontend/src/types.ts`: shared frontend response types.
- `frontend/src/styles.css`: design system tokens, layout, and responsive rules.

Frontend async-work contract:

- The app shell owns user-visible progress for durable Concordance work. Page controls start runs through a shell-level `startConcordanceRun` helper so the request is recorded in shell state before the API call returns.
- The shell reconciles local "starting" jobs with `/api/concordance/runs` and `/api/concordance/jobs` polling data, then renders active work in the reserved header progress slot while work is starting, queued, or running.
- Header progress shows imports first when imports are active, otherwise a single active Concordance/citation/Inquest background run or an aggregate active-count summary across multiple background runs. It is hidden but width-preserving when idle and opens Queue when clicked.
- Page-level controls still own their local disabled state, soft blue in-flight button/icon/progress treatment, and transient result flash. Completion blends through green; a failed start or failed watched job flashes red and shows a concise popover error.
- The Library DOI and citation Refresh actions queue a forced `citation_refresh` Concordance Run for the current document. DOI Refresh remains available when DOI is missing so stored text and Crossref/title evidence can be searched; APA Reference List and APA In-Text Citation buttons start the same durable pair refresh because both citation surfaces are generated from the same citation metadata/model preference, validated together, and displayed with shared in-flight/success/error feedback. Summary Refresh queues a forced `summary_refresh` Concordance Run for the current document and uses only the selected Summary model; if the current summary is validated, the detail action requires confirmation before clearing validation and queueing replacement, while generic Concordance summary refresh work skips validated summaries. Tag Refresh queues a forced `tag_refresh` Concordance Run for the current document and uses only the selected Tag Suggestions model plus the import-style tag governance scorer. If the user stays on the document pane, the button-level watcher can flash completion/failure; success flashes fade quickly while error flashes remain visible longer. If the user navigates away, the app shell still follows the durable run and displays terminal state.
- Settings, selected-document batch Concordance, and document-level Concordance controls use the same shell-owned starter so navigation away from those pages does not abandon UI reconciliation.
- Import jobs remain represented by Queue rows and the header active-work progress control because their progress is already dashboard-backed; retry, bulk retry, and clear controls use the same transient button-feedback convention.
- Inquest creation writes a durable document-owned row, tries to answer inline with the selected model, and falls back to the worker queue when the inline timeout is reached. Selected-document polling shows queued/running/complete/failed state inline in the detail pane, and the Ask button uses the same transient in-flight/success/error treatment as Concordance and citation refreshes while the row is being created and tracked.
- Recommendation refresh/download actions are not full Concordance runs today, but their buttons follow the same local success/error feedback convention until recommendation downloads become durable background fetch jobs.

## Data Model

Current core entities:

- `User`, `SessionToken`
- `AppPreference`: local DB-backed operational preferences such as import worker concurrency, Library alternate-row shading, day/night accent colors, Download Naming templates, saved GCS bucket, service-account display metadata/path, document-analysis model choices, and document cache size. Service-account private key material is stored only on disk under ignored managed-secret paths, not in PostgreSQL.
- `Domain`: nestable knowledge hierarchy.
- `Tag`: flat library label. The legacy `kind` column is retained for compatibility but normalized to `tag`; keyword/topic distinctions from extraction are flattened into the tag namespace. Alembic revision `20260620_0013` normalizes existing rows. Tag API responses include an active-document count for management views.
- `TagAlias`: normalized source label remembered from tag merges. The alias points at the current canonical `Tag` so later AI tag suggestions, Concordance refreshes, manual correction tags, bulk tag names, and tag creation resolve an old merged label to the kept tag. Aliases are moved forward when their target tag is merged again.
- `SavedSearch`: named query and filter presets for repeated research views and Concordance scopes.
- `Domain`: nested knowledge organization nodes with name, parent, description, color, sort order, document links, associated tags, and soft delete. Domain tags reuse the flat `Tag` vocabulary through `domain_tags` so future domain-filing suggestions can compare document tags/summaries against domain descriptions and tag metadata. The API enforces no parent cycles, rejects duplicate active sibling names, rebuilds affected document search text when a domain rename changes searchable domain text, records document history for domain rename/delete effects, detaches deleted domains from documents and notes, and moves deleted-domain children up one level. Domain API responses keep `document_count` as the direct active-library document count and expose `subtree_document_count` as the unique active-library total across that domain and all descendant domains for hierarchy displays.
- `Document`: canonical source-processing object and processing/search state, including generated citation text and the source document's extracted Markdown-compatible `Bibliography` reference-list field when available. `document_kind` distinguishes normal `library` rows from hidden `portfolio_version` and `portfolio_material` rows that reuse storage, extraction, search text, Composition, costs, and events without entering Library lists/counts by default.
- `DocumentVersion`: metadata correction/history snapshots.
- `DocumentCapability`: per-document completion state for versioned import/concordance capabilities.
- `OpenAIUsageRecord`: per-call OpenAI Responses/embeddings/Gemini usage ledger with document/job/run context, model, task, token counts, cached input tokens, PDF/file-context bytes, status, and recent error text.
- `ModelPricingRecord`: model-pricing history for OpenAI and Google models with provider, model, pricing tier/basis, per-million token rates, optional long-context/Gemini over-200k rates, source URL, observed/check timestamps, and `superseded_at` for price changes. Refreshes update `last_checked_at` on unchanged active prices and create a new historical row only when the rate signature changes.
- `DocumentCompositionRecord`: per-document provenance and cost ledger for imports, Concordance Runs, and edits. Rows record persisted pre-processing cost estimates, second-pass local/import stages, Concordance capability stages, synced model/embedding usage costs, provider/model/method, status, stage ordering, processing warnings/errors, and pipeline metadata. Concordance composition statuses are bounded lifecycle buckets such as `complete`, `skipped`, `warning`, and `failed`; detailed capability/evidence outcomes such as protected-bibliography regression labels stay in metadata so future evidence labels cannot become schema-breaking job state. Estimate rows can seed fallback pipeline nodes for configured steps that did not yet have an actual runtime row, while later Concordance rows carry run/job ids in metadata so Composition can append those runs chronologically. The optional `usage_record_id` links back to the raw AI usage row when available.
- `BackupRun`: durable full database backup/restore progress rows with kind, reason, status, phase, progress, storage URI or local-path metadata, zstd dump checksum, restore source metadata, safety-backup linkage, and error/completion timestamps.
- `DocumentRecommendation`: cached DOI/title-based related-paper recommendations for a source document, including provider/relation evidence, DOI, title, authors, venue, description, open PDF/source URLs, existing-library/import matches, and import status.
- `DoiStash`: saved DOI follow-up rows for related-paper recommendations, including optional title/source evidence, source recommendation/document links, import job/document links, upload filename, status, and soft-delete state.
- `PortfolioItem`, `PortfolioVersion`, `PortfolioVersionEdge`, `PortfolioMaterial`, `PortfolioSuggestion`, `PortfolioAssessmentRun`, and `PortfolioAssessmentFinding`: Portfolio workspace records. Items own user-authored or education/research deliverables; versions point to immutable hidden `Document` rows and preserve original source filename/type/checksum/storage URI/size; edges preserve parent-child ancestry such as `supersedes`; materials attach rubrics, assignment prompts, guides, references, feedback, sources, or other context at item or version scope; suggestions cache Library/external resource leads; assessment runs and findings record model-selection provenance, material snapshots, local/model findings, scorecards, grade estimates, narrative feedback, model outputs, agreement metadata, and evidence.
- `PortfolioAuditEvent` and `PortfolioAuditAnchor`: tamper-evident Portfolio audit records. Events store canonical JSON payloads, SHA-256 payload hashes, previous-event hashes, event hashes, Ed25519 signatures, public-key fingerprints, UTC occurrence times, and Portfolio entity links. Anchors store root hashes, covered event ranges, RFC 3161 timestamp authority metadata, raw timestamp response bytes as base64, and verification status/errors. The signing private key lives only in ignored local data by default at `data/audit/portfolio-ed25519.key`.
- `ReconInquiry`, `ReconRun`, `ReconEvidence`, and `ReconAnswerVersion`: corpus inquiry records. Inquiries own reusable questions, instructions, scope, default mode, and model choice; runs snapshot the resolved scope, mode, progress, estimates, and terminal state; evidence rows persist document/chunk/page snippets and citation/relevance metadata; answer versions store the generated or local evidence summary plus limitations and model provenance.
- `DocumentAccessorySummary`: storage record for user-facing Inquests owned by a document, with prompt/question, optional title, selected model, generated Markdown answer, status/attempt/lock fields, completion timestamp, and model/evidence metadata.
- `DocumentPage`: raw extracted per-page text, normalized reader text, source, low-text flags, and optional page image URI; the document detail API exposes these pages for the full-text reader.
- `TextChunk`: chunked full text and optional embedding vector.
- `Figure`: extracted figure, chart, photo, and diagram crops with durable asset URIs, page geometry, user-correctable labels, captions, searchable gists, and extraction-scope metadata such as document import or Reader page scan.
- `Document.locked_at`: optional per-library-item lock timestamp exposed as `is_locked`/`locked_at` in list and detail payloads and toggled through `/api/documents/{document_id}/lock`. Locked documents stay visible, readable, downloadable, and copyable, but document metadata edits, field verification changes, derived-content refreshes, Reader Notes writes, page text scrubs/restores, figure writes, Related refreshes/recommendation-download queueing, import overwrite, Trash, bulk edits, and Concordance jobs are blocked or skipped until unlocked. The lock state is separate from DOI/APA/Bibliography verified evidence and must not change verified badges or verified-field visual treatment.
- Second-pass state: import-processing presets currently live in `AppPreference`, import batches/jobs/documents snapshot the selected preset in evidence, `Document.bibliography` stores extracted source reference lists, `metadata_evidence.doi_verification`, `metadata_evidence.apa_citation_verification`, `metadata_evidence.apa_in_text_citation_verification`, and `metadata_evidence.bibliography_verification` record manual field verification user/timestamp state; Bibliography verification also records when the accepted value is intentionally empty because the document has no provided reference list. `metadata_evidence.summary_validation` records the manually validated exemplar summary with user/timestamp state, an exemplar marker, and a digest of the accepted `rich_summary` text so validation does not carry across replacement text. `metadata_evidence.formula_capture` stores manual Concordance LaTeX formula evidence, and `Figure` rows store local visual crops with geometry, labels, captions, source kind, orientation metadata, extraction scope, and local context. Reader page scans append `metadata_evidence.visual_page_scans` entries and processing events so targeted visual rescue attempts remain auditable. Remaining planned entities include layout blocks, first-class structured table rows/cells, durable visual hints/bounding boxes, visual asset candidates, visual audit warnings, and richer figure context/crop-quality records so raw extraction, cleaned body text, removed boilerplate, source reference lists, formula evidence, and derived visual assets can be inspected or regenerated independently.
- `Annotation`: page-aware highlights/notes with color, body, soft delete, and reserved geometry for future PDF overlays.
- `Note`: document/domain/project notes and reminders.
- `AttributeDefinition`, `DocumentAttributeValue`: custom per-document attributes.
- `Project`, `ProjectItem`, `ProjectBibliography`: run sheets, resource status/priority/used tracking, project notes, and citation exports.
- `ImportBatch`, `ImportJob`, `ProcessingEvent`: durable import bookkeeping.
- `ConcordanceRun`, `ConcordanceJob`: durable retroactive upgrade bookkeeping.
- `SlipstreamClient`, `SlipstreamEnrollment`, `SlipstreamLease`: remote-processing registration and quorum state. Enrollments store only one-time token hashes and expiry/use state. Clients store public keys, capability/capacity metadata, status, revocation state, last check-in, and recent nonce replay data. Leases store job type/id, assigned worker kind/client, lease token hash, heartbeat/expiry/completion state, payload/idempotency metadata, and terminal error/cancel details. A partial unique active-lease index over `(job_type, job_id)` enforces one active owner for a job across local and remote workers.
- `CitationCandidate`: reviewable citation/metadata candidates.

Important modeling decisions:

- Documents are soft-deleted via `deleted_at`.
- Duplicate detection starts with source/stored SHA-256 and stored MD5 fingerprints, but fingerprints are not unique in the data model because the user can deliberately import an exact duplicate.
- Import duplicate decisions are explicit: skip duplicates, overwrite an existing matching document, or import anyway as a separate document.
- Import and Library duplicate matching also use normalized DOI, case-insensitive normalized title, author family overlap, publication year, journal, publisher, source URL, and close page count. Library views surface duplicate counts, match-basis labels, and a duplicate-status filter. Duplicate resolution from Library review soft-deletes the unkept document and records evidence/history instead of destroying originals. False-positive duplicate dismissals are stored bidirectionally in document metadata evidence and suppress that exact pair from future Library duplicate matching without changing import-time duplicate preflight.
- Citation status is explicit, with `needs_review` as the safe uncertain state.
- Accepted citation candidates apply their metadata/citation to the document, set citation status to `verified`, and create a `DocumentVersion` audit snapshot.
- Metadata evidence is stored as JSON so extraction, Crossref, OpenAI, and future sources can be audited.
- AI usage accounting is stored separately from document metadata in `OpenAIUsageRecord` so cost/debug history survives metadata correction and can include failed calls. The ledger records usage reported by OpenAI and Gemini calls, and future OpenAI rows snapshot the configured pricing tier in usage metadata. Finances estimates dollars from `ModelPricingRecord` history when available, falling back to the current official-pricing table for the configured `MEDUSA_OPENAI_PRICING_TIER` (`standard`, `batch`, `flex`, or `priority`) plus OpenAI embedding and Gemini Developer API text prices. Usage cost lookup resolves model aliases and timestamp-matches each call to the price row active when the call happened; unknown or unavailable models remain unpriced, and token counts stay the durable source of truth because model pricing, billing tier, regional uplift, discounts, and project access can change outside the app. `DocumentCompositionRecord` is the document-facing provenance layer over that ledger: it preserves the staged cost estimate, actual import pipeline, and stage/model composition later Concordance logic can inspect before deciding whether a document already satisfies a capability/model requirement.
- Author records in `Document.authors` use JSON objects with `given`, `family`, `affiliation`, and `email` when visible. Import and Concordance GPT prompts should normalize semi-obfuscated email forms such as `someone{at}university{dot}edu`, `someone [at] university [dot] edu`, and `someone at university dot edu` into `someone@university.edu`; emails must not be inferred when absent.
- Title-only citation evidence must pass a strong normalized-title match before it is stored as Crossref evidence.
- Crossref evidence may fill missing citation fields such as authors, year, venue, DOI, publisher, and source URL; it should not silently overwrite existing user-corrected fields.
- When AI metadata, local text DOI regex, and Crossref title lookup do not find a DOI, import and `citation_refresh` try Semantic Scholar title lookup and then an enabled targeted `"paper title" DOI` static web-search fallback. Strong title support is required before the found DOI is stored under `Document.metadata_evidence["doi_discovery"]`; the citation path then retries Crossref by that DOI.
- The broader DOI discovery strategy should prefer free, structured metadata services before generic web search. Candidate sources include Crossref REST and Crossref Simple Text Query for reference-string matching, OpenAlex works search and DOI lookups, Semantic Scholar Graph API title/DOI lookups, DataCite Public API for DataCite-registered works and datasets, OpenCitations Meta for DOI/PMID/OpenAlex-linked bibliographic metadata, and PubMed/Europe PMC for biomedical title/PMID/PMCID/DOI matching. DOI.org/content-negotiation and Registration Agency checks are useful after a candidate DOI is found; Unpaywall is useful for open-PDF/source-link enrichment after DOI discovery rather than as a title-to-DOI matcher. Generic targeted web search remains the last fallback and must store compact evidence only.
- APA citations should favor DOI links whenever a DOI can be located and verified. If no DOI can be verified, the citation should prefer a direct stable source link, ideally a PDF or other static document, over a transient search or generic landing page.
- Citation and metadata text from Crossref, OpenAI, PDFs, or user review candidates should be normalized for display and exports, including decoding HTML entities such as `&amp;`, `&quot;`, and numeric character references into their actual characters. `Document.apa_citation` stores the APA Reference List entry; `Document.apa_in_text_citation` stores the APA parenthetical in-text citation. Each has model and source fields so the UI can show the generating model or `user provided` after manual override.
- Recommendation matching prefers normalized DOI equality and falls back only to high-confidence title matches with strong normalized title similarity plus year and/or author support except for exact-title matches. Recommendations may be cached from multiple providers; source/provider evidence is retained so a candidate can be inspected later.
- Recommendation v2 metadata is stored under `DocumentRecommendation.raw_metadata.recommendations_v2` so cached rows can carry relation family, reason chips, known status, hidden reason, diversity score, query strings, context score/sources, evidence URL/DOI/PDF fields, and duplicate-suppression basis without a migration-heavy successor table. The listing service recomputes this metadata when rows are loaded so old cached rows and newly staged/stashed/library-matched items stay in agreement. The default ranking uses a maximum-marginal-relevance style pass that balances provider score, query/context-neighborhood score, and open-PDF/DOI availability with diversity across authors, years, venues, providers, and relation families.
- Recommendation and stash DOI imports do not create a parallel processing path. When an open PDF URL is available from a lawful scholarly metadata source or resolver, the download endpoint creates normal `ImportBatch` and `ImportJob` records, stores the PDF through the configured storage adapter, and lets the worker process it like any other PDF. Relatedness currently comes from bounded OpenAlex, Semantic Scholar, and Crossref scholarly search over generated title/topic/evidence queries, DOI/reference graph calls from those providers when DOI exists, locally parsed stored Bibliography references, and a bounded context expansion over top ready Library documents that share projects, domains, tags, authors, or nearby publication years with the source document. Context expansion can add the known neighbor itself as an audit-only Already Known recommendation, parse that neighbor's bibliography into new Other Related Articles leads, and run a small number of DOI-provider lookups seeded by the strongest neighbor documents. Open-PDF availability can be enriched from Unpaywall and arXiv before recommendations are cached. Bibliography entries are parsed into DOI/title/source-url candidates with raw reference evidence, then pass through the same enrichment, existing-library matching, ranking, and stash/import handling as provider candidates. Provider refresh failures plus query, source-bibliography, and context seed counts are recorded in the `recommendations_refreshed` processing event payload. Stash Import DOI uses the same enabled DOI metadata and open-PDF resolver sources, records resolver evidence on the queued document, and does not automate downloads from user-opened external lookup pages. Google Scholar is exposed only as a user-opened search link, not an automated scraper, because its search surfaces are not treated as a programmatic recommendation/download source. Recommendations without open PDF URLs remain metadata-only candidates and can be saved into the DOI-backed acquisition Wishlist lane when they have a DOI.
- DOI stashes are a durable follow-up list for recommendation or hand-entered DOIs that the user wants to revisit later. Stashing is DOI-unique and soft-deleted rows are reactivated on repeat stash. Stash bibliographic metadata, including optional open-PDF URL evidence, is stored in `DoiStash.metadata` rather than a parallel table; imported Library document fields take precedence at display time, followed by recommendation snapshots and then public DOI metadata lookup results. The Stashes API remains one list, while the frontend derives Wishlist, Open PDF, Queued, In Library, and All lanes from import status, library matches, and stored open-PDF evidence. Uploading a PDF from a stash creates the same `ImportBatch`, `Document`, `ImportJob`, cache, storage, and duplicate-skip records as the normal import path, with the stash DOI/source evidence copied onto the queued document. Stash listing syncs completed import-job status and independently imported ready documents by normalized DOI and high-confidence title match so matched rows show as imported and can be removed without deleting the Library document.
- Full-text search data is stored on `Document.search_text`; chunk embeddings live on `TextChunk.embedding`. PostgreSQL search uses a GIN expression index over title, search text, APA reference text, and APA in-text citation with `websearch_to_tsquery`, plus existing title trigram support for title fallback matching. SQLite keeps a simpler `ILIKE` fallback for focused tests.
- Library-visible document filters require `Document.document_kind == "library"` in addition to ready, undeleted processing state. Portfolio versions/materials can be searched and assessed through Portfolio APIs, but they are excluded from normal Library rows, dashboard Library counts, tag/domain counts, project bibliographies, recommendation existing-library suppression, duplicate scans, and default Concordance scopes unless a future explicit include-Portfolio control says otherwise.
- `/api/documents/list` is the primary Library list contract. It returns slim `DocumentListRow` pages, total matching document/page counts, pagination state, focus-position metadata when the caller anchors on a document, and a revision token. `/api/documents` remains available for compatibility and for secondary workspaces that need an all-document reference list; callers can skip duplicate and project enrichments when they do not need Library row badges.
- Duplicate row badges and duplicate filters use persisted `Document.duplicate_count`, `Document.duplicate_reasons`, and `Document.duplicate_checked_at` fields so ordinary list reads do not recompute the duplicate graph. The explicit Library duplicate scan refreshes those fields for active Library documents, and duplicate resolve/dismiss actions refresh them after mutating duplicate state.
- API responses under `/api/` include lightweight request timing headers (`X-Medusa-Request-Duration-Ms`, `X-Medusa-Sql-Count`, and `X-Medusa-Sql-Duration-Ms`), and the backend logs slow API requests through the `medusa.performance` logger. These measurements should guide future cache decisions.
- Valkey is now part of the optional runtime path as a derived response cache, but PostgreSQL query shape and indexing remain the first remedy for Library list/search latency. Expand Valkey usage only when measured bottlenecks are cross-request recomputation, fan-out invalidation, ephemeral activity streams, job-progress pub/sub, distributed locks, or hot aggregate caches that cannot be served well from PostgreSQL indexes/materialized tables.
- Search and reader copy prefer `DocumentPage.normalized_text` when present and fall back to raw extracted `DocumentPage.text`.
- Manual extracted-text edits persist to `DocumentPage.normalized_text` with `text_source="manual"`, rebuild document search immediately, and record page-level before/after snapshots in `DocumentVersion`.
- Reader Scrub removes the selected exact text from every page's reader/search text, promotes affected pages to manual normalized text, rebuilds search, and records one `DocumentVersion` row with the scrub text, match count, and page-level before/after snapshots.
- Document annotations contribute their body text to `Document.search_text`; deleted annotations are excluded from active document detail and search rebuilds.
- Processing capabilities are versioned so Medusa can tell which documents need a Concordance Run.
- `DocumentVersion` is the complete document edit/audit ledger for user-facing document changes. Manual metadata edits, citation acceptance, import overwrites, in-place Library replacements, extracted-text cleanup, Scrub actions, history restores, and Concordance cleanup that changes document/page fields must write before/after snapshots rather than silently replacing title, authors, citations, page text, annotations, tags, domains, attributes, or other mutable document fields. In-place replacement must also preserve prior `DocumentCompositionRecord` rows and processing events so cost history and accession history are additive rather than rewritten.
- Library Title Cleanup is an audited bulk document mutation. It normalizes active document titles by trimming leading/trailing whitespace and collapsing repeated whitespace to one space, rebuilds document search text for changed documents, and writes `DocumentVersion` plus composition history for each changed title.
- Tag rename and merge operations are user-facing document changes. They update document tag relationships, rebuild affected document search text, and append a `DocumentVersion` snapshot for each affected document with before/after tag state plus operation metadata such as old/new tag names, selected source tag ids, target tag id, removed tag ids, and remembered alias names. Tag Merge also writes `TagAlias` rows for selected source names and retargets aliases from tags being removed, preserving transitive canonicalization. Tags also carry governance status (`canonical`, `candidate`, `retired`, or `blocked`), optional definition/use/avoid guidance, and metadata used by import scoring. `TagRelationship` stores approved semantic relationships such as `covered_by`, `broader`, `narrower`, `related`, and `cluster_peer`. `DocumentTagAssessment` records per-document tag scoring decisions with document relevance, library fit, novelty value, overall score, decision, rationale, and import/Concordance job context. Tag Optimize is suggestion-only: it records AI usage for the taxonomy review but does not mutate tags or documents until a user approves a merge, status, relationship, assignment-pruning, or orphan-pruning suggestion. Orphan pruning is a guarded tag-row delete path for tags with no `document_tags` links at all; it nulls historical `DocumentTagAssessment.tag_id` references while preserving candidate-name evidence.
- Restore as Current is the history-undo contract. Restoring a selected version applies the version's restorable document and page snapshots to the live document, rebuilds search, and appends a new `DocumentVersion` row that references the restored version instead of mutating or deleting older history.

## Processing Pipeline

Current import path:

1. User uploads one or more PDFs, DOCX, RTF, HTML documents, or plain-text/Markdown files through `/api/imports/batches`.
2. Frontend calls `/api/imports/duplicates` to classify supported source formats, hash the proposed upload source bytes, and detect exact checksum matches against Library-visible documents, active/recoverable import rows, and files within the same drop. Cleared/canceled queue-only rows are not duplicate sources.
3. If duplicates are found, the user chooses skip, overwrite, or import anyway before `/api/imports/batches` stages the batch.
4. The upload request includes current batch defaults: optional label, domain IDs, tag IDs, project IDs, priority, read status, and attributes.
5. Backend applies the duplicate strategy. Skip creates a completed `duplicate_skipped` job, overwrite reuses and reprocesses the selected existing document record, and import-anyway creates another document with the same checksum.
6. Backend applies batch defaults to each imported document and creates project run-sheet items for selected projects.
7. PDF uploads are stored as-is. DOCX, RTF, HTML, and plain-text/Markdown uploads are parsed from the raw source for semantic cues such as title/headline/heading/paragraph/list structure, rendered locally with PyMuPDF into a PDF mezzanine, and recorded with source checksum/provenance plus generated-PDF checksum in `Document.metadata_evidence["source_import"]`.
8. The durable original object written to GCS/local storage is always a PDF: either the uploaded PDF or the generated PDF mezzanine for non-PDF sources.
9. A document-specific local PDF cache copy is saved under `data/processing-cache` and recorded as `document_cache_path`; the original has already been written to GCS/local storage before cache policy applies.
10. `Document`, `ImportBatch`, and staged `ImportJob` records are committed. Each staged document stores an estimated page count and a persisted rough dollar estimate when available so the UI can show pre-processing cost and Composition can later compare the estimate with actual import spend. These pre-import `Document` rows are operational queue records only; they are excluded from Library lists/search, dashboard document counts, domain/tag counts, project bibliographies, recommendation existing-library checks, and Concordance document scopes until processing completes and `Document.processing_status` becomes `ready`.
11. The user presses Process Uploads to promote all staged import jobs to `queued`; local workers and enabled Slipstream clients claim queued jobs through the shared lease coordinator, then move them through extraction, enrichment, indexing, and completion. Import processing defaults to 4 concurrent local jobs from one worker process and can be changed to any positive value in Settings; Slipstream clients additionally enforce their registered remote capacity and one active lease per job.
12. Raw PDF text/layout extraction is a Settings-selectable task for PDF-origin documents. The default preference is local Marker, with Docling and PyMuPDF also listed under Local and enabled OpenAI models listed as cloud fallback choices. Marker is installed in the backend/worker image, but its downloaded model weights are stored under the mounted `data/model-cache` path rather than baked into the image. The first Marker run on a machine/cache may download weights; later imports reuse that cache. PyMuPDF remains the bundled no-credential fallback when Marker is unavailable or times out. Docling remains listed as a planned local extractor option until its runtime is wired. DOCX/RTF/HTML/plain-text imports use the parsed source-page text as the first extraction surface instead of re-deriving text from the generated PDF mezzanine.
13. Two-column pages should read down the left column before crossing to the right column, while full-width headers/sections remain in vertical order.
14. Detected tables are converted to Markdown and included in page text so table content is searchable and available to metadata/summarization.
15. Extracted, normalized, chunked, and assembled search text is sanitized before persistence so PDF control bytes such as NUL cannot break PostgreSQL `TEXT` writes or retry loops.
16. Page text is normalized into standard readable paragraph flow. The default mode is local-first `MEDUSA_OPENAI_PAGE_NORMALIZATION_MODE=auto`: normal pages use deterministic cleanup, while low-text or artifact-heavy pages may escalate to the Settings-selected Text on Pages model up to `MEDUSA_OPENAI_PAGE_NORMALIZATION_AUTO_MAX_PAGES` per document. Auto mode sends extracted page text only and does not attach the original PDF per page. `always` restores the older all-pages OpenAI path and may include PDF context when `MEDUSA_OPENAI_SEND_PDF=true`; `never` keeps page normalization fully local. The normalizer must preserve wording/order, headings, labels, captions, citations, equations, lists, tables, and logical flow without summarizing graphics or converting charts/photos/diagrams into Markdown. Page-normalization requests use `MEDUSA_OPENAI_PAGE_NORMALIZATION_TIMEOUT_SECONDS` and fall back locally on timeout/error. Manual reader edits and Scrub cleanup use the same normalized text surface, mark affected pages as manual, rebuild search, and create history snapshots.
17. PDF figure/photo/chart assets are extracted with PyMuPDF as 300 DPI cropped page graphics. Embedded raster images, page image blocks, and vector-drawn graphic clusters are stored through the configured storage adapter and recorded as `Figure` rows with page number, crop geometry, source kind, extraction scope, label, and nearby caption when available. Captions and labels such as `Figure 1.` remain text anchors in normalized page text; the actual graphic remains an asset instead of Markdown. Reader page scans reuse the same local extractor against one selected page and first return selectable review candidates with inline thumbnails and page-map geometry. Keeping selected candidates replaces only that page's figure rows, preserves all other pages, rebuilds document search, and records metadata evidence plus a processing event/history entry; discarding the review leaves the document unchanged. Stored figures can later be relabeled, given corrected captions/descriptions, or deleted as audited manual corrections; each change rebuilds search and records `DocumentVersion` history.
18. Normalized text is chunked for search/embedding, falling back to raw extracted text when needed.
19. OpenAI metadata extraction runs only when `OPENAI_API_KEY` exists; otherwise a low-confidence review record is produced. Metadata extraction asks for visible authors, affiliations, and normalized contact emails and stores them in `Document.authors`.
20. Extraction and async document-intelligence work are split into Settings-selectable tasks: Raw Text Extraction, Metadata, Summary, APA Citation Matching, Tag Suggestions, Text on Pages (Normalization), Bibliography Cleanup, Formula Capture, Text Chunk Encoding, Inquests, Recon, and Portfolio Assessment. The compatible internal key for Tag Suggestions remains `keywords_topics`, but persisted output is flattened into tags. Metadata and APA fallback matching default to `OPENAI_MODEL=gpt-5.5`; APA Citation Matching uses `MEDUSA_OPENAI_APA_REASONING_EFFORT=high` by default; Summary defaults to `gpt-5.4`; Tag Suggestions defaults to `gpt-5.4-mini`; Bibliography Cleanup defaults to `gpt-5-mini`, has an expensive off-by-default `MEDUSA_OPENAI_BIBLIOGRAPHY_REASONING_EFFORT` option for GPT-5-family hard cases, runs a targeted author-preserving repair retry when cleanup drops visible authors, then retries remaining unsafe cleanup once with `gpt-5.4-mini`, and is used for forced/ad hoc Bibliography Refresh rather than default import; Formula Capture defaults to `gpt-5.4` and is manual-only through Concordance; Inquests defaults to `gpt-5.4`; Recon defaults to the current Inquests-style synthesis model; Portfolio Assessment defaults to `DEFAULT_GPT_MODEL` currently `gpt-5.5`; Text Chunk Encoding defaults to `OPENAI_EMBEDDING_MODEL` and offers `text-embedding-3-small`, `text-embedding-3-large`, and `text-embedding-ada-002`.
21. By default, document intelligence is routed by task. Metadata extraction may send the original PDF as a Responses API file input when `MEDUSA_OPENAI_SEND_PDF=true` and the file is below `MEDUSA_OPENAI_PDF_FILE_MAX_MB`; summary and tag extraction use extracted text only. `MEDUSA_OPENAI_COMBINE_DOCUMENT_INTELLIGENCE=true` is an opt-in legacy mode that runs Metadata, Summary, APA Citation Matching, and Tag Suggestions as one structured `core_document_intelligence` Responses call using the Metadata model selection.
22. Tag Suggestions output is treated as candidate evidence and then scored by tag governance before tags are attached. The scorer is existing-first, not existing-only: it checks alias memory, governance status, optional definitions, library counts, approved relationships, deterministic lexical similarity, optional cached embedding similarity, near-existing matches, and semantic covered-by matches. Each candidate is scored on document relevance, library fit, and novelty value using title/summary/body support. Strong covered-by or close-match candidates reuse the existing tag; low-value form/generic labels are skipped; near-existing but ambiguous candidates are recorded without creating a new tag. Import may attach at most five scored tags per document and may create at most one new `candidate` tag, and new tags require stronger relevance/novelty thresholds than reused tags. Weak or redundant candidates are recorded but not attached. Import and Concordance both persist `DocumentTagAssessment` rows and document metadata evidence for these decisions.
23. OpenAI Responses calls pass stable prompt-cache keys derived from the document checksum, hashing overlong keys to fit the Responses API 64-character limit, and use `MEDUSA_OPENAI_PROMPT_CACHE_RETENTION` when configured and supported by the installed OpenAI SDK; if that SDK does not expose a retention parameter, Medusa omits the retention hint instead of failing the import. Dedicated APA Citation Matching calls also pass OpenAI `reasoning.effort` from `MEDUSA_OPENAI_APA_REASONING_EFFORT` (`minimal`, `low`, `medium`, `high`, or off), defaulting to `high`; Bibliography Cleanup has its own `MEDUSA_OPENAI_BIBLIOGRAPHY_REASONING_EFFORT` switch that defaults to `off`; lower-risk summary/tag routes do not inherit those reasoning settings. Concordance reruns hydrate original PDFs from the local document cache or durable storage when a task needs PDF context.
24. Each OpenAI Responses, embeddings, or Gemini request records a durable `OpenAIUsageRecord` when usage data is available, including task/model, provider, import, Concordance, or Inquest context, token counts, cached input tokens, PDF/file-context bytes, and failure status. Settings reads `/api/openai/usage` to show totals, task/model rollups, recent calls, and model-pricing status; `/api/model-pricing/refresh` stores the latest enabled model prices and only appends history on price changes. Import queue cost previews model rough per-document cost from page count plus prior import usage exemplars by task/model, falling back to broader task/library rates and then to a conservative per-page default when there is not enough history. Exemplar-based cloud-step estimates keep a one-page model-pricing floor so prior per-page rates cannot hide the per-document base cost of many short model calls. When prior documents have both persisted estimates and actual composition costs, Medusa applies a bounded actual-to-estimate calibration factor to future staged-upload estimates, but calibration cannot reduce a staged document below that aggregate one-call-per-cloud-step floor.
25. During imports, `DocumentCompositionRecord` rows are written for the staged cost estimate, each local stage, and synced per-call AI usage rows. Rows record stage order, method/model/provider, high-precision known dollar cost, local duration, tokens, status, processing warnings/errors, and pipeline metadata. Estimate rows are not counted as actual provider spend; Composition displays them separately as estimate-vs-actual comparison. Actual provider spend must include every priced usage item, including sub-cent and sub-micro-dollar embedding calls, and the Composition summary can recover current pricing from linked raw usage records when older composition rows rounded tiny costs to zero. Local stages that only have a configured cloud fallback, such as local-first page normalization, must display as local work unless a separate provider usage record shows that the model was actually called. Older documents without rows intentionally show Composition as not available.
26. Stored `rich_summary` text must begin with the semantic substance of the summary itself, not a standalone heading such as `Summary`, `Overview`, `Abstract`, `Synopsis`, or similar, not a single-word opener, and not bibliographic framing such as author, year, medium, venue, or source-title throat-clearing. The AI prompts also request complete-sentence default summaries as technical plain-text paragraphs written at a graduate academic level suitable for a master's-degree reader: the opening should state a substantive claim, problem, method, finding, or conceptual contribution; key findings and concrete facts appear early; sentences avoid starting with prepositions; and the summary covers original ideas/concepts, subject-matter areas, research questions raised, conclusions or novel insights, surprising/counterintuitive results when present, academic context, main takeaways near the end, and adjacent research areas or related topics worth pursuing for continued reading without bold, italics, bullets, em dashes, fancy quotes, leaked schema metadata, confidence labels, or review-reason trailers unless the user explicitly asks for another format. Import/Concordance cleanup strips standalone first-line headings, common bibliographic lead-ins, and accidental trailing `confidence` or `needs_review_reasons` blocks before persistence.
27. DOI is discovered from AI metadata, local DOI regex over extracted text, Crossref DOI/title lookup with optional first-author and publication-year constraints, Semantic Scholar title lookup, and then the enabled targeted `"paper title" DOI` static web-search fallback. If Crossref evidence is available, missing citation fields are filled from that evidence without overwriting existing values. Title-search DOI evidence is stored on document metadata before Crossref is retried by the found DOI.
28. APA Reference List and APA In-Text Citation text are generated together from the same citation metadata and Settings-selected APA Citation Matching model preference. DOI/Crossref evidence is gathered first and sent with known document metadata, compact excerpts, and high OpenAI reasoning effort by default so the model can generate/check the pair, complete confident DOI-specific fields such as page ranges or article numbers, and report conflicts. The paired output is normalized and validated for obvious APA structure, parenthetical in-text shape, year, title, author anchors, and known page ranges; malformed supplied candidates fall back to deterministic formatting from current metadata without a second model call. It is marked `verified` only when enough metadata exists and DOI/Crossref evidence is present.
29. When DOI/Crossref cannot verify the citation, Medusa still asks the Settings-selected APA Citation Matching model, defaulting to `gpt-5.5`, to generate/check APA Reference List and parenthetical in-text candidates from compact metadata and extracted-text excerpts without attaching the PDF. The call requests both citation fields in a single structured response. The result remains `needs_review` unless later verified or accepted.
30. Uncertain citations create `CitationCandidate` review records.
31. Successful jobs retain their local PDF cache copy up to the configured Document Cache Size. Budget pruning deletes oldest non-active cache files and leaves GCS/local original storage untouched.

Library replacement path:

- `POST /api/documents/{document_id}/replace` accepts one supported import source file for a ready, unlocked Library document. It writes a new durable original and processing-cache PDF for the existing document id, clears source-derived content, review state, and live page-specific annotations, preserves filing context and prior composition/history rows, records a `DocumentVersion` snapshot plus `document_replacement_queued` processing event, and creates a normal queued `ImportJob` in a one-file `ImportBatch`.
- Replacement jobs enter the same worker, lease, extraction, enrichment, indexing, Composition, Finances, retry, and progress surfaces as other queued imports. During replacement processing the document follows the ordinary queued/running/failed/ready status contract, so ready-only Library surfaces do not treat the replacement as a completed Library document again until the import finishes.

Portfolio processing status:

1. Portfolio uploads are accepted through `/api/portfolio/{item_id}/versions` and `/api/portfolio/{item_id}/materials`, not through the normal staged Import dropzone.
2. Supported source formats are PDF, DOCX, RTF, TXT, and Markdown. Non-PDF sources preserve the original source object under `portfolio/sources/...` and also create a generated PDF mezzanine for preview, extraction, search, and model context.
3. Each Portfolio version or material creates a hidden `Document` row with `document_kind` set to `portfolio_version` or `portfolio_material`, a normal storage object, cache metadata, Composition estimate row, processing event, `ImportBatch`, and queued `ImportJob`.
4. Portfolio jobs enter the worker queue immediately rather than waiting for the Import workspace's Process Uploads action. They still use the same extraction, enrichment, indexing, Composition, Finances, retry, and event conventions as ordinary imports.
5. Uploading a new Portfolio version creates a new immutable `PortfolioVersion` and a `PortfolioVersionEdge` from the previous/current version with relation `supersedes`. Prior versions, original source URIs, generated PDF mezzanines, processing history, and assessment history remain available.
6. Portfolio suggestions refresh from the Recon retrieval service over Library-visible documents and store `PortfolioSuggestion` rows with retrieved snippets, pages/chunks where available, and score basis. External resource search remains a planned extension.
7. Portfolio assessments create an assessment run with material/suggestion/completeness findings, selected model provenance, Recon Library evidence, and model-backed scorecards, grade estimates, narrative feedback, revision priorities, findings, model outputs, and agreement metadata when the configured Portfolio Assessment model is available; local baseline findings remain the fallback. Multiple model ids can be requested and every run snapshots exact ids.
8. Portfolio audit events are appended for item creation/update, version upload/current-version switch, material upload, resource refresh, assessment completion, and bundle export. Events are canonicalized, hash-chained, and signed; optional RFC 3161 timestamp anchors are configured with `MEDUSA_AUDIT_TIMESTAMP_URLS`.
9. `POST /api/portfolio/{portfolio_item_id}/bundle` streams an audited ZIP containing all Portfolio-uploaded source/version/material files, generated previews when distinct, assessment JSON/Markdown reports, Library suggestion metadata, manifests/checksums, public keys, event-chain JSONL, timestamp-anchor proofs, and verification summary. Library originals are excluded unless explicitly uploaded as Portfolio materials.

Second-pass processing status:

1. The first branch deliverable is documentation: `docs/SECOND_PASS_DOCUMENT_PROCESSING.md`, this architecture record, and `TODO.md` define the work before runtime code begins.
2. Import staging records the selected processing preset id and a snapshot of the preset values. Built-in presets are Balanced, Strict Local, and Deep Review. Balanced is the default for Settings and Import.
3. `document_structure_cleanup` runs after raw extraction and before page normalization, chunking, enrichment, search, and asset-context work. It removes repeated headers/footers, page numbers, watermarks, decorative text art, front matter noise, excess whitespace, broken line wraps, bullet/list artifacts, and drop-cap styling artifacts while preserving meaningful body text, headings, captions, citations, equations, lists, and tables. Removed text is retained as evidence but excluded from body search/enrichment.
4. `ocr_fallback` currently audits low-text/scanned page eligibility and records pending-provider evidence. Bibliography extraction can use tail-page visual OCR as a references rescue when the selected preset enables OCR: Google Vision is tried when configured, and the backend image also includes Tesseract as a local/no-credential fallback. Full OCR page-text persistence is not yet wired into the page extraction retry loop.
5. Page normalization stays local for clean pages. Balanced mode escalates only flagged pages to cheap task-specific OpenAI or Google models, capped at 6 pages or 15 percent of pages per document, whichever is larger. Full-PDF or every-page cloud analysis is reserved for explicit Deep Review work.
6. `structured_tables` currently records table-like cleanup evidence in document metadata. First-class table rows/cells, captions, page regions, and source geometry remain planned.
7. `visual_asset_extraction` now runs local extraction for embedded raster images, displayed page-image regions, and vector drawing clusters, recording durable 300 DPI crops with page geometry, source kind, orientation, captions, and basic warnings. Exhaustive full-page scan/table-region coverage, duplicate/incomplete crop audit, and complete axes/legend expansion remain planned.
8. `visual_asset_context` links figures to labels, captions, nearby text, and explicit references such as `Figure 2` today. Cropped-region model calls, searchable visual gists, premium gating, and per-call visual usage/cost records remain planned.
9. `bibliography_extraction` detects References, Bibliography, and Works Cited sections and stores the paper's own reference list in `Document.bibliography` as one newline-delimited source per entry. Import-time extraction remains local by default: it removes numeric/bracketed entry prefixes and bracketed author/year source keys such as `[Ariani 2013]`, folds blank-line gaps and list-marker continuations back into the current reference, handles repeated `References` page headers inside long reference lists, recognizes unnumbered legal-caption, periodical/news, organization-year, and `Surname, Initials` reference starts, uses PDF span metadata when available so visible italics in the reference list can be preserved as Markdown emphasis, falls back to parsed page text when PDF-span extraction stops on an earlier page and parsed text recovers substantially more later references, orders strong non-marker two-column bibliography pages by detected column, and preserves native PDF line order on marker-heavy numbered or source-key reference pages so standalone markers stay attached to their citation text. If PDF span and parsed-page extraction both return `not_found`, the active preset allows OCR, and the original PDF is available, bibliography extraction renders the tail pages and tries visual OCR as a last-resort references rescue: Google Vision is used when configured, and Tesseract provides a local fallback when Vision is unavailable or disabled. Full-page OCR is parsed first; when it fails to find the bibliography, Medusa retries OCR in left/right column order so two-column reference pages are not scrambled into publisher recommendations, cited-by sections, or download boilerplate. OCR errors are stored in extraction evidence and still complete as `not_found` instead of failing the whole refresh. Forced/ad hoc Bibliography Refresh then applies the Settings-selected Bibliography Cleanup model, defaulting to `gpt-5-mini`, may use GPT-5-family OpenAI reasoning only when `MEDUSA_OPENAI_BIBLIOGRAPHY_REASONING_EFFORT` is enabled, runs a targeted author-preserving repair retry when output drops visible authors, and uses one `gpt-5.4-mini` safety retry when output remains incomplete, low-confidence, duplicate-producing, or unsafe, to conform the output to the selected reference/source style, make APA-style source grouping, personal-author inversion, first-author-surname sorting, and Markdown italics paramount, and still forbid invented bibliographic fields.
10. `formula_capture` is a manual-only Concordance refinement pass. It uses the Settings-selected Formula Capture model, defaulting to `gpt-5.4`, with extracted page text and original PDF file context when the configured OpenAI PDF-file setting permits it. It captures visible equations and mathematical expressions as LaTeX/MathJax-compatible source in `metadata_evidence.formula_capture`, makes formulas searchable, appends a clearly marked Formula capture block to non-manual parsed page text, and protects pages with `text_source="manual"` from silent overwrite.
11. Composition records second-pass stages, warnings, model/provider choices, local duration, token/file-context usage, and costs where rows and usage data exist. A more explicit preset-snapshot display and richer second-pass warning surfaces remain planned.

Durability decisions:

- Jobs are database-backed and step-oriented.
- Manual batch uploads start as staged import jobs. Staged jobs already have stored originals, cache paths, duplicate decisions, batch defaults, page-count estimates, processing events, and document rows, but workers do not claim them until Process Uploads promotes them to `queued`. Those document rows are not considered library documents until they finish processing; only ready/complete/restored document statuses are eligible for Library, search, dashboard/document counts, project bibliography, recommendation, and Concordance scopes. The Import page Clear Staged action hard-deletes staged-only upload documents/jobs and removes their managed cache files and staged originals from GCS or local storage; if a staged job unexpectedly shares a document with other import history, Medusa falls back to clearing the job without deleting the shared document.
- Processing events are appended for auditability.
- Import batch completion appends one `import_batch_complete` processing event with the batch ID, label, status, and file counts. The richer Ingestion History view is derived from the durable batch/job/composition/usage ledgers rather than a separate mutable summary table.
- The app must tolerate stop/start without losing queued jobs.
- Worker startup immediately requeues `running` imports and Concordance jobs from the previous worker process when no active Slipstream lease owns that job. Worker claims also use `locked_at` and `MEDUSA_WORKER_STALE_JOB_SECONDS` as a stale-lock recovery guard.
- Local and Slipstream claims create `SlipstreamLease` rows so one coordinator owns the running transition. PostgreSQL is the quorum authority: a partial unique active-lease constraint over `(job_type, job_id)` prevents double assignment, while `worker_kind` distinguishes local workers from remote clients. Slipstream leases heartbeat every `MEDUSA_SLIPSTREAM_HEARTBEAT_SECONDS` seconds by convention and expire after `MEDUSA_SLIPSTREAM_LEASE_TTL_SECONDS`; expiry returns the job to `queued`, clears the job lock, records a processing event, and allows another client or local worker to claim it. Late results from expired/released leases are rejected unless they are duplicate submissions for the already accepted lease idempotency key.
- Worker exception handling must roll back an invalid transaction before writing failed job or lease bookkeeping. Otherwise a failed ledger flush can leave Concordance jobs looking active after the worker has already crashed.
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
- The worker processes import jobs first, up to the configured import concurrency preference, then Concordance jobs from the same durable database queue pattern. Slipstream clients use the same lease coordinator for import and Concordance job claims, so remote and local processors cannot own the same job at the same time.
- The frontend app shell tracks started Concordance runs independently from the page that launched them and reconciles progress from run/job polling so navigation does not hide accepted work.
- Settings includes a Concordance panel that can estimate and start scoped runs while displaying current capability/run/job status.
- The document detail pane estimates a current-document Concordance Run before asking the user to confirm the run, while button-scoped refresh actions can target a single capability directly.

Current first capabilities:

- `page_text_normalization` v3: conforms raw extracted page text into standard readable paragraph flow using OpenAI when configured and local cleanup as a fallback; it preserves headings, labels, captions, citations, equations, lists, tables, and reading flow across columns/graphics without converting graphics to Markdown. Concordance reruns use the original PDF context when available.
- `search_index` v3: rebuilds `Document.search_text` from title, authors, visible author contact emails, abstract, summary, extracted Bibliography, APA reference-list and in-text citations, normalized pages, figure labels/captions/gists, notes, custom attributes, tags, and domains.
- `citation_refresh` v4: regenerates Markdown APA 7 reference-list text with sentence-case cited work titles and title-case containers plus APA parenthetical in-text text by gathering DOI/Crossref evidence first, filling missing fields, and sending the selected APA Citation model a compact packet of DOI evidence, known title/authors/year/venue metadata, excerpts, and the configured APA reasoning effort so it can format the pair, complete confident DOI-specific fields such as page ranges or article numbers, and flag DOI mismatches. Missing DOI discovery can use Semantic Scholar title lookup or targeted `"paper title" DOI` static web-search evidence before retrying Crossref. The paired APA output is validated, numeric page ranges are normalized with en dashes, malformed or missing model output falls back to deterministic metadata formatting without another model call, model-reported DOI conflicts keep the citation in Queue review, and model/provenance are recorded.
- `summary_refresh` v1: button-scoped capability used by document Summary Refresh. It regenerates only the main `rich_summary` using the selected Summary model, records usage with task key `summary`, rebuilds document search when the summary changes, and keeps broader metadata/tag extraction out of one-off summary refreshes. Validated summaries are skipped unless the document-level Summary Refresh action has first cleared validation through a confirmation-gated request. It is accepted by the Concordance API for explicit Summary Refresh requests but is not included in default all-capability Concordance selections.
- `tag_refresh` v1: button-scoped capability used by document Tag Refresh. It runs only the selected Tag Suggestions model against the current document text, fails before mutating tags when the model route is unavailable, removes the document's current tag links, applies the same existing-first import tag governance scorer, rebuilds search, records `DocumentVersion` history, and is accepted by the Concordance API for explicit document refresh requests but is not included in default all-capability Concordance selections.
- `summary_topics` v8: uses the configured AI adapter to fill missing metadata, visible author contacts, default paragraph-style summaries, and flattened tag suggestions without overwriting user-corrected identity metadata. The default path routes metadata through the high-quality model, summaries through GPT-5.4 text-only calls, and tag extraction through GPT-5.4-mini text-only calls. Tag extraction receives a compact sorted manifest of existing canonical/candidate tags and is instructed to prefer exact existing tags when they fit. Suggested tag names resolve through remembered merge aliases, then pass through the aggressive tag-governance scorer for existing-first/not-existing-only, three-axis relevance/fit/novelty scoring, optional embedding similarity, cluster-aware checks, low-value suppression, near-existing reuse/blocking, semantic covered-by reuse, and strict attachment caps before creating or attaching tags. Concordance `summary_topics` is additive for tags: it may attach newly scored tags but must not evict tags already on the document. Weak assignment removal remains an explicit Optimize pruning approval. Legacy combined `core_document_intelligence` remains opt-in.
- `bibliography_extraction` v4: extracts the source document's own reference list into the `Bibliography` field when a references/bibliography/works-cited section is present, normalizes it as one source per line without numeric/bracketed source prefixes or bracketed author/year source keys, and preserves Markdown italics when PDF span evidence exposes emphasis. Local PDF-span extraction orders strong non-marker two-column bibliography pages by detected column before reference-section scoring so a left-column heading can still capture the right-column continuation, preserves native PDF line order on marker-heavy numbered or source-key reference pages so standalone markers stay attached to their citation text, and yields to parsed page text when the span result stops on an earlier page while page text recovers substantially more later references. It treats repeated `References` labels as page headers when followed by continuation text, skips subscription footers, IEEE permission footers, report distribution footers, publisher download/recommendation blocks, cited-by sections, and known running headers inside the reference flow, rejects method-section wording such as "Reference List Search" or "References cited" as a bibliography boundary, and keeps bracketed reference-list marker style so wrapped numeric page/DOI continuations such as `302. doi...` do not become separate sources. Unnumbered reference splitting recognizes court-case captions, news/periodical title starts, organization-year starts, and author `Surname, Initials` starts without letting wrapped `Retrieved`, URL, title, conference-name continuation lines, or terminal page spans block the next source. When span/page extraction returns `not_found`, the original PDF is available, and the active preset enables OCR, Medusa renders the last bibliography-candidate pages and parses OCR text as a visual references rescue, using Google Vision when configured and Tesseract as the local fallback; if full-page OCR fails to find the bibliography, it retries the same pages in left/right column order and records `ocr_layout="two_column"` in extraction evidence. Unavailable or disabled OCR is recorded under `metadata_evidence.bibliography_extraction.visual_ocr` while the refresh still completes as `not_found`. Concordance fills missing bibliographies and protects user-edited values from silent overwrite except for explicit forced document-level Bibliography Refresh requests, which also run the selected Bibliography Cleanup model to produce APA-sorted Markdown entries with cited work titles in sentence case, journal/proceedings/container titles in title case, personal authors inverted, entries sorted by first-author surname, and intelligent grouping. Bibliography Cleanup can opt into GPT-5-family OpenAI reasoning through `MEDUSA_OPENAI_BIBLIOGRAPHY_REASONING_EFFORT`, but the default is `off` because large reference lists are expensive. Bibliography Refresh prioritizes completeness over short-list assumptions: cleanup is allowed for extracted lists up to 300 entries and 120,000 characters, while larger lists are kept complete with separator-insensitive deterministic sorting and explicit `skipped_large_bibliography` evidence instead of being silently truncated. If forced refresh extraction would reduce an existing bibliography by parsed entry count, broader DOI/year reference-signal count, or suspicious character coverage, Medusa preserves the existing bibliography and records `rejected_regression_existing_bibliography` evidence instead of overwriting a more complete stored list. If model cleanup drops visible coauthors, Medusa first runs a targeted author-preserving repair retry that includes the missing author token groups and the rejected cleanup output; if cleanup still returns fewer entries than extraction detected, drops visible coauthors, adds duplicate entries, or reports very low confidence, the default path retries once with `gpt-5.4-mini`; if that retry is also unsafe, cleanup is rejected and Medusa keeps the complete deterministic extraction with `rejected_incomplete`, `rejected_author_loss`, `rejected_duplicate_cleanup`, or `rejected_low_confidence` evidence. Missing page placeholders such as `n/a` are stripped instead of stored. Document detail surfaces skipped/rejected cleanup evidence beside the bibliography.
- `formula_capture` v1: manual refinement capability that captures visible formulas as page-scoped LaTeX evidence using the selected Formula Capture model. It appears in the Concordance capability picker but is not preselected with the ordinary broad maintenance set and is excluded from backend default capability selection when no keys are supplied. It can also be invoked directly from the open document's preview or expanded Reader action row through a Formulas button that queues only this capability. It appends searchable formula notes to non-manual parsed page text and stores all returned formula entries in document evidence; read-mode parsed text renders recognized LaTeX delimiters as math while edit/copy surfaces preserve source text. Manually edited pages are protected and counted instead of being overwritten.
- `visual_asset_extraction` v2: extracts 300 DPI rendered page-image and vector graphic crops plus embedded-image fallbacks into durable storage and attaches them to document records with geometry, labels, captions, source kind, orientation, and audit warnings. Visible page-image crops are rendered from the page before raw embedded bytes are used so PDF color-space, mask, and decode instructions are preserved. The legacy `figure_assets` capability key remains accepted for older queued jobs.
- `visual_asset_context` v2: enriches extracted assets with caption, heading, nearby paragraph, explicit mention context, and parsed-text inline figure markers without requiring whole-PDF cloud calls.
- `recommendations` v1: refreshes related-paper recommendations from bounded OpenAlex/Semantic Scholar/Crossref title/topic/evidence search, DOI/reference graph calls when DOI exists, locally parsed stored Bibliography references, and bounded project/domain/tag context-neighbor expansion, enriches open-PDF availability from Unpaywall/arXiv when configured, marks already-present library matches, exposes manual Google Scholar search links, and caches provider/query/reference/context evidence without importing full text automatically.

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

- Single-user password login with optional authenticator-app TOTP.
- Session cookies are HTTP-only and backed by hashed session tokens in PostgreSQL.
- Default dev credentials exist only so a fresh local stack is usable. Real use should set `MEDUSA_PASSWORD` in `.env`.
- `MEDUSA_ADMIN_EMAIL` and `MEDUSA_PASSWORD` seed the first admin account only. Once the user row exists, the live login email and password are PostgreSQL account state, and Settings > Account is the supported in-app rotation path.
- Account credential changes require the current password. Password changes hash the new password and revoke other active sessions while preserving the browser session that made the change.
- Settings > Account can generate a TOTP setup key, require a current authenticator code before enabling 2FA, store the TOTP secret and hashed recovery codes on the user row, and disable 2FA only after current-password plus TOTP or recovery-code verification. Enabling or disabling 2FA revokes other sessions.

Secrets:

- `.env` is ignored.
- `.env.example` documents expected variables.
- Google service-account JSON files are ignored under `data/secrets`.
- Settings can upload a Google service-account JSON key into ignored `data/managed-secrets/google-service-account.json`; Medusa writes the managed directory as `0700` and the key as `0600` where the host filesystem supports POSIX modes. PostgreSQL stores only display metadata and the managed path, never the private key JSON.
- GCS service accounts must be able to create original PDFs and extracted assets, read them back for preview/export/reprocessing, and delete temporary smoke-test objects when verifying credentials.
- Do not track API keys, service-account JSON, or generated data.

Network:

- The app listens externally on HTTPS port `3737` through the HAProxy service.
- HAProxy terminates TLS for `medusa.home.musial.io`, redirects plain HTTP requests on the same port to `https://medusa.home.musial.io:3737`, routes `/api/*` to the internal backend service on `backend:8000`, and proxies browser shell/assets to the internal frontend service on `frontend:3737`.
- Backend, worker, database, frontend, and HAProxy stats are internal Docker services.
- The optional Prometheus exporter is not part of the browser/API exposure path. When enabled with `docker-compose.metrics.yml`, HAProxy publishes only `/metrics` and `/healthz` on `MEDUSA_METRICS_BIND_IP:MEDUSA_METRICS_PORT`, terminates TLS with the existing Medusa certificate, and routes to the private exporter container. `/metrics` requires `MEDUSA_METRICS_BEARER_TOKEN` or `MEDUSA_METRICS_BEARER_TOKEN_FILE` unless `MEDUSA_METRICS_REQUIRE_AUTH=false` is set for a deliberately private lab network. Prometheus should scrape it once per minute or slower. Expensive corpus, storage, and optional Docker metrics are rendered into a Valkey-backed snapshot on exporter startup and refreshed out-of-band by `MEDUSA_METRICS_HEAVY_TTL_SECONDS`, so routine scrapes do not run wide PostgreSQL aggregation. GCS bucket inventory and object-cost metrics are intentionally excluded so observability cannot become a storage-listing cost source.
- Slipstream clients use outbound HTTPS polling to the central app. They never accept inbound connections, never connect to PostgreSQL, and must sign request paths that claim work, heartbeat, read artifacts, write events, upload results, or fail a lease. TLS is required by default; deployments behind a trusted proxy must preserve `X-Forwarded-Proto: https` for Slipstream routes.

Operational settings:

- The active GCS bucket can be saved from Settings as an `AppPreference`. If no saved bucket exists, Medusa falls back to `GCS_BUCKET`; saving an empty bucket intentionally disables GCS and leaves local storage as the active backend. Settings reads the bucket lifecycle policy through an authenticated backend endpoint when Google credentials and bucket metadata permission are available, then presents storage-class transition and delete rules in user-friendly language so retention-based Nearline/Coldline/Archive behavior is visible without raw GCS JSON.
- Uploaded Google service-account JSON is preferred for GCS, Google Vision, and Gemini calls. Gemini uses the service account through Vertex AI with `GOOGLE_CLOUD_PROJECT` or the JSON `project_id` and `GOOGLE_CLOUD_LOCATION` defaulting to `global`; when no managed JSON is available, Gemini can still use the existing Developer API key fallback.
- `MEDUSA_IMPORT_WORKER_CONCURRENCY` sets the startup default for concurrent import processing. The built-in default is 4, and Settings accepts any positive value while warning that higher values can create a burst of OpenAI calls and cost.
- `MEDUSA_SLIPSTREAM_ENABLED` gates remote work claims. `MEDUSA_SLIPSTREAM_PUBLIC_BASE_URL` lets work bundles return absolute artifact URLs. `MEDUSA_SLIPSTREAM_LEASE_TTL_SECONDS`, `MEDUSA_SLIPSTREAM_HEARTBEAT_SECONDS`, `MEDUSA_SLIPSTREAM_MAX_RESULT_MB`, and `MEDUSA_SLIPSTREAM_REQUIRE_TLS` bound remote lease recovery, check-in expectations, upload size, and transport security.
- `MEDUSA_DOCUMENT_CACHE_SIZE_MB` sets the startup default for the bounded local document cache. The built-in default is 1,024 MB, and Settings can change the active value without affecting GCS/local original storage writes. Settings also displays the current `data/processing-cache` footprint rounded to the nearest MB through `/api/document-cache/status`.
- `MEDUSA_RAW_TEXT_EXTRACTION_TIMEOUT_SECONDS` bounds local raw extraction tools such as Marker before falling back or failing the current extraction attempt.
- `MEDUSA_CITATION_TITLE_WEB_SEARCH` controls the targeted `"paper title" DOI` static web-search fallback used by import and citation refresh when local text, Crossref title matching, and Semantic Scholar title lookup do not find a DOI; `MEDUSA_CITATION_TITLE_WEB_SEARCH_TIMEOUT_SECONDS` bounds that request. The fallback stores compact DOI evidence instead of full search pages.
- `MEDUSA_OPENAI_PAGE_NORMALIZATION_MODE` controls page-normalization spend. `auto` is the default local-first mode; `always` sends every page through the configured OpenAI page-normalization model; `never` keeps page normalization local. `MEDUSA_OPENAI_PAGE_NORMALIZATION_AUTO_MAX_PAGES` caps auto-mode cloud escalations per document.
- Docker sets `HOME`, `XDG_CACHE_HOME`, `HF_HOME`, `TORCH_HOME`, and `MPLCONFIGDIR` under `/app/data` so local ML model downloads survive container recreation through the existing `./data:/app/data` volume instead of entering the image. The backend image also installs PostgreSQL 16 client tools plus `zstd` so `pg_dump`, `pg_restore`, and zstd compression match the PostgreSQL 16 server used by Compose.
- HAProxy certificate material lives in ignored local files at `data/haproxy/fullchain.pem` and `data/haproxy/privatekey.pem`. Compose combines them into a runtime PEM inside the HAProxy container and renders the HAProxy redirect/check host from `MEDUSA_PUBLIC_HOST`; certificate private keys must never be committed. The HAProxy image reads the mounted cert files as UID/GID `99`, so server certificate installs keep `data/haproxy` group-executable and PEM files group-readable for group `99` while avoiding world-readable private keys. `MEDUSA_PUBLIC_HOST` defaults to `medusa.home.musial.io`, `MEDUSA_ALLOWED_HOSTS` allows that host through the Vite frontend server by default, `MEDUSA_BIND_IP` defaults the HAProxy IPv4 host bind to `0.0.0.0`, `MEDUSA_BIND_IPV6` defaults the dedicated-server override's IPv6 bind to `::1`, and `MEDUSA_HAPROXY_STATS_URL` defaults to the internal `http://haproxy:8404/stats;csv` feed used by Utilities. `MEDUSA_ALLOWED_HOSTS` accepts a comma-separated allowed-host list or `*` / `all` / `true` for a temporary open-host migration mode.
- Prometheus text metrics are served by `python -m app.tools.prometheus_exporter` in the optional metrics sidecar, with HAProxy owning the public TLS listener for `MEDUSA_METRICS_BIND_IP:MEDUSA_METRICS_PORT`. `MEDUSA_METRICS_BIND_HOST` controls the exporter's in-container bind host, `MEDUSA_METRICS_PORT` defaults to `43737`, and `/metrics` requires a bearer token from `MEDUSA_METRICS_BEARER_TOKEN` or the preferred ignored file path `MEDUSA_METRICS_BEARER_TOKEN_FILE` such as `data/secrets/prometheus-token`. `MEDUSA_METRICS_INTERNAL_TOKEN` enables the exporter's private backend snapshot call to `/api/internal/metrics/snapshot`; leaving it blank keeps the endpoint dark and reports backend snapshot metrics as unavailable. `MEDUSA_METRICS_OVERLAY=auto` tells host deploy/release commands to preserve `docker-compose.metrics.yml` whenever the token file, an internal token, or another explicit metrics credential is present, so app rebuilds do not recreate HAProxy without the metrics listener; `false` disables that auto-preservation and `true` forces the overlay. The exporter seeds the heavy database/storage/Docker metric catalog into Valkey at startup and refreshes that rendered text snapshot out-of-band; `/metrics` reads the snapshot and appends lightweight live Valkey, HAProxy, backend-snapshot, and exporter-health metrics. `MEDUSA_METRICS_HEAVY_TTL_SECONDS` controls the heavy snapshot refresh cadence, and the snapshot can be rebuilt from PostgreSQL because Valkey is only a metrics cache. `MEDUSA_METRICS_DOCKER_SOCKET_PATH` plus an explicit read-only Docker socket mount enables host/container metrics but is optional because the Docker socket is high-trust. The exporter reports Medusa corpus, queue, Concordance, cache, Valkey, HAProxy, AI usage, cost-composition, pricing freshness, backup, release, and bounded local storage metrics; it deliberately avoids standard node-exporter system metrics and GCS bucket inventory/cost metrics.
- HAProxy uses five-minute client/server timeouts so intentionally synchronous long-running API calls, especially Tags Optimize plan generation over broad tag scopes, can finish while the UI progress strip remains visible. The Docker frontend service builds and serves the compiled Vite bundle, giving browser reloads hashed asset URLs instead of relying on the development `/src/App.tsx` module graph. For local frontend previews, `VITE_MEDUSA_API_PREFIX` can expose an alternate browser-visible API prefix that Vite rewrites back to `/api` before proxying to the Medusa backend, leaving production `/api` paths unchanged. When the `medusa_frontend` backend has no healthy frontend server, HAProxy returns the local `deploy/haproxy/restarting.html` waiting page for non-API browser routes with `X-Medusa-Restarting: true`, `Cache-Control: no-store`, and automatic refresh; `/api/*` routes directly to the backend and fails only while the backend itself is unavailable, so release and startup health probes stay strict. The waiting page uses compact proxy-safe emblem derivatives under `deploy/haproxy/`, mounted as the public emblem paths only inside HAProxy, because HAProxy's inline `http-request return file` fallback cannot serve large frontend PNG assets during config validation.
- The active import concurrency, citation convention, Library alternate-row shading preference, accent color preferences, Download Naming template, saved GCS bucket, managed service-account display/path metadata, document cache size, and model selections are stored in PostgreSQL through `AppPreference` and can be changed in Settings without editing `.env`; private credential JSON remains outside PostgreSQL and outside exports.
- Portable deployment logic must distinguish repository data from database data: `./data` bind mounts application files and caches, while the default `medusa-postgres` volume remains host-local Docker state. Moving to another machine should restore a full PostgreSQL dump; running directly from removable media should require a separate Compose override and a reliability warning for slow or flash-style storage. Dedicated hosts can use the additive `docker-compose.server.yml` override plus a server `.env` derived from `deploy/server/.env.server.example` to pin services to `MEDUSA_CPUSET`, bind HAProxy through `MEDUSA_BIND_IP` and `MEDUSA_BIND_IPV6`, start with conservative import concurrency, and make the 50 GB document-cache cap explicit without changing the local Compose default. `deploy/server/medusa-certbot.sh` records the target-side Let's Encrypt standalone HTTP-01 workflow, copies renewed certificate material into ignored `data/haproxy/`, and installs the certbot deploy hook that refreshes the HAProxy mount after automatic renewal. `scripts/medusa-portability-audit.py` is the source-side checklist for active work, required runtime files, cache sizes, and verified backups; `scripts/medusa-server-doctor.py` is the target-side readiness check for Docker, CPU sets, IPv4/IPv6 bind IPs, port `3737`, rendered HAProxy host bindings, required certs/secrets, and Compose rendering.
- Release and maintenance detection is file-backed so the web backend does not need host Docker or git control. `MEDUSA_RELEASE_STATUS_PATH` defaults to `/app/data/deploy/release-status.json`, and `MEDUSA_RELEASE_REQUEST_PATH` defaults to `/app/data/deploy/release-request.json`; the app can also write `release-check-request.json` for an on-demand check and `maintenance-request.json` for an on-demand maintenance run. A host-side release agent such as `scripts/medusa-release-agent.py` owns `git fetch`, fast-forward-only merge, dependency-change classification, HAProxy cert/key preflight, Compose rebuild/restart with configured Compose override files, same-tag runtime refreshes with `docker compose up -d --build --pull always`, release-history recording, and health verification for both `/api/health` and `/` against `MEDUSA_PUBLIC_HOST` resolved to `MEDUSA_RELEASE_HEALTHCHECK_IP`, `MEDUSA_BIND_IP`, `MEDUSA_BIND_IPV6`, or localhost. Before any apply restarts Compose, the agent verifies non-empty `data/haproxy/fullchain.pem` and `data/haproxy/privatekey.pem` so missing local TLS material fails while the existing proxy can keep serving. Before database/runtime-sensitive applies run Compose, the agent invokes `python -m app.tools.database_backup --reason pre_maintenance --wait --json` inside the backend container and requires a completed backup with URI/local path, SHA-256, nonzero size, manifest evidence, and verified checksum. The backup gate is skipped for routine restarts, same-tag refreshes, safe app updates, and non-database frontend/backend changes. The agent also writes the target `MEDUSA_BUILD_VERSION`, `MEDUSA_BUILD_DATE`, `MEDUSA_BUILD_HASH`, and `MEDUSA_GIT_SHA` into ignored `.env` before Compose rebuilds so later container recreates keep the same runtime/browser build identity. After a successful health-checked fast-forward apply from a prior hash to a pushed main hash, the agent appends `data/deploy/release-history.json` with the applied date/time, commit timestamp, full and short hash, previous hash, branch, source kind, changed files, and concise per-commit change notes; same-hash runtime refreshes do not create release-history entries. The backend reads the status file and writes a request file when an authenticated user clicks `Upgrade Now`, but if the status file's recorded running identity disagrees with the current container's runtime build identity, runtime identity wins for browser reload decisions so stale status JSON cannot keep `Reload Now` visible after a rebuild. Any signed-in browser whose embedded build version differs from the running server build receives `Reload Now`, even after release status has settled back to `current`; same-hash runtime refreshes do not prompt because the version still matches. Server systemd units can own the Compose stack, refresh release status on a timer, and consume upgrade-request or maintenance-request files outside the container. The signed-in frontend performs lightweight release-status checks on a short idle cadence so newly available upgrades appear promptly, then treats an accepted upgrade or maintenance transaction as blocking until the agent reports completion, backend health answers, the exact app shell route being reloaded answers without the HAProxy maintenance page marker, and the browser has begun the cache-busting reload into the new bundle. When the browser bundle is stale, the header action is labeled `Reload Now`, but it performs the same readiness checks before reloading.
- Active-user maintenance gating is based on `sessions.last_seen_at`. Signed-in visible tabs post `/api/activity/heartbeat` roughly once per minute; scheduled maintenance waits until no non-expired session has been seen within the five-minute grace period. User-approved maintenance may override active browser sessions, but it cannot override active imports, Concordance jobs, Inquest jobs, backup/restore runs, or database maintenance. Release status includes maintenance phase, backup gate state, active sessions, blockers, update classification, and host Docker/Compose versions; Docker Engine/Compose host updates remain visible report-only work.

Safe deletion:

- Documents use soft delete. `/api/documents/trash` and the legacy single-document delete route set `deleted_at`, append `DocumentVersion` history plus composition audit rows, and leave originals/assets intact. Original object cleanup is intentionally not automatic yet.
- Original PDFs are served through authenticated `/api/documents/{document_id}/original` responses and should not require public GCS objects. Adding `download=1` returns an attachment whose filename is rendered from the local Download Naming preference; the `.pdf` extension is implicit. The in-app Reader preview renders individual pages through authenticated `/api/documents/{document_id}/pages/{page_number}/image` PNG responses so page-scoped controls can track scroll position and later support geometry hints without depending on browser PDF plugin internals.
- Parsed pages are served as part of authenticated `/api/documents/{document_id}` detail responses for the in-app full-text reader.
- Full database backup/restore routes are authenticated and tracked through `BackupRun`. A manual backup creates a PostgreSQL custom-format dump with `pg_dump`, compresses it with `zstd`, writes it under `data/backups/database` by default, then validates the stored file's SHA-256 checksum before marking the run complete. Optional GCS database backups require `MEDUSA_DATABASE_BACKUP_STORAGE=gcs` on a non-local instance and are blocked when `MEDUSA_LOCAL_AUTO_LOGIN=true`.
- Backup object names use `medusa-postgres-YYYYMMDD-HHMMSS-<short-hostname>.dump.zst`; a sibling `.manifest.json` records backup id, object key, storage kind, storage URI/local path, compressed size, source database size, SHA-256, hostname, compression/dump format, database identity without password, selected non-secret runtime settings, and safety flags.
- The reserved header active-work control includes backup and restore progress. Backup phases are `initializing`, `dumping`, `compressing`, `uploading`, `verifying`, and `complete`/`failed`; restore phases include `safety_backup`, `fetching`, `checking`, `restoring`, `migrating`, and terminal state.
- `/api/backups/estimate` reports the current PostgreSQL database size, configured backup storage kind, and a likely compressed backup size, using the latest completed backup's compression ratio when a manifest has source database size. `/api/backups/artifacts` lists available backup `.dump.zst` artifacts for the active storage mode; Utilities sums those rows to show the total backup footprint and plots completed backup sizes over time. `/api/backups/gcs` remains available only for explicitly enabled GCS database-backup mode. `/api/backups/database` starts a new full backup. `/api/restores/database` starts restore from a selected backup artifact URI. `/api/restores/database/upload` remains an authenticated API recovery hook but is not exposed in the normal Utilities UI.
- Every restore must first create a new full pre-restore safety backup and verify its checksum before the target dump is fetched or opened, checked, decompressed, and applied. Restore uses `pg_restore --clean --if-exists --no-owner --no-privileges`, then runs Alembic migrations so older dumps can be brought to the current schema. Because `pg_restore` replaces `BackupRun` rows, the backend must reconstruct the completed restore row afterward, preserve the verified safety-backup row, and neutralize active backup/restore rows inherited from the restored snapshot; if the selected source backup's own row was captured mid-dump, it is completed from the verified source artifact instead of blocking future work. The Utilities UI asks for confirmation before creating a restore run. A full database restore can replace session rows, so the browser may need to sign in again after restore.
- Full database backups are true PostgreSQL snapshots and therefore include auth tables such as password hashes, session rows, TOTP secrets, and hashed recovery codes. API keys and service-account JSON are not stored in PostgreSQL and are not written into backup manifests; managed Google key files remain in ignored local data paths and must exist on the restored machine for GCS/Google integrations.
- Full database backup/restore is the supported portability path for the system of record. Copying the repo, `data/originals`, or `data/processing-cache` without a database dump is not a complete library move.
- Legacy backup/export routes are authenticated and intentionally omit API keys, service-account credentials, password hashes, session tokens, TOTP secrets, and recovery-code hashes.
- `/api/exports/metadata` returns full metadata JSON with organization state, extracted text, notes, correction history, jobs, Concordance history, and an embedded storage manifest.
- `/api/exports/storage-manifest` returns the durable original/page/figure asset URI manifest by itself.
- `/api/openai/usage` returns authenticated usage totals, task/model rollups, recent OpenAI/Gemini call records, pricing status, the active OpenAI pricing tier, and estimated costs for a requested period (`last_day`, `last_month`, `last_3_months`, or `all_time`). Unknown models are counted as unpriced rather than guessed.
- `/api/model-pricing/refresh` records the current enabled OpenAI tier-specific and Google standard-pricing snapshot into `ModelPricingRecord`, updating unchanged rows' `last_checked_at` and appending a new row only when a model price changes. Settings warns when the configured tier's rows are missing or the latest active pricing check is more than two days old.
- `/api/status/library-fun` returns authenticated visible-library corpus totals for the final Status-page fun stats section. It excludes staged, queued, failed, cleared, restored-paused, and soft-deleted operational rows, counts parsed words from preferred page text, counts indexed words from `Document.search_text`, and reports coverage totals for DOI values, verified citations, bibliography references, project resources, notes, annotations, domains, and tags.
- `/api/cache/status` returns authenticated Valkey/cache health, memory, policy, key count, hit/miss/eviction/expiry counters, per-family backend cache counters, last refresh/hydration timestamps, hot-route p95 request metrics, active queue depth and oldest active-work age, largest PostgreSQL relation footprints, and key Medusa storage footprints. The profile menu and Status cache card show used-memory utilization against the active Valkey limit, with the profile menu adding a mini utilization graph; the Status Cache Details panel includes a Valkey resource monitor for used memory, limit, peak, RSS, keys, evictions, expiries, connected clients, and ops/sec. `/api/cache/refresh` manually advances all durable cache revision families, records the refresh timestamp, warms dashboard, Library Fun Stats, organization lists, and the first Library page, and leaves old keys to expire or be evicted because revision-aware keys make them unreachable. `/api/cache/hydrate` does not advance revisions; it preloads the current revision's derived payloads from PostgreSQL, walking deterministic Library pages, active saved-search result pages, and visible document-detail payloads subject to the same payload cap and Valkey LRU policy as read-through caching. Valkey outages degrade to cache misses or unavailable status instead of making PostgreSQL-backed app reads fail.
- `/api/utilities/database/status` reports database-maintenance counts for Utilities, including the hidden import cache count used by the Clear Import Cache button, the active-document MD5-missing count used by Backfill Document Hashes, plus any active or last completed database maintenance operation. `/api/utilities/database/compact` starts PostgreSQL `VACUUM (FULL, ANALYZE)` as a backend-owned background maintenance operation through an autocommit connection and returns immediately with `status: running`; `/api/utilities/database/optimize` does the same for PostgreSQL `ANALYZE`. `/api/utilities/document-hashes/backfill` hydrates missing originals through the storage adapter into the document cache, computes MD5 on the durable stored original, stores it on `Document.checksum_md5`, and records hash evidence without making GCS objects public. Utilities polls status while those operations are active and shows elapsed time/detail rather than holding a single long browser request. `/api/utilities/import-cache/clear` removes hidden terminal import document rows, their terminal import jobs, stale `ProjectItem` links, managed processing-cache files, and staged original objects where deletion is available; cache-file and staged-original deletes are best effort so storage unavailability does not block removing stale hidden database rows. It must not remove Library-visible documents or staged/queued/running/failed/restored-paused import rows. `/api/utilities/container/status` includes a runtime-version inventory for HAProxy, backend Python/package/system binaries, frontend Node/Vite, the frontend build stamp, and optional current-backend Docker image/layer sizing when `MEDUSA_DOCKER_SOCKET_PATH` points at a mounted Docker Engine socket. Status and Utilities should still show the backend base-image identity from the Python runtime inventory when Docker Engine details are unavailable, rather than reducing the backend-image card to a blank unavailable state. `/api/utilities/haproxy/status` returns authenticated HAProxy stats derived from the internal CSV feed and degrades to an unavailable status when the backend is not running inside the Compose deployment.
- `/api/release/status` returns authenticated release status from the host-agent status file plus current runtime identity. `/api/release/history` returns authenticated release-history entries from `data/deploy/release-history.json` for the Release History page. `/api/release/upgrade` writes an authenticated upgrade request file when a newer upstream release is available and the host agent marked apply as available. If the server is already on a newer build than the browser bundle, the same status response tells the frontend to reload instead of requesting another deploy; the initiating upgrade flow keeps the UI blocked until release completion, `/api/health`, the app shell route, and the cache-busting browser reload have all completed enough for the new bundle to take control.
- `/api/slipstream/status`, `/api/slipstream/enrollments`, `/api/slipstream/clients/{client_id}/disable`, `/api/slipstream/clients/{client_id}/revoke`, and `/api/slipstream/leases/{lease_id}/cancel` are authenticated admin routes used by Settings. Remote clients use `/api/slipstream/register` with a one-time enrollment token, then signed requests to `/api/slipstream/check-in`, `/api/slipstream/leases/claim`, `/api/slipstream/leases/{lease_id}/heartbeat`, `/api/slipstream/leases/{lease_id}/artifact`, `/api/slipstream/leases/{lease_id}/events`, `/api/slipstream/leases/{lease_id}/results`, and `/api/slipstream/leases/{lease_id}/fail`.
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
- Reader Notes restore the annotation UI for page-aware parsed-text notes with create/search/edit/delete and selected-text quote evidence. PDF geometry overlays, due-date reminder handling for annotation reminders, and richer backlinks into the standalone Notes workspace remain future work.
- Saved searches, smart filters, and bulk edit controls are implemented; saved searches can be renamed, duplicated, overwritten from the current scope, and confirmation-deleted, while custom ordering and richer multi-condition filter builders are still future work.
- Metadata correction UI exists for core identity fields, citation status, read/priority state, tags, domains, summaries, custom attributes, and reader text cleanup. Correction history is captured as `DocumentVersion` snapshots and can be restored as the current document state; a fuller field-by-field diff viewer is still future work.
- Notes/reminders exist, but the Notes workspace is not yet a full research-notes system for standalone topics, ideas, concepts, backlinks, and many-to-many document/source links.
- Queue, header progress, backup progress, Finances, and Composition each expose slices of background work, but there is not yet a unified Activity and Work Ledger across imports, Concordance, recommendations, backups, OCR, embeddings, research runs, and maintenance jobs.
- Slipstream has the secure enrollment/signature/lease/result-apply foundation plus a basic PDF text-import client. Richer capability-specific remote runners, central scoped provider-call proxying for model steps, asset-bundle uploads beyond manifest-driven document/page/capability updates, and broader end-to-end UI smoke coverage remain future work.
- Related-paper recommendations support diverse ranking, already-known suppression, title/topic/evidence search, bibliography seeding, open-PDF enrichment, project/domain/tag context expansion, and DOI-backed acquisition wishlist triage, but they are not yet a durable scheduled discovery/acquisition workflow with centralized provider failure visibility, background downloads, no-DOI wishlist records, and richer acquisition status/notes.
- Library health issues are currently spread across Library, Queue, Settings, Tags, Composition, and Concordance instead of summarized in a Corpus Health dashboard.
- Auth is single-user only; no roles or sharing model.
- Full database backup/restore is implemented as authenticated Utilities controls backed by local backup artifacts by default, zstd, checksum verification, and mandatory pre-restore safety backups. Legacy metadata JSON exports remain available, optional GCS database-backup mode is explicit and disallowed for local auto-login instances, and scheduled backup drills/retention policy remain future work.
- Inquests are implemented for current-document Library detail and Reader runs. Batch Inquest prompts across selected documents, saved searches, or Concordance scopes remain future work.
- Recon V1 is implemented as a durable corpus inquiry workspace with manual Source Finder, Quick Answer, Broad Sweep, and Exhaustive modes, but Broad Sweep and Exhaustive are retrieval-backed rather than worker-backed per-document map/reduce runs. Remaining gaps are resumable long-running deep runs, richer negative-coverage recording, answer search/promotion workflows, and broader Corpus Health reporting for semantic-index coverage.
- Portfolio is implemented as a dense assignment upload/version/material/suggestion/assessment/audit workbench. Find Resources uses Recon retrieval; assessments call the Portfolio Assessment model with material and Library evidence for structured scorecards, grade estimates, narrative feedback, revision priorities, and model provenance; bundle export and metadata export/restore include Portfolio rows and audit proofs. Remaining gaps are higher-fidelity DOCX/RTF layout preservation, external search-backed resource suggestions, deeper real-rubric calibration, richer multi-model disagreement analysis, explicit include-Portfolio Concordance scopes, and any later editor-like interaction; the feature-specific roadmap lives in `docs/PORTFOLIO_ROADMAP.md`.

High-value next steps:

- Wire OCR fallback for low-text pages with Google Vision.
- Add exhaustive DOI/source-link resolution, robust citation verification beyond Crossref basics, and richer field-level evidence review.
- Add arbitrary-filter scopes and richer saved-search management for Concordance Runs.
- Add provider abstraction and usage accounting for Gemini, Anthropic, and local embedding routes before changing non-OpenAI defaults.
- Build richer history review/diff UI for manual corrections and imported metadata candidates.
- Add AI figure caption/gist enrichment and include figure gists in richer semantic search.
- Evaluate local BGE-M3 or comparable embeddings against the current OpenAI embedding path.
- Extend Inquests to selected-document, saved-search, and Concordance-style scoped runs.
- Calibrate Portfolio assessments with real rubrics and add richer version-to-version assessment comparison.
- Add richer layout fixtures for two-column PDFs, multi-page tables, and table-heavy papers.
- Add a real annotation workflow with parsed-text highlight capture, note creation/editing, and later PDF geometry overlays.
- Add richer multi-condition filter builders.
- Add a unified Activity and Work Ledger for all durable background work.
- Build out Notes into a document-linked and standalone topic/idea research-notes workspace.
- Expand Related into a diverse discovery and acquisition workflow with already-known suppression and wishlist triage.
- Add a Corpus Health dashboard for missing metadata, stale capabilities, failed work, and repair entry points.
- Benchmark Library list/search at 10x and 50x current corpus size using the detailed plan in `docs/PERFORMANCE_ROADMAP.md`, and evaluate Valkey only for measured cache/pub-sub/coordination needs that PostgreSQL indexes, pagination, and query shaping do not solve cleanly.
- Add scheduled full-database backup drills and retention controls.
- Add Playwright smoke tests for login, import, library search, citation copy, project bibliography, and day/night modes.

## Decision Log

### 2026-06-30: In-place Library document replacement

Decision: Add a Library detail Replace action that uploads a supported source file onto the same document record and queues a full import job immediately.

Why: Some Library records may have been accessioned from incomplete source material such as summaries. The user needs to replace the source with the complete document without creating a duplicate Library item or losing accession/cost/log history.

Consequences:

- Replacement reuses the existing `Document.id`, preserves `DocumentVersion` history, processing events, prior `DocumentCompositionRecord` rows, domains, project links, priority, and read state, and records previous/new accession snapshots.
- Replacement clears source-derived metadata, parsed pages, chunks, figures, capabilities, pending citation candidates, tags, custom attributes, and live page-specific annotations before queueing the new import, so the next worker run rebuilds the document from the new source.
- Replacement creates a normal one-document `ImportBatch` and queued `ImportJob`; it is not a parallel importer. The queued/running/failed/ready visibility contract remains the same as ordinary imports.
- Locked documents cannot be replaced until the user unlocks them.

### 2026-06-28: Direct academic summary openings and takeaways

Decision: Tighten the default document-summary and Inquest prompt contract so generated summaries begin with substantive analysis rather than author, year, medium, venue, or source-title framing, and end with main takeaways plus continued-reading research directions.

Why: Library rows already store bibliographic metadata separately. The summary field should help the user understand what the work contributes, explores, questions, concludes, contextualizes, or makes surprising without wasting the first sentence on metadata throat-clearing.

Consequences:

- Summary prompts now ask for openings that state a substantive claim, problem, method, finding, or conceptual contribution, and explicitly discourage phrases such as `In this article`, `In this paper`, `This article by`, and `This 2013 chapter`.
- Default summaries should cover original ideas/concepts, subject-matter areas, research questions raised, conclusions or novel insights, surprising or counterintuitive results when present, academic context, main takeaways near the end, and adjacent research areas or related topics worth pursuing for continued reading.
- Summary cleanup strips common bibliographic lead-ins in addition to standalone headings and leaked schema trailers before persistence.

### 2026-06-27: Slipstream remote processing leases

Decision: Add Slipstream as an API-mediated remote processing path for import and Concordance jobs, with PostgreSQL-backed leases as the single quorum authority.

Why: Medusa can offload document processing to registered machines without exposing PostgreSQL, duplicating secrets, or opening inbound client ports. The central app remains scheduler, database writer, storage/provenance owner, UI source of truth, and revocation point.

Implications:

- Slipstream clients enroll with one-time tokens, generate Ed25519 keys locally, and sign polling, claim, heartbeat, artifact, event, result, and failure requests with timestamp, nonce, body hash, and signature headers.
- `SlipstreamLease` rows are created for both local worker claims and remote claims; the active partial unique index over `(job_type, job_id)` prevents double assignment.
- Remote result uploads are manifest-driven. The central app validates lease state and idempotency before applying document/page/capability/composition updates in the database.
- Backup, restore, database maintenance, release upgrades, and tag-optimization approval remain local central-app workflows.
- The first bundled remote client is intentionally conservative: it handles basic PDF text import manifests. Richer capability-specific runners and central provider-call proxying remain planned follow-up work.

### 2026-06-27: Portfolio workspace for user-authored documents

Decision: Add Portfolio as a first-class workspace for user-uploaded drafts, assignments, research notes, rubrics, references, feedback, and other education/research artifacts, while keeping those files distinct from the normal Library corpus.

Why: Medusa should help evaluate and improve user-authored work against the user's research library and attached criteria without polluting Library counts, bibliographies, duplicate suppression, or Concordance scopes. User documents also need ancestry: a new draft should not overwrite the prior draft or erase prior analysis.

Consequences:

- The horizontal nav inserts Portfolio between Stashes and Queue, with `/portfolio`, label `Portfolio`, Lucide `Briefcase`, and shortcut `W`.
- `Document.document_kind` partitions `library`, `portfolio_version`, and `portfolio_material` rows. Existing documents default to `library`.
- Portfolio versions and materials reuse Medusa's source storage, generated PDF mezzanine, processing cache, extraction, search text, embeddings, Composition, Finances, processing events, and authenticated Portfolio preview/source routes.
- Portfolio rows are hidden from normal Library lists/search/counts, recommendation existing-library suppression, project bibliographies, duplicate scans, and default Concordance scopes.
- `PortfolioVersionEdge` preserves lineage such as `supersedes`, while `PortfolioItem.current_version_id` selects the current working version without deleting older versions.
- `PortfolioMaterial` attaches rubrics, references, prompts, and feedback at item or version scope so assessments can take quality/focus/completeness criteria into account.
- `PortfolioSuggestion` initially caches Library-resource suggestions from the local search stack; external search-backed suggestions remain future work.
- `PortfolioAssessmentRun` and `PortfolioAssessmentFinding` establish the assessment ledger. Runs store local baseline findings, selected-model provenance, material/evidence snapshots, structured scorecards, grade estimates, narrative feedback, revision priorities, model outputs, and agreement metadata.

### 2026-06-29: Portfolio assignment grading, bundle export, and audit proofs

Decision: Evolve Portfolio into a school-assignment iteration cockpit using existing `PortfolioItem.title` and `description` as the assignment title and brief/context, while adding structured assessment metadata, an audited ZIP bundle endpoint, and a signed hash-chained audit ledger with optional RFC 3161 timestamp anchors.

Why: School paper iteration needs fast draft grading against rubrics and guides, but it also needs durable provenance: the original files, every draft version, every AI assessment, and the timing/identity of key events should be exportable and tamper-evident without making Portfolio documents ordinary Library records.

Consequences:

- `PortfolioMaterial.role` now treats `rubric`, `assignment`, `guide`, `reference`, `feedback`, `source`, and `other` as the supported assignment-context roles; labels and notes remain the user-facing context labels.
- Portfolio Assessment defaults to the repo high-quality default model (`DEFAULT_GPT_MODEL`, currently `gpt-5.5`) unless Settings overrides the `portfolio_assessment` task, and every run snapshots exact model ids.
- Assessment output includes scorecard rows, grade estimate, narrative feedback, revision priorities, per-model outputs, and agreement metadata in addition to persisted findings.
- Portfolio audit events are canonical JSON payloads hashed with SHA-256, chained through previous-event hashes, and signed by Medusa's local Ed25519 key. The private key is ignored local data; exports and bundles include only public keys/fingerprints, signatures, hashes, and timestamp proofs.
- RFC 3161 timestamp authority URLs are optional through `MEDUSA_AUDIT_TIMESTAMP_URLS`; missing or failed TSA calls leave the local chain valid and surface `anchor_pending` or `anchor_failed` rather than blocking Portfolio work.
- `POST /api/portfolio/{portfolio_item_id}/bundle` records a bundle export event and streams a ZIP containing uploaded versions/materials, generated previews when distinct, assessment JSON/Markdown reports, resource metadata, checksums, manifest data, public keys, event-chain JSONL, timestamp-anchor proofs, and verification summary.
- Metadata exports and restore now include Portfolio items, versions, edges, materials, suggestions, assessments, audit events, and audit anchors while continuing to omit private signing keys and other secrets.

### 2026-06-27: Valkey as an optional derived cache layer

Decision: Add internal Valkey as the default open-source response-cache service for rebuildable hot API payloads and operational counters, while keeping PostgreSQL authoritative for documents, search, jobs, history, evidence, auth, and backups.

Why: The database can currently fit in memory, but repeated dashboard/list/detail/status/organization payload assembly is still shared cross-request work. Valkey gives backend and worker processes a common, bounded, optional cache without changing the durable model. Durable PostgreSQL `cache_revisions` rows are part of the cache key, so invalidation is correctness-oriented even when Valkey key deletion is best effort.

Consequences:

- Compose starts an internal `valkey/valkey:9.1.0-alpine` service with no host port, no persistence, `allkeys-lru`, an 8 GB default memory budget, and a private cache-only Docker network shared only with backend and worker.
- Cached v1 API families are `documents:list`, `documents:detail`, `dashboard`, `status:library_fun`, and `organization`; Valkey failures become misses.
- SQLAlchemy session hooks broadly bump cache revision families after ORM/bulk writes in the same database transaction, while manual Refresh Cache advances all revision families and warms common payloads.
- Backend startup and manual Hydrate Cache preload the current revision from PostgreSQL without bumping revisions, so concurrent committed writes still make any older hydrated payloads unreachable.
- Status and the profile menu expose cache utilization, memory, hit rate, mode, per-family counters, refresh/hydration controls, a Valkey resource monitor, and last refresh/hydration timestamps; Settings exposes the saved Valkey Memory Limit and applies it to the running service on Save All; `/api/*` cached responses expose `X-Medusa-Cache` and `X-Medusa-Cache-Family`.
- Valkey contents are internal, derived, non-secret-bearing where practical, not backed up, and never restored as system-of-record data.

### 2026-06-27: Twice-weekly dependency update cadence

Decision: Add a Renovate-backed dependency-update plan that checks Medusa's Docker, Python, and npm dependency surfaces twice weekly while keeping urgent security fixes eligible for immediate handling.

Why: Medusa now depends on more long-running runtime components, including Valkey, HAProxy, PostgreSQL/pgvector, backend/frontend base images, Python packages, and npm tooling. These should receive security patches and useful feature releases on a predictable schedule without floating unreviewed tags into the app.

Consequences:

- Root `renovate.json` schedules checks Tuesday and Friday during the local workday and groups updates by runtime image, backend Python, and frontend npm ecosystem.
- Docker runtime image PRs are not auto-merged, and Valkey update PRs carry cache/security-review labels.
- `docs/DEPENDENCY_UPDATE_PLAN.md` is the operating checklist for Valkey review, published-port verification, standard tests, rebuild verification, and rollback.
- The dependency-update invariant is the same as the runtime security invariant: only HAProxy may publish host port `3737`; Valkey remains internal-only on the private backend/worker cache network.

### 2026-06-26: Library list and search scale first on PostgreSQL

Decision: Keep Library search/list performance on PostgreSQL for this pass, adding a paged slim list endpoint, virtualized frontend rows, Postgres full-text search indexes, persisted duplicate summary fields, batched aggregate counts, lean secondary-workspace document fetches, and request/query timing headers. Do not add Valkey yet.

Why: The current slowdown comes from query shape, enrichment cost, frontend over-rendering, and repeated cross-workspace fetches. Those are lower-risk to fix inside the existing PostgreSQL-backed architecture than adding a new cache tier before there is timing evidence that cache/pub-sub/coordination is the bottleneck.

Consequences:

- `/api/documents/list` is the Library's primary list endpoint and returns bounded rows plus total counts, while `/api/documents` remains a compatibility/reference-list endpoint.
- Search uses PostgreSQL FTS plus existing title fallback where available, with SQLite retaining a simple test fallback.
- Duplicate badges are cheap list fields refreshed by explicit duplicate scan/resolve/dismiss actions instead of recomputed during every list read.
- Valkey remains a candidate for later job-progress fan-out, hot aggregate caches, ephemeral activity streams, distributed locks, or read-through caches after 10x/50x benchmarks show PostgreSQL is no longer the right layer for that specific workload.
- Detailed future performance notes, benchmark phases, read-model candidates, frontend/runtime improvements, and Valkey/external-search decision criteria live in `docs/PERFORMANCE_ROADMAP.md`.

### 2026-06-25: Targeted title-search DOI discovery

Decision: Add Semantic Scholar title DOI lookup and a targeted `"paper title" DOI` static web-search fallback to import enrichment and `citation_refresh`.

Why: Some papers do not expose a DOI in the PDF text and are not recovered by Crossref title search, but the DOI is easy to locate from exact-title search-result evidence. The app should use that evidence before falling back to uncertain APA model output.

Consequences:

- Missing-DOI imports and DOI Refresh first try local text, Crossref, Semantic Scholar title lookup, then targeted title web-search evidence before giving up.
- Strong title support is required before a DOI from web-search text is accepted, and compact evidence is stored in `Document.metadata_evidence["doi_discovery"]`.
- The found DOI is fed back through the existing Crossref and APA citation path rather than creating a separate citation formatter.
- Full exhaustive DOI verification remains future work for Crossref Simple Text Query/reference-string matching, OpenAlex, DataCite, OpenCitations Meta, PubMed/Europe PMC, DOI.org/Registration Agency checks, publisher pages, source-link fallback selection, and field-level evidence comparison.

### 2026-06-26: Explicit no-DOI flag

Decision: Store manually confirmed no-DOI status in document metadata evidence instead of using a placeholder DOI string.

Why: A blank DOI can mean unknown, not-applicable, not-yet-reviewed, or truly absent. The Library list needs a quiet `No DOI` chip only for the reviewed truly-absent case, and citation/DOI discovery must still be able to treat ordinary blanks as unresolved work.

Consequences:

- The document detail DOI controls include a right-aligned `No DOI` button beside Copy, Edit, and Refresh.
- Pressing `No DOI` clears any stored DOI and records `metadata_evidence["no_doi"]` with manual confirmation metadata.
- Saving a real DOI clears the no-DOI flag so Library rows cannot display stale absence state.
- Library document rows show the `No DOI` chip only from this explicit flag, not merely because `Document.doi` is empty.

### 2026-06-25: Host-agent release refresh for portable servers

Decision: Add a file-backed release status and upgrade-request contract for portable server deployments such as carrot.

Why: Medusa should be able to show that newer code has been pushed and offer an authenticated `Upgrade Now` action without giving the web backend broad host control. The server needs a narrow boundary between browser consent, backend state, and host-owned git/Docker operations.

Consequences:

- The app reads `data/deploy/release-status.json` and `data/deploy/release-history.json`, and writes `data/deploy/release-request.json`; all live under ignored runtime data.
- A host-side release agent checks upstream git state, blocks dirty checkouts, fast-forwards only, verifies HAProxy cert/key material before Compose restarts, rebuilds Compose with explicit build identity variables, verifies `/api/health` and `/` through the public proxy, and updates the status file.
- The header button appears with the other right-side status/actions, uses the active accent color, uses a Rocket icon rather than Refresh, and confirms before browser reload with an unsaved-edits warning.
- Database portability remains the full PostgreSQL backup/restore workflow; copying `data/` preserves secrets/caches/local originals but not the default Docker named Postgres volume.

### 2026-06-27: Idle-gated maintenance builds with policy backup gate

Decision: Extend the host release agent into a twice-weekly idle-gated maintenance lane for safe dependency/runtime refreshes.

Why: Medusa should pick up already-reviewed package changes, base-image rebuilds, and same-tag runtime security refreshes without surprising an active user. Routine restarts and safe app refreshes should not spend time creating a full database backup, but database schema, backup/restore, runtime container, PostgreSQL/pgvector, and other major underlying program changes still need a restorable database snapshot before they proceed.

Consequences:

- Scheduled maintenance runs Tuesday and Friday during `03:00-06:00 America/Indiana/Indianapolis`, and Utilities/Status can request an immediate check or maintenance run through file-backed host-agent request files.
- The release agent classifies whether a backup is required. Safe app updates, same-tag refreshes, and routine rebuilds record the backup gate as `not_required`; database schema/persistence changes, backup/restore code changes, runtime container definition changes, non-patch backend runtime dependency changes, and major underlying program version changes first run the backend full PostgreSQL backup CLI and require a completed, checksum-verified backup with manifest evidence. Backup failure records maintenance status and prevents Compose commands only when the backup is required by policy.
- Active browser tabs heartbeat to `sessions.last_seen_at`; scheduled maintenance waits for the idle grace period. Explicit user approval may override active browser sessions but not active imports, Concordance jobs, Inquests, backup/restore, or database maintenance.
- Already-merged patch/security dependency changes and same-tag image/base rebuild refreshes can auto-apply after the gates pass. Major/minor jumps, runtime image tag changes for HAProxy/Valkey/PostgreSQL/pgvector, non-dependency code changes, dirty checkouts, unknown classifications, or migration/release-note risk still require explicit approval.
- Docker Engine and Docker Compose plugin updates stay outside Medusa automation and are surfaced as report-only host maintenance recommendations.

### 2026-06-24: Move backup and restore controls to Utilities

Decision: Move the browser-facing full database backup/restore panel and legacy export links from Settings into Utilities.

Why: Backup, restore, and metadata/export drills are operational maintenance actions. Utilities already owns database maintenance, container/runtime inspection, HAProxy status, and restart controls, while Settings should stay focused on saved preferences, credentials, model routing, storage defaults, and Concordance configuration.

Consequences:

- Utilities now shows Database Backup & Restore alongside database maintenance and runtime operations.
- The backup/restore routes, `BackupRun` records, artifact listing, estimate refresh, checksum validation, header progress, and safety-backup gate remain the backend contract.
- Settings no longer owns backup/restore-specific polling or action state.

### 2026-06-26: Stash rows carry bibliographic metadata

Decision: Treat Stashes rows as DOI-backed bibliographic follow-up records rather than DOI-only strings.

Why: Recommendations already know useful document identity fields, and hand-entered DOIs can often be resolved through public DOI metadata services before the user finds or uploads a PDF. The Stashes list should help the user decide what to pursue without opening every DOI.

Consequences:

- `DoiStashOut` exposes title, authors, publication year, venue, description, page count when known, and metadata source.
- Recommendation-created stashes snapshot recommendation metadata into `DoiStash.metadata`; manual DOI stashes run a public DOI metadata lookup through the existing recommendation providers.
- Display precedence is Library imported document, recommendation snapshot, public DOI metadata, then the raw stash DOI.

### 2026-06-26: Utilities bulk intake for duplicate-safe staging

Decision: Add Bulk Intake to Utilities as a full-batch duplicate preflight for large document drops, while continuing to use the normal staged import queue for any new documents.

Why: The Import page's duplicate panel is optimized for immediate per-drop decisions and intentionally keeps the preview compact. Large acquisition batches need a review surface that can show every already-known file before any new files are staged.

Consequences:

- Bulk Intake sends the complete selected/dropped file set to `/api/imports/duplicates`, which already checks active Library rows, Queue rows, and repeated files in the current drop.
- The Utilities panel lists every checked file, highlights Library/Queue matches and repeated-drop rows, and links matched documents back to Library for validation.
- Stage New sends only files with no existing match and no repeated-drop duplicate to `/api/imports/batches` with duplicate skipping, so the worker, Process Uploads, cost estimates, and queue-only visibility rules remain unchanged.

### 2026-06-26: Repair backup run state after full restore

Decision: Reconstruct terminal backup/restore history after full PostgreSQL restore.

Why: A full restore replaces the database table that records backup and restore progress. A dump can also capture its own `BackupRun` row while that backup is still marked `running`, so restoring that dump can make Utilities report a stale backup as active even though no local backup process exists.

Consequences:

- After `pg_restore` and migrations complete, Medusa recreates a completed restore run row in the restored database.
- The verified pre-restore safety backup row is preserved in history even though it was created after the restored snapshot.
- Active backup/restore rows inherited from the restored snapshot are marked inactive; the selected source backup row is marked complete when it matches the verified source artifact.

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

Why: Originals still belong in GCS or the configured local fallback store, but keeping recent imported PDFs locally makes Concordance and Inquest runs faster and less dependent on immediate storage reads.

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

- Primary navigation renders left-to-right above the work surface, with Settings moved into the far-right user options menu and no persistent left rail.
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
- OpenAI extraction prompts now request complete-sentence technical paragraph summaries written at a graduate academic level suitable for a master's-degree reader, with openings that begin with substantive analysis rather than author/year/medium/source-title framing, place key findings and concrete facts early, avoid starting sentences with prepositions, avoid single-word openers or standalone headings, and avoid bold, italics, bullets, em dashes, and fancy quotes unless the user explicitly asks for another format.
- APA formatter output uses Markdown italics for APA publication elements and Crossref volume/issue/page fields when available, sentence-cases cited work titles, and keeps journal/proceedings/container titles in title case.
- The document detail and expanded Reader surfaces include DOI, APA Reference List, APA In-Text Citation, and Bibliography Copy/Edit/Refresh/Verify controls where applicable. Bibliography Verify remains available when no Bibliography text is stored so the user can affirm that the source document truly has no provided reference list; that empty confirmation is stored as verification evidence and still protects the field from unconfirmed edit/refresh changes. APA citation and Bibliography edit modes accept Markdown italics/bold through toolbar buttons and Cmd/Ctrl-B/I shortcuts, so APA publication elements can be stored and rendered with italics. Refresh from either APA citation section queues one forced `citation_refresh` Concordance Run for that document, validates both APA citation strings together, shows shared feedback on both APA refresh buttons, and disables while a matching queued/running job exists. Citation refresh requires confirmation before clearing manually verified DOI or APA fields. The document-level Bibliography Refresh action uses `/api/documents/{document_id}/bibliography-refresh` to queue a forced `bibliography_extraction` Concordance Run for the selected ready Library document, requires the same confirmation before clearing manually verified Bibliography state, and preserves app-shell background run feedback while guaranteeing existing bibliography text does not make the refresh a no-op. If fresh extraction appears to regress against a fuller stored bibliography, the stored bibliography is preserved as the cleanup input so the selected Bibliography Cleanup model can still reformat it instead of silently completing with no visible change. If the run completes with `not_found` and no bibliography, the surface shows a styled Medusa alert saying it was not able to find references instead of reporting a normal success.
- APA citation and Bibliography copy actions provide rich HTML and plain-text clipboard formats, preserving italics/bold/underline/code in rich paste targets without setting a font face.
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

Decision: Route document-intelligence work by task cost and quality risk. Keep citation-critical Metadata and APA Citation Matching on `gpt-5.5`, run dedicated APA Citation Matching with high OpenAI reasoning effort by default, default Summary and Inquests to `gpt-5.4`, default Tag Suggestions to `gpt-5.4-mini`, default ad hoc Bibliography Cleanup to `gpt-5-mini` with an off-by-default reasoning option for expensive hard cases and author-loss repair before `gpt-5.4-mini` safety retry, and use DOI/Crossref evidence as compact grounding for model-generated APA reference-list and in-text citation pairs before deterministic validation/fallback.

Why: APA correctness is brittle and citation verification should be evidence-backed, while summaries and organization tags are lower-risk and reviewable. DOI/Crossref metadata can often identify the work quickly once title, authors, year, or DOI are known, and GPT is strong at producing the paired APA forms from that compact evidence. The model must still see known document metadata so DOI evidence that belongs to another work stays reviewable instead of being promoted solely because a DOI resolved.

Consequences:

- `.env` should hold the private API key and `OPENAI_MODEL=gpt-5.5` as the startup default.
- Settings exposes extraction/analysis model controls inside Import Processing as shared defaults: Raw Text Extraction, Metadata, Summary, APA Citation Matching, Tag Suggestions, Text on Pages (Normalization), Bibliography Cleanup, Formula Capture, Text Chunk Encoding, Inquests, Recon, and Portfolio Assessment.
- Raw Text Extraction uses grouped Settings options: Local includes Docling, Marker, and PyMuPDF with Marker as the default preference; OpenAI includes the enabled GPT model options for cloud fallback choices. Marker is installed in the worker image and uses the mounted `data/model-cache` path for downloaded weights. PyMuPDF remains the built-in fallback; Docling remains a listed local option until its runtime is wired.
- Text on Pages (Normalization) is local-first by default. `MEDUSA_OPENAI_PAGE_NORMALIZATION_MODE=auto` escalates only low-text or artifact-heavy pages, sends extracted page text without repeated PDF file context, and caps escalations per document. Use `always` only for intentional all-pages cloud normalization.
- Metadata, Summary, APA Citation Matching, Tag Suggestions, Text on Pages (Normalization), Bibliography Cleanup, Formula Capture, Inquests, Recon, and Portfolio Assessment are GPT/Responses tasks. Metadata and APA Citation Matching remain the high-quality citation path; dedicated APA Citation Matching calls pass `reasoning.effort` from `MEDUSA_OPENAI_APA_REASONING_EFFORT`, defaulting to `high`; Summary, Formula Capture, Inquests, and Recon default to the current `gpt-5.4` family defaults unless overridden; Portfolio Assessment defaults to `DEFAULT_GPT_MODEL` currently `gpt-5.5` unless overridden in Settings; Tag Suggestions defaults to `gpt-5.4-mini`; Bibliography Cleanup defaults to `gpt-5-mini`, can pass GPT-5-family `reasoning.effort` only when `MEDUSA_OPENAI_BIBLIOGRAPHY_REASONING_EFFORT` is enabled, runs a targeted author-preserving repair retry when cleanup drops visible authors, retries remaining unsafe cleanup once with `gpt-5.4-mini`, and is only used for user-triggered refresh, not import-time source bibliography extraction; Formula Capture is likewise manual-only through Concordance; Text Chunk Encoding remains the embeddings endpoint and defaults to `OPENAI_EMBEDDING_MODEL`.
- `MEDUSA_OPENAI_SEND_PDF=true` enables Responses API file input for original PDFs below `MEDUSA_OPENAI_PDF_FILE_MAX_MB`.
- `MEDUSA_OPENAI_COMBINE_DOCUMENT_INTELLIGENCE=false` is the default routed mode. Setting it to `true` restores the previous single-call `core_document_intelligence` mode for metadata, summary, APA candidate, and tag suggestions, but that mode cannot use separate cheaper models for summary/tags.
- `MEDUSA_OPENAI_PROMPT_CACHE_RETENTION=24h` adds OpenAI prompt-cache retention hints keyed by document checksum for retries and Concordance reruns when the installed SDK supports the Responses retention parameter; otherwise Medusa sends the cache key only. Overlong cache keys are hashed to satisfy the Responses API 64-character key limit.
- DOI regex extraction plus Crossref DOI/title/author/year matching runs before APA generation. DOI/Crossref evidence, known document metadata, and compact excerpts are sent to the selected APA Citation model for paired APA Reference List and APA In-Text Citation output; when the DOI strongly identifies the same work, the model may complete DOI-specific bibliographic fields such as page ranges or article numbers that compact Crossref evidence omits, and the validator normalizes numeric page ranges with en dashes. Malformed or missing model output falls back to deterministic metadata formatting, and model-reported DOI/title/author conflicts keep the citation reviewable.
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
- Queue cost previews use stored page counts plus recorded import usage exemplars by task/model when available, then task-level/library-level fallbacks, then a conservative per-page default. Exemplar rates and downward calibration are still bounded by a per-document one-page model-pricing floor for cloud steps, which keeps large batches of short documents from undercounting fixed model-call output costs. Each staged document persists its rough estimate as a `DocumentCompositionRecord` with record kind `estimate`; Composition compares that estimate to actual model/embedding spend once the import records usage. Future queue estimates apply a bounded calibration factor derived from prior persisted-estimate versus actual-cost pairs.
- The header active-work progress does not treat staged jobs as active imports; Queue navigation still counts them as attention-worthy work.
- When a released import queue drains, the worker runs PostgreSQL `VACUUM (ANALYZE)` across all tables. Staged jobs waiting for a future Process Uploads click do not prevent that post-drain optimization.

### 2026-06-20: Bookmarkable workspace URLs

Decision: Give every top-level workspace a canonical browser path while keeping the existing single-page app shell and Settings save-before-leaving guard.

Why: Research work should be resumable from bookmarks, browser refreshes, and copied links. Top-level navigation should behave like real page navigation without introducing a louder routing framework or losing durable app-shell state.

Consequences:

- The quiet horizontal navigation renders as links to `/library`, `/domains`, `/projects`, `/tags`, `/stashes`, `/queue`, `/import`, `/budget`, `/utilities`, and `/settings`; `/notes` remains routable but is temporarily hidden from the visible nav.
- Document focus renders as `/documents/{document_id}` and selects that document in Library; `/documents/{document_id}/reader` opens expanded Reader mode. `/document/{document_id}`, `/documents/{document_id}/detail`, and `/reader/{document_id}` are accepted and normalized to canonical document routes.
- Plain clicks use in-app navigation and push browser history; modifier-clicks and copied links use the normal anchor URL.
- Document row title areas are links, document browsing pushes history entries, and the detail pane exposes a Copy Link action for the focused document.
- Direct loads, refreshes, and Back/Forward derive the active workspace, document focus, and Reader/detail mode from the URL. `/` maps to Library and is normalized to `/library` once the shell loads.
- Leaving dirty Settings through navigation or browser history keeps the same save prompt used by internal page changes.

### 2026-06-20: Settings citation convention and summary output polish

Decision: Persist a Settings citation convention preference, keep APA 7 as the only current convention, and tighten the default generated-summary contract across canonical summaries and Inquests.

Why: Citation format is a library-level preference that will eventually need choices, but the current product should expose only the implemented convention. Generated summaries should read like technical prose by default, not like formatted outlines, and document controls should use consistent Refresh language for durable background work.

Consequences:

- Settings > Preferences stores `citation_convention` as an `AppPreference`; the current radio group has one enabled option, APA (7th Ed.), represented internally as `apa_7`.
- Future citation conventions must extend the same preference, API schema, citation generation/formatting paths, and bibliography/export surfaces rather than adding one-off UI controls.
- The Settings opening Runtime, Storage, and AI overview tiles are removed; Settings now starts directly with operational panels. Settings section icons sit left-aligned above section header text.
- DOI, APA citation, and Summary document actions use Refresh wording because they queue durable Concordance-backed refresh work.
- Citation provenance labels display the model name or `user provided` without prepending repetitive labels such as APA Citation Matching.
- The shared summary prompt hint applies to document summaries and Inquests. Defaults are technical plain-text paragraphs with complete sentences, a graduate academic level suitable for a master's-degree reader, key findings and concrete facts early, openings that state substantive claims/problems/methods/findings/contributions rather than author/year/medium/source-title framing, main takeaways and continued-reading research directions near the end, no sentence starts with prepositions, no standalone Summary/Overview-style opening, no single-word opener, no bold, italics, bullets, em dashes, fancy quotes, or decorative Markdown unless the user explicitly asks for another format.
- Import and Concordance summary persistence strips standalone first-line summary headings, common bibliographic lead-ins, and accidental trailing schema metadata blocks before storing `rich_summary`.

### 2026-06-20: PDF mezzanine for HTML and text imports

Decision: Accept HTML and plain-text/Markdown uploads through the normal Import workflow, parse their raw source semantics for reader/search text, and store a locally generated PDF as the durable original object.

Why: Medusa's preview, storage, cache, OpenAI file-context, and download paths already assume PDF as the universal document surface. HTML and text still carry useful structure before rendering, especially titles, headings, paragraphs, list items, and captions, so source parsing should feed extraction rather than treating the generated PDF as the only truth.

Consequences:

- Duplicate detection for non-PDF uploads uses the uploaded source-byte SHA-256, while `metadata_evidence["source_import"]["mezzanine"]` stores the generated PDF checksum, filename, size, format, and renderer.
- GCS/local original storage and `data/processing-cache` receive PDF bytes for every document, including non-PDF imports.
- Worker extraction uses persisted parsed source pages for HTML/text imports and compacts full parsed-page text out of metadata after `DocumentPage` rows are written.
- Current HTML rendering is semantic text-first and does not preserve remote images, full CSS layout, or interactive content. Richer HTML asset capture can be added later without changing the PDF mezzanine contract.

### 2026-06-19: Inquests

Decision: Add current-document Inquests as durable document-owned rows, answered inline when possible and otherwise generated by the worker from a user prompt and Settings-selected model.

Why: Focused research questions should not overwrite the canonical document summary. They need their own prompt, model, body, title, evidence, status, and retry surface so arbitrary topic summaries remain auditable and cost-visible.

Consequences:

- `DocumentAccessorySummary` stores prompt/question, optional title, selected model, generated answer, evidence, status, attempts, lock time, and completion time.
- `/api/documents/{document_id}/inquests` creates an Inquest row, tries inline answering with `MEDUSA_INQUEST_INLINE_TIMEOUT_SECONDS`, and requeues the row for worker processing on timeout. `/api/documents/{document_id}/accessory-summaries` remains as the legacy queue-only compatibility route, and `/api/accessory-summaries/{summary_id}` saves optional titles.
- The worker processes queued Inquests after imports and Concordance jobs, requeues interrupted running rows on startup, and marks failed rows with visible errors.
- Inquest OpenAI calls use task key `accessory_summaries`, record Finances usage, may include original PDF file context when configured and under size limits, and use prompt-cache keys derived from document checksum plus summary id.
- Source-finding prompts, including requests for more, newer, similar, or related papers, use Related-paper recommendation rows instead of generic Inquest AI generation. Cached recommendations can answer inline; prompts that need fresh provider discovery are deferred to the worker and return a Markdown source list with DOI/source/open-PDF links plus recommendation evidence.
- Completed Inquests contribute title, prompt/question, and answer body text to document search.
- Metadata exports include Inquests as document children; restored queued/running rows are parked unless restore is explicitly allowed to reactivate jobs.

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
- Figure extraction, page visual scans, figure relabeling, and figure deletion resync parsed-page Markdown image markers of the form `![Figure 1](medusa-figure:<id>)`; document detail responses also derive per-page `reader_text` with markers from current live `Figure` rows so existing figure assets render inline even before a Concordance marker-sync run rewrites stored page text.

### 2026-06-18: Metadata backup and storage manifest exports

Decision: Add authenticated JSON exports for Medusa metadata and durable storage manifests.

Why: Medusa is meant to be safe to stop, restart, move, and back up. A metadata export gives the user a portable record of the library's research organization and processing state without copying credentials or relying on direct database access.

Consequences:

- Utilities now includes backup/export controls for full metadata and the asset manifest.
- `backend/app/services/exports.py` owns export construction so future restore tooling can share the schema.
- Metadata exports include documents, extracted text, tags, domains, annotations, notes, attributes, correction history, projects, jobs, Concordance state, citation candidates, and storage URI references.
- Exports intentionally omit service-account credentials, API keys, password hashes, session tokens, TOTP secrets, and recovery-code hashes.
- JSON metadata restore later became the CLI `restore_export` workflow; full disaster recovery is handled by the 2026-06-19 PostgreSQL backup/restore workflow.

### 2026-06-27: Local database backups by default

Decision: Store full PostgreSQL database backups on local disk by default under `data/backups/database`; require explicit `MEDUSA_DATABASE_BACKUP_STORAGE=gcs` for GCS database-backup mode, and block GCS database backups when `MEDUSA_LOCAL_AUTO_LOGIN=true`.

Why: Full database backups include auth tables, session rows, TOTP secrets, and recovery-code hashes. A single-user local instance should not silently place those complete database snapshots in GCS just because GCS is configured for originals or extracted assets.

Consequences:

- `/api/backups/artifacts` lists backup artifacts for the active backup storage mode. The Utilities backup panel uses this generic artifact list and no longer requires a saved GCS bucket to create local backups.
- Manual backups write `medusa-postgres-YYYYMMDD-HHMMSS-<short-hostname>.dump.zst` plus a sibling manifest under `data/backups/database`, then verify SHA-256 from the stored file before marking the run complete.
- Restore from the browser uses the selected artifact URI and always creates a fresh safety backup using the same configured backup storage mode before applying the selected dump.
- `/api/backups/gcs` remains available only for explicit GCS database-backup mode on non-local-auto-login instances; original document and figure storage can still use GCS independently.
- The release/maintenance backup gate accepts verified local backup manifests as well as explicit non-local GCS manifests.

### 2026-06-19: Full database backup and restore through GCS

Decision: Add browser-driven full PostgreSQL backup and restore backed by GCS, zstd compression, checksum verification, visible header progress, and mandatory pre-restore safety backups. This decision was superseded for local instances by the 2026-06-27 local-backups-by-default decision.

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

### 2026-06-18: Authenticated PDF preview and annotation groundwork

Decision: Serve original PDFs through an authenticated document route and add backend annotation/highlight records for a future Reader workflow.

Why: Medusa needs to support reading and marking documents, not just cataloging metadata around them. Originals should remain private in GCS/local storage while still being previewable in the app.

Consequences:

- `/api/documents/{document_id}/original` streams the durable original object through the storage adapter with inline content disposition.
- The detail pane embeds the original PDF and provides an open-in-new-tab control.
- `Annotation` rows are exposed through CRUD endpoints and can remain part of document detail payloads as dormant infrastructure.
- Annotation body text contributes to document search, and soft-deleted annotations are excluded from active detail/search rebuilds.
- Reader Notes now use `Annotation` rows for pane-aware page, kind, color, body, and selected parsed-text quote capture; future geometric overlay selection can reuse the existing `geometry` field.

### 2026-06-18: Parsed full-text reader

Decision: Expose extracted `DocumentPage` rows through the document detail API and add a PDF/Text reader switch in the document pane.

Why: Original PDFs need to remain viewable, but parsed scholarly text also deserves a clean reading surface for review and search validation.

Consequences:

- `/api/documents/{document_id}` includes stored page text, derived Reader text, source, low-text flags, and page image URI references.
- The document pane can switch between the authenticated original PDF and parsed page text.
- Parsed page text may include private `medusa-figure` Markdown image markers, and detail serialization derives the same markers into page-level `reader_text` from current live `Figure` rows when stored text lacks them. The Reader resolves those markers against the document's current `Figure` rows, renders a constrained inline thumbnail for the Text pane, and links the thumbnail to the full authenticated figure asset route.
- Reader Notes expose page-aware annotation capture and keep records backend-searchable; future work can map annotation geometry onto PDF overlays.
- Low-text pages are visible in the reader, giving the future Google Vision OCR path an obvious review surface.

### 2026-06-26: Withdraw unfinished annotation UI

Decision: Remove the visible Library detail annotation section until annotation creation, editing, parsed-text highlight capture, and eventual PDF overlay behavior are designed and implemented together.

Why: A visible empty `Annotations` panel implied the user could create or use annotations, but the app only had dormant storage/API and delete-only display plumbing. Hiding the unfinished surface keeps the cockpit honest while preserving the roadmap and backend groundwork.

Consequences:

- Superseded on 2026-06-27 by the Reader Notes annotation workflow. The decision remains as history for why the earlier incomplete panel was removed.
- `Annotation` rows, API endpoints, export/restore coverage, and search indexing behavior remained the durable foundation for the restored workflow.

### 2026-06-27: Restore Reader Notes Annotation Workflow

Decision: Restore annotation UI as a Reader Notes section below the active Reader surface, backed by existing `Annotation` CRUD endpoints.

Why: Page-aware research notes are useful during reading, but the UI must be honest: create, search, edit, delete, and page-jump behavior need to work before annotation controls are visible again.

Consequences:

- Reader Notes can create page-aware annotations with kind, color, page, body, and optional selected parsed-text quote evidence.
- Annotation rows can be searched within the document, jumped back to their page, edited inline, and soft-deleted.
- Annotation body text continues to rebuild document search through the existing backend endpoint behavior.
- PDF-native geometry overlays, reminder due dates for annotation reminders, and backlinks into the standalone Notes workspace remain planned work.

### 2026-06-26: Duplicate false-positive dismissal

Decision: Add a Library duplicate-review action for marking a duplicate pair as different documents.

Why: Duplicate detection intentionally uses broad evidence such as normalized titles and supporting metadata, so legitimate separate documents can be flagged. The user needs a durable way to keep both records visible and remove the `Duplicate` label without weakening the matcher for other pairs.

Consequences:

- `Different documents` records bidirectional false-positive evidence in each document's metadata and writes `DocumentVersion` plus manual composition history.
- Library duplicate scans, duplicate filters, row badges, and detail badges ignore dismissed pairs.
- Import-time duplicate preflight remains unchanged so newly uploaded exact duplicates are still reviewed.

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
- `/api/dashboard` includes import queued/running counts plus active batch progress totals, active step, elapsed seconds, and a bounded, freshness-windowed list of failed AI-provider usage rows so the shell can render active progress and live failed-call alerts without replaying older Finances ledger failures.
- The active-work progress control is visually hidden when no imports or background runs are queued/running but keeps its reserved header slot.

### 2026-06-19: Shell-owned async progress and action feedback

Decision: Move Concordance-starting UI through an app-shell starter and render active durable async work in the reserved header progress control, while keeping local button-level in-flight, success, and error feedback for immediate action visibility.

Why: A user can start small-looking work, such as an APA citation refresh, then switch views. The backend should still finish the durable job, and the UI should make it obvious that Medusa received the request, is processing it, and eventually completed or failed.

Consequences:

- Citation Refresh queues a forced `citation_refresh` Concordance Run for DOI plus both APA citation surfaces through the document citation-refresh endpoint, which can require confirmation before clearing manually verified DOI/APA state. Bibliography Refresh follows the same durable pattern through a dedicated document endpoint that wraps a forced `bibliography_extraction` Concordance Run and can require confirmation before clearing manually verified Bibliography state.
- The app shell records a local "starting" job immediately, reconciles it with persisted Concordance run/job state, and displays starting/queued/running status in the header active-work control. After a short grace window, the dashboard's active Concordance count is authoritative so optimistic local background chips do not remain stuck when the server has no active Concordance work.
- Page-local controls can unmount without losing the shell's progress/error display. If the originating page remains mounted, its button can still flash completion/failure from the watched job. Fresh failed provider calls also appear through the shell-level failed-call alert as soon as their `OpenAIUsageRecord` row invalidates dashboard cache state; older failures remain available in Finances without replaying as live alerts.
- Buttons that start async work use the same restrained feedback language: soft blue plus a spinning in-button icon and slim progress bar while work is in flight, a timed green success blend on completion, red plus a short error popover for failure, then a fade back to the normal button color. When the originating control can see durable job state, such as Concordance refresh jobs or backup/restore runs, the in-button bar fills from that state; operations with no reliable percent, such as SQL maintenance, keep the animated in-flight rail.
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

Why: Finances and document Composition need clean cost accounting even when provider prices change. Daily checks should not create duplicate history rows, but true price changes must leave an auditable old/new price boundary.

Consequences:

- Settings shows the active OpenAI pricing tier, latest local pricing refresh timestamp, the source snapshot date, a Refresh Models & Pricing button using the standard async button animation, and a warning when the configured tier rows are missing or pricing has not been refreshed in more than two days.
- Refreshing stores current enabled OpenAI GPT prices for the configured tier, OpenAI embedding prices, and Google Gemini standard paid-tier token prices. It updates `last_checked_at` for unchanged prices and inserts a new active row only when the rate signature changes, setting `superseded_at` on the prior row.
- Finances, active import spend, import cost exemplars, and Composition sync cost each usage record against the historical price row active at the usage timestamp and pricing tier, with the current official pricing table for the configured tier as fallback when no database history exists yet.
- Google text model options remain limited to non-preview, non-shutdown models. Current Google pricing covers Gemini 3.1 Flash-Lite and the Gemini 2.5 Pro/Flash/Flash-Lite family; legacy Gemini 2.0 and unsupported `gemini-3.5-flash` values are not built-in current options.

### 2026-06-19: APA reference-list and in-text citation surfaces

Decision: Split the Library detail citation display into `APA Reference List` and `APA In-Text Citation` sections, with separate Copy/Edit controls and shared Refresh behavior.

Why: Research writing needs both the reference-list entry and the parenthetical in-text form. They should be visibly distinct but generated from the same evidence/model preference so they do not drift.

Consequences:

- `Document.apa_citation` remains the Markdown-compatible reference-list entry. `Document.apa_in_text_citation` stores the parenthetical in-text citation.
- Each citation has stored model/source provenance. The UI displays the model name when model/generated provenance is present and `user provided` after a manual override.
- Inline citation edits PATCH only the edited field and create normal `DocumentVersion` history. User edits do not silently mark the paired citation as user-provided.
- `citation_refresh` v4 refreshes both citation fields together, gives the selected APA Citation Matching model DOI/Crossref evidence plus known metadata when available, validates the paired output, and records model/provenance while retaining deterministic fallback formatting for missing or malformed model output.
- Existing populated APA reference-list citations are backfilled as generated by `gpt-5.5`; their in-text citations are derived from stored authors/year where possible.

### 2026-06-19: Gemini model options and AI cost rollups

Decision: Add Google Gemini text-generation models as a provider group in Settings > Import Processing shared model defaults and record Gemini `generateContent` calls in the existing AI usage ledger.

Why: Medusa needs model/method preferences that can compare OpenAI and Google choices without hiding cost. The user may choose Gemini for summaries, metadata, page normalization, APA fallback checks, and Inquests, and those calls must remain visible in Finances by task, model, document, and time.

Consequences:

- `data/secrets/gemini.env` is the preferred ignored local secret file for `GEMINI_API_KEY`; backend and worker also honor direct `GEMINI_API_KEY` environment configuration.
- Settings-managed Google service-account JSON is preferred over `GEMINI_API_KEY` for Gemini model calls and routes through Vertex AI using the saved key plus `GOOGLE_CLOUD_PROJECT`/JSON `project_id` and `GOOGLE_CLOUD_LOCATION`.
- Settings > Import Processing shared model defaults group compatible text-generation choices under OpenAI and Google, and exclude Gemini model ids containing `preview` plus deprecated/shutdown Gemini defaults from the Google group. Current built-in Google options include Gemini 3.1 Flash-Lite, Gemini 2.5 Pro, Gemini 2.5 Flash, Gemini 2.5 Flash-Lite, and stable latest aliases that resolve to those priced families.
- Gemini text-generation calls use Vertex AI `generateContent` when managed service-account credentials are available, otherwise the Developer API `generateContent` route with `GEMINI_API_KEY`; both paths use extracted text only. Original PDF file attachment remains an OpenAI Responses path until Gemini PDF-context handling is explicitly wired and verified.
- Finances records Gemini calls with provider `google` in the existing `OpenAIUsageRecord` table, estimates known Gemini text-model costs from model-pricing history or the local pricing fallback, and leaves unknown/ambiguous models unpriced.
- Finances rollups now include model, task, document, calendar day, and calendar hour views so expensive documents or time windows can be isolated.

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

Why: Finances answers broad spend questions, but a research document also needs provenance: exactly which local stages and cloud models generated it, how long import work took, which provider/model costs contributed dollars, and which warnings, errors, or edits happened afterward. Concordance can later use this same ledger to avoid reprocessing documents already generated with a specific capability and model.

Consequences:

- Imports write `DocumentCompositionRecord` rows for local stages, synced AI usage, warnings/errors, and manual citation/metadata edits.
- `/api/documents/{document_id}/composition` summarizes those rows into cost entries, provider spend, local duration entries, pipeline chart steps, and processing issues. Cost entries and provider spend are priced usage, not visual guesses: sub-cent model or embedding calls remain listed and included in totals, while local stages only show configured fallback models when the model actually has a provider usage row. If no rows exist, the endpoint returns `available=false`.
- The Library detail pane has a Composition button beside Edit/Concord/Reader/Related. It opens a centered modal with a Cost Composition overview, total known dollar cost, total import duration, provider breakdown, Local Time collapsed behind an explicit disclosure, processing issues, and a multi-row React Flow Document Accession chart with contained stage nodes.
- The header active-work progress slot is wider and includes current known import spend while imports are queued/running.
- Metadata exports include composition rows; restore preserves their costs/tokens/stage metadata and clears raw usage-record pointers when usage rows are not part of the export.

### 2026-06-19: Composition Pipeline Chart

Decision: Render the Composition pipeline with `@xyflow/react` instead of custom flex boxes, and rename visible Errata language to Processing Issues.

Why: Pipeline provenance needs a real graph surface that can fit, pan, and zoom without text bleeding between stages. "Errata" was too opaque and incorrectly suggested publication corrections rather than import warnings or errors.

Consequences:

- The Composition modal uses read-only React Flow nodes and custom arrowed edges that draw a subtle visible stroke from each source node into the next target node. React Flow handles are hidden anchor points, not visible connection controls. Document Accession steps remain ordered by import stage and same-stage task execution rather than alphabetic model names, and the viewport refits on open and resize so every recorded node is visible by default across screen sizes.
- Processing Issues is reserved for warnings/errors; completed manual edits remain in the composition ledger but are not listed as issues.
- The API field remains `errata` for compatibility, but product copy should use Processing Issues unless the backend contract is revised.

### 2026-06-19: DOI stashes for related-paper follow-up

Decision: Make DOI stashes a first-class database-backed workflow with a top-level Stashes view, while keeping Related recommendations visually quiet and auto-refreshing by default.

Why: Related-paper discovery often produces useful DOI targets before the PDF is immediately available. The user needs a durable follow-up list that survives navigation and lets a later PDF upload join the normal import queue without re-entering metadata.

Consequences:

- Related recommendations default to Hide Existing, auto-refresh when an eligible document has no cached rows, and keep row actions below the recommendation text so titles, venues, and descriptions have horizontal space.
- `DoiStash` rows are unique by normalized DOI, can be reactivated after soft delete, and keep recommendation/source evidence plus import job/document pointers.
- Stashes view lists saved DOIs with local sorting, per-row DOI copy, manual Sci-Hub DOI links in a new window that first copy the paper title, resolver-backed Import DOI, Upload PDF, compact dashed drag target controls, and Library validation plus stash-record deletion for already matched documents.
- Stash uploads create normal import batches, documents, storage writes, cache records, import jobs, duplicate-skip events, and queue progress. Once the import job completes, a duplicate match is accepted as already imported, or a ready Library document matches by DOI/title, the stash can be removed from the active list.

### 2026-06-26: Database-backed password hashes and account 2FA

Decision: Keep the first admin password as a first-boot `.env` seed only, store the live password as `users.password_hash`, and add optional authenticator-app TOTP to the single-user account.

Why: Medusa is LAN-accessible through HAProxy, so the login process should not depend on a long-lived plaintext `.env` password after the account exists. The app also needs a second factor that fits the local-first single-user model without adding an external identity provider.

Consequences:

- `users` stores TOTP enablement, the TOTP secret, last-used time step, confirmation timestamp, and hashed one-time recovery codes.
- `/api/auth/login` verifies the password hash and, when enabled, requires a current TOTP code or unused recovery code before issuing the HTTP-only session cookie.
- Settings > Account generates a setup key, confirms the first code before enabling 2FA, shows recovery codes once, and requires current password plus TOTP or recovery code to disable 2FA.
- Enabling or disabling 2FA revokes other active sessions. Password changes continue to revoke other sessions while preserving the current browser session.
- Legacy metadata exports and restore validation treat TOTP secrets and recovery-code hashes as secret auth material. Full PostgreSQL backups include them because they are complete database snapshots.

### 2026-06-27: Bibliography refresh stale-output handling

Decision: Treat publisher "References: this document contains references to N other documents" front matter as bibliography boilerplate, not a source-reference heading, and let forced Bibliography Refresh clear stale machine-extracted bibliography text when the current extractor finds no supported reference list.

Why: Some publisher PDFs include clean front/back matter but corrupt embedded text for the article body. A stale import-time bibliography can therefore be visibly worse than no bibliography because it may contain publisher recommendations, download notices, or encoded symbol noise instead of the document's own references.

Consequences:

- `bibliography_extraction` capability version 2 rejects publisher reference-count boilerplate before scoring reference-section candidates.
- `bibliography_extraction` capability version 3 adds visual OCR fallback for tail-page reference lists when ordinary PDF span and parsed-page extraction find nothing and the active preset allows OCR; Google Vision is tried when available, with Tesseract as the local fallback in the backend image.
- Bibliography extraction evidence records symbol-heavy unreadable text pages and `ocr_recommended=true` when the text layer looks OCR-worthy even though it is not low-text.
- Forced document-scoped Bibliography Refresh clears the existing `Document.bibliography` only when prior bibliography evidence shows it was machine-extracted from `page_text` or `pdf_span_layout`; user-supplied bibliography text remains intact when extraction returns `not_found`.
- Full OCR page-text persistence for corrupt-but-not-low-text pages remains part of the OCR fallback backlog; until then, stale machine output is removed rather than preserved as if it were refreshed.

### 2026-06-30: Column-aware bibliography OCR rescue

Decision: Treat full-page visual OCR as the first rescue attempt, then retry bibliography OCR in column order when full-page OCR cannot isolate a reference list.

Why: Some scholarly PDFs have visibly readable reference pages but corrupt embedded text. Full-page OCR can also merge two-column references with the opposite column's cited-by, download, or recommendation boilerplate, which makes a real page-11 reference list look like nonsense or spill into page 12.

Consequences:

- `bibliography_extraction` capability version 4 retries tail-page OCR with left/right column clips after full-page OCR returns `not_found`.
- Extraction stops at cited-by sections and publisher download/recommendation headings so post-reference pages are not stored as source references.
- Unnumbered reference splitting recognizes organization-year starts, surname/initial patterns without a final initial period, and terminal page-span endings so adjacent OCR references separate cleanly.
- Visual OCR bibliography evidence records the chosen OCR layout, attempted pages, and the full-page fallback result when column OCR succeeds.

### 2026-06-28: Recon corpus inquiry V1

Decision: Add Recon as the durable corpus inquiry layer for ad-hoc Library questions and Portfolio research support.

Why: Inquests answer one question against one document. Medusa also needs a corpus-scoped artifact that can find sources, synthesize only from stored evidence, and keep the answer/evidence separate from document metadata until the user promotes it elsewhere.

Consequences:

- `/recon` is inserted between Projects and Tags with shortcut `R`, a three-pane workbench, inquiry creation/update, scope controls, mode selector, model selector, estimates, run controls, answer display, and evidence inspection.
- New tables are `recon_inquiries`, `recon_runs`, `recon_evidence`, and `recon_answer_versions`, with Alembic revision `20260628_0029_recon.py` and SQLite metadata creation support for focused tests.
- The `recon_inquiry` Settings model task defaults to the current Inquests-style synthesis model. Source Finder can run locally from retrieval evidence; Quick Answer and other synthesis modes use the selected model when configured and otherwise store a local fallback summary.
- Recon retrieval combines Library-visible scope resolution, saved-search filters, metadata/citation/tag/domain signals, lexical chunk scoring, optional pgvector chunk similarity when a query embedding can be generated, snippet packaging, page/chunk references, and per-document diversity caps. Evidence rows are the only citable support for generated answers.
- The Concordance `search_index` capability is version 4 and now refreshes missing text chunk embeddings as part of retroactive semantic-index repair. Import still may cap initial embedding work, but Concordance can bring older documents into fuller semantic coverage without re-uploading.
- Portfolio Find Resources now uses Recon retrieval while preserving the `PortfolioSuggestion` surface. Portfolio Assessment includes selected Library evidence and attached materials in a model-backed assessment call when available, with local findings as fallback.
- Broad Sweep and Exhaustive are explicit modes with estimates and warnings, but V1 does not yet run full worker-backed per-document map/reduce passes or persist negative relevance judgments for every scoped document.

### 2026-06-29: Library Item Lock

Decision: Add a per-document Library lock backed by `Document.locked_at`, surfaced as a padlock action before Trash in the detail and expanded Reader action bars.

Why: Some imported documents become canonical after manual cleanup, citation verification, or project use. The user needs a reversible guardrail that prevents accidental edits, refreshes, overwrites, Trash, and property changes without confusing that protection with citation or bibliography verification.

Consequences:

- Locked documents remain visible in Library, search, Reader, Related, exports, and authenticated original/figure asset views.
- Mutating document endpoints return HTTP 423 while locked; bulk edits, Trash, duplicate resolution/dismissal, review-queue candidate acceptance, figure writes, annotations, Reader text edits/scrubs/restores, recommendations refresh, Inquests, field verification, and import overwrite must require unlock first.
- Concordance scope planning excludes locked documents, and already-queued Concordance jobs for a locked document complete as skipped with a `concordance_skipped_locked` processing event.
- The active lock icon uses its own subdued amber treatment. Verified DOI/APA/Bibliography badges and Library verified-state omission rules remain unchanged.

### 2026-06-29: Inline Figures In Reader Text

Decision: Keep extracted visual assets as durable `Figure` rows, but mark their positions in parsed page text with private Markdown image links such as `![Figure 1](medusa-figure:<figure_id>)`.

Why: The Text reader should preserve the document's visual flow without converting figures into prose or requiring a separate figure list lookup. The marker keeps the internally derived text inspectable, copyable, and repairable while letting the Reader render the current cropped asset inline.

Consequences:

- Import-time figure extraction, Concordance visual extraction/context, Reader page-scan keep actions, figure relabeling, figure deletion, parsed-text page edits, and parsed-text Scrub all resync page-level markers from the current live `Figure` rows.
- Document detail serialization derives markerized `reader_text` from current live `Figure` rows, so older documents and deleted figures do not depend on a stored-text rewrite before the Reader shows or removes inline figure thumbnails.
- `visual_asset_context` capability version 2 is the retroactive marker-sync path for older documents that already have extracted `Figure` rows.
- Marker placement prefers the extracted caption or label paragraph, then falls back to page geometry when available. The original caption text remains in the parsed text so visible labels and annotations are not erased.
- The Reader resolves markers only when the referenced figure is present in the current document detail payload. Stale or deleted marker IDs are ignored in the frontend and removed by the next backend sync.
- Inline Reader figures use the same authenticated `/api/figures/{figure_id}/asset` route as figure cards, render within the current Text pane, and open the full asset in a new browser tab when clicked.
