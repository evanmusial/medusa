<p align="center">
  <img src="docs/assets/medusa-emblem-blue.png" alt="Medusa logo" width="160">
</p>

# Medusa

Medusa stands for **Metadata-Enhanced Document Understanding, Search, and Analysis**. It is a local-first research library and assistant for turning messy academic PDFs, web documents, drafts, notes, and source lists into a searchable, organized, auditable research cockpit.

Medusa is built for one serious reader who wants their corpus to stay under their control. It preserves original files, extracts text and visual evidence, generates reviewable metadata and citations, tracks cost and provenance, and gives older documents a way to catch up when the system learns a new capability.

## Cool Features

- **Staged imports instead of file chaos.** Drop in a batch, review it, handle duplicates, apply organization defaults, and release it only when it is ready.
- **A Library that stays clean.** Half-finished, failed, paused, or duplicate import records stay out of the real corpus until they become usable research documents.
- **Reader plus repair loop.** Read the original and parsed text side by side, search within a document, edit extracted pages, keep notes, and preserve history as the record improves.
- **Citation work that admits uncertainty.** APA references, in-text citations, DOI evidence, publication metadata, and bibliographies can be refreshed, edited, verified, or sent to review.
- **Concordance Runs.** New extraction and enrichment abilities can be applied to old documents without re-uploading them, so the Library keeps getting better over time.
- **Research organization cockpit.** Domains, Tags, saved searches, priorities, read state, custom attributes, duplicate review, and bulk editing make large collections manageable.
- **Smart tag governance.** Tag suggestions are treated as candidates, checked against the existing taxonomy, and routed through reviewable merge, alias, relationship, and cleanup workflows.
- **Related-paper discovery.** Medusa can turn one document into a set of useful leads, hide papers already in the Library, stash DOI candidates, and queue open PDFs through the normal import path.
- **DOI stashes and acquisition lanes.** Interesting sources can wait in Wishlist, Open PDF, Queued, or In Library states instead of vanishing into browser tabs.
- **Project run sheets.** Projects can collect sources, mark what is used, track priority and status, keep notes, and produce bibliographies.
- **Recon inquiries.** Ask corpus-grounded research questions across a Library scope and keep the answer, evidence, and cost trail with the rest of the work.
- **Portfolio workspace.** Keep user-authored drafts, rubrics, feedback, source materials, assessments, and exportable bundles separate from the Library while still letting Library evidence help.
- **Cost and provenance visibility.** Medusa shows what happened during processing, where model spend went, what failed, and how a document was assembled.
- **Health and Activity surfaces.** Gaps, failures, review queues, backups, imports, and long-running work are visible as first-class work rather than hidden maintenance chores.
- **Local-first posture.** Originals are preserved, the library remains under the user's control, and cloud services are optional where practical.

## The Medusa Workflow

Medusa begins with a staging area, not a blind import button. New sources can be reviewed, labeled, checked for duplicates, and released only when the batch is ready.

Once processing starts, Medusa turns source material into a usable research record: searchable page text, citations, summaries, bibliographies, figures, notes, tags, domains, project links, and review evidence. Work in progress stays out of the Library until it is ready.

The Library is the active corpus. It is built for reading, correction, organization, discovery, and reuse rather than passive file storage.

AI is an enrichment layer, not the only source of truth. Evidence, user corrections, review state, and history stay visible so generated metadata can be trusted, repaired, or rejected.

## Documentation

The main README is intentionally a product showcase. Technical design, operating commands, implementation plans, and future-work notes live under `docs/`.

- [Codex Document Map](docs/CODEX_DOCUMENT_MAP.md) explains which document owns which kind of project knowledge.
- [Local Operations](docs/LOCAL_OPERATIONS.md) covers local setup, runtime commands, credentials, development commands, backup/restore, metrics, and safety behavior.
- [Architecture Record](docs/ARCHITECTURE.md) is the living product and technical design record.
- [TODO](TODO.md) is the planned-work ledger for unfinished work.
