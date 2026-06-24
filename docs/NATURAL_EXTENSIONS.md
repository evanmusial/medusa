# Medusa Natural Feature Extensions

Last updated: 2026-06-23

This document collects feature ideas that feel like natural extensions of Medusa's current shape. It is a planning artifact, not an implementation commitment. Move individual ideas into `TODO.md` only after they become planned work with concrete acceptance criteria, and update `docs/ARCHITECTURE.md` only when a direction becomes a product or architecture decision.

The through-line is simple: Medusa should keep becoming a dependable research cockpit for thesis work. New features should preserve the current local-first, quiet, durable, auditable character while making the system faster to trust, easier to operate, and more useful during real reading and writing.

## Product Principles

- Extend existing workflows before adding isolated surfaces.
- Make long-running work durable, inspectable, resumable, and cost-visible.
- Keep uncertainty visible rather than hiding it behind confident generated text.
- Prefer evidence-linked research artifacts over free-floating AI answers.
- Let Projects become the bridge between the library and actual thesis writing.
- Keep the interface dense, calm, and consistent; new pages should feel like Medusa on day one.

## Best First Bets

If only one or two ideas move forward soon, the strongest candidates are:

1. Activity And Work Ledger. This is the best infrastructure-shaped product improvement because it would make imports, Concordance, backups, OCR, recommendation fetches, Accessory Summaries, and future Recon runs feel like one coherent operating system. It supports performance work, background scheduling, and safer dogfooding without committing to a large new research feature first.
2. Research Notes for documents, topics, and ideas. This replaces the earlier separate Evidence Notebook concept with a fuller Notes direction: document-linked notes, standalone topic/idea notes, and explicit links between notes and documents. It is the best thesis-shaped user feature because it turns reading and thinking into reusable research material.

The Library Related Documents expansion below is also a strong near-term candidate because the feature already exists in the document pane and can become much more valuable without inventing a new workspace.

## Highest Leverage Extensions

### Activity And Work Ledger

Medusa already has durable imports, Concordance Runs, citation refreshes, Accessory Summaries, backup/restore progress, and header-level active-work feedback. The natural next step is a unified Activity or Work Ledger that treats every background operation as one inspectable work item.

What it would add:

- One place to inspect imports, Concordance, citation refreshes, Accessory Summaries, recommendation downloads, backups, OCR, embeddings, future Recon runs, and maintenance jobs.
- Common status language for staged, queued, running, paused, blocked, failed, retryable, complete, and cleared work.
- Lane-based prioritization so a quick document refresh does not get stuck behind a giant library maintenance run.
- Row actions for retry, pause, resume, cancel, open result, open source document, and view cost/time details.
- A small Activity detail view with processing events, model/provider calls, warnings, errors, retries, and next action.

Why it fits: Queue already exists, but its mental model is still import and review heavy. A broader Activity ledger would make Medusa feel operationally trustworthy as more work moves into background tasks.

### Performance Observatory

Budget & Costs answers money questions, and Composition answers per-document provenance questions. The complementary feature is a Performance Observatory that answers time and responsiveness questions.

What it would add:

- Import throughput by stage: storing, extraction, normalization, figure extraction, metadata, citation, tagging, indexing, cache cleanup.
- Queue wait time, run time, retry count, and failure clusters by task.
- Slow endpoint and slow query summaries for Library, search, document detail, Queue, Budget & Costs, and Settings.
- Cache hit/miss information for originals, document cache, model cache, recommendation cache, and pricing/model registry refreshes.
- Visible "why this is slow" explanations for large actions, such as broad Concordance or whole-library research runs.

Why it fits: Medusa already records usage, cost, processing events, and composition rows. Performance visibility would turn dogfooding frustration into concrete optimization work instead of guesses.

### Background Work Scheduling

As the app gains OCR, semantic search, recommendation fetches, Recon, and more Concordance capabilities, background work needs a small scheduler rather than a single queue priority rule.

What it would add:

- Work lanes for interactive document refreshes, imports, Concordance, backups/restores, recommendation fetches, OCR, embeddings, and research inquiries.
- Per-lane concurrency limits, cost caps, and pause controls.
- "Run while idle" and "defer expensive cloud work" options.
- A clear preflight for expensive runs with document count, page count, expected model, rough cost, rough time, and resumability notes.
- A global "pause cloud/model calls" control that still allows local work where safe.

Why it fits: The current worker already prioritizes imports before Concordance. A scheduling layer would make that policy explicit and adaptable as Medusa becomes the user's daily research machine.

### UI Consistency Kit

Medusa has a strong design language, but new workbenches can drift if every page reinvents its own command strip, status chip, and progress treatment.

What it would add:

- Shared page patterns for workbench layouts: command strip, scope chips, compact metrics, table/list rows, right-side review pane, empty states, and result detail panes.
- A shared async action pattern for all job-starting buttons, matching the current soft-blue running, green success, red failure language.
- Standard status pills for document state, citation state, processing state, provider state, cost state, and review state.
- A consistent "model/provenance chip" pattern that keeps labels short near documents and fuller inside Settings.
- A visual QA checklist for Library, Import, Queue, Projects, Tags, Notes, Budget & Costs, Settings, and future Recon.

Why it fits: This keeps the app from feeling like a pile of excellent parts. The goal is not decorative consistency; it is operational fluency.

## Thesis Research Extensions

### Research Notes For Documents, Topics, And Ideas

Projects currently organize sources and bibliographies, and Medusa already has a Notes surface. The stronger thesis extension is not a separate Evidence Notebook brand, but a fully built-out Notes workspace that handles both document-grounded evidence and standalone topic or idea notes that can link back to documents.

What it would add:

- Standalone notes for topics, concepts, questions, ideas, thesis sections, and research hunches.
- Document-linked notes that can point to one or more documents, pages, annotations, figures, tables, citations, projects, domains, tags, or saved searches.
- Note types such as general note, quote, paraphrase, method note, finding, definition, counterpoint, limitation, idea, question, and "use in chapter."
- Backlinks so a document shows every linked note, and a note shows every linked source or organizing object.
- Project section assignment so notes can be grouped under thesis outline areas without requiring every note to belong to a project.
- Search, filters, status, reminders, soft delete/restore, and export formats that preserve linked citation context.

Why it fits: This turns Medusa from a library manager into a research workbench without pretending to be a word processor, and it preserves the existing Notes mental model instead of scattering research thinking across another surface.

### Literature Matrix

A Literature Matrix would give thesis work a structured comparison surface over selected project resources.

What it would add:

- Rows for papers or project resources.
- Columns for research question, method, population/sample, data source, theory/framework, key findings, limitations, useful quote, and relevance.
- AI-assisted draft cells with evidence links and explicit "needs review" state.
- Custom project-specific columns.
- Export to CSV/Markdown for writing workflows.

Why it fits: Projects already know which sources matter. A matrix would make synthesis work visible and editable.

### Argument Map

An Argument Map would let the user organize claims, evidence, objections, and source support.

What it would add:

- Claim cards linked to evidence notebook items, documents, annotations, and citations.
- Support, contradiction, qualifies, background, and example relationships.
- Per-claim confidence and evidence sufficiency.
- A project-level view that shows where claims lack sources or rely too heavily on one source.
- Optional export to outline format.

Why it fits: Medusa already tracks evidence and provenance. This would make the step from reading to thesis argument less lossy.

### Reading Plan And Review Cadence

Medusa has priority, read status, reminders, notes, and projects. A reading plan would combine those into a practical research rhythm.

What it would add:

- A project-scoped reading queue ordered by priority, deadline, relevance, citation status, and unread/partially read state.
- "Next three sources" suggestions based on project goals and current gaps.
- Review reminders for important sources or stale notes.
- A weekly digest of newly imported, newly verified, newly failed, and newly useful sources.
- Lightweight reading-session notes that attach to project resources.

Why it fits: This helps the app become a daily instrument instead of only a repository.

## Corpus Intelligence Extensions

### Library Related Documents Discovery

The current Library detail pane already exposes Related recommendations for DOI-bearing documents, hides existing matches by default, and can queue open PDFs through the normal import pipeline. The natural extension is to make Related a better discovery instrument: exclude what is already in the library by default, reach farther than near-duplicate paper suggestions, and present a diverse set of reference material that helps the user understand the surrounding literature.

What it would add:

- Exclude library-held documents by default. Candidates whose DOI or strong normalized title already matches a ready document should be suppressed from the main Related list, not merely badged, so the user sees genuinely new leads first.
- Also suppress active imports, staged imports, and already-stashed DOI targets by default. These can remain visible in a secondary "Already Known" or "In Library / Queued / Stashed" view when the user wants auditability.
- Keep duplicate detection strict: DOI equality first, then strong normalized-title matching with year/author support before suppressing a result.
- Expand provider and evidence sources beyond immediate related-paper APIs. Use OpenAlex, Semantic Scholar, Crossref, Unpaywall, arXiv, DOI.org, publisher pages where lawful, extracted references, citing works, same-author works, venue context, and document tags/domains.
- Separate result families so Related is not one flat list of similar papers. Useful families include close continuations, foundational sources, newer citing work, contrasting or critical work, methods/background references, datasets/standards/reports, and accessible open PDFs.
- Rank for both relevance and diversity. Use a maximum-marginal-relevance style blend so the top set covers different authors, years, venues, methods, source types, domains, and relation types rather than ten versions of the same article cluster.
- Show compact reason chips such as cites this, cited by this, same method, shared domain, newer review, foundational source, policy report, book chapter, open PDF, or outside current library.
- Add controls for discovery intent: Closest, Newer, Foundational, Methods, Contrasting, Open PDF, Reference Material, and Diverse Set.
- Preserve evidence for every suggestion: provider, relation type, DOI/source URL, matched references, abstract snippets, open-PDF evidence, and duplicate-suppression reason if hidden.
- Let useful non-PDF or not-yet-open candidates move into an acquisition wishlist rather than disappearing because no PDF is immediately available.
- Support project/domain-aware expansion: when the current document is in a project or domain, Related can bias toward sources that fill gaps in that project while still keeping the candidate outside the existing library.

Why it fits: Related already lives at the exact moment when the user is reading a source and asking "what else should I know?" The next version should be less like a simple similarity list and more like a disciplined literature expansion tool.

Suggested interaction:

1. Opening Related loads the Diverse Set tab by default and excludes library-held, queued, and stashed items.
2. The header shows how many candidates were hidden as already known, with a quiet link to review them.
3. Result rows explain why the item appears and what kind of source it is.
4. Row actions support stash DOI, queue open PDF, open source, copy DOI, copy title, and mark not useful.
5. A "Reach Further" action runs a broader background discovery pass that may take longer and writes progress through the Activity ledger once that exists.

Implementation notes:

- Treat this as durable recommendation work, not request-time-only fetching. Refreshes should become background jobs with retry, provider-failure visibility, and cost/time accounting.
- Store relation family, diversity features, duplicate-suppression reason, and evidence payloads with `DocumentRecommendation` or a successor table.
- Keep Google Scholar manual-only, consistent with the current architecture, but make manual search links more targeted by title, author, DOI, and key phrase.
- Do not require open PDF availability for a candidate to be useful. Open PDF is an acquisition convenience, not the definition of relatedness.
- Let Concordance eventually refresh related discovery for a document, project, domain, or saved search.

### Recon Integration Points

`docs/RECON.md` already sketches a corpus-question workspace. Natural adjacent features would make Recon output useful across Medusa.

What it would add:

- Promote Recon findings into linked research notes.
- Attach Recon runs to Projects and project sections.
- Flag stale Recon answers when source documents, tags, domains, annotations, or saved-search scopes change.
- Compare two Recon runs over time to show what changed in the corpus or answer.
- Let Broad Sweep create a coverage map showing which scoped documents had supporting, contradicting, or no relevant evidence.

Why it fits: Recon should not become a sealed chat box. Its best outputs should feed the rest of the research cockpit.

### Concept Map

Tags, domains, relationships, notes, citations, and semantic search can support a map of concepts across the library.

What it would add:

- Concept nodes from tags, domains, detected themes, author keywords, and recurring phrases.
- Edges from approved tag relationships, co-occurrence, citations, project membership, and user-approved links.
- Scope controls for whole library, domain, project, saved search, or selected documents.
- A quiet evidence side panel rather than a flashy graph-only interface.
- Actions to merge tags, create relationships, save searches, or start Recon from a concept cluster.

Why it fits: Tag governance has already moved toward a deliberate taxonomy. A concept map would expose structure without replacing the normal lists.

### Research Gap Finder

A gap finder would look for areas where the current project or domain has weak coverage.

What it would add:

- Missing-method, missing-author, missing-year-range, missing-domain, and missing-counterargument signals.
- Project-specific warnings such as "many sources mention this concept, but none are marked used" or "this claim has no recent source."
- Integration with recommendations and stashes to suggest acquisition targets.
- A clear distinction between actual gaps and low-confidence hints.

Why it fits: The app already knows source metadata, tags, domains, projects, and recommendations. Gap finding is the natural next layer.

### Citation Graph And Source Lineage

Recommendations already use scholarly metadata services. A citation graph would make source relationships inspectable.

What it would add:

- Cites, cited by, related, same author, same venue, and same DOI-family relationships.
- Project-level view of foundational sources and overrepresented clusters.
- "Find newer work citing this" and "find earlier foundations" actions.
- DOI/source-link evidence attached to graph edges.

Why it fits: This builds on recommendation and citation-verification work without turning Google Scholar into an automated scraper.

## Reader And Annotation Extensions

### Figure And Table Gallery

Figure extraction exists, but figures and tables can become first-class research objects.

What it would add:

- A document-level and project-level gallery of figures, charts, photos, diagrams, and tables.
- Figure/table notes, tags, and evidence links.
- AI-generated figure/table gists stored as reviewable candidates.
- Copy/export for figure citations and source page references.
- Inclusion in semantic and full-text search.

Why it fits: Many research claims live in figures and tables. Medusa already extracts figure assets and plans richer table objects.

### Annotation Layer Upgrade

Annotations exist as records, but creation and geometric overlays are deferred. The natural extension is a more capable annotation layer.

What it would add:

- PDF text highlights and region highlights stored in `Annotation.geometry`.
- Page-aware highlight rendering in the Reader.
- Annotation editing, color meanings, and note templates.
- Project/resource assignment for annotations.
- Search and filter by annotation kind, color, page, project, or review status.

Why it fits: It completes an already-started reader workflow rather than inventing a separate note-taking system.

### Source Quality And Trust Panel

Medusa could show a compact trust panel for each document.

What it would add:

- Citation verification status, DOI/source-link evidence, metadata confidence, OCR/extraction quality, missing pages/text warnings, figure/table extraction status, and user corrections.
- A short list of recommended fixes: refresh citation, run OCR, inspect metadata conflict, add domain, verify source link.
- A single "bring this document up to current standards" action that queues scoped Concordance work.

Why it fits: It gives the user a fast sense of whether a source is research-ready.

## Acquisition And Library Growth Extensions

### Acquisition Wishlist

Stashes already save useful DOIs. A broader acquisition wishlist would track sources the user wants but does not yet have.

What it would add:

- Items from recommendations, DOI searches, manual entry, citations inside imported papers, and Recon gap findings.
- States such as wanted, open PDF found, requested, imported, duplicate, unavailable, rejected.
- Attach a target project/domain before the PDF arrives.
- Batch "check availability again" background work.

Why it fits: It extends Stashes into a durable research acquisition workflow.

### Reference Harvesting

Imported papers often contain reference lists. Medusa could harvest candidate sources from references.

What it would add:

- Parse references into candidate citation records.
- Match candidates to existing library documents by DOI/title.
- Suggest missing sources for acquisition wishlist or recommendations.
- Preserve extracted reference evidence and confidence.

Why it fits: This supports DOI-first citation work, recommendation discovery, and thesis bibliography expansion.

### Import Intake Review

The current staged import queue is good for cost and duplicate control. Intake Review would add pre-processing organization and risk checks.

What it would add:

- Batch-level source label, project, domain, priority, and expected purpose.
- Preflight duplicate, large-file, scanned-page-likely, missing-title, and high-cost warnings.
- "Process cheap local stages first" option before cloud enrichment.
- Batch templates for thesis chapters or course/research contexts.

Why it fits: It makes large uploads calmer and easier to dogfood.

## Maintenance And Governance Extensions

### Corpus Health Dashboard

A Corpus Health dashboard would show library quality without becoming a generic admin screen.

What it would add:

- Documents missing DOI, source link, authors, year, pages, summary, tags, domain, project, OCR, figures, embeddings, or verified citation.
- Documents with stale capability versions.
- Failed or partially completed jobs grouped by failure reason.
- Tag/domain/project hygiene indicators.
- One-click scoped Concordance or review filters from each issue.

Why it fits: It turns hidden maintenance debt into navigable research work.

### Model And Provider Bench Lab

Medusa already routes tasks by model and records cost. A bench lab would compare provider/model choices on representative documents before changing defaults.

What it would add:

- Side-by-side runs for metadata, summary, tag suggestions, APA fallback, OCR, embeddings, and Recon answers.
- Quality notes, latency, failure modes, token usage, and estimated cost.
- Saved benchmark sets from real library documents.
- A clear path from benchmark result to Settings default change.

Why it fits: It keeps model changes empirical, not vibes-based.

### Backup And Portability Drills

Full backup/restore exists. The natural extension is scheduled and verified operational confidence.

What it would add:

- Scheduled backups with retention policy.
- Dry restore drills that validate the latest backup without replacing the live database.
- GCS/local object manifest validation.
- Portability readiness report before moving machines.

Why it fits: Medusa is local-first and intended to become a durable thesis asset. Recovery confidence matters.

## Writing Workflow Extensions

### Project Export Pack

Projects already generate bibliographies. A Project Export Pack would gather the research context for writing.

What it would add:

- Bibliography files in APA/BibTeX/RIS/CSL JSON.
- Linked notes export by section or topic.
- Literature Matrix export.
- Source list with read status, priority, used state, domains, tags, notes, and citation verification state.
- Optional Markdown bundle for a thesis chapter folder.

Why it fits: It helps carry Medusa's structured research into the writing environment without trying to replace the writing tool.

### Claim-To-Citation Assistant

This would help match a draft claim or paragraph to evidence already in the library.

What it would add:

- Paste a claim or paragraph.
- Search the project/library for supporting, contradicting, or contextual evidence.
- Return source candidates with page/chunk links and citation text.
- Let the user save the result as a linked note or project note.

Why it fits: It is a practical thesis-writing companion built on search, citations, and evidence, not a generic writing generator.

### Chapter Workspace

A lightweight Chapter workspace could sit inside Projects without becoming a full editor.

What it would add:

- Chapter/section outline.
- Linked sources, evidence items, claims, notes, and reminders per section.
- Coverage status: no evidence, weak evidence, enough evidence, needs citation check.
- Exportable outline with linked references.

Why it fits: It lets Projects become thesis-aware while preserving Medusa's role as research cockpit.

## Suggested Sequencing

### Near Term

Start with features that make the existing app easier to trust and dogfood:

1. Activity and Work Ledger.
2. Performance Observatory.
3. UI Consistency Kit.
4. Library Related Documents Discovery.
5. Corpus Health Dashboard.
6. Research Notes for documents, topics, and ideas.

### Mid Term

Then build features that deepen thesis workflows:

1. Literature Matrix.
2. Figure and Table Gallery.
3. Annotation Layer Upgrade.
4. Acquisition Wishlist.
5. Recon integration with Projects and evidence.

### Later

Save broader synthesis and writing-adjacent features for after search, evidence, and background work are stronger:

1. Concept Map.
2. Research Gap Finder.
3. Citation Graph and Source Lineage.
4. Argument Map.
5. Claim-To-Citation Assistant.
6. Chapter Workspace.

## Open Questions

- Should Activity replace Queue, or should Queue remain import/review-focused while Activity becomes a separate workspace?
- Should Corpus Health live in Settings, Library, or its own workbench?
- Should Research Notes be project-only at first, or available across the whole library?
- Should Related replace its current simple Hide Existing behavior with a default exclusion model plus an Already Known audit tab?
- Which Related discovery mode should be the default: Closest, Newer, Foundational, Open PDF, or Diverse Set?
- Should Recon findings be allowed to write notes automatically, or only propose notebook items for approval?
- Should performance instrumentation be visible to the user by default, or tucked behind a compact diagnostics mode?
- Which thesis workflow matters most first: reading plan, evidence capture, matrix synthesis, argument mapping, or writing export?
