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
- **Flexible processing power.** Imports and upgrades can run on the Medusa host, burst through cloud container workers such as GCP Cloud Run or AWS Fargate, or spread to other enrolled machines through Slipstream.
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

Once processing starts, Medusa turns source material into a usable research record. Originals are preserved, files are checked against the existing corpus, pages are extracted or transcribed into searchable reading text, and rough source material is broken into working metadata: title, authors, publication venue, year, DOI, abstract, page count, references, bibliography, figures, captions, keywords, topics, and processing evidence.

Processing does not have to live on one machine. Medusa can process documents locally on the server or computer hosting the container, use cloud container workers such as GCP Cloud Run or AWS Fargate for burst capacity, and enroll other laptops, desktops, servers, or spare machines through Slipstream. These modes can run at the same time, with configurable concurrency, worker capacity, leases, heartbeats, and queue coordination so jobs move quickly without double-processing the same document.

Remote processing is designed around a secure control plane. Slipstream clients use outbound HTTPS, one-time enrollment, signed requests, scoped capabilities, lease expiry, and central result validation. Remote workers do not need direct database access or provider credentials; Medusa keeps secrets, final writes, provenance, and review state under the central app's control.

The document then becomes more than a PDF in a folder. Medusa generates summaries, APA reference-list entries, APA in-text citations, DOI evidence, bibliography candidates, related-paper leads, tag suggestions, domain/project context, and figure records that can be searched, reviewed, corrected, or refreshed later. Work in progress stays out of the Library until it is ready.

Medusa is built around reviewable document intelligence. Scholarly metadata is treated as evidence-backed working data, not magic text: DOI and publication details can be verified, uncertain citation output can go to review, extracted bibliography text can be cleaned into APA form, and user corrections are preserved as history instead of disappearing into the latest generated answer.

The taxonomy layer is designed to reduce organizational drag. Keywords and topics become candidate tags, but Medusa compares them against the existing tag system before attaching them, prefers reuse when a concept is already covered, and routes weak or overlapping suggestions into governance workflows for merge, alias, relationship, downgrade, or pruning decisions.

Figures and visual material are first-class research evidence. Medusa can extract charts, diagrams, photos, screenshots, maps, and other embedded visuals into durable figure records, keep them connected to page context, and let older documents receive newer visual extraction through Concordance Runs.

The Library is the active corpus. It is built for reading, correction, organization, discovery, and reuse rather than passive file storage.

## AI In Medusa

AI is an enrichment layer, not the only source of truth. Medusa uses models to help read difficult documents, extract usable metadata, normalize page text, suggest tags, summarize arguments, clean bibliographies, draft APA citations, find related sources, answer corpus-grounded research questions, and improve older records through Concordance Runs.

Medusa is deliberately LLM agnostic. Model-powered steps are configurable, and any model that fits a supported task can be used when the appropriate API key or provider credential is available. A real production deployment can mix providers, such as the OpenAI API for GPT and Text Extractor workflows alongside Google for Gemini-based generation, review, and document-intelligence tasks.

The app keeps model work accountable. Provider, model, task, cost, evidence, failures, and generated values remain visible so AI output can be compared with deterministic extraction, DOI/Crossref-style evidence, parsed page text, and human corrections. The goal is not to hide complexity behind a chatbot; it is to make a messy research library easier to trust, repair, and extend.

## Documentation

The main README is intentionally a product showcase. Technical design, operating commands, implementation plans, and future-work notes live under `docs/`.

- [Codex Document Map](docs/CODEX_DOCUMENT_MAP.md) explains which document owns which kind of project knowledge.
- [Local Operations](docs/LOCAL_OPERATIONS.md) covers local setup, runtime commands, credentials, development commands, backup/restore, metrics, and safety behavior.
- [Architecture Record](docs/ARCHITECTURE.md) is the living product and technical design record.
- [TODO](TODO.md) is the planned-work ledger for unfinished work.
