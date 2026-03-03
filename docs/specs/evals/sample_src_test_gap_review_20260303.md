# Sample `/sample/src` Test-Gap Review — 2026-03-03

Scope: Only `sample/src` (unit-level), informed by existing integration test `tests/test_sample_integration.py`.

## Coverage Map (current vs missing)

- `sample/src/stages/ingest_source.py`
  - Functions: `run_whole(ctx)`
  - Currently covered: indirectly by integration run producing `items.jsonl`.
  - Missing: unit tests for output shape, newline handling, encoding, idempotency.

- `sample/src/stages/draft_translation.py`
  - Functions: `run_item(ctx, item)`
  - Currently covered: indirectly via generated flow; no direct unit tests.
  - Missing: lang key resolution from `ctx.keys`, append semantics, directory creation, handling missing fields, non-ASCII.

- `sample/src/stages/qa_pass.py`
  - Functions: `run_item(ctx, item)`; constant: `FAIL_ONCE_MARKER`.
  - Currently covered: partially by integration; no precise assertions on "fail once" loop logic or return `ItemResult`.
  - Missing: deterministic fail-once behavior, loop iteration gating, marker file lifecycle, success append and return typing.

- `sample/src/stages/qa_finalize.py`
  - Functions: `run_whole(ctx)`
  - Currently covered: indirectly (reports exist) but not validated for duplicate rows, empty lines.
  - Missing: unique item counting, empty/whitespace lines, nonexistent source behavior, output formatting (sorted keys, trailing newline).

- `sample/src/stages/publish.py`
  - Functions: `run_whole(ctx)`
  - Currently covered: manifest existence and exact content asserted by integration.
  - Missing: unit verification of encoding/newline, idempotency (overwrite), invariants independent of upstream stages.

## Proposed Tests (≥10) with Priorities and Exact Paths

Note: paths assume repo root execution (consistent with other tests). Create these under `tests/sample_src/` to isolate from core library tests.

1) P0 — `tests/sample_src/test_ingest_source_unit.py::test_writes_expected_jsonl_rows`
   - Arrange temp cwd; call `run_whole(ctx=Dummy)`; assert `items.jsonl` exists, has 2 lines, each parseable JSON with required keys.

2) P1 — `tests/sample_src/test_ingest_source_unit.py::test_newline_and_encoding`
   - Assert file ends with `\n`, open/read with `utf-8`, no decoding errors.

3) P2 — `tests/sample_src/test_ingest_source_unit.py::test_idempotent_overwrite`
   - Call twice; ensure second run overwrites (not doubles). Expect exactly 2 lines after second run.

4) P0 — `tests/sample_src/test_draft_translation_unit.py::test_uses_lang_from_ctx_keys`
   - With `ctx.keys={"lang":"fr"}` and item `{item_id:"p-001", text:"Hi"}`, assert append to `pass1_pre/fr/paragraphs.jsonl` with expected JSON fields and prefix `draft(fr):`.

5) P1 — `tests/sample_src/test_draft_translation_unit.py::test_creates_parent_dirs_and_appends`
   - Call twice with two items; assert file has two lines and parent dirs created.

6) P1 — `tests/sample_src/test_draft_translation_unit.py::test_handles_missing_fields_and_non_ascii`
   - Item missing `text` and with non-ASCII chars; assert defaults `""` and proper encoding.

7) P0 — `tests/sample_src/test_qa_pass_unit.py::test_fail_once_behavior_for_fr_p001_first_loop`
   - Ensure when `lang="fr"`, `item_id="p-001"`, `_loop_iteration=1`, and marker absent → returns `ItemResult(ok=False)` and creates marker; subsequent call with same inputs in same loop returns `ok=True` and appends one row.

8) P0 — `tests/sample_src/test_qa_pass_unit.py::test_no_fail_for_non_matching_or_later_loops`
   - Vary lang (`de`), item id, or `_loop_iteration=2`; always returns `ok=True` and appends.

9) P1 — `tests/sample_src/test_qa_pass_unit.py::test_appends_jsonl_and_returns_itemresult_type`
   - Verify return is instance-compatible with `ItemResult` (has fields), file has trailing newline and expected keys.

10) P0 — `tests/sample_src/test_qa_finalize_unit.py::test_counts_unique_item_ids_and_ignores_empty_lines`
    - Prepare `qa/<lang>/rows.jsonl` with duplicates and blank lines; assert report has `checked_items` equal to unique count.

11) P2 — `tests/sample_src/test_qa_finalize_unit.py::test_missing_source_raises`
    - Remove `qa/<lang>/rows.jsonl`; expect `FileNotFoundError` (document current behavior) or add guard if design changes.

12) P1 — `tests/sample_src/test_publish_unit.py::test_manifest_contents_and_trailing_newline`
    - Assert `published_manifest.json` equals expected JSON (with `sort_keys=True` formatting) and ends with `\n`.

13) P2 — `tests/sample_src/test_publish_unit.py::test_idempotent_overwrite`
    - Run twice; assert stable contents and single file.

## Risks If Not Added

- Silent regressions in stage I/O contracts (paths, filenames, JSON shapes) may only surface in end-to-end tests, slowing triage.
- The `qa_pass` deterministic fail-once logic is fragile; without direct tests, loop control regressions can deadlock or over-retry.
- Encoding and newline invariants affect downstream diffing/golden files; missing tests increase flakiness across platforms.
- `qa_finalize` uniqueness and whitespace handling, if altered, can under/over-count checked items and misreport status.
- Unit tests localize failures and speed development of new stages without running full pipeline.

## Done / Not-Done Checklist

- [x] Inventory `sample/src` modules and behaviors
- [x] Map current coverage vs. missing unit tests
- [x] Propose ≥10 concrete tests with exact paths and priorities
- [x] Enumerate risks of not adding tests
- [ ] Implement proposed unit tests
- [ ] Wire into CI to run alongside existing suite

## Notes

- Tests should use `tempfile.TemporaryDirectory()` and `chdir` context helpers to avoid polluting repo.
- Use small helper `DummyCtx` with `.keys` dict and `.run_config` dict to satisfy stage signatures.
- Maintain Windows-safe path joins via `pathlib.Path`.
