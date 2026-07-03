# Codex Document Map

Last updated: 2026-06-30

This is the routing map for future Codex work in Medusa. The README is intentionally a product showcase; do not put architecture notes, technical plans, operating commands, setup guides, or backlog details there.

## Start Here

- `AGENTS.md`: repo-specific Codex rules. Read this first when present.
- `README.md`: concise product introduction, Cool Features showcase, and non-technical facts for humans encountering Medusa.
- `docs/QUICK_START.md`: exact short local setup path, first run, LLM keys, and current storage-backend credential setup.
- `docs/ARCHITECTURE.md`: living product, UX, backend, persistence, processing, storage, safety, and operational architecture record. Update this when implementation changes materially affect app behavior or system design.
- `TODO.md`: planned-work ledger for unfinished work, acceptance criteria, partial-completion notes, and explicitly deferred implementation.
- `docs/LOCAL_OPERATIONS.md`: local setup, credentials, runtime commands, development commands, tests, backup/restore, metrics, local workers, cloud worker pools, Slipstream, and safety operations.
- `docs/OBSERVABILITY.md`: Prometheus metric catalog, Grafana dashboard contract, current scrape-state notes, and observability validation checks.

## README Cleanup Map

The README was intentionally narrowed to product orientation. Keep using this routing when future changes need to add or move information:

| Former README material | Current home | Notes |
| --- | --- | --- |
| Product one-liner, core value, Cool Features showcase, and non-technical workflow facts | `README.md` | Keep this concise, human-facing, and showcase-oriented. |
| First-run local setup and minimal credential path | `docs/QUICK_START.md` | Keep this exact, runnable, and short; move broader operations to `docs/LOCAL_OPERATIONS.md`. |
| README logo/showcase image | `docs/assets/medusa-emblem-blue.png` | Blue transparent variant derived from the real app emblem for GitHub light/dark readability. |
| README screenshots | `docs/assets/screenshots/*.png` | Optimized public showcase screenshots used only by `README.md`; keep captions in README and avoid adding operating notes around the images. |
| Long implemented-feature inventory | `docs/ARCHITECTURE.md` | The architecture record owns current feature contracts and behavior details. |
| Docker Compose startup, TLS certificate setup, login defaults | `docs/QUICK_START.md` and `docs/LOCAL_OPERATIONS.md` | Quick Start owns the shortest happy path; Local Operations owns the full runbook. |
| HAProxy, Valkey, metrics, cache hydration, operational env vars | `docs/LOCAL_OPERATIONS.md` and `docs/OBSERVABILITY.md` | Local Operations owns setup/runbook commands; Observability owns the metric catalog and Grafana dashboard. Server-specific variants belong in `docs/PORTABLE_DEPLOYMENT.md`. |
| GCS, OpenAI, Gemini, recommendation, DOI, and credential settings | `docs/LOCAL_OPERATIONS.md` | Exact env-var examples live here; routing strategy and model choices belong in `docs/AI_COST_ROUTING.md`. |
| GCS asset CDN setup, signed URL env, and live CDN spot checks | `docs/LOCAL_OPERATIONS.md`, `docs/ARCHITECTURE.md`, and `TODO.md` | Local Operations owns setup and verification; Architecture owns the authenticated-gate-plus-CDN design; TODO owns unfinished page-preview and certificate-renewal gaps. |
| Detailed AI behavior, citation/tag/summary defaults, provider-routing rationale, and cost strategy | `docs/ARCHITECTURE.md` and `docs/AI_COST_ROUTING.md` | Use architecture for current behavior contracts and cost-routing for model strategy. |
| Slipstream local/remote runner commands and worker recovery settings | `docs/LOCAL_OPERATIONS.md` | Architecture-level Slipstream contracts remain in `docs/ARCHITECTURE.md`; unfinished Slipstream work stays in `TODO.md`. |
| Cloud container worker pools, Cloud Run defaults, IAM, cost model, and command snippets | `docs/CLOUD_RUN_WORKER_POOL.md` | Runtime command snippets are also summarized in `docs/LOCAL_OPERATIONS.md`; current architecture contracts still belong in `docs/ARCHITECTURE.md`. |
| Backend/frontend/worker development commands and verification commands | `docs/LOCAL_OPERATIONS.md` | Keep test commands current with project practice. |
| Backup, restore, metadata export restore, portability reminders | `docs/LOCAL_OPERATIONS.md` | Host move and release-agent details belong in `docs/PORTABLE_DEPLOYMENT.md`. |
| Dependency maintenance policy and Renovate behavior | `docs/DEPENDENCY_UPDATE_PLAN.md` | Keep routine update plans out of README. |
| Safety model for staged imports, queue visibility, leases, maintenance, release requests | `docs/LOCAL_OPERATIONS.md` and `docs/ARCHITECTURE.md` | Operations guide explains what to do; architecture explains durable design constraints. |
| Future plans, partial work, acceptance criteria, and planned enhancements | `TODO.md` or a feature-specific docs file | Do not place plans in README. |

## Product And Design Records

- `docs/ARCHITECTURE.md`: canonical current-state design and architecture.
- `docs/NATURAL_EXTENSIONS.md`: speculative product extension ideas before they become committed roadmap or implementation work.
- `docs/PERFORMANCE_ROADMAP.md`: performance and scaling notes.
- `docs/RECON.md`: Recon workspace planning, scope, and future implementation notes.
- `docs/PORTFOLIO.md`: Portfolio module contract and current behavior.
- `docs/PORTFOLIO_ROADMAP.md`: Portfolio-specific sequencing and acceptance notes.

## Processing And Intelligence

- `docs/AI_COST_ROUTING.md`: model/provider routing, cost-control strategy, implemented defaults, and candidate routes.
- `docs/CLOUD_RUN_WORKER_POOL.md`: default-disabled Cloud Run worker-pool implementation note, IAM boundary, cost model, runtime entrypoint, and limitations.
- `docs/LOCAL_OPERATIONS.md`: Cloud Run command snippets and Slipstream runner operations.
- `docs/SECOND_PASS_DOCUMENT_PROCESSING.md`: second-pass extraction and cleanup design.
- `docs/TAG_GOVERNANCE.md`: tag suggestion, scoring, governance, merge, relationship, pruning, and Optimize behavior.

## Operations

- `docs/LOCAL_OPERATIONS.md`: day-to-day local run and development operations.
- `docs/PORTABLE_DEPLOYMENT.md`: moving Medusa between hosts, server-specific Compose overlays, certbot, release-agent, systemd, and portability checks.
- `docs/OBSERVABILITY.md`: Prometheus metric catalog, Grafana dashboard JSON ownership, scrape-health notes, and dashboard validation checks.
- `docs/DEPENDENCY_UPDATE_PLAN.md`: Renovate and dependency maintenance policy.

## Where New Notes Belong

- Put product scope, navigation, workflow, UX contract, service boundary, API, persistence, job, storage, auth, security, backup, or runtime decisions in `docs/ARCHITECTURE.md`.
- Put unfinished work, acceptance criteria, partial completion, or explicitly deferred items in `TODO.md`.
- Put broad future ideas in `docs/NATURAL_EXTENSIONS.md` until they graduate into the architecture record or TODO ledger.
- Put feature-specific roadmaps in a named feature document when the scope is too large for one TODO item.
- Put local commands, environment variables, startup/shutdown, credential placement, backup/restore drills, and developer commands in `docs/LOCAL_OPERATIONS.md`.
- Put GCS asset-CDN setup and live verification notes in `docs/LOCAL_OPERATIONS.md`; put the durable signed-URL design contract in `docs/ARCHITECTURE.md`; keep unfinished persisted page-preview assets and certificate-renewal work in `TODO.md`.
- Put Prometheus metric semantics, Grafana dashboard design, and observability validation checks in `docs/OBSERVABILITY.md`.
- Put server move, host-agent, certbot, and systemd details in `docs/PORTABLE_DEPLOYMENT.md`.
- Put cost/model/provider strategy in `docs/AI_COST_ROUTING.md`.
- Keep `README.md` focused on what Medusa is, what it helps with, and which features are worth showing off.
