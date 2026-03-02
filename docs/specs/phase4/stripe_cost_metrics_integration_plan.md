# Stripe Cost Metrics Integration Plan (Phase 4)

_Last updated: 2026-03-02_
_Status: Proposed (future-only, not implemented)_

## Scope Guardrail
This document and the contracts under `docs/specs/phase4/contracts/` are **future contracts**.
They are intentionally **not** part of the current compile/run contract surface and have no runtime effect until promoted.

## Summary
Integrate Stripe into Seedpipe cost metrics using:
1. Stripe meter events + finalized invoices as billing source.
2. Run-level cost attribution.
3. Daily reconciliation batch.

This preserves current metric semantics (`metric_name=cost`, `unit=USD`) while defining a future deterministic and auditable reconciliation path.

## Intended Future Outcomes
- Stripe-derived USD cost can be emitted as `cost` metric rows with deterministic provenance.
- Every billable run has either:
  - a Stripe-attributed cost row, or
  - an explicit reconciliation finding (`unmapped`, `stale`, `missing`).
- Reconciliation is replay-safe and idempotent.

## Design (Future)

### 1) Billing Source and Windowing
- Source of truth: Stripe meter events + finalized invoices.
- Cadence: daily batch.
- Default window: previous UTC day (`[00:00, 24:00)`).
- Backfill: explicit date range override.
- Currency: normalize to USD with recorded FX context.

### 2) Attribution Model
- Attribution unit: run.
- Mapping convention:
  - `function_id = pipeline::<pipeline_id>`
  - `run_id` remains the execution run identifier.
- Aggregation key: `(run_id, pipeline_id)`.
- Attribution method identifier: `run_level_v1`.

### 3) Future Contracts
- `docs/specs/phase4/contracts/stripe_invoice_row.schema.json`
- `docs/specs/phase4/contracts/stripe_meter_event_row.schema.json`
- `docs/specs/phase4/contracts/stripe_run_cost_row.schema.json`
- `docs/specs/phase4/contracts/stripe_reconciliation_report.schema.json`

### 4) Future Pipeline Surface
Proposed future reconciliation pipeline:
1. Ingest Stripe snapshots.
2. Reconcile per-run costs.
3. Emit cost metrics.
4. Publish reconciliation report.

### 5) Guardrails
- Idempotency key includes stripe account, window bounds, run id, and attribution method.
- Duplicate rows are suppressed deterministically.
- Unmapped rows are retained with explicit reason codes.

## Non-Goals (Current System)
- No change to `docs/specs/phase1/contracts/`.
- No change to current compiler contract resolution.
- No runtime or watcher behavior changes.

## Promotion Criteria (Future)
Before any adoption into current runtime:
1. Contracts validated with fixtures.
2. Reconciliation logic implemented with deterministic tests.
3. Governance integration defined for stale/unmapped coverage.
4. Explicit migration note from phase4 future contracts to active contract set.
