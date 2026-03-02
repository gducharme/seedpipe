# TODO

## Code Quality Issues

### High Priority

1. **Type Errors in verify.py** (`seedpipe/tools/verify.py`)
   - Line 52: `ArtifactRef` type used incorrectly with `dict`
   - Lines 91, 104, 122, 144: `DefectLocation` type mismatches
   - Lines 161, 187: `Manifest` passed to `diff_manifests` which expects `dict[str, Any]`
   - Fix: Add proper type casting or update function signatures

2. **Scaffold Fails on Existing Files** (`tools/scaffold.py`)
   - Raises `FileExistsError` without `--force` flag
   - Error message isn't user-friendly for first-time users
   - Fix: Make default behavior clearer or add helpful error message

### Medium Priority

3. **Duplicate Code Structure**
   - Two tool directories: `/tools/` (CLI) and `/seedpipe/tools/` (core)
   - Relationship between them is unclear
   - Fix: Clarify architecture or consolidate

4. **Missing items_row.schema.json in Required Contracts** (`tools/compile.py`)
   - `load_contracts` requires: `manifest`, `artifact_ref`, `item_state_row`, `metrics_contract`
   - Pipeline uses `items_row.schema.json` but it's not validated
   - Fix: Add `items_row.schema.json` to required contracts

5. **Empty Placeholder File** (`tools/agent_loop.py:1-2`)
   - Only contains docstring, no implementation
   - Fix: Implement or document as TODO

6. **Type Error in runner.py** (`seedpipe/tools/runner.py:40`)
   - `manifest_payload` type mismatch with `Manifest` type
   - Fix: Add proper type annotation or casting
