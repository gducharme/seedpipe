# Agentic Command Policy

This policy defines required commands, gates, and lane behavior for agent-assisted development in this repository.

## Scope

Applies to all FD-driven implementation work (`docs/features/FD-*.md`) and all agent-authored diffs.

## Lane Setup Policy

1. One lane = one branch/worktree.
2. Branch names must use `codex/` prefix.
3. No concurrent coding in the same worktree.

Recommended lane creation:

```bash
git worktree add ../seedpipe-fd-<N>-<lane> -b codex/fd-<N>-<lane>
```

## Required Start-of-Work Commands

Run at session start:

```bash
mulch prime
sd prime
cn prime
```

For FD workflow:

1. `fd-new` (if no FD exists for the change)
2. `fd-status` (confirm current active state)
3. `fd-explore` (when context is stale or first pass in a repo area)

## Required Validation Gates

At least one test gate is mandatory for every code change:

```bash
python -m unittest discover tests
# or
pytest tests/ -v
```

When pipeline/contracts/compiler surfaces are changed, `seedpipe-compile` is mandatory:

```bash
seedpipe-compile
```

When environment supports mypy, run:

```bash
python -m mypy seedpipe tools
```

## Handoff Command Policy

Before handoff:

1. Run `fd-verify` workflow.
2. Capture gate results in summary.
3. Keep diff scoped to FD file plan; if scope expands, update FD first.

For closeout:

1. Run `fd-close` after successful verification.
2. Ensure archive/index/changelog behavior matches FD disposition.

## Circuit Breaker Rules

Immediately stop the lane if any condition holds:

1. Required validation gate fails 3 times consecutively.
2. Lane repeatedly edits files outside FD scope.
3. Diff volume grows beyond FD plan with no accepted scope change.

When tripped:

1. Stop coding in lane.
2. Summarize failure mode.
3. Re-run from a clean branch/worktree with narrower scope.

## Prohibited Behaviors

1. Sharing one branch among multiple active coding agents.
2. Merging without passing required gates.
3. Patching low-quality outputs repeatedly when full rerun is cheaper.
4. Large, multi-concern PRs that violate single-FD scope.

## Promote / Rollback

Promote only after all merge criteria pass.
Rollback via standard git revert/branch reset procedures owned by the human integrator.

## Evidence Template

Include in handoff:

```text
FD: FD-XXX
Lane: <branch/worktree>
Checks:
- pytest: pass/fail
- compile (if required): pass/fail
- mypy (if run): pass/fail
Scope:
- files changed align with FD: yes/no
Risk:
- <one-line residual risk>
Rollback:
- <one-line rollback path>
```
