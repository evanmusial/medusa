# AI Cost Routing Plan

Last updated: 2026-06-20

This page captures the current and proposed model/tool routing strategy for reducing cloud LLM spend while preserving rigorous academic quality in Medusa. Implemented defaults are called out in the pipeline table; candidate routes should be validated against a small gold set of representative papers before becoming defaults.

## Goals

- Preserve academic quality for summaries, citations, metadata, search, and page reading.
- Avoid sending full PDFs or page images to cloud LLMs unless the document actually needs visual or high-context reasoning.
- Prefer deterministic evidence and local scholarly parsers for extractive work.
- Use cheap cloud models for low-risk enrichment and premium models only for synthesis, ambiguity, or high-value documents.
- Keep every cloud route observable through durable usage records, including provider, model, task, token counts, file/PDF bytes, status, and errors.

## Current Implemented Defaults

- Raw extraction prefers local Marker, with PyMuPDF as the bundled fallback.
- Page text normalization is local-first and escalates only flagged pages in `auto` mode.
- Metadata and APA fallback matching stay on `gpt-5.5`.
- Summary and Accessory Summary generation default to `gpt-5.4` and are prompted as technical plain-text paragraphs by default, not Markdown outline summaries.
- Tag suggestion extraction defaults to `gpt-5.4-mini`. The legacy internal task key remains `keywords_topics`, but extracted concepts are stored, displayed, searched, exported, and optimized as flat tags. Prompts include a compact manifest of existing canonical/candidate tags and prefer matching existing labels before proposing new concise labels. Model output is candidate evidence; import and Concordance run it through tag-governance scoring with alias memory, deterministic similarity, optional cached embedding similarity, library/relationship context, and three-axis relevance/fit/novelty scoring before attaching tags.
- DOI regex plus Crossref DOI/title/author/year matching runs before GPT APA fallback; Crossref-backed APA can be formatted locally.
- The Budget ledger currently records OpenAI calls and Gemini `generateContent` calls. Anthropic and local model accounting remain backlog work.
- OpenAI text chunk encoding remains the current embedding default; local BGE-M3 is a candidate, not yet the app default.

## Pipeline

| Medusa step | Current/default route | Fallbacks | Escalation path | Cost-control rule |
| --- | --- | --- | --- | --- |
| PDF hashing, duplicate detection, storage | Local checksum and storage adapter only | None | None | No LLM use. |
| Raw text and layout extraction | Marker by default, with model weights cached under `data/model-cache`; PyMuPDF remains the bundled fallback | Docling for an alternate local parser; GROBID for scholarly TEI/full text and references; local Qwen-VL or olmOCR-style OCR for hard pages | Gemini Flash or Claude/GPT PDF analysis only when local extraction fails on important documents | First Marker use may download local weights once per cache. Do not send full PDFs by default just to obtain text. |
| Text normalization | Local cleanup by default after Marker/PyMuPDF extraction | Auto-escalate only low-text or artifact-heavy pages, capped per document and text-only by default | Gemini 2.5 Flash-Lite/Flash, Claude, or GPT only for flagged pages; premium models only for exceptional pages | Never send the full PDF once per page by default. `MEDUSA_OPENAI_PAGE_NORMALIZATION_MODE=always` is the explicit override for all-pages cloud normalization. |
| Metadata and citation identity | GPT-5.5 metadata extraction with PDF context when size-safe | Local DOI regex plus Crossref DOI/title/author/year matching | GPT-5.5 compact APA fallback only when DOI/Crossref cannot verify the citation | Do not ask GPT to create APA when Crossref metadata can format it deterministically. |
| Summary | GPT-5.4 text-only paragraph-style summary | GPT-5.5 only for selected high-value reruns | Gemini/Claude alternatives only after quality evaluation | Avoid attaching the PDF for routine summaries. Default output should be complete-sentence technical paragraphs without bold, italics, bullets, standalone headings, em dashes, or fancy quotes unless explicitly requested. |
| Tag suggestions | GPT-5.4-mini text-only extraction plus local governance scoring | Local tag extraction or Gemini Flash-Lite after eval | Premium model only if organization quality is poor | Organization tags are reviewable, flattened, scored before attachment, and should use the cheap path first. |
| DOI and source verification | Deterministic DOI/title/author/year matching through Crossref, with DOI regex over extracted text | Semantic Scholar, OpenAlex, DOI.org, publisher/static source evidence | GPT-5.5 only to adjudicate ambiguity from a compact evidence packet | Verified status must come from evidence or explicit user acceptance, not model confidence alone. |
| Accessory summaries | Current-document durable prompt summaries defaulting to GPT-5.4 | Gemini Flash or cheap GPT/Claude tier for drafts after provider support exists | GPT-5.5, Claude Sonnet, or Gemini Pro for important summaries | Not part of import; let task importance drive cost. Use the same technical paragraph defaults as canonical document summaries. |
| Text chunk encoding | Current OpenAI embedding model; proposed target is local BGE-M3 after evaluation | Gemini Embedding, Voyage, or OpenAI embeddings if local runtime is impractical | None needed for quality beyond embedding evals | Strong local candidate. Reindex through Concordance when switching embedding models. |
| Figure and caption gists | Local figure extraction and nearby caption parsing | Local Qwen-VL for targeted page/figure understanding | Gemini Flash for visual gists; premium model only for critical figures | Send cropped figure/page regions, not whole PDFs, whenever possible. |
| Retroactive refreshes | Concordance Runs with provider/model recorded per capability version | Batch or Flex-style cloud processing for slow non-urgent refreshes | Premium model only for selected scope or failed cheap/local pass | Large library refreshes should default to async discounted processing. |

## Non-ChatGPT Options

### Gemini 2.5 Flash-Lite

Best fit:

- Tag suggestions.
- Low-risk metadata fallback.
- Cheap flagged-page normalization when local cleanup is poor.

Pros:

- Very low published token pricing compared with premium models.
- Multimodal and document-capable.
- Good candidate for high-volume, low-risk enrichment.
- Batch/Flex-like pricing modes can lower cost further for async work.

Cons:

- Should not be trusted as the final academic summarizer without Medusa-specific evals.
- Lower reasoning quality than premium models on ambiguous citations or nuanced paper interpretation.
- Full-document PDF use can still become expensive if repeated per task or per page.

### Gemini 2.5 Flash

Best fit:

- Harder metadata fallback.
- Flagged page normalization.
- Draft summaries or figure/caption gists.

Pros:

- Still relatively inexpensive.
- Stronger than Flash-Lite while retaining multimodal/document support.
- Large context makes it useful for selected long-section analysis.

Cons:

- More expensive than Flash-Lite, so it should not become the new default for every page.
- Quality for final academic summaries must be benchmarked against GPT-5.5, Claude Sonnet, and human review.

### Gemini 2.5 Pro

Best fit:

- Premium challenger for summaries, accessory summaries, and difficult PDF reasoning.
- Long-context analysis where visual document understanding matters.

Pros:

- Strong multimodal document understanding.
- Good candidate for evaluating whether OpenAI premium calls can be reduced for synthesis.
- Useful when the whole-document context genuinely matters.

Cons:

- Too expensive for routine metadata, tag suggestions, or page cleanup.
- Needs side-by-side evaluation before becoming a trusted final-summary model.

### Claude Haiku

Best fit:

- Cheap-ish extraction and classification.
- Metadata or tag-suggestion fallback when Anthropic provider support is desirable.

Pros:

- Good instruction following for structured extraction.
- Faster and cheaper than Sonnet/Opus-style models.
- Claude PDF support can analyze text, charts, tables, and visual PDF content.

Cons:

- More expensive than Gemini Flash-Lite for routine enrichment.
- Not obviously better than purpose-built local tools for scholarly metadata.
- Should not be the default if the main goal is lowest safe cloud spend.

### Claude Sonnet

Best fit:

- Serious summaries.
- Ambiguous citation reasoning.
- Review notes where prose quality and cautious reasoning matter.

Pros:

- Strong analysis and academic writing quality.
- Good fit as a premium alternative to GPT-5.5.
- PDF support and prompt caching can help repeated analysis.

Cons:

- Too expensive for routine extractive work.
- PDF visual analysis can be token-heavy because pages are processed with text and images.
- Needs provider abstraction, credential handling, and usage accounting before integration.

### Claude Opus or Fable tier

Best fit:

- Evaluation benchmark.
- Rare, high-value "this paper really matters" analysis.

Pros:

- Highest expected reasoning and writing quality from Anthropic.
- Useful for calibrating whether cheaper models are losing important nuance.

Cons:

- Not an economizing path for default imports.
- Should require an explicit user action or high-value Concordance scope.

### GROBID

Best fit:

- Scholarly metadata.
- Author, title, abstract, affiliation, reference, and bibliographic structure extraction.

Pros:

- Purpose-built for scientific and technical publications.
- Local and evidence-friendly.
- Likely better than a general LLM for many header and reference extraction tasks.
- Can produce structured TEI that maps well to provenance and review surfaces.

Cons:

- Not a summarizer.
- Can struggle on scans, unusual layouts, and poor OCR.
- Needs integration, confidence scoring, and field-level conflict handling.

### Docling

Best fit:

- Local PDF/document conversion.
- Reading order, OCR, tables, formulas, and structured downstream text.

Pros:

- Targets the exact "messy PDF to structured text" problem.
- Local and open-source.
- Can reduce the need for cloud page normalization.

Cons:

- Needs benchmarking on Medusa's real academic PDFs.
- A clean-looking conversion can still be semantically wrong if reading order or table structure is off.

### Marker

Best fit:

- PDF to Markdown/JSON/chunks/HTML.
- Tables, forms, equations, inline math, links, references, images, and artifact removal.

Pros:

- Can run on GPU, CPU, or Apple MPS.
- Produces LLM-ready representations and can optionally use local/remote LLMs for accuracy boosts.
- Good candidate for replacing much of page normalization and chunk preparation.

Cons:

- Needs evals for faithfulness, especially tables, equations, and multi-column pages.
- Optional LLM boosting needs tight configuration to avoid hidden cloud cost or hallucinated cleanup.

### Qwen2.5-VL or Qwen3-VL local

Best fit:

- Difficult OCR/layout pages.
- Figure, table, chart, and page-region understanding.
- Local visual document parsing experiments.

Pros:

- Strong document-parsing orientation, including layout-aware formats in the Qwen-VL family.
- Local/private once installed.
- Useful for targeted visual repair without sending full PDFs to a cloud model.

Cons:

- Hardware-heavy, especially for larger models.
- Structured output reliability and hallucination control need careful prompting and validators.
- Slower CPU-only operation may be impractical for large library refreshes.

### BGE-M3

Best fit:

- Local text chunk embeddings.
- Semantic search and hybrid retrieval experiments.

Pros:

- Local, no per-token cloud spend.
- Supports 100+ languages and up to 8192-token inputs.
- Supports dense, sparse, and multi-vector retrieval modes.

Cons:

- Requires local embedding runtime, vector dimension decisions, and Concordance reindexing.
- Search quality must be evaluated against OpenAI/Gemini/Voyage embeddings on Medusa queries.

### Gemini Embedding

Best fit:

- Cheap cloud embedding fallback if local BGE-M3 is not practical.

Pros:

- Low-cost managed embedding route.
- Avoids local model hosting and dependency weight.

Cons:

- Still cloud spend.
- Embedding provider changes require reindexing and compatibility tracking.

### Voyage Embeddings

Best fit:

- High-quality managed retrieval if local embeddings underperform.

Pros:

- Strong reputation for retrieval-specific models.
- Useful challenger for academic semantic search quality.

Cons:

- Adds another provider and credential surface.
- Still cloud spend and another usage/pricing integration.

## Evaluation Before Implementation

Use a small, fixed evaluation set before changing defaults:

- 10 to 20 representative PDFs: born-digital two-column papers, scanned pages, tables, equations, book chapters, front matter before articles, bad metadata, and multi-author papers.
- Metadata score: exact/normalized title, author order, affiliations, email extraction without inference, year, venue, publisher, DOI, abstract.
- Citation score: APA correctness, DOI/source link correctness, verified vs needs-review calibration.
- Normalization score: reading order, hyphenation, line wrapping, headings, captions, table preservation, no summarization, no hallucinated text.
- Keyword score: useful primitives, no verbose compounds, no near-duplicate clutter, stable taxonomy fit.
- Summary score: faithfulness, methodological nuance, caveats, usefulness, and no invented claims.
- Retrieval score: known-item search, semantic query relevance, and false positives.
- Cost score: token count, file/PDF bytes, cache hits, output tokens, failures, retries, and wall-clock time.

## Implementation Notes

- Add provider routing only after the usage ledger can distinguish `provider`, `endpoint`, `model`, `task_key`, and file/PDF context for every non-OpenAI call.
- Keep provider API keys in `.env` and document them in `.env.example`; never commit credentials.
- Store model/provider choices in Settings preferences so Concordance Runs can refresh older documents when defaults change.
- Preserve local/no-credential fallbacks: imports should still complete with local extraction and reviewable metadata when all cloud credentials are absent.
- Treat provider/model changes as capability-version changes for affected Concordance tasks.
- Do not silently overwrite user-corrected metadata. Local or model output should fill missing fields or create reviewable candidates unless the user explicitly asks for replacement.

## Source Pointers

Pricing and capabilities change. Recheck these pages before implementation:

- [OpenAI API pricing](https://developers.openai.com/api/docs/pricing)
- [OpenAI Batch API](https://developers.openai.com/api/docs/guides/batch)
- [OpenAI Flex processing](https://developers.openai.com/api/docs/guides/flex-processing)
- [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Gemini document understanding](https://ai.google.dev/gemini-api/docs/document-processing)
- [Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- [Claude PDF support](https://platform.claude.com/docs/en/build-with-claude/pdf-support)
- [GROBID documentation](https://grobid.readthedocs.io/)
- [Docling](https://www.docling.ai/)
- [Marker](https://github.com/datalab-to/marker)
- [Qwen3-VL](https://github.com/QwenLM/Qwen3-VL)
- [BGE-M3](https://huggingface.co/BAAI/bge-m3)
- [Voyage AI pricing](https://docs.voyageai.com/docs/pricing)
