# TODO

## Code Quality Issues

### High Priority

1. **Fix default `unittest` discovery breakage from `generated/` imports**
   - Running `python3 -m unittest` can import `generated.stages` and fail with:
     `ModuleNotFoundError: No module named 'seedpipe.generated'`.
   - Fix:
     - Standardize test invocation to explicit `tests/` discovery, and/or
     - prevent `generated/` from being discovered/imported in test runs.
   - Acceptance:
     - `python3 -m unittest` (or documented default command) runs cleanly without generated-module import failures.

2. **Make YAML dependency failures explicit in compiler**
   - `tools.compile.load_pipeline()` falls back to `json.loads` when `PyYAML` is missing, causing confusing `JSONDecodeError` for YAML files.
   - Fix:
     - emit a clear error when YAML input is detected but `PyYAML` is unavailable, or
     - enforce/install `PyYAML` in all supported runtime/test environments.
   - Acceptance:
     - Missing `PyYAML` produces a clear actionable compile error (not raw JSON parse failure).

### Medium Priority

3. **Consolidate metric contract file naming in docs/specs phase1 contracts**
   - Both files exist:
     - `docs/specs/phase1/contracts/metrics_contract.json`
     - `docs/specs/phase1/contracts/metrics_contract.schema.json`
   - Runtime resolver still checks both paths.
   - Fix:
     - choose one canonical file (prefer `.schema.json`),
     - remove duplicate,
     - simplify resolver fallbacks and docs references.
   - Acceptance:
     - single canonical metrics contract file remains; tests and runtime resolution continue to pass.

4. **Narrow broad exception handling in watcher**
   - `tools/watch.py` uses multiple broad `except Exception` handlers.
   - Fix:
     - narrow exception classes where possible,
     - preserve detailed context in status/events for unrecoverable failures.
   - Acceptance:
     - watcher behavior remains stable, and failure diagnostics are more specific and consistent.

### Low Priority

5. **Keep TODO document lean and issue-like**
   - Avoid stale headings or “already done” entries.
   - Fix:
     - keep only active backlog items with priority, owner (if known), and acceptance criteria.
   - Acceptance:
     - TODO contains only actionable open items.
