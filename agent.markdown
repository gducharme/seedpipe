# Agent Instructions

- Whenever you make a change to this repository, increment at least the patch version by one.
- Runtime and generated stage implementations should treat `./artifacts/outputs/<run-id>/defects/` as the canonical location for structured failure records.
- When adding or modifying run behavior, ensure the run creates and preserves the `defects/` directory so failures are inspectable and resume-safe.
