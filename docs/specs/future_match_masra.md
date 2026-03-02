# Seedpipe vs Mastra Workflow Features (Current + Future Crosswalk)

_Last updated: 2026-03-02_
_Status: Analysis draft for roadmap/spec triage_

## Purpose
This document compares the Mastra workflow feature set (from `/Users/geoffreyducharme/Downloads/deep-research-report.md`) against:
- Seedpipe **current implemented state** (`docs/specs/current_system_spec.md`, `README.md`)
- Seedpipe **future specs** (`docs/specs/future_system_spec.md`, `docs/phase3_agent_control_plane.md` remaining scope)

## 1) Feature-by-Feature Comparison vs Current Seedpipe

Legend:
- `Implemented`: present now
- `Partial`: present with narrower semantics
- `Missing`: not currently implemented
- `Intentional non-goal`: deliberately outside Seedpipe model

| Mastra feature | Seedpipe current status | Notes |
| --- | --- | --- |
| Workflow/step schema-first definitions | `Partial` | Seedpipe has schema-first pipeline/stage contracts, but as compile-time YAML + generated runtime wrappers, not runtime Step/Workflow objects. |
| Sequential composition (`then`) | `Implemented` | Ordered stage list in pipeline spec gives deterministic sequential execution. |
| Mapping/adapters between steps (`map`) | `Partial` | Template expansion + family/pattern + foreach interpolation exist, but no arbitrary inline data-transform composition primitive. |
| Parallel composition (`parallel`) | `Missing` | No native concurrent stage graph execution; model is deterministic ordered stages/per-item loops. |
| Conditional branching (`branch`) | `Missing` | No first-class runtime branch primitive. Existing loop reroute (`reentry`/`go_to`) handles retry-like routing only. |
| Array foreach primitive with per-loop concurrency | `Partial` | `per_item` mode exists; stage-level `foreach` expands artifact dimensions; no explicit concurrency control API equivalent to Mastra foreach runtime option. |
| Loop primitives (`dowhile`, `dountil`) | `Partial` | Seedpipe has bounded reroute loops via `pipeline_type=looping` + `max_loops`, but not generic condition-evaluated loop operators. |
| Workflow sleep/sleepUntil | `Missing` | No native sleep primitives in runtime control flow. |
| Shared workflow state object persisted across run | `Partial` | Run manifest + artifacts persist state, but there is no typed mutable in-memory workflow state API exposed to stages. |
| Durable suspend/resume API (`suspend`/`resume`) | `Partial` | Implemented for `human_required` stage via waiting marker + manifest + resume proof, but not generic step-level suspend API for arbitrary stage logic. |
| Time travel to re-execute from arbitrary step | `Missing` | Resume-from-failure exists; no arbitrary historical replay-from-step semantics with snapshot selection. |
| Streaming events during execution | `Missing` | No `run.stream()` equivalent or event stream protocol. |
| Custom step-authored stream events | `Missing` | No writer/event channel from stage execution. |
| Foreach progress events | `Missing` | No dedicated progress event stream type. |
| Observe/reconnect stream | `Missing` | No streaming surface exists to reconnect to. |
| Restart active runs after disconnect | `Missing` | No runtime service managing active live runs; runs are CLI/process scoped. |
| Cancel API / abort signal | `Missing` (planned) | Cancellation is listed in Phase 3 remaining scope (`CANCELLED` file convention), not implemented currently. |
| Retry configuration (workflow + step) | `Partial` | Retry-like behavior exists via rerun/resume and loop reroute for failed cohorts; no declarative retry policy object (`attempts`, `delay`) on stages/workflow. |
| Early successful bailout primitive (`bail`) | `Missing` | No explicit built-in control primitive for terminal success short-circuit from stage API. |
| Lifecycle callbacks (`onFinish`, `onError`) | `Missing` | No callback hook API around run lifecycle in current CLI/runtime contract. |
| Rich run status taxonomy (`success`, `failed`, `suspended`, `tripwire`, `paused`, etc.) | `Partial` | Manifest includes stage/run progress with waiting states; no full discriminated status union with tripwire/paused semantics. |
| Request context schemas/validation | `Missing` | No first-class request-context schema channel equivalent to Mastra requestContext. |
| Human-in-the-loop | `Implemented` | `mode=human_required` compile/runtime orchestration is implemented and spec’d. |
| Snapshot persistence backend abstraction | `Partial` | Filesystem manifest/artifacts act as persistence; no pluggable storage backend abstraction for snapshots. |
| Built-in REST workflow API | `Missing` | No `/api/workflows/*` server in Seedpipe core. |
| OpenAPI/Swagger exposure | `Missing` | No built-in API docs surface. |
| Studio UI workflow graph + step traces | `Missing` | No equivalent visual workflow studio in current repository. |
| Cloud deployment as managed workflow endpoints | `Intentional non-goal` (currently) | Seedpipe positions itself as filesystem-first substrate, not managed cloud workflow platform. |
| Auth providers + route auth policy | `Missing` | No built-in HTTP route/auth framework for workflows. |
| External workflow runner integration (e.g., Inngest) | `Missing` | No dedicated runner integration abstraction beyond local/docker watcher execution. |
| OTEL-native workflow tracing/exporters | `Missing` | No documented OTEL trace export pipeline currently. |
| Function metrics + governance eligibility | `Implemented` | FR-006..FR-010 metrics/governance contracts and runtime utilities are implemented. |

## 2) Feature-by-Feature Comparison vs Seedpipe Future Specs

Future-spec sources used:
- `docs/specs/future_system_spec.md` (FR-001..FR-025)
- `docs/phase3_agent_control_plane.md` remaining target scope

| Mastra feature area | Coverage in Seedpipe future specs | Alignment level | Notes |
| --- | --- | --- | --- |
| Function identity/discovery graph | `FR-001..FR-005` | `Divergent but complementary` | Seedpipe future focus is enterprise function governance/discovery, not orchestration primitives. |
| Metric contracts/governance/comparison | `FR-006..FR-019` | `Complementary` | Strongly aligned to Seedpipe’s replacement-proof objectives, outside Mastra core control-flow scope. |
| Pipeline metadata + metric hooks | `FR-020..FR-025` | `Partial` | Enables richer runtime metadata, but still does not define branch/parallel/time-travel/streaming APIs. |
| Fan-out composable child runs | Phase 3 remaining scope | `Partial alignment` | Could cover part of Mastra’s parallelization needs at run level (child-run fan-out), not in-graph step parallel primitive. |
| Cancellation control plane | Phase 3 remaining scope | `Partial alignment` | Planned via `CANCELLED` artifact convention, not API abort-signal model yet. |
| Observability/resource reporting | Phase 3 remaining scope | `Partial alignment` | Planned resources artifacts; no streaming/event protocol or traces taxonomy specified. |
| Human-in-the-loop suspend/resume | Already delivered | `Aligned` | Seedpipe has explicit human-required wait/resume path now. |
| REST API, OpenAPI, Studio, Cloud | Not in future specs | `Not planned` | No current future-spec commitment. |
| Time travel / replay from arbitrary step | Not in future specs | `Not planned` | Only deterministic resume/rerun semantics currently emphasized. |
| Workflow graph primitives (`parallel`, `branch`, `map`, `sleep`) | Not in future specs | `Not planned` | Current and future docs preserve “not a workflow engine” posture. |

## 3) Missing Features List (Candidate Backlog for `future_match_masra`)

These are Mastra capabilities not present in Seedpipe today; grouped by whether they can fit Seedpipe’s architecture.

### 3.1 High-fit additions (likely compatible with Seedpipe principles)

| Candidate feature | Why it fits Seedpipe | Suggested spec target |
| --- | --- | --- |
| Standardized run status algebra (`running`, `waiting_human`, `failed`, `cancelled`, `completed`) with strict exit-code mapping | Improves agent control loops while staying filesystem-first. | Extend `docs/phase3_agent_control_plane.md` + promote into `docs/specs/current_system_spec.md` when implemented |
| Cancellation primitive (`CANCELLED` marker + manifest transitions + wrapper checks) | Already in remaining Phase 3 scope; high leverage for long runs. | `docs/phase3_agent_control_plane.md` (remaining section 3) |
| Event log taxonomy (append-only NDJSON execution events) | Gives some streaming-like observability without adding server dependency. | New doc: `docs/specs/phase3/execution_events_contract.md` |
| Stage-level retry policy metadata (`max_attempts`, `delay_seconds`) compiled into deterministic behavior | Closes major orchestration gap while preserving deterministic runtime. | New doc: `docs/specs/phase3/retry_policy_contract.md` |
| Child-run fan-out contract with deterministic ID derivation and parent aggregation invariants | Already envisioned in Phase 3 remaining scope. | `docs/phase3_agent_control_plane.md` fan-out section + pipeline schema update spec |
| Request context contract via `run_config` schema + stage access | Could satisfy multi-tenant/context validation need without HTTP server dependency. | New doc: `docs/specs/phase3/request_context_contract.md` |

### 3.2 Medium-fit additions (possible, but needs careful scoping)

| Candidate feature | Risk/tradeoff | Suggested spec target |
| --- | --- | --- |
| Generic suspend/resume API for non-human stages | Risk of drifting toward full workflow engine semantics; needs strict artifact contract. | New doc: `docs/specs/phase3/suspend_resume_generalized.md` |
| Conditional branch primitive in pipeline spec | Adds expressive power but may reduce simple deterministic readability if unconstrained. | New doc: `docs/specs/phase4/branching_primitives.md` |
| Limited parallel stage groups | Requires deterministic aggregation and failure semantics; concurrency may affect reproducibility guarantees. | New doc: `docs/specs/phase4/parallel_groups.md` |
| Time-travel from stage checkpoint | Useful for debugging/recovery but increases state model complexity. | New doc: `docs/specs/phase4/time_travel_semantics.md` |

### 3.3 Low-fit / intentional non-goals (for now)

| Mastra-like feature | Why low fit currently |
| --- | --- |
| Built-in workflow REST server + OpenAPI/Swagger | Seedpipe architecture is CLI/filesystem substrate, not service control-plane by default. |
| Studio visual graph UI | Valuable but not required for deterministic artifact-state-machine operation. |
| Managed cloud platform surface | Outside current repository scope and positioning. |
| Pluggable auth provider framework | Depends on HTTP control plane that Seedpipe does not currently define. |

## 4) Recommended Next Spec Moves

1. Add this file as the Mastra parity reference and treat it as triage input, not commitment.
2. Fold high-fit items into existing Phase 3/4 docs with requirement IDs (`MM-001...`).
3. Keep explicit guardrails in each new spec section: preserve `filesystem truth + compiler-owned runtime + rerun=resume`.
4. Avoid committing to server/UI/cloud features unless product direction intentionally changes from current posture.

## 5) Sources
- `/Users/geoffreyducharme/Downloads/deep-research-report.md`
- `docs/specs/current_system_spec.md`
- `docs/specs/future_system_spec.md`
- `docs/phase3_agent_control_plane.md`
- `README.md`
