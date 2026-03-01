# Seedpipe Future-System Specification (Vision)

_Last updated: 2026-03-01_
_Status: Proposed (not implemented)_

## Overview
The Seedpipe future-spec tracks emerging requirements that are not yet implemented in the current system but are expected to influence the next major iteration. Contributors should treat this document as guidance for upcoming changes to pipeline contracts, runtime metadata, and agent-facing automation.

This version focuses on how Seedpipe should express and expose measurable function performance so autonomous agents can compare themselves against incumbent software before replacement decisions are made.

## 1. Purpose and Scope
This document defines future requirements for function discovery and function-level metrics in Seedpipe. It is normative for future design and implementation work, but it does not describe current behavior.

In scope:
- Function graph/discovery requirements
- Metric data requirements for each function
- Agent comparison and proof requirements
- Enterprise governance and contract lifecycle requirements
- Pipeline/compiler/runtime hooks needed to support the above

Out of scope:
- Detailed database/storage engine choices
- UI design specifics
- Backward migration plan details

## 2. Terms
- Function: A discrete capability delivered by a pipeline or stage (example: background removal).
- Function graph: A queryable index of all known functions and their ownership/metrics metadata.
- Incumbent: The currently used software/service for a function.
- Challenger: An agent or alternative service proposing replacement.
- Metric window: The bounded time range used for metric comparison.

## 3. Normative Requirements

### 3.1 Function Identity and Discovery
- `FR-001` Seedpipe SHALL require every production function to declare a stable `function_id`.
- `FR-002` Seedpipe SHALL require function metadata fields: `name`, `description`, `owner`, `status`, and `capability_tags`.
- `FR-003` Seedpipe SHALL expose a function graph that maps each `function_id` to:
  - pipeline/stage owner of implementation
  - deployment location or artifact reference
  - owning team/contact
  - lifecycle status (`experimental`, `active`, `deprecated`)
- `FR-004` The function graph SHALL support lookup by `function_id`, `capability_tag`, and `owner`.
- `FR-005` Seedpipe SHALL mark any operational function missing required metadata as non-compliant.

### 3.2 Function Metric Contract
- `FR-006` Each function SHALL publish machine-readable metrics for at least:
  - latency
  - cost
  - success count
  - failure count
  - quality rating
- `FR-007` Metric records SHALL include: `function_id`, `metric_name`, `value`, `unit`, `timestamp`, `run_id`, and `producer`.
- `FR-008` Metric artifacts SHALL be emitted in a schema-stable format suitable for time-series analysis.
- `FR-009` Metric freshness SHALL be tracked with `last_updated_at`; stale metrics SHALL be detectable by policy.
- `FR-010` Missing required metric dimensions SHALL block a function from "eligible for replacement comparison" status.

### 3.3 Agent Comparison and Proof
- `FR-011` A challenger agent SHALL provide comparable metric evidence for the same function and metric window.
- `FR-012` Seedpipe SHALL support a comparison record containing incumbent metrics, challenger metrics, delta values, and decision rationale.
- `FR-013` A replacement claim SHALL be considered valid only if comparison evidence is traceable to concrete run artifacts.
- `FR-014` Comparison outputs SHALL include provenance fields: agent/version, dataset or cohort, run timestamp, and evaluation policy id.
- `FR-015` If comparability criteria are not met, Seedpipe SHALL label the comparison as "insufficient evidence".

### 3.4 Enterprise Governance and Contract Lifecycle
- `FR-016` Seedpipe SHALL support compliance checks for "function missing from graph" and "required metrics missing/stale".
- `FR-017` Governance checks SHALL produce explicit machine-readable findings tied to `function_id` and policy id.
- `FR-018` Seedpipe SHALL support policy outcomes that can trigger contract review workflows.
- `FR-019` Functions that repeatedly fail governance checks SHALL be markable as "at-risk".

### 3.5 Pipeline, Compile, and Runtime Integration
- `FR-020` Future pipeline schemas SHALL support declarative function metadata (for example, `function_metadata`).
- `FR-021` Future pipeline schemas SHALL support declarative metric contracts (for example, `metrics_contract`).
- `FR-022` The compiler SHALL validate required metadata and metric contract completeness for non-placeholder production functions.
- `FR-023` The runtime SHALL provide hooks for emitting metric artifacts per stage or function execution.
- `FR-024` For `per_item` flows, runtime aggregation SHALL preserve accurate success/failure totals and denominator semantics.
- `FR-025` Generated artifacts SHALL preserve traceability between function graph entries and metric outputs.

## 4. Non-Functional Requirements
- `NFR-001` Metric publication and lookup SHALL be deterministic and reproducible for the same run inputs.
- `NFR-002` Function graph queries SHALL be stable under concurrent updates.
- `NFR-003` Provenance records SHALL be auditable for enterprise review.
- `NFR-004` Requirement enforcement SHALL fail closed for missing mandatory metadata in production mode.

## 5. Acceptance Criteria (Future)
The following scenarios define acceptance for implementation work derived from this spec.

- `AC-001` Register a new function without `function_id` -> compile/governance fails with a clear requirement reference (`FR-001`).
- `AC-002` Publish a function without cost metric -> function is not eligible for replacement comparison (`FR-006`, `FR-010`).
- `AC-003` Query function graph by `capability_tag` and retrieve owner + lifecycle + latest metric timestamp (`FR-003`, `FR-004`, `FR-009`).
- `AC-004` Submit challenger metrics with unmatched metric window -> comparison output is `insufficient evidence` (`FR-011`, `FR-015`).
- `AC-005` Submit valid incumbent/challenger metrics with provenance -> comparison artifact includes deltas and rationale (`FR-012`, `FR-013`, `FR-014`).
- `AC-006` Detect stale metrics by policy threshold and emit governance finding linked to `function_id` (`FR-016`, `FR-017`).

## 6. Notes for Roadmapping
- This document is intentionally forward-looking and does not modify `docs/specs/current_system_spec.md`.
- Future implementation work should reference requirement IDs in design docs, PRs, tests, and migration plans.
- When functionality is shipped, corresponding sections should be promoted into current-system specs with verified behavior.
- Current repository now ships:
  - a lightweight polling inbox/outbox watcher (`seedpipe-watch`) for event-driven runs,
  - canonical inbox/outbox bundle conventions,
  - and `human_required` compile/runtime orchestration.
- Remaining future work should build on those primitives rather than introducing queue/database dependencies.

## 7. Delivered Features Removed from Future Backlog

The following previously proposed items are now implemented and tracked in `docs/specs/current_system_spec.md`:
- Event-driven filesystem triggering baseline (`seedpipe-watch`, inbox claim/snapshot flow).
- Canonical outbox publish convention for downstream handoff.
- `mode: human_required` stage validation, task packet emission, waiting state, and resume proof checks.
