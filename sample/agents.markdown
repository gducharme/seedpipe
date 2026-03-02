# Seedpipe agent guide

- Never edit files under `generated/`; they are compiler output and will be overwritten.
- Put hand-written stage logic in `src/stages/*.py`.
- If pipeline structure changes, update `docs/specs/phase1/pipeline.yaml` and re-run `seedpipe-compile`.
- Keep contract schemas in `docs/specs/phase1/contracts/` in sync with artifact formats.
- `artifacts/inputs/` should contain the artifacts required to start a run.
- `artifacts/outputs/<run_id>/` should contain stage artifacts for that specific run ID.
- CLI entrypoints may be unavailable until installation; use `python -m tools.scaffold|compile|run` from a checkout.
- Use `seedpipe-scaffold --loop` to generate a loop-enabled starter pipeline with `pipeline_type: looping`, `max_loops`, and `reentry`/`go_to` stage wiring.

## Practical implementation notes

- After stage-order edits in `docs/specs/phase1/pipeline.yaml`, use a new `run-id`. Reusing an old run ID can fail with `ValueError: run manifest stage order does not match compiled flow`.
- Runtime schema validation loads declared output payloads as JSON. Declaring `.txt`, `.md`, or `.csv` outputs with schemas can fail at JSON parsing.
- Preferred output pattern:
  - Keep machine-contract outputs in JSON artifacts declared in `pipeline.yaml`.
  - Write human-readable `.md` or `.csv` as side artifacts from stage code unless wrapped in JSON.
- Side artifacts are a convenience layer; the canonical contract should stay in JSON for downstream stage consumption.
- In loop pipelines, prefer returning `ItemResult(ok=False, error=...)` for business-rule failures in `run_item` and let runtime route failed cohorts through `go_to` reentry.
- For narrative diagnostics, keep explicit lanes:
  - `run_document_diagnostics` for document-level metrics.
  - `run_paragraph_diagnostics` for paragraph-level metrics.
  - `run_hybrid_diagnostics` for global baseline plus local anchors.
  - Merge lanes in `merge_report` into a stable bundle contract.

## Fast debug checklist

- Compile failures:
  - Confirm every object-form input/output defines `family`, `pattern`, and `schema`.
  - Confirm schema files exist under `spec/stages/<stage_id>/...`.
- Run failures:
  - Confirm stage code writes every declared output artifact.
  - Confirm produced output payload shape matches declared stage schema.
  - Use a new `run-id` after stage-graph edits.
