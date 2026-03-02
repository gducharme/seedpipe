# TODO

## Design-Pattern Refactor Tasks

### High Priority

1. **Remove duplicate `StageContext` class definition in runtime context** `(DONE 2026-03-02)`
   - File: `seedpipe/runtime/ctx.py`
   - Why:
     - The module currently declares `StageContext` twice; the latter shadows the former.
     - This creates dead code and increases maintenance risk.
   - Acceptance:
     - only one `StageContext` declaration remains,
     - runtime context tests continue to pass.

2. **Split compiler flow generation by stage strategy** `(DONE 2026-03-02)`
   - File: `tools/compile.py` (`emit_flow_py`)
   - Pattern:
     - Template Method + Strategy for stage-mode-specific generation (`whole_run`, `per_item`, `human_required`).
   - Acceptance:
     - stage-mode code generation lives in isolated helpers/strategies,
     - generated flow behavior stays test-equivalent.

3. **Introduce a code-emission builder for generated Python source** `(DONE 2026-03-02)`
   - File: `tools/compile.py`
   - Pattern:
     - Builder for indentation-aware source assembly instead of long concatenation chains.
   - Acceptance:
     - `emit_flow_py` and stage wrapper generation no longer rely on monolithic string concatenation.

### Medium Priority

4. **Extract run-manifest repository/model API** `(DONE 2026-03-02)`
   - Files: `tools/run.py`, generated flow emitted by `tools/compile.py`
   - Pattern:
     - Repository + Value Object for manifest read/write, row access, and completion/resume semantics.
   - Acceptance:
     - manifest shape checks and status transitions are centralized behind one API.

5. **Refactor watcher bundle lifecycle into explicit states** `(DONE 2026-03-02)`
   - File: `tools/watch.py`
   - Pattern:
     - State pattern for `ready`, `claimed`, `rejected`, `done`, `stale-reclaimed`.
   - Acceptance:
     - lifecycle transitions are explicit and tested by state transitions, not scattered conditionals.
   - Follow-up:
     - watcher runner dispatch now uses backend adapters (`RunnerBackend`, `LocalRunnerBackend`, `DockerRunnerBackend`) selected by `_select_runner_backend`.

### Low Priority

6. **Modularize compile validation as validator chain** `(DONE 2026-03-02)`
   - File: `tools/compile.py` (`validate_pipeline_structure`)
   - Pattern:
     - Chain of Responsibility for top-level, stage-level, loop, and human-required validation slices.
   - Acceptance:
     - compile validation logic is split into composable validators with unchanged error quality.

7. **Replace artifact schema mapping conditionals with specs** `(DONE 2026-03-02)`
   - File: `tools/compile.py` (`resolve_artifact_schemas`)
   - Pattern:
     - Specification pattern for artifact-to-schema rules.
   - Acceptance:
     - mapping rules are declared as ordered specs, minimizing hardcoded branching.
