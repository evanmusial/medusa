# Tag Governance Notes

Last updated: 2026-06-20

These notes preserve the tagging instructions and design decisions from the keyword-reduction discussion. The goal is to reduce noisy tag growth without blocking genuinely new and valuable concepts.

## Import-Time Tag Scoring

Medusa should treat AI topic/keyword output as candidate evidence, not as an automatic list of final taxonomy changes.

Adopt these methods for import and Concordance tagging:

- Embedding similarity: compare proposed tag concepts against existing tag concepts when embeddings are available, falling back to lexical similarity when credentials or cached embeddings are unavailable.
- Hybrid and LLM scoring: combine deterministic string overlap, phrase occurrence, model confidence, existing alias memory, optional embedding similarity, and model-provided tag candidates.
- Library-aware scoring: prefer tags already used in the library when they truly fit, account for tag status, document counts, aliases, definitions, and prior relationships, and avoid retired or blocked tags.
- Cluster-aware scoring: consider near-duplicate groups, broader/narrower terms, repeated prefixes, singular/plural variants, and candidate clusters before creating yet another label.
- Existing first, not existing only: reuse an existing canonical tag when it is equivalent, synonymous, or a fair broader concept; create a new tag when the concept is missing or the existing tag would be misleading.
- Score tags on three axes:
  - Document relevance: how strongly this concept is supported by the imported document.
  - Library fit: how well the concept maps to the existing Medusa taxonomy.
  - Novelty value: whether the concept adds useful information not already covered.
- Semantic covered-by checks: before creating a new tag, ask whether an existing tag semantically covers the candidate well enough for retrieval. Covered-by should reuse or relate to the existing tag without pretending the candidate is meaningless.

Import should attach only the strongest scored candidates by default. The current import gate is deliberately conservative: no more than five scored tags may attach to one imported document, no more than one of those may be a brand-new tag, and every new tag starts as `candidate`. Low-value form/generic labels such as document-type words or broad method words are recorded as skipped rather than attached. Before creating a new tag, Medusa searches existing active tags with alias memory, lexical similarity, optional embedding similarity, approved relationships, and near-match thresholds; near-existing candidates are reused when confidence is high or recorded as not attached when the fit is too ambiguous. Per-document scores and skip reasons are recorded so later Optimize reviews can compare estimated value to actual library value.

## Management Workflow

Tag management should remain user-in-the-loop. Optimize is the right home for semantics, relationships, merging, pruning, and candidate governance because it already presents a review plan and waits for approval.

Extend Optimize beyond merge suggestions:

- Tag statuses: `canonical`, `candidate`, `retired`, and `blocked`. Alias behavior remains handled by `TagAlias`, not by keeping duplicate visible tags alive.
- Tag definitions: scope notes, use guidance, avoid guidance, and representative evidence help future import scoring decide what an existing tag means.
- Relationship suggestions: covered-by, broader/narrower, sibling/related, and cluster-review relationships can be approved without forcing a merge.
- Assignment pruning: weak document-tag links should be reviewable and removable from individual documents with `DocumentVersion` history. This fixes the "everything is miscellaneous" problem when the tag itself is valid but over-applied.
- Orphan cleanup: true zero-link tags should not linger as retired clutter. Optimize should first try to alias-merge an orphan into a useful used tag with strong variant, broader-prefix, or semantic evidence; if no strong target exists, it should offer guarded prune-entirely approval that deletes only tags with no document links.
- Candidate promotion: repeated, high-scoring candidate tags can be promoted to canonical; low-value candidates can be retired or blocked.
- Legacy singleton review: older imports may have created many canonical one-document tags before governance scoring existed. Optimize should treat singleton canonical tags without score evidence as review candidates, suggesting downgrade to `candidate`, retirement for low-value or near-duplicate labels, and document-tag assignment pruning where the tag adds little retrieval value.
- Cleanup plans, not instant mutation: Optimize should propose actions, explain rationale/confidence, and keep the user in the approval loop. When the user applies the whole current plan through Approve All, the pane should keep visible top-level progress feedback because bulk merge/orphan-prune/status/relationship/assignment-prune application can take noticeable time.

Merge reduces vocabulary size. Pruning fixes bad assignments. Relationships teach the taxonomy without erasing useful specificity.
