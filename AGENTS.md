# Repository Agent Notes

## Development Environment

This project requires Python 3.10+ to use `NotRequired` from typing. Use [mise](https://mise.jdx.dev/) to manage Python versions:

```bash
mise install python@3.10
mise use python@3.10
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Testing

Run tests with unittest or pytest:

```bash
# Using mise Python runtime
mise run python -m unittest discover tests

# Or using pytest if available
pytest tests/ -v
```

## Code Quality

- Any new feature or code fix should include a corresponding entry in the docs specs document.
- Any code change should at least increment the patch version; for larger features, consider incrementing the minor version.
- Before building or modifying a pipe, read `pipeline.yaml` to understand the format, requirements, and stage graph that the pipeline is supposed to satisfy.
- When you change `pipeline.yaml` or any related models, run `seedpipe-compile` to regenerate `generated/` so you can see the resulting structure before coding stages.
- Once the scaffold is regenerated, implement each stage using the compiled contracts—run `seedpipe-run` (or the appropriate stage invocation) to produce artifacts and schemas, replacing placeholders as needed before chaining the next stage.
- Follow this inspect-compile-implement-validate pattern for every new requirement so the pipe stays consistent and reproducible.

## Agentic Engineering v2

- Follow `docs/agentic_engineering_v2_playbook.md` for the operational model (explore -> exploit -> delete, deterministic gates, contracted handoffs).
- Enforce command-level behavior from `docs/agentic_command_policy.md` (lane isolation, required checks, circuit breakers, and FD workflow commands).
- Treat agent output as untrusted until required gates pass.
