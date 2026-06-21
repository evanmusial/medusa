# Recon Planning Notes

Last updated: 2026-06-21

Recon is a proposed Medusa workspace for asking specific research questions against the user's own corpus. It should behave like a small product inside Medusa: inquiries can be created, run, viewed later, edited, and re-processed when the corpus, model choice, or instructions change.

This document is intentionally a planning artifact, not an implementation spec. Revisit it when the library/search/Concordance foundations are more mature.

## Product Shape

Recon belongs in the top navigation between Projects and Tags.

The core object is a Recon inquiry. An inquiry contains a scope, a model choice, free-form question/instructions, run settings, current answer, evidence, and run history. The user should be able to return to an inquiry later, inspect prior runs, modify the question or scope, and run it again.

Supported scopes should mirror Medusa's research organization:

- Whole library.
- One or more domains.
- One project.
- A saved search or saved view.
- Selected documents, if the calling surface supplies them later.

The first screen should be the working Recon surface, not a landing page. It should show an inquiry list, selected-inquiry editor, scope controls, model selector, instructions box, Start Research button, progress/status, answer, and evidence/citation panels.

## Feasibility Summary

Recon is feasible, but the product should not promise that every byte of every selected document is fed into one model prompt.

For the current live library checked on 2026-06-21:

- 219 visible documents.
- 2,752 pages.
- 4,267 embedded text chunks.
- About 13.0 million extracted/search characters.
- Roughly 2.9M to 3.3M tokens of usable text, depending on counting method.

That is too large for a single normal prompt and larger than the documented 1M-token context window of current high-context OpenAI GPT models. The right architecture is scoped retrieval and staged synthesis.

Recon should describe the selected documents as the allowed ground-truth corpus. It should retrieve, rank, and synthesize from that corpus, preserving citations to the exact documents/pages/chunks used. When a deeper run is requested, it should run per-document or per-batch evidence passes before final synthesis.

## Suggested Run Modes

Quick Answer should be the default. It searches the selected corpus, retrieves the strongest chunks, and sends a bounded evidence packet to the selected model. This is appropriate for directional answers, quick comparisons, and most ordinary questions.

Broad Sweep should inspect every scoped document at least lightly. It should ask each document or small document batch whether it contains evidence relevant to the question, persist compact findings, then synthesize across those findings. This is better for "what does the corpus say about..." questions where negative coverage matters.

Exhaustive should be an explicit deep run. It should read each selected document's full extracted text in batches where possible, produce per-document notes, then synthesize. This should require a cost/time preview because it may take much longer and cost materially more.

Avoid making a naive "send all text" mode the default. Splitting the whole corpus into giant long-context prompts is expensive, slow, and less auditable than map/reduce with evidence records.

## Current Cost And Latency Estimate

These estimates use the current live library size above and current documented OpenAI pricing as of 2026-06-21. Actual cost depends on selected model, answer length, cached input eligibility, provider mode, and question complexity.

| Mode | Evidence strategy | Approximate cost per question | Approximate latency |
| --- | --- | ---: | ---: |
| Quick Answer | Retrieve best 40-80 chunks, synthesize once | $0.03-$0.06 on `gpt-5.4-mini`; $0.10-$0.20 on `gpt-5.4`; $0.20-$0.40 on `gpt-5.5` | 10-60 seconds |
| Broad Sweep | Compact pass over every document, then synthesize | About $0.80 on `gpt-5.4-mini`; $2.60 on `gpt-5.4`; $5.25 on `gpt-5.5` | 2-10 minutes |
| Exhaustive | Full-text document/batch map-reduce | About $2.80 on `gpt-5.4-mini`; $9.30 on `gpt-5.4`; $18.60 on `gpt-5.5` | 10-40+ minutes |
| Naive whole-corpus long-context shards | Stuff the corpus into large prompt shards | About $17+ on `gpt-5.4`; $34+ on `gpt-5.5` | 10-30+ minutes, with poor auditability |

The saved Medusa model preference at the time of planning included `gpt-5.2` for summaries/accessory summaries, but the public OpenAI docs checked during planning did not list `gpt-5.2`. If that model remains callable in the local deployment, Medusa's internal pricing table estimated Broad Sweep around $2.08 and Exhaustive around $6.93.

## Grounding And Evidence Contract

Recon answers should be evidence-backed by default.

Each final answer should store:

- The question/instructions.
- The selected scope and resolved document IDs.
- The selected model and provider.
- The run mode.
- The retrieved or analyzed chunks/documents.
- Citations to source documents, pages, chunks, and relevant snippets.
- Negative or low-evidence notes when Broad Sweep or Exhaustive checked a document but found no support.
- Token usage, estimated cost, latency, and failure/retry state.

The UI should distinguish "searched the scoped corpus" from "read every selected document in full." Quick Answer may miss obscure evidence if retrieval misses it; Broad Sweep and Exhaustive should be presented as stronger but slower choices.

## Architecture Sketch

Recon should be its own durable module, not a Concordance capability. Concordance brings documents into agreement with current processing features. Recon creates user-owned research artifacts over a corpus state.

Likely backend entities:

- `ReconInquiry`: title, question/instructions, scope type/data, selected model, default run mode, status, timestamps.
- `ReconRun`: inquiry ID, resolved scope snapshot, model/provider, run mode, status, progress, token/cost totals, started/completed/error fields.
- `ReconEvidence`: run ID, document ID, chunk/page references, rank/score, snippet, extracted finding, relevance judgment, citation metadata.
- `ReconAnswerVersion`: run ID, answer Markdown/text, structured claims if useful, evidence summary, created timestamp.

Recon should use existing Medusa primitives where possible:

- Saved searches, domains, projects, and selected document IDs for scopes.
- `Document`, `DocumentPage`, and `TextChunk` as the grounding source.
- Existing embeddings and lexical search for retrieval.
- `OpenAIUsageRecord` and Budget & Costs for usage tracking.
- The shell-owned async progress pattern for durable run feedback.
- The same Start button convention: soft blue while running, animated icon and slim progress bar, green when done, red on failure.

## Prerequisites And Risks

The current chunk index is promising but needs improvement before Recon becomes a high-trust corpus research surface. At planning time every visible chunk had an embedding, but the import path has historically capped embedding generation per document. Before building Recon, confirm that all relevant chunks are encoded after imports and Concordance refreshes, or add a fuller semantic-search/embedding Concordance capability.

Retrieval quality will drive answer quality. Recon should combine lexical filtering, vector similarity, document metadata, tags/domains/projects, citation metadata, and page proximity instead of relying on one nearest-neighbor query.

Cost preview matters. Starting a whole-library Broad Sweep or Exhaustive run should show document count, approximate input tokens, expected model, rough dollar estimate, and rough time estimate before launch.

Long-running runs need safe stop/start behavior. Recon runs should be database-backed, resumable, idempotent enough to retry failed document passes, and visible in the header active-work control or a Recon-specific progress surface.

Answers should not mutate documents. Recon may create notes or follow-up tasks later, but initial Recon output should be a separate artifact unless the user explicitly promotes something into notes, project resources, tags, or document metadata.

## Open Design Questions

- Should Recon expose Quick, Broad Sweep, and Exhaustive as explicit mode controls, or infer mode from a cost/time selector?
- Should the default model be a dedicated Recon preference, the Accessory Summaries model, or a per-inquiry free selection only?
- Should Recon have a "draft from fast model, verify with premium model" option?
- How should citations appear: inline footnotes, side evidence panel, claim-level expandable evidence, or all three?
- Should project-scoped Recon be able to write findings back into the project run sheet as notes?
- Should completed Recon runs contribute to document or library search, or remain searchable only inside Recon?
- Should stale runs be flagged when scoped documents are edited, deleted, reprocessed, or newly added to the saved scope?

## Deferred Implementation Notes

When the app is ready, start with a narrow implementation:

1. Add the Recon top-level route and quiet cockpit surface.
2. Add durable inquiry/run/evidence tables and migrations.
3. Implement Quick Answer over current embeddings plus lexical fallback.
4. Record usage/cost and show run progress.
5. Add evidence/citation display.
6. Add Broad Sweep after Quick Answer is trustworthy.
7. Add Exhaustive only after cost previews, cancellation, and resume behavior are solid.

This staged path gives Medusa a useful research-question feature early while avoiding the expensive trap of pretending that whole-library full-text prompting is the default answer.
