# Phase 1 verifier (`seedpipe/tools/verify.py`)

`verify.py` is the deterministic judge for Phase 1. It runs exactly three checks:

1. Contract validation (manifest + referenced artifacts)
2. Determinism (same fixture run twice produces equal semantic output)
3. Resume safety (crash once mid-stage, rerun same workspace, compare with golden)

Defects are emitted as one JSON file per failure under `defects/` with stable naming:

- `contract_validation_failed`
- `contract_missing_schema`
- `contract_missing_artifact`
- `determinism_mismatch`
- `resume_mismatch`
- `resume_incomplete`

Each defect uses `defect_version: phase1-v0`, `severity: error`, and includes location, hint, and evidence.

Contract mappings are sourced from `seedpipe/spec/phase1/contracts/artifact_contracts.yaml`.
