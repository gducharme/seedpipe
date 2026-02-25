# Seedpipe Roadmap Tracking: Phase 3 Agent-Operable Control Plane

This document tracks the intended Phase 3 target as the **minimal agent-operable control plane** that unifies deterministic execution, resumable failure handling, event-driven triggering, fan-out composability, and machine-readable observability.

Core invariant to preserve:

> **filesystem truth + compiler-owned runtime + rerun = resume**

---

## Phase 1 Recap — Deterministic Pipeline Core

### Core Concepts
- Compile-time orchestration.
- Spec-defined linear stages.
- Artifact contracts.
- Strict determinism by default.
- No hidden runtime state.

### Runtime Guarantees
- Stage input validation before execution.
- Stage output validation after execution.
- No forward artifact references.
- `generated/` is compiler-owned.
- `rerun = resume` based on artifact truth.

### Required Artifacts (per run)

```text
artifacts/
  outputs/<run-id>/
    <stage outputs>
```

---

## Phase 2 Recap — Failure + Resume Semantics

### Capabilities
- Whole-run failure handling.
- Per-item granular failure handling.
- Append-only item state log.
- Deterministic resume.
- Structured defect reporting.

### Required Artifacts

```text
artifacts/
  outputs/<run-id>/
    status.json
    run_meta.json
    item_states.ndjson
    defects/
      <stage>/<item>.json
```

### Artifact Definitions

#### `status.json`
Machine-readable run state:

```json
{
  "run_id": "...",
  "pipeline_id": "...",
  "state": "running | failed | completed",
  "current_stage": "...",
  "stages": {},
  "items": { "total": 100, "completed": 87, "failed": 3 },
  "started_at": "...",
  "updated_at": "..."
}
```

#### `run_meta.json`
Provenance and reproducibility:

```json
{
  "pipeline_spec_hash": "...",
  "generated_hash": "...",
  "src_git_commit": "...",
  "run_config_hash": "...",
  "input_bundle_hash": "...",
  "compiler_version": "..."
}
```

#### `item_states.ndjson`
Append-only item transition log:

```json
{ "stage": "transform", "item_id": "42", "status": "completed", "attempt": 1 }
```

#### `defects/<stage>/<item>.json`
Structured failure envelope.

### Phase 2 Extension: Optional Output Schema Validation
Pipeline authors may optionally attach JSON Schema validation to stage outputs.

- Output schema validation is **opt-in** per output artifact.
- If configured, runtime validates produced output against the declared JSON Schema before marking stage completion.
- Validation failures are treated as normal stage failures and should produce structured defects.
- This extends existing output existence checks; it does not replace them.

---

## Phase 3 Target — Agent Substrate + Composable Runtime

Phase 3 is the completion of the agent substrate, not a broad feature grab.

### 1) Event-Driven Triggering

Pipeline auto-starts when a valid input bundle lands.

#### Inbox Convention

```text
inbox/<pipeline_id>/<bundle_id>/
```

#### Claim + Snapshot
- Claim with atomic rename or lockfile.
- Snapshot into immutable run inputs:

```text
artifacts/inputs/<run-id>/
```

#### Trigger Metadata (`run_meta.json`)

```json
{
  "trigger": {
    "type": "filesystem",
    "source_bundle": "...",
    "claimed_at": "..."
  }
}
```

#### Invariants
- Bundle validates before claim.
- Claim is atomic.
- Inputs immutable after claim.

### 2) Fan-Out / Parallelization (Composable Runs)

One upstream artifact can spawn N parameterized child runs.

```text
artifacts/
  outputs/<parent-run>/
    children/
      fr/<child-run>/
      de/<child-run>/
      es/<child-run>/
```

#### Parent Status Tracks Children

```json
"children": {
  "fr": "child-run-1",
  "de": "child-run-2"
}
```

#### Invariants
- Child runs are independent.
- Parent aggregation is deterministic.
- Resume checks child state before spawning.
- Child run IDs are deterministic from input bundle hash + run config + fan-out parameter.

### 3) `run_config.json` as First-Class Input

Required per run:

```text
run_config.json
```

- Included in provenance hash.
- Available to all stages.
- Sole sanctioned runtime mutation surface for per-run behavior.

### 4) Observability + Resource Reporting

Required artifact:

```text
resources.json
```

```json
{
  "wall_time_seconds": 123,
  "cpu_seconds": 95,
  "max_rss_mb": 512
}
```

Optional artifact:

```text
resources.ndjson
```

for time-series snapshots.

#### Invariants
- Reporting does not alter determinism.
- Reporting writes are atomic.
- Reporting survives crashes safely.

### 5) Cancellation + Control Plane

Cancellation signal:

```text
CANCELLED
```

in the run directory.

Wrappers check for cancellation:
- Before stage start.
- Between per-item executions.

#### Invariants
- Cancellation must never mark a stage as completed incorrectly.
- Partial outputs fail validation unless complete.

---

## Agent Control Surface (Phase 3 Minimum)

An agent only needs to:
1. Write inputs.
2. Write `run_config.json`.
3. Execute `seedpipe-run`.
4. Inspect `status.json`, `defects/`, `run_meta.json`, and `manifest.json`.
5. Patch `src/` or `spec/`.
6. Recompile.

No hidden APIs, runtime database, or scheduler abstraction.

---

## Phase 3 Capability Matrix

| Capability      | Primitive            | Artifact-backed | Deterministic |
| --------------- | -------------------- | --------------- | ------------- |
| Resume          | Rerun same run-id    | ✔               | ✔             |
| Per-item retry  | Append-only log      | ✔               | ✔             |
| Trigger on file | Atomic claim         | ✔               | ✔             |
| Fan-out         | Child runs           | ✔               | ✔             |
| Long chains     | File inbox + publish | ✔               | ✔             |
| Observability   | status/resources     | ✔               | ✔             |
| Reproducibility | run_meta hash        | ✔               | ✔             |
| Agent control   | Filesystem mutation  | ✔               | ✔             |

---

## Conceptual Integrity Check

Seedpipe remains:

> Compiler + filesystem + deterministic wrappers.

It does **not** become a distributed scheduler, graph runtime, job queue system, or workflow engine.

It remains:

> A deterministic artifact state machine that agents can operate safely.


---

## Phase 4 (Locked Scope): Agent Leverage Additions

Phase 4 is intentionally narrow. It adds only four primitives with high long-term agent leverage and no change to the core model.

### 1) `manifest.json` as First-Class Artifact

`manifest.json` is formalized as the machine index of run reality.

Minimum contents:
- Declared artifacts for the run.
- Artifact hashes.
- Validation status.
- Producing stage.
- Logical role (`input` | `output` | `intermediate`).

Why:
- O(1) inspection for agents.
- No directory walking for basic introspection.
- Clean determinism and audit surface.

### 2) `stage_attempts.ndjson` (Stage-Level Attempt Envelope)

Add append-only stage-attempt records for both whole-run and per-item stage modes.

```json
{
  "stage": "transform",
  "attempt": 2,
  "started_at": "...",
  "ended_at": "...",
  "result": "failed"
}
```

Why:
- Stage-level performance regression detection.
- Flaky stage detection.
- Better retry strategy intelligence for agents.

### 3) `seedpipe-run` Exit Code Contract

Define a strict, small exit code algebra for agent syscall ergonomics.

| Code | Meaning |
| ---- | ------- |
| 0 | Completed successfully |
| 1 | Deterministic pipeline failure (requires `src/` or `spec/` fix) |
| 2 | Transient environment/system failure |
| 3 | Cancelled |

Why:
- Fast decisioning without parsing multiple files first.
- Stable control-loop behavior across agent implementations.

### 4) Canonical Publish Convention for Long Chains

Define a standard filesystem handoff convention for downstream triggers.

```text
outbox/<downstream-pipeline>/<bundle-id>/
```

(Equivalent `publish/` naming can be supported if desired, but one canonical convention should be documented and preferred.)

Why:
- Prevents divergent handoff conventions.
- Makes cross-pipeline composition predictable.
- Preserves filesystem-native control-plane semantics.

### Phase 4 Non-Goals

Do not add:
- Message bus.
- Internal queue.
- Runtime database.
- Scheduler layer.
- Worker orchestration subsystem.

These remain explicitly out of scope to preserve the Seedpipe invariant:

> Filesystem truth is the control plane.

---

## Primitive Additions (Not a New Phase)

These additions are not new features and not a new phase. They are filesystem-native primitive patterns that strengthen agent operability across real-world lifecycle loops while preserving the core invariant:

> **filesystem truth + compiler-owned runtime + rerun = resume**

### 1) Promotable / Portable Artifact Identity

This formalizes a named, portable promotion unit via `manifest.json`, so agents do not infer deployable or certifiable outputs by directory scanning.

Pattern (manifest-indexed identity):
- Stable `artifact_id`.
- Content hash.
- Producing stage.
- Provenance (`run_id`, source commit, config hash).
- Logical role (for example `release_candidate`, `certified_dataset`, `invoice`).

This enables deterministic promotion across environments, rollback by reference, and dataset/model/release certification without introducing new runtime behavior.

### 2) Generic Run Lineage (Beyond Fan-Out Parent/Child)

Fan-out captures structural parent→child execution; iterative loops also need explicit lineage semantics.

Examples:
- campaign wave → optimization → next wave
- experiment generations
- retraining cycles

Minimal addition to `run_meta.json`:

```json
"lineage": {
  "parent_run_id": "...",
  "reason": "optimization | retry | backfill | supersedes"
}
```

This preserves deterministic history, graph reconstruction, and agent reasoning across generations.

### 3) Stable Environment State Artifact

Certain workflows need a deterministic answer to “what is currently live/certified/in production.”

Pattern:

```text
state/<domain>/current.json
```

This artifact is written by normal stages using atomic replace semantics.

It enables promotion by reference, deterministic rollback, and environment introspection by agents without introducing a database.

### 4) Formal `NOT_READY` Stage Result

Long-running workflows can be input-valid while still blocked on deterministic external conditions (time window, approval artifact, or expected event arrival).

A stage should be able to return `NOT_READY` as a non-failing, non-mutating, deterministic state:
- inputs are valid
- readiness condition is not yet satisfied
- rerun semantics remain clean

### 5) Idempotent Side-Effect Envelope (Intent → Effect)

For external side effects (payments, PO creation, deploys, containment), standardize:
1. Write `intent.json` (deterministic action input).
2. Perform side effect.
3. Write `effect.json` (remote identifier + confirmation).

Resume rule:
- If `effect.json` exists, do not repeat the side effect.

This provides exactly-once behavior through artifact truth, not coordinators.

## Why These Are Primitives (Not Features)

These additions do not add a scheduler, database, queue, or control-plane branching subsystem.

They only:
- make state explicit,
- remove agent heuristics, and
- standardize patterns already needed in real workflows.

Seedpipe remains:

> A deterministic artifact state machine that agents operate by mutating the filesystem.

## Outcome

With these primitive patterns, the same substrate can support CI/CD promotion and rollback, financial lifecycle auditability, campaign optimization generations, ELT certification and backfills, and incident containment with safe replay—without extending the control plane model.
