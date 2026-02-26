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
- Module fallbacks are documented:
  - `python -m tools.compile`
  - `python -m tools.scaffold`
  - `python -m tools.run`

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
  - `stages` ordered array (at least one stage)
- Per-stage (core linear model):
  - `id` (required)
  - `mode` (`whole_run` or `per_item`, default `whole_run`)
  - `inputs` (default `[]`)
  - `outputs` (default `[]`)
  - `placeholder` (default `false`)
- Optional DSL expansion accepted by compiler normalization:
  - Stage-level `foreach` + `key` fan-out into concrete stage instances.
  - Object entries in `inputs` with `family` + `pattern` + `schema` for template-based artifact resolution.
  - Object entries in `outputs` with `family` + `pattern` + `schema` and keying by `key` or output-level `foreach` + `key`.
  - `{var}` template interpolation in string `inputs`/`outputs` from stage/output scope.
  - Compiler expansion tracks resolved family selection values as stage/output `keys` metadata (not `bind` fields), and these keys are propagated into generated runtime stage contexts.
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

## 2.2 `tools.compile` executable behavior

### Inputs
- CLI args:
  - `--pipeline` (default `spec/phase1/pipeline.yaml`)
  - `--contracts-dir` (optional; auto-picks default directories)
  - `--output-dir` (default `generated`)
  - `--no-ir` (disables `generated/ir.json`)

### Functional stages
1. Load pipeline (`YAML` via PyYAML if available; JSON fallback).
2. Normalize defaults (`item_unit`, `determinism_policy`, stage defaults).
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
- No stages.
- Duplicate stage IDs.
- Invalid stage mode.
- Non-boolean `placeholder`.
- Non-array inputs/outputs.
- Non-string artifact names.
- Any stage input is unresolved at that point in stage order.
- Invalid DSL expansion requests (e.g., unresolved `foreach` paths, missing required object fields, out-of-scope key vars, or missing template variables).
- Compiler/runtime generation path is key-only for stage/output fan-out metadata (`keys`), with no `_bindings` metadata emitted in normalized stages, IR, or generated flow artifacts.
- Contracts directory has no schema files or misses required schemas.
- Resolved artifact schema name is absent from contract set.

### Generated outputs
Compiler emits (at minimum):
- `generated/models.py`
- `generated/flow.py`
- `generated/stages/<stage>.py` wrappers
- `generated/stages/__init__.py`
- `generated/compile_report.json`
- `generated/_meta.json`
- optional `generated/ir.json`

It also ensures source stage stubs exist under `src/stages/*.py` for non-placeholder stages.

### Runtime semantics embedded in generated code
- `whole_run` stages:
  - validate declared inputs before executing user impl.
  - validate declared outputs after execution.
- `per_item` stages:
  - iterate deterministic item stream.
  - append item-state transitions (`in_progress`, then `succeeded`/`failed`).
  - stage exception returns an error-bearing `ItemResult` instead of raising.
- Placeholder stages skip user imports; behavior is no-op success pattern by mode.

## 2.3 `tools.run` executable behavior

### Inputs
- CLI args:
  - `--run-id` (required)
  - `--attempt` (default `1`)
  - `--generated-dir` (default `generated`)
  - `--inputs-dir` (default `artifacts/inputs`)
  - `--output-dir` (default `artifacts/outputs/<run_id>`)

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

## 2.4 `tools.scaffold` executable behavior

### Inputs
- CLI args:
  - `--dir` target directory (default CWD)
  - `--force` to allow overwrite

### Files created
Scaffold writes:
- `agents-readme.markdown` (copied from repo README when available)
- `agents.markdown` (agent usage guidance)
- `spec/phase1/pipeline.yaml`
- `spec/phase1/contracts/*.schema.json`
- `artifacts/inputs/.gitkeep`
- `artifacts/outputs/.gitignore`
- `src/__init__.py`
- `src/stages/__init__.py`
- starter `src/stages/{ingest,transform,publish}.py`

### Write policy
- Refuses overwrite by default (raises `FileExistsError`).
- Overwrites when `--force` is set.

## 2.5 Other executable script files
- `tools/verify.py` exists as a wrapper entrypoint to `seedpipe.tools.verify:main`.
- `tools/agent_loop.py` is a placeholder and currently has no operational loop logic.

## 3) Runtime Module Specification

## 3.1 `StageContext` (`seedpipe.runtime.ctx`)
- Holds immutable run/stage context (`run_id`, `stage_id`, `attempt`, run directory, config).
- `make_base` validates non-empty string `run_id`.
- `for_stage` creates stage-scoped derived context.
- `validate_inputs` and `validate_outputs` enforce file existence for declared artifacts.
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
- DSL normalization expands stage/output fan-out and family/pattern object references into concrete artifacts.
- DSL error cases are rejected (invalid foreach/key wiring, missing required object fields, out-of-scope key variables, and missing template variables).
- forward input references are rejected for non-placeholder stages and allowed for placeholder stages.
- IR includes correct artifact producer mapping.
- compilation emits expected generated files and report mappings.
- placeholder stage compilation behavior is supported.
- missing required contracts fail compilation.
- compile can omit IR with `emit_debug_ir=False`.
- generated wrapper behavior validates declared outputs and imports expected stage modules.

## 4.2 `tests/test_run.py` coverage
The run tests assert:
- generated flow can execute and write artifacts.
- run receives attempt value and run config fields.
- default output directory resolution works.
- existing run directory raises `FileExistsError`.
- missing `flow.py` raises `FileNotFoundError`.
- missing inputs directory raises `FileNotFoundError`.
- local `src/stages` can be mounted for generated wrappers importing `seedpipe.src.stages.*`.

## 4.3 `tests/test_scaffold.py` coverage
The scaffold tests assert:
- scaffold writes expected baseline files and output policies.
- scaffolded project compiles successfully with `compile_pipeline`.
- README copy source follows runtime `REPO_ROOT` (patchable in test).
- no-force overwrite protection is enforced.

## 5) Constraints and Non-Goals in Current Implementation

- No scheduler or service control plane is implemented.
- No persistent DB state management; filesystem is authoritative.
- `tools/agent_loop.py` does not yet implement control-loop behavior.
- Contract validation beyond compile-time mapping exists in `seedpipe.tools.verify`, but this document focuses on core compile/run/scaffold and tested guarantees.

## 6) Operational Notes for Contributors

- Treat `generated/` as compiler-owned output.
- Place hand-written stage logic under `src/stages/`.
- Re-compile after any pipeline contract change.
- Keep schema contracts in sync with produced artifact formats.
