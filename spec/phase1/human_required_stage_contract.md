# Human-Required Stage Contract

Status: Implemented in current compiler/runtime behavior.

## Purpose
Define deterministic pause/resume behavior for stages that require human intervention while preserving lineage and artifact truth.

## Stage declaration contract
A stage using this flow declares:
- `mode: human_required`
- standard `inputs` and `outputs`
- `instructions` payload:
  - `summary: string`
  - `steps: string[]`
  - `done_when: string[]`
  - optional `troubleshooting: string[]`
  - optional `validation_command: string`

## Runtime flow contract
When the runner reaches `mode: human_required`:
1. Validate stage inputs exist.
2. Emit task packet JSON:
   - `runs/<run_id>/tasks/<stage_id>.task.json`
3. Emit task packet Markdown:
   - `runs/<run_id>/tasks/<stage_id>.md`
4. Emit waiting marker:
   - `runs/<run_id>/WAITING_HUMAN.<stage_id>`
5. Update `.seedpipe_run_manifest.json` stage row:
   - `status: waiting_human`
   - add `waiting_human` object:
     - `task_id`
     - `task_packet_json`
     - `task_packet_md`
     - `marker_path`
     - `expected_outputs`
     - `validation_status`
     - `blocked_at`
6. Exit cleanly in waiting state (exit code `20`).

## Resume contract
On `seedpipe-run --resume <run_id>` (or rerun against the same `run_id`):
1. Detect waiting stage from run manifest.
2. Verify completion proof:
   - all expected outputs exist
   - outputs pass declared schema checks
3. If proof succeeds:
   - clear or retire waiting marker
   - set stage status to `completed`
   - continue with downstream stages
4. If proof fails:
   - keep `status: waiting_human`
   - record validation outcome in `waiting_human.validation_status`
   - exit cleanly in waiting state

## Task packet contract
Task packet JSON is the machine source of truth and includes:
- `stage_id`
- `run_id`
- `purpose` (from `instructions.summary`)
- `required_inputs` (resolved run-relative paths)
- `exact_commands` (rendered from `instructions.steps`)
- `expected_outputs` (resolved run-relative paths)
- `validation_command` (if declared)
- `done_when`
- `troubleshooting` (if declared)

Markdown is a deterministic rendering of the same payload for human operators.

## Determinism and lineage requirements
- For identical run inputs/config, task packet payload is deterministic except explicit timestamps.
- Pause/resume decisions depend only on filesystem truth and manifest state.
- Human sign-off without artifact proof is non-authoritative.
- Manifest updates are auditable and must preserve stage history.

## Failure and edge-case behavior
- Missing required instructions fields: compile-time error.
- Missing outputs on resume: remain waiting.
- Schema-invalid outputs on resume: remain waiting with validation detail.
- Pipelines without `human_required` stages: no behavior change.

## Acceptance scenarios (implemented)
- First entry to manual stage emits task packet + marker and sets waiting state.
- Resume blocks until completion proof passes.
- Resume proceeds deterministically after valid completion proof.
- Downstream stages never execute while waiting marker/state is active.
