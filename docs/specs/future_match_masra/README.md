# Future-Match Mastra Pipelines

This folder contains a four-pipeline design using the current Seedpipe pipeline format to close gaps identified in `docs/specs/future_match_masra.md`.

## Pipeline A: Analysis + Ticketing
- File: `pipeline_a_analysis_ticketing.yaml`
- Pipeline ID: `masra-gap-analysis-ticketing`
- Purpose:
  - ingest and normalize the future-match analysis,
  - perform product-impact analysis per gap,
  - draft engineering tickets,
  - publish a ready ticket bundle for implementation.

Final-stage artifacts include:
- `planning/publish/bundle_manifest.json`
- `planning/publish/ready/items.jsonl`

## Pipeline B: Coding Execution
- File: `pipeline_b_coding_execution.yaml`
- Pipeline ID: `masra-gap-coding-execution`
- Purpose:
  - execute coding work per ready ticket,
  - validate ticket-level implementation outputs,
  - run human coding review gate,
  - publish approved/rejected implementation bundles.

Loop semantics:
- `implement_ticket` declares `reentry: retry_implementation`.
- `validate_implementation` declares `go_to: retry_implementation`.
- Failed implementation cohort is rerouted until empty or `max_loops=4` is exceeded.

Final-stage artifacts include:
- `implementation/publish/approved/items.jsonl`
- `implementation/publish/rejected/items.jsonl`
- `implementation/publish/coding_manifest.json`

## Pipeline C: QA Review + Ticket Closure
- File: `pipeline_c_qa_ticket_closure.yaml`
- Pipeline ID: `masra-gap-qa-ticket-closure`
- Purpose:
  - ingest coding outputs,
  - run QA checks and remediation loop,
  - perform human closure review,
  - publish closed/reopened ticket bundles.

Loop semantics:
- `qa_ticket` declares `reentry: retry_qa`.
- `remediate_defects` declares `go_to: retry_qa`.
- Failed QA cohort is rerouted until empty or `max_loops=3` is exceeded.

Final-stage artifacts include:
- `qa/publish/closed/items.jsonl`
- `qa/publish/reopened/items.jsonl`
- `qa/publish/closure_manifest.json`

## Pipeline D: Done vs Remaining Analysis
- File: `pipeline_d_progress_analysis.yaml`
- Pipeline ID: `masra-gap-progress-analysis`
- Purpose:
  - reconcile baseline ticket set vs coding/QA outcomes,
  - quantify what is done, what remains, and residual impact,
  - publish next-cycle workset.

Final-stage artifacts include:
- `analysis/progress/progress_summary.json`
- `analysis/progress/gap_closure_scorecard.json`
- `analysis/publish/remaining/items.jsonl`

## Suggested watcher chaining
1. Run Pipeline A to produce the authoritative ticket baseline.
2. Run Pipeline B against `planning/publish/ready/items.jsonl`.
3. Run Pipeline C against implementation outputs from Pipeline B.
4. Run Pipeline D to compute done vs remaining and publish next-cycle items.
5. Feed `analysis/publish/remaining/items.jsonl` into the next coding cycle.
