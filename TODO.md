# TODO

## Top Backlog: Autocoding Production Reliability

1. **Define canonical ticket contracts and status transitions** `(NEW)`
   - Scope:
     - Add schema contracts for shared ticket rows across pipelines A/B/C/D.
     - Enforce one canonical status algebra: `ready`, `in_progress`, `implemented`, `qa_failed`, `approved`, `rejected`, `closed`, `reopened`.
   - Why:
     - Current multi-pipeline flow depends on implicit row shapes and status meaning.
     - Without a shared contract, handoffs drift and closure logic becomes non-deterministic.
   - Acceptance:
     - new schema files added under `docs/specs/phase1/contracts/`,
     - compiler/runtime validation catches invalid status transitions,
     - tests cover at least one invalid and one valid transition path.

2. **Add ticket-level acceptance contract fields** `(NEW)`
   - Scope:
     - Require each ticket to declare objective closure criteria:
       - expected file paths/artifacts,
       - required test command(s),
       - target spec references,
       - evidence pointers.
   - Why:
     - Prevents subjective closure and review ambiguity in coding + QA stages.
   - Acceptance:
     - ticket schema includes mandatory acceptance fields,
     - `pipeline_b_coding_execution` and `pipeline_c_qa_ticket_closure` stage code validates evidence against those fields,
     - failed evidence forces deterministic non-closure state.

3. **Implement loop guardrails and escalation policy** `(NEW)`
   - Scope:
     - Add deterministic guardrails:
       - max retries per ticket,
       - auto-quarantine after threshold,
       - mandatory human escalation marker for repeated failures.
   - Why:
     - Prevents infinite churn loops and silent rework cycles in autocoding.
   - Acceptance:
     - guardrail policy encoded as machine-readable artifact,
     - ticket exceeding threshold transitions to `reopened` or `quarantined` deterministically,
     - tests confirm loops stop with explicit reason.

4. **Define deterministic requeue semantics from progress analysis** `(NEW)`
   - Scope:
     - Specify how `analysis/publish/remaining/items.jsonl` maps back into next-cycle ready tickets.
     - Include dedupe/idempotency and carry-forward evidence rules.
   - Why:
     - Closed-loop autonomy requires deterministic recycle of remaining work.
   - Acceptance:
     - documented requeue contract and schema,
     - repeat runs do not duplicate tickets,
     - tests verify stable IDs and evidence continuity across cycles.

5. **Implement concrete stage modules for B/C/D pipeline artifacts** `(NEW)`
   - Scope:
     - Build `src/stages/*.py` implementations for:
       - coding execution + validation,
       - QA closure + human review packet output,
       - done-vs-remaining analysis and scorecard output.
   - Why:
     - Current pipeline specs define orchestration shape; production readiness requires executable stage logic with deterministic outputs.
   - Acceptance:
     - all stage modules exist and emit declared artifacts,
     - compile + run integration test covers A→B→C→D happy path,
     - at least one failure-path test validates loop + reopen behavior.

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
