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

## Feature Design (FD) Management

Features are tracked in `docs/features/`. Each FD has a dedicated file (`FD-XXX_TITLE.md`) and is indexed in `FEATURE_INDEX.md`.

### FD Lifecycle

| Stage | Description |
|-------|-------------|
| **Planned** | Identified but not yet designed |
| **Design** | Actively designing (exploring code, writing plan) |
| **Open** | Designed and ready for implementation |
| **In Progress** | Currently being implemented |
| **Pending Verification** | Code complete, awaiting verification |
| **Complete** | Verified working, ready to archive |
| **Deferred** | Postponed (low priority or blocked) |
| **Closed** | Won't implement (superseded or not needed) |

### Codex Skills

- `fd-init` — Initialize FD system in a repository
- `fd-new` — Create a new feature design
- `fd-explore` — Explore project and FD context
- `fd-deep` — Deep 4-angle analysis for hard problems
- `fd-status` — Show active FDs with status and grooming
- `fd-verify` — Post-implementation: commit, proofread, verify
- `fd-close` — Complete/close an FD, archive file, update index, update changelog

### Conventions

- **FD files**: `docs/features/FD-XXX_TITLE.md` (XXX = zero-padded number)
- **Commit format**: `FD-XXX: Brief description`
- **Numbering**: Next number = highest across all index sections + 1
- **Source of truth**: FD file status > index (if discrepancy, file wins)
- **Archive**: Completed FDs move to `docs/features/archive/`

### Managing the Index

The `FEATURE_INDEX.md` file has four sections:

1. **Active Features** — All non-complete FDs, sorted by FD number
2. **Completed** — Completed FDs, newest first
3. **Deferred / Closed** — Items that won't be done
4. **Backlog** — Low-priority or blocked items parked for later

### Changelog

- **Format**: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) with [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
- **Updated by**: `fd-close` (complete disposition only) adds entries under `[Unreleased]`
- **FD references**: Entries end with `(FD-XXX)` for traceability
- **Subsections**: Added, Changed, Fixed, Removed
- **Releasing**: Rename `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD`, add fresh `[Unreleased]` header
