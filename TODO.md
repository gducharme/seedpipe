# TODO

## Code Quality Issues

### High Priority

1. **Python 3.10 Compatibility Issue** (`seedpipe/tools/types.py:3`)
   - Uses `NotRequired` from `typing` which was added in Python 3.11
   - `pyproject.toml` requires `>=3.10`
   - Fix: Use `typing_extensions.NotRequired` or bump minimum Python to 3.11

2. **Type Errors in verify.py** (`seedpipe/tools/verify.py`)
   - Line 52: `ArtifactRef` type used incorrectly with `dict`
   - Lines 91, 104, 122, 144: `DefectLocation` type mismatches
   - Lines 161, 187: `Manifest` passed to `diff_manifests` which expects `dict[str, Any]`
   - Fix: Add proper type casting or update function signatures

3. **Duplicate Schema Files**
   - `/spec/phase1/contracts/*.schema.json`
   - `/seedpipe/spec/phase1/contracts/*.schema.json`
   - Fix: Consolidate to single location, remove duplicates

4. **Scaffold Fails on Existing Files** (`tools/scaffold.py:284`)
   - Raises `FileExistsError` without `--force` flag
   - Error message isn't user-friendly for first-time users
   - Fix: Make default behavior clearer or add helpful error message

### Medium Priority

5. **Duplicate Code Structure**
   - Two tool directories: `/tools/` (CLI) and `/seedpipe/tools/` (core)
   - Relationship between them is unclear
   - Fix: Clarify architecture or consolidate

6. **Missing items_row.schema.json in Required Contracts** (`tools/compile.py:373`)
   - `load_contracts` requires: `manifest`, `artifact_ref`, `item_state_row`
   - Pipeline uses `items_row.schema.json` but it's not validated
   - Fix: Add `items_row.schema.json` to required contracts

7. **Empty Placeholder File** (`tools/agent_loop.py:1-2`)
   - Only contains docstring, no implementation
   - Fix: Implement or document as TODO

8. **Generated Code in Repo** (`generated/`)
   - Contains auto-generated code that should be regenerated
   - Fix: Add to `.gitignore` or document that it's intentional

9. **Type Error in runner.py** (`seedpipe/tools/runner.py:40`)
   - `manifest_payload` type mismatch with `Manifest` type
   - Fix: Add proper type annotation or casting

### Low Priority

10. **Code Duplication in compile.py**
    - String concatenation for code generation is verbose (lines 422-757)
    - Consider using a template engine or separate code generation module

11. **Missing Test Coverage**
    - No dedicated tests for: `seedpipe/tools/contracts.py`, `seedpipe/tools/diff.py`
    - Fix: Add unit tests for these modules

12. **No Type Checking Config**
    - No mypy.ini, pyproject.toml [tool.mypy] section
    - Consider adding mypy configuration for type safety

13. **Duplicate Tool Entrypoints**
    - Both `tools/verify.py` and `seedpipe/tools/verify.py` exist
    - Unclear which should be used
    - Fix: Document the relationship or consolidate
