# Seedpipe Failure + Resume Invariants (Rework)

These invariants define the correctness contract for failure handling, resume behavior, and selective rework in Seedpipe.

## I. Artifact truth & run directory invariants

1. **Single run root**  
   Every run executes inside exactly one run directory: `./artifacts/outputs/<run-id>/` by default.

2. **Artifact truth is authoritative**  
   Completion and resume status MUST be inferred from on-disk artifacts + validation, not in-memory flags.

3. **No implicit mutation of prior runs**  
   A run MUST NOT mutate artifacts of any other `run_id`.

4. **Deterministic re-run is allowed**  
   Re-running the same `run_id` is supported and MUST converge to the same final outputs when inputs/config are unchanged and determinism policy is strict.

## II. Stage boundary & completion invariants

5. **Stage input closure**  
   A stage MUST NOT start unless declared inputs exist and pass required validation.

6. **Stage output closure**  
   A stage MUST NOT be marked completed unless declared outputs exist and validate.

7. **Completion is skip-safe**  
   If a stage is considered completed, skipping it MUST preserve downstream semantics.

8. **No half-commit completion**  
   Downstream MUST NOT observe a stage as completed while outputs are partial/invalid.

9. **Whole-run atomicity by directory**  
   `whole_run` stages SHOULD write through temp locations and atomically commit into place (or equivalent).

## III. Failure semantics invariants

10. **Failure is explicit and inspectable**  
    Any stage failure MUST emit a structured defect record under the run directory (for example `defects/...`) with stage id, mode, attempt, error details, and evidence pointers.

11. **Failure never silently advances**  
    On failure, downstream stages MUST NOT execute in that run.

12. **Failed state is retryable without manual surgery**  
    Re-running the same `run_id` MUST continue from the earliest incomplete stage unless user overrides behavior.

## IV. Per-item semantics invariants (`per_item`)

13. **Stable item identity**  
    Each processed unit MUST have a stable `item_id`; if stable identity cannot be derived, `per_item` mode MUST fail clearly.

14. **Append-only item state log**  
    Item outcomes MUST be recorded as append-only records inside the run directory.

15. **Monotone item-state progression**  
    For `(stage_id, item_id)`, effective state is the last valid record; attempts are ordered and attributable.

16. **Per-item output isolation**  
    One item’s outputs MUST NOT corrupt or overwrite another’s.

17. **Skip semantics for completed items**  
    On rerun, completed items MUST be skipped unless explicit recompute is requested.

18. **Retry semantics for failed items**  
    On rerun, failed items MAY be retried and retries MUST be distinguishable by attempt metadata.

## V. Idempotency & safety invariants

19. **Stage wrapper idempotency**  
    Generated wrappers MUST be safe to re-enter after crashes/restarts without silent corruption.

20. **No destructive cleanup on startup**  
    Resume logic MUST NOT auto-delete artifacts beyond scoped temp/lock paths.

21. **Locks do not define truth**  
    Locks MAY gate concurrency but MUST NOT be the sole source of completion/progress truth.

## VI. Determinism invariants (strict)

22. **Strict determinism means reproducible outputs**  
    Identical inputs/config under strict policy MUST produce identical output hashes (modulo declared exclusions).

23. **Resume determinism**  
    A resumed run MUST match a clean run result under strict policy.

24. **Ordering determinism**  
    `per_item` iteration order MUST be deterministic or explicitly defined.

## VII. Validation & contracts invariants

25. **Contracts are enforced at boundaries**  
    Contract validation MUST occur post-production and pre-consumption as required.

26. **Manifest integrity**  
    Any manifest MUST reference only artifacts that exist and validate.

27. **`generated/` is compiler-owned**  
    Runtime MUST treat generated code as immutable for a run.

## VIII. UX invariants (simplicity constraints)

28. **Default command is resumable**  
    `seedpipe-run --run-id X` MUST start a new run or resume an existing run directory by default.

29. **No recovery DSL required in phase 1**  
    Recovery MUST NOT require users to author retry policy graphs/languages.

30. **Selective rework stays file-centric**  
    Supported manual escape hatch: remove specific outputs or item-state records, rerun, and rely on deterministic regeneration.
