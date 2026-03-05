# Agentic Engineering v2 Playbook

This playbook operationalizes multi-agent coding as a deterministic system:

`probabilistic generation + deterministic validation + measured reliability + aggressive deletion + contracted composition`.

## Why This Exists

Agents produce useful proposals quickly, but they also amplify entropy. This repo treats agent output as untrusted until it passes explicit contracts and quality gates.

## Non-Negotiables

1. No implementation starts without a scoped work unit (`FD-XXX`) and acceptance criteria.
2. No concurrent coding in a shared branch or shared mutable workspace.
3. No handoff without deterministic evidence (tests/checks, scope note, risk note).
4. No repair of low-quality agent output in place when rerun is cheaper and safer.
5. Humans keep merge authority and module ownership.

## Operating Model

### 1. Work Unit

Track each change as an FD item in `docs/features/`:

- scope
- explicit inputs/outputs
- edge cases
- verification steps

### 2. Phase Model

Use a strict lifecycle for each FD:

1. Explore
2. Exploit
3. Delete

#### Explore

- Generate options in isolated branches/worktrees.
- Allow high entropy and experiments.
- Do not merge from this phase directly.

#### Exploit

- Select one approach.
- Harden implementation and enforce strict checks.
- Prepare small reviewable diffs.

#### Delete

- Remove dead paths, scaffolding, debug artifacts, stale branches/worktrees.
- Collapse to one clean implementation path.

### 3. Agent Topology

Default topology per FD:

- 1 implementer agent
- 1 reviewer/validator agent
- 1 human integrator (owner)

Do not exceed 3 active agents for one FD unless the owner explicitly approves.

### 4. Contracted Handoff

Every agent handoff must include:

- diff summary (what changed)
- validation evidence (what ran + result)
- risk note (what might still break)
- rollback note (how to undo safely)

Treat handoff as a stage artifact, not a chat message.

## Deterministic Filters

Apply checks based on change type:

1. Python/runtime changes:
- `python -m unittest discover tests`
- or `pytest tests/ -v`

2. Pipeline/spec changes (`pipeline.yaml`, contracts, compiler model):
- run `seedpipe-compile`
- run relevant pipeline execution validation (`seedpipe-run` or fixture tests)

3. Type checks (when available in environment):
- `python -m mypy seedpipe tools`

If a required gate fails, do not merge.

## Reliability Policy (SRE Lens)

Track these per FD and weekly:

- run success rate
- retries per accepted change
- diff-size outliers
- test churn rate
- revert rate after merge

Initial error budget policy:

- If failed/aborted runs exceed 20% for a 7-day window on a workflow, freeze parallel expansion and revert to single implementer + reviewer until stable.

## Circuit Breakers

Stop and quarantine a lane when any trigger fires:

1. Coverage or tests regress from baseline unexpectedly.
2. Agent repeatedly edits files outside declared FD scope.
3. Diff size is materially larger than FD scope without justification.
4. Same check fails more than 2 times consecutively for the same lane.

Quarantine action:

1. Stop merging that lane.
2. Preserve artifacts/logs.
3. Rerun from last clean point with tighter scope.

## Merge Criteria

Merge only when all are true:

1. FD acceptance criteria satisfied.
2. Required gates pass.
3. Reviewer findings resolved.
4. Scope remains within declared FD boundaries (or FD updated explicitly).

## Daily Loop

1. Prime context and inspect current FD state.
2. Run explore/exploit/delete discipline on active FD.
3. Keep diffs small and isolate lanes with worktrees.
4. Verify with `fd-verify` workflow.
5. Close with `fd-close` only after verification.
6. Record learnings for reuse.

## Minimal Command Sequence (Reference)

```bash
# isolate lane
git worktree add ../seedpipe-fd-123-a -b codex/fd-123-agent-a

# implement and validate
pytest tests/ -v

# when pipeline/contracts changed
seedpipe-compile

# final sanity
git status
```

Use this file with `docs/agentic_command_policy.md` for enforceable command-level behavior.
