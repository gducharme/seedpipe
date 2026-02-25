# Seedpipe agent guide

## Working agreement

- Never edit files under `generated/`; these files are compiler output and are overwritten by `seedpipe-compile`.
- Implement pipeline behavior in `src/stages/*.py` and keep stage functions aligned to stage mode (`run_whole` or `run_item`).
- Treat `spec/phase1/pipeline.yaml` as the source of truth for stage order, inputs, and outputs.
- Keep schema contracts in `spec/phase1/contracts/` aligned with the bytes your stage code writes.

## Typical workflow

1. Scaffold a project (`seedpipe-scaffold`) if starting from scratch.
2. Edit `src/stages/*.py` for implementation changes.
3. Update pipeline/contracts under `spec/phase1/` when interface changes are required.
4. Re-compile (`seedpipe-compile`) to refresh `generated/`.
5. Execute (`seedpipe-run --run-id <id>`) and verify outputs.


## Command availability note

- `seedpipe-scaffold`, `seedpipe-compile`, and `seedpipe-run` are available after installing this repository into an environment.
- If those entrypoints are unavailable (for example, when working from a raw checkout), use `python -m tools.scaffold`, `python -m tools.compile`, and `python -m tools.run` instead.
