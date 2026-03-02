# Seedpipe Python Improvements by Version

_Last updated: 2026-03-01_  
_Status: Proposed implementation guide_

## 1. Purpose
Define Python 3.12, 3.13, and 3.14 features that are relevant to Seedpipe, with a practical adoption plan that preserves current compatibility (`requires-python >=3.11`).

This document is intended for coding agents implementing incremental runtime/CLI/platform improvements.

## 2. Current Baseline
- Project runtime floor is Python 3.11 (`pyproject.toml`).
- Seedpipe has multiple CLIs (`seedpipe-compile`, `seedpipe-run`, `seedpipe-watch`) and heavy filesystem artifact orchestration.
- Current priorities include deterministic artifacts, watcher robustness, and improved operator/agent ergonomics.

## 3. Version-Sliced Improvements

## 3.1 Python 3.12

### Candidate features
1. `itertools.batched()`
- Relevance: medium.
- Why: useful for deterministic batching in per-item processing and validation loops.
- Adoption: replace ad-hoc batching helpers where present; for 3.11 compatibility, provide local fallback.

2. `pathlib.Path.walk()`
- Relevance: medium.
- Why: cleaner recursive traversal for artifact/watcher scans.
- Adoption: use when directory walking logic becomes complex; retain `os.walk` fallback for 3.11.

3. `sys.monitoring` (PEP 669)
- Relevance: medium-high for future metrics instrumentation.
- Why: low-overhead hooks can support function/stage telemetry collection with less runtime penalty than tracing/profiling APIs.
- Adoption: prototype behind feature flag; do not make this mandatory for runtime correctness.

4. Type parameter syntax (PEP 695)
- Relevance: low (near-term).
- Why: can improve type readability, but would force 3.12+ syntax if used directly.
- Adoption: defer until project minimum Python is raised.

### Recommendation for 3.12
- Use as an optional enhancement layer only.
- Do not introduce hard 3.12 syntax/runtime dependencies while floor is 3.11.

## 3.2 Python 3.13

### Candidate features
1. `argparse` deprecation metadata (`deprecated=` in `add_argument` / `add_parser`)
- Relevance: high.
- Why: Seedpipe CLI evolution can deprecate flags/subcommands with first-class parser support.
- Adoption: for 3.11 compatibility, gate usage via version checks or parser capability detection.

2. `copy.replace()`
- Relevance: medium.
- Why: cleaner immutable-style updates for config/state structs (when using dataclass/namedtuple-like objects).
- Adoption: opportunistic refactor only where it improves clarity.

3. `PythonFinalizationError`
- Relevance: medium for watcher/process shutdown.
- Why: improves explicit handling of interpreter-finalization edge cases in process/thread launch paths.
- Adoption: catch conditionally in shutdown-sensitive code paths.

4. Free-threaded CPython (PEP 703, experimental in 3.13)
- Relevance: low for immediate adoption.
- Why: potentially useful long-term for parallel stage execution, but ecosystem/tooling risk is still high.
- Adoption: do not target in production plan yet; allow exploratory benchmarking only.

### Recommendation for 3.13
- Prioritize CLI deprecation plumbing (`argparse`), then selective shutdown hardening.
- Keep free-threaded work explicitly experimental.

## 3.3 Python 3.14

### Candidate features
1. `argparse` improvements: `suggest_on_error` and `color`
- Relevance: high.
- Why: materially better operator UX for Seedpipe CLIs and fewer support mistakes.
- Adoption: enable opportunistically when available (attribute set after parser creation to preserve backward compatibility).

2. `pathlib.Path.copy()/copy_into()/move()/move_into()`
- Relevance: high.
- Why: simplifies inbox claim/publish and artifact relocation code; reduces bespoke file operation logic.
- Adoption: wrap file moves/copies in compatibility helpers so 3.11 continues to work.

3. `compression.zstd` stdlib support
- Relevance: high.
- Why: useful for compact metric/artifact bundles without third-party dependency overhead.
- Adoption: implement optional zstd artifact mode; keep uncompressed/jsonl path as baseline.

4. Deferred annotation evaluation default + `annotationlib`
- Relevance: medium.
- Why: repo currently uses `from __future__ import annotations` broadly; in 3.14 this future import is deprecated.
- Adoption: do not mass-edit now; plan a controlled cleanup when minimum version is raised and tooling is aligned.

### Recommendation for 3.14
- Prioritize CLI ergonomics and file operation simplification first.
- Add optional zstd artifact transport/compression for large outputs and watcher workflows.

## 4. Implementation Strategy While `>=3.11` Is Required

1. Introduce compatibility helpers
- Centralize feature detection (`hasattr`, `sys.version_info`) in one module.
- Avoid scattering version checks across codebase.

2. Prefer progressive enhancement
- New behavior is enabled on 3.12+ / 3.13+ / 3.14+.
- Baseline behavior remains correct on 3.11.

3. Keep wire contracts version-stable
- Python-version-specific optimizations must not change artifact schema contracts unless explicitly versioned.

4. Expand CI matrix before broad rollout
- Validate at least 3.11, 3.12, 3.13, 3.14 for CLI and runtime tests.

## 5. Prioritized Backlog (Agent-Ready)

1. CLI ergonomics tranche (3.13 + 3.14 capable, 3.11-safe)
- Add parser capability layer.
- Enable deprecation metadata where available.
- Enable `suggest_on_error` and `color` where available.
- Target files: `tools/run.py`, `tools/compile.py`, `tools/watch.py`.

2. Filesystem operation tranche (3.14 capable, 3.11-safe)
- Add path copy/move abstraction.
- Refactor watcher claim/publish paths to use shared abstraction.
- Target file: `tools/watch.py`.

3. Artifact compression tranche (3.14 capable, optional)
- Add optional zstd compression mode for selected artifacts/bundles.
- Keep default outputs unchanged unless explicitly enabled.

4. Telemetry instrumentation exploration (3.12 optional)
- Prototype `sys.monitoring` integration for function/stage metrics collection overhead analysis.
- No contract changes until proven stable.

## 6. Acceptance Criteria for This Improvement Track

1. No regressions on Python 3.11 for existing workflows.
2. New CLI niceties activate automatically on runtimes that support them.
3. Feature-gated code paths are covered by tests (or explicit unit tests with monkeypatched capability checks).
4. Documentation clearly states which improvements are opportunistic vs mandatory.

## 7. Primary References
- Python 3.12: [What’s New In Python 3.12](https://docs.python.org/3.12/whatsnew/3.12.html)
- Python 3.13: [What’s New In Python 3.13](https://docs.python.org/3.13/whatsnew/3.13.html)
- Python 3.14: [What’s New In Python 3.14](https://docs.python.org/3.14/whatsnew/3.14.html)
- `argparse`: [Python 3.14 argparse docs](https://docs.python.org/3.14/library/argparse.html)
- `pathlib`: [Python 3.14 pathlib docs](https://docs.python.org/3.14/library/pathlib.html)
- `compression.zstd`: [Python 3.14 compression.zstd docs](https://docs.python.org/3.14/library/compression.zstd.html)
