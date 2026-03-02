# Seedpipe Current-System Specification (As Implemented)

## Scope

This document specifies the **currently implemented** behavior of the repository based on source code, tests, and README content. It intentionally excludes:

- Future roadmap phases.
- Desired but unimplemented architecture.

## 1) Product and Operating Model (README-Specified)

### 1.1 Core product statement
- Seedpipe is presented as a deterministic, filesystem-first pipeline substrate for agent-driven workflows.
- The system emphasizes reproducibility, auditability, and explicit artifact/state management.

### 1.2 Installation and distribution model
- The package is installable from a local path (`pip install /path/to/seedpipe` and editable mode).
- Installed console scripts are documented as:
  - `seedpipe-compile`
  - `seedpipe-scaffold`
  - `seedpipe-run`
  - `seedpipe-watch`
- Module fallbacks are documented:
  - `python -m tools.compile`
  - `python -m tools.scaffold`
  - `python -m tools.run`
  - `python -m tools.watch`

### 1.3 Scaffolded project expectations
README defines the scaffold outcome as including:
- Agent guidance files.
- Phase-1 pipeline spec + schema contracts.
- Inputs/outputs artifact roots.
- Starter stage implementations.

### 1.4 Pipeline contract summary
README defines the expected `pipeline.yaml` model:
- Top-level:
  - `pipeline_id` (required string)
  - `item_unit` (default `item`)
  - `determinism_policy` (`strict` or `best_effort`, default `strict`)
  - `pipeline_type` (`straight` or `looping`, default `straight`)
  - `max_loops` (integer >= 0, default `0`; must be `0` when `pipeline_type=straight`, and >=1 when `pipeline_type=looping`)
  - `stages` ordered array (at least one stage)
- Per-stage (core linear model):
  - `id` (required)
  - `mode` (`whole_run`, `per_item`, or `human_required`, default `whole_run`)
  - `inputs` (default `[]`)
  - `outputs` (default `[]`)
  - `placeholder` (default `false`)
  - `reentry` (optional string; unique loop anchor name, only for `pipeline_type=looping`)
  - `go_to` (optional string; must reference an earlier stage `reentry`, only for `pipeline_type=looping`)
- Optional DSL expansion accepted by compiler normalization:
  - Stage-level `foreach` + `key` expands stage I/O templates across all parameter values while keeping a single concrete stage ID (no stage-module duplication).
  - Object entries in `inputs` with `family` + `pattern` + `schema` for template-based artifact resolution.
- Object entries in `outputs` with required `family` + `pattern` and optional `schema`, keyed by `key` or output-level `foreach` + `key`.
  - `{var}` template interpolation in string `inputs`/`outputs` from stage/output scope.
  - Compiler expansion tracks resolved family selection values as stage/output `keys` metadata (not `bind` fields), and these keys are propagated into generated runtime stage contexts.
- For stage-level `foreach`, compiler now composes one stage with unioned concrete input/output artifact paths and per-output `keys` metadata so runtime invocations remain parameter-aware without generating one Python wrapper per parameter value.
- Rule after expansion: non-placeholder stage inputs must be produced by prior stages (no forward references for executable stages).

### 1.5 Compile and run usage expectations
- Compile consumes pipeline + contracts and emits generated code/metadata.
- Run executes generated flow and fails if:
  - output run directory already exists.
  - input directory is missing.

## 2) Executable and Entrypoint Specification

## 2.1 Declared console entrypoints
`pyproject.toml` declares:
- `seedpipe-compile -> tools.compile:main`
- `seedpipe-scaffold -> tools.scaffold:main`
- `seedpipe-run -> tools.run:main`
- `seedpipe-watch -> tools.watch:main`

## 2.2 `tools.compile` executable behavior

### Inputs
- CLI args:
  - `--pipeline` (default `docs/specs/phase1/pipeline.yaml`)
  - `--contracts-dir` (optional; defaults to `docs/specs/phase1/contracts`)
  - `--output-dir` (default `generated`)
  - `--no-ir` (disables `generated/ir.json`)

### Functional stages
1. Load pipeline (`YAML` via PyYAML if available; JSON fallback).
2. Normalize defaults (`item_unit`, `determinism_policy`, `pipeline_type`, stage defaults).
3. Validate structure and ordering constraints.
4. Build internal IR (pipeline/stage metadata + artifact producer map).
5. Load schema contracts and enforce required contract files.
6. Resolve produced artifact names to contract schema names.
7. Emit generated package files.
8. Emit compile report and metadata.

### Validation rules
Compilation fails when:
- Pipeline file missing or not object-like.
- `pipeline_id` missing/empty.
- Invalid `determinism_policy`.
- Invalid `pipeline_type`.
- Invalid `max_loops` value.
- No stages.
- Duplicate stage IDs.
- Invalid stage mode.
- Non-boolean `placeholder`.
- Non-string `reentry`/`go_to`.
- Non-array inputs/outputs.
- Non-string artifact names.
- Any stage input is unresolved at that point in stage order.
- `pipeline_type=looping` without any stage `reentry`.
- `pipeline_type=looping` with `max_loops < 1`.
- Duplicate `reentry` names.
- `go_to` references unknown `reentry` name.
- `go_to` does not point to an earlier stage.
- `pipeline_type=straight` with any `reentry` or `go_to` stage field.
- `pipeline_type=straight` with non-zero `max_loops`.
- Invalid DSL expansion requests (e.g., unresolved `foreach` paths, missing required object fields, out-of-scope key vars, or missing template variables).
- Compiler/runtime generation path is key-only for stage/output fan-out metadata (`keys`), with no `_bindings` metadata emitted in normalized stages, IR, or generated flow artifacts.
- Contracts directory has no schema files or misses required schemas.
- Resolved artifact schema name is absent from contract set.

### Generated outputs
Compiler emits (at minimum):
- `generated/models.py`
- `generated/flow.py`
- `generated/run_manifest_template.json` (compile-time template for per-run resume manifest seeding)
- `generated/stages/<stage>.py` wrappers
- `generated/stages/__init__.py`
- `generated/compile_report.json`
- `generated/_meta.json`
- optional `generated/ir.json`

Compiler does not create or modify source stage implementation files (`src/stages/*.py`).

### Runtime semantics embedded in generated code
- `whole_run` stages:
  - validate declared inputs before executing user impl.
  - validate declared outputs after execution.
  - validate declared output schemas after execution when `schema` is provided.
  - snapshot declared outputs under `<stage_id>/loops/<NNNN>/` and update manifest artifact index for logical-to-concrete resolution.
- `per_item` stages:
  - iterate deterministic item stream.
  - append item-state transitions (`in_progress`, then `succeeded`/`failed`) with per-item attempt counters.
  - validate declared output schemas after each item execution when `schema` is provided.
  - stage exceptions and runtime validation failures are normalized into error-bearing `ItemResult` failures.
- Loop execution behavior (`pipeline_type=looping`):
  - failed per-item cohort at a stage with `go_to` is rerouted to the resolved reentry stage.
  - reruns process failed items only.
  - reroute cycles stop when cohort is empty or `max_loops` is exceeded (hard error).
  - run manifest stores loop iteration, active item cohort, item attempts, and artifact index for deterministic resolution and resume context.
- Manifest artifact index entries must remain relative to the run directory without `..` components so snapshots cannot escape the workspace.
- Placeholder stages skip user imports; behavior is no-op success pattern by mode.
- `human_required` stages:
  - require `instructions` at compile-time (`summary`, `steps`, `done_when`).
  - emit deterministic task packet artifacts and waiting marker.
  - set stage status to `waiting_human` in run manifest and exit cleanly.
  - on resume, validate completion proof (expected outputs exist + schema-valid) before continuing.

## 2.3 `tools.run` executable behavior

### Inputs
- CLI args:
  - one of `--run-id` or `--resume` (required)
  - `--attempt` (default `1`)
  - `--generated-dir` (default `generated`)
  - `--inputs-dir` (default `artifacts/inputs`)
  - `--output-dir` (default `artifacts/outputs/<run_id>`)
  - `--run-config-file` (optional JSON object, merged with CLI run id / resume selection)

### Preflight checks and setup
- Requires `<generated-dir>/flow.py`.
- Requires `inputs_dir` to exist and be directory.
- Requires run output directory not to already exist.
- Creates run output directory.
- Mounts inputs into run dir as `artifacts/inputs` by symlink, falls back to copytree.

### Import/mount semantics
- Dynamically mounts generated package path as `seedpipe.generated`.
- Mounts local source path as `seedpipe.src` when `src/` exists adjacent to generated dir.
- Purges prior `seedpipe.generated*` modules from `sys.modules` before import.

### Execution
- Imports `seedpipe.generated.flow`.
- Changes CWD into run output directory for run execution.
- Calls `flow.run(run_config=<effective>, attempt=<attempt>)` and returns its int exit code.
- `run_config` may be directly supplied; must contain valid string `run_id` (or be set by `--run-id`).
- Seeds and consumes a per-run manifest at `<run_output_dir>/.seedpipe_run_manifest.json` to drive rerun behavior.
- Existing run directories are no longer always rejected: rerun is refused only when manifest marks every stage `completed`.
- If an existing run manifest contains a failure/incomplete stage, runner injects `_resume_stage_id` into `run_config` so generated flow resumes at the failure point.

## 2.4 `tools.scaffold` executable behavior

### Inputs
- CLI args:
  - `--dir` target directory (default CWD)
  - `--force` to allow overwrite
  - `--loop` to scaffold a loop-enabled starter pipeline (`pipeline_type=looping`, `max_loops`, and `reentry`/`go_to` wiring)

### Files created
Scaffold writes:
- `agents.markdown` (agent usage guidance)
- `docs/specs/phase1/pipeline.yaml`
- `docs/specs/phase1/contracts/*.schema.json`
- `spec/stages/<stage_id>/*.schema.json` (runtime output schema enforcement defaults)
- `artifacts/inputs/.gitkeep`
- `artifacts/outputs/.gitignore`
- `inbox/.gitkeep`
- `outbox/.gitkeep`
- `Dockerfile`
- `docker-compose.yml`
- `src/__init__.py`
- `src/stages/__init__.py`
- starter `src/stages/{ingest,transform,publish}.py`
- when `--loop` is set, scaffold also seeds loop-stage starter code (`src/stages/seed.py`) and a loop-oriented `docs/specs/phase1/pipeline.yaml`

### Write policy
- Refuses overwrite by default (raises `FileExistsError`).
- Overwrites when `--force` is set.
- Scaffolded `agents.markdown` includes operational guidance for:
  - using a fresh `run-id` after stage-order edits,
  - keeping schema-enforced outputs JSON-shaped,
  - emitting `.md/.csv` as side artifacts when appropriate,
  - diagnostics-lane conventions and a compile/run debug checklist.

## 2.5 Other executable script files
- `tools/verify.py` exists as a wrapper entrypoint to `seedpipe.tools.verify:main`.
- `tools/agent_loop.py` runs a control loop that repeatedly executes `tools.watch --once` at a fixed interval.
- Tooling layout is split intentionally:
  - `/tools`: CLI wrappers and operational entrypoints.
  - `/seedpipe/tools`: reusable core logic consumed by wrappers/tests.

## 2.6 `tools.watch` executable behavior

### Inputs
- CLI args:
  - `--pipeline` (`all` or specific pipeline id; default `all`)
  - `--inbox-root` (default `inbox`)
  - `--outbox-root` (default `outbox`)
  - `--poll-seconds` (default `5`)
  - `--runner` (`docker|local|auto`, default `auto`)
  - `--once` (single scan and exit)
  - `--max-concurrent` (default `1` bundle per pipeline per scan)
  - `--stale-claim-seconds` (default `900`)
  - `--generated-dir` (default `generated`)
  - `--outputs-root` (default `artifacts/outputs`)
  - `--inputs-root` (default `artifacts/inputs`)

### Bundle and trigger contract
- Canonical inbox path: `inbox/<pipeline_id>/<bundle_id>/`.
- Bundle is considered runnable only when `_READY` exists.
- Required bundle members:
  - `manifest.json` (must parse as object)
  - `payload/` directory
- Optional members:
  - `run_config.json`
  - `trigger.json`
- Invalid bundles are moved to `inbox/<pipeline_id>/.rejected/<bundle_id>/` with `.reason.json`.

### Claim / process lifecycle
- Claims by atomic rename into `inbox/<pipeline_id>/.claimed/<bundle_id>.<watcher_id>`.
- Writes `.claim.json` immediately after claim.
- Reclaims stale `.claimed/` entries older than threshold back into inbox.
- Materializes payload snapshot into `artifacts/inputs/<run_id>/` (symlink-first on non-Windows, copy fallback).
- Computes watcher `run_id` as `<pipeline_id>_<unix_timestamp>_<payload_hash>` where timestamp is claim time in Unix seconds and payload hash is derived from `payload/`.
- Invokes local runtime (`tools.run:run_generated_flow`) by default fallback behavior.
- If `runner` resolves to docker and a lock image is available, invokes `docker run ... python -m tools.run ...`.
- Writes watcher status and event logs:
  - `watcher/status.json`
  - `watcher/events.ndjson`

### Outbox publishing
- If incoming manifest declares `downstreams` and `publish_artifacts`, watcher publishes to:
  - `outbox/<downstream_pipeline>/<bundle_id>/`
- Published bundle includes:
  - `manifest.json`
  - `run_config.json`
  - `payload/*`
  - `_READY`
- Watcher also scans completed runs under `artifacts/outputs/*` on each polling cycle.
- For runs whose manifest shows all stages `completed`, watcher publishes final-stage snapshot artifacts to:
  - `outbox/<pipeline_id>/<bundle_id>/`
- Run directories are marked with `.seedpipe_outbox_published.json` to keep outbox publication idempotent across repeated scans.

## 3) Runtime Module Specification

## 3.6 Metrics Contract (FR-006..FR-010)

### 3.6.1 Metric Record Emission (`seedpipe.runtime.metrics.MetricRecord`, `MetricsEmitter`)
- Function-level metrics are emitted as machine-readable records with all FR-007 fields:
  - `function_id`: stable identifier for the function being measured
  - `metric_name`: one of `latency`, `cost`, `success_count`, `failure_count`, `quality_rating` (FR-006)
  - `value`: numeric value of the metric
  - `unit`: canonical unit (`ms`, `USD`, `count`, or `1-5`)
  - `timestamp`: ISO 8601 timestamp when recorded
  - `run_id`: run identifier this metric belongs to
  - `producer`: agent/system producing this metric

### 3.6.2 Metrics Emitter (`MetricsEmitter`)
- Writes metrics to `artifacts/metrics/` directory in JSONL format
- Each function+metric combination produces a deterministic filename: `{function_id}__{metric_name}__{run_id}.jsonl`
- Records are appended per execution for replay/reproducibility

### 3.6.3 Governance Checker (`MetricsGovernanceChecker`)
- Validates completeness and freshness of metrics (FR-008, FR-009)
- Checks required metric dimensions: `latency`, `cost`, `success_count`, `failure_count`, `quality_rating`
- Detects stale metrics based on configurable `max_age_seconds` policy threshold
- Produces machine-readable governance findings tied to `function_id` and policy ID (FR-016, FR-017)
- Emits schema-valid `last_updated_at` values; when no metric rows exist, uses epoch fallback (`1970-01-01T00:00:00+00:00`)

### 3.6.4 Eligibility Determination (FR-010)
- Functions missing required metrics are marked ineligible for replacement comparison
- Stale metrics also block eligibility
- Output includes explicit reasons in `findings` array with severity levels (`error`, `warning`)
- `eligible_for_comparison` flag enables agent-vs-incumbant decision logic

### 3.6.5 Schema Contracts
- `docs/specs/phase1/contracts/metrics_contract.schema.json`: row-level metric record schema
- `docs/specs/phase1/contracts/function_metric_governance.schema.json`: governance findings and eligibility result
- `docs/specs/phase1/contracts/function_metric_row.schema.json`: canonical units metadata for metrics
- `docs/specs/phase1/contracts/function_metric_status.schema.json`: per-function eligibility/status payload schema (`policy_id`, `max_age_seconds`, `findings`, `metrics_present`)

### 3.6.7 Compile-Time Contract Validation
- Compiler requires `metrics_contract.schema.json` in phase1 contracts.
- Compiler validates metrics contract completeness:
  - required metric row fields (`function_id`, `metric_name`, `value`, `unit`, `timestamp`, `run_id`, `producer`)
  - required metric name enum entries (`latency`, `cost`, `success_count`, `failure_count`, `quality_rating`)

### 3.6.6 Runtime API Export
All metrics utilities are exported from `seedpipe.runtime` for use in generated flows:
- `MetricRecord`, `MetricsEmitter`, `MetricsValidator`
- `GovernanceFinding`, `FunctionMetricStatus`, `MetricsGovernanceChecker`

## 3.1 `StageContext` (`seedpipe.runtime.ctx`)
- Holds immutable run/stage context (`run_id`, `stage_id`, `attempt`, run directory, config).
- `make_base` validates non-empty string `run_id`.
- `for_stage` creates stage-scoped derived context.
- `validate_inputs` and `validate_outputs` enforce file existence for declared artifacts.
- `validate_expected_outputs` enforces output schemas declared in stage `outputs` object entries (`schema` key), resolving schema files from `spec/stages/<stage_id>/<schema_name>`.
- `resolve_artifact` resolves relative paths against run directory.

## 3.2 Deterministic item iteration (`seedpipe.runtime.items`)
- Reads JSONL items artifact.
- Skips blank lines.
- Requires each row to decode to a JSON object.
- Sorts rows lexicographically by `item_id` (coerced to string) before yielding.

## 3.3 Item state appending (`seedpipe.runtime.state`)
- Appends JSON-serialized rows to `artifacts/item_state.jsonl` by default.
- Ensures parent directories exist.
- Uses stable key ordering (`sort_keys=True`) for emitted JSON rows.

## 4) Test Suite Specification (Behavioral Guarantees)

## 4.1 `tests/test_compile.py` coverage
The compile tests assert:
- pipeline normalization defaults are applied.
- loop configuration defaults/validation are enforced (`pipeline_type`, `reentry`, `go_to`).
- DSL normalization expands stage/output fan-out and family/pattern object references into concrete artifacts.
- DSL error cases are rejected (invalid foreach/key wiring, missing required object fields, out-of-scope key variables, and missing template variables).
- forward input references are rejected for non-placeholder stages and allowed for placeholder stages.
- IR includes correct artifact producer mapping.
- compilation emits expected generated files and report mappings.
- placeholder stage compilation behavior is supported.
- missing required contracts fail compilation.
- compile can omit IR with `emit_debug_ir=False`.
- generated wrapper behavior validates declared outputs and imports expected stage modules.
- generated stage wrappers (both `whole_run` and `per_item`) validate emitted output paths from runtime `expected_outputs` metadata and then enforce declared output schemas via `ctx.validate_expected_outputs(...)`.

## 4.2 `tests/test_run.py` coverage
The run tests assert:
- generated flow can execute and write artifacts.
- run receives attempt value and run config fields.
- default output directory resolution works.
- completed run manifest in an existing run directory raises `FileExistsError`.
- existing incomplete run resumes from manifest failure stage.
- missing `flow.py` raises `FileNotFoundError`.
- missing inputs directory raises `FileNotFoundError`.
- local `src/stages` can be mounted for generated wrappers importing `seedpipe.src.stages.*`.

## 4.3 `tests/test_scaffold.py` coverage
The scaffold tests assert:
- scaffold writes expected baseline files and output policies.
- scaffolded project compiles successfully with `compile_pipeline`.
- `--loop` scaffold mode emits a looping pipeline and compiles successfully.
- README copy source follows runtime `REPO_ROOT` (patchable in test).
- no-force overwrite protection is enforced.

## 5) Constraints and Non-Goals in Current Implementation

- No scheduler or service control plane is implemented.
- No persistent DB state management; filesystem is authoritative.
- Contract validation beyond compile-time mapping exists in `seedpipe.tools.verify`, but this document focuses on core compile/run/scaffold and tested guarantees.
- Verifier/runner typed contracts now model manifests, artifact refs, and defects using `TypedDict` + `Literal` aliases (`seedpipe.tools.types`) while preserving runtime behavior.
- Human-gated stage orchestration (`mode=human_required`) is implemented in compiler/runtime paths and covered by compile/run tests.

## 6) Operational Notes for Contributors

- Treat `generated/` as compiler-owned output.
- Place hand-written stage logic under `src/stages/`.
- Re-compile after any pipeline contract change.
- Keep schema contracts in sync with produced artifact formats.
