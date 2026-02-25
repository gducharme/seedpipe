# Spec: Directory-Based Pipes with Per-Pipe Runtime Isolation (Docker-First)

## Status

Draft

## Objective

Define the default architecture where:

- **seedpipe** is installed once as a *launcher/runtime orchestrator*,
- each **pipe** is a self-contained **directory root**,
- each pipe may pin a **different seedpipe runtime version** and dependency set,
- execution is **isolated per pipe**, typically via Docker, enabling time-travel stability and composable subpipes.

## Core Definitions

- **Pipe Root**: a filesystem directory representing one independent workflow instance (not a Python distribution).
- **Runner**: an execution backend that runs a pipe root (e.g., docker, local).
- **Runtime Pin**: the declaration of the exact seedpipe runtime + environment required by a pipe root.

## Architecture Overview

### High-Level Model

The system is composed of two distinct layers:

- **Host Launcher** (single installation)
- **Per-Pipe Runtime** (isolated execution environment, usually Docker)

The host `seedpipe` CLI is a thin orchestration tool. It does not execute pipelines directly in the default model.

Instead, it:

- reads a pipe root,
- resolves the runtime defined in `seedpipe.lock`,
- starts the correct execution environment,
- delegates execution to the runtime inside that environment.

This makes every pipe:

- independently reproducible,
- version-isolated,
- composable,
- safe to run concurrently.

### Layer 1 — Host Launcher

Installed once per machine / CI environment:

```bash
pip install seedpipe
```

The launcher is responsible only for:

- locating the pipe root,
- parsing `seedpipe.lock`,
- selecting the runner (`docker` by default),
- resolving or building the runtime image,
- mounting the pipe directory into the runtime,
- forwarding CLI arguments,
- returning exit codes.

It must not:

- execute pipeline logic,
- import pipe stage code,
- maintain global mutable state,
- depend on pipe-specific Python packages.

Conceptually it behaves like:

```bash
docker run <resolved-runtime> /work
```

### Layer 2 — Per-Pipe Runtime

The runtime is where the actual pipeline execution happens.

Each pipe root pins its runtime in `seedpipe.lock`.

This runtime defines:

- seedpipe engine version,
- Python version (optional but typical),
- stage dependencies,
- execution backend.

Inside the container the command is:

```bash
python -m seedpipe._runtime run /work
```

So the executing seedpipe version is the one inside the container, not the host.

This allows:

- different pipes -> different seedpipe versions,
- old pipes -> remain runnable,
- new pipes -> upgrade independently.

### Pipe Root as the Unit of Isolation

A pipe is a self-contained directory:

```text
pipes/<pipe_id>/
```

It contains:

- workflow definition (`pipeline.yaml`),
- runtime pin (`seedpipe.lock`),
- stage logic (`src/`),
- generated orchestrator (`generated/`),
- outputs (`artifacts/`),
- locks (`locks/`).

All reads and writes are root-scoped. No cross-pipe state exists by default.

## Non-Goals

- Plugin packaging, entry points, multi-distribution installs for pipes.
- Global registries of available pipes.

## Directory Contract (Pipe Root Layout)

A pipe root MUST be self-contained:

```text
pipes/<pipe_id>/
  pipeline.yaml
  seedpipe.lock            # REQUIRED: runtime pin + environment pin
  src/                     # user-authored stage logic (optional but typical)
  generated/               # compiler output (optional; may be regenerated)
  artifacts/               # outputs, manifests, progress, defects
  locks/                   # root-scoped locks
  .seedpipe/               # OPTIONAL internal working dir, MUST be root-scoped
```

### seedpipe.lock (Required)

Purpose: freeze the runtime/environment used to execute this pipe.

Minimum fields:

- `runner`: `"docker" | "local"` (default `"docker"`)
- `runtime`:
  - `seedpipe_version`: `"X.Y.Z"` *(or)*
  - `image`: `"ghcr.io/org/seedpipe-runtime@sha256:<digest>"`
- `python`: `"3.12"` (if building images)
- `deps`: list of pip requirements OR reference to `requirements.lock`
- `api_version`: `"1"`  # host<->pipe contract version

Key invariant:

- Two different pipe roots MAY specify different seedpipe versions and dependency graphs without conflict.

## CLI Contract

```bash
seedpipe run <PIPE_ROOT> [--runner docker|local] [--] [runner_args...]
```

Examples:

- `seedpipe run ./pipes/pr`
- `seedpipe run ./pipes/qa --runner docker`
- `seedpipe compile ./pipes/pr`
- `seedpipe verify ./pipes/pr`
- `seedpipe init ./pipes/new_feature`

## Execution Semantics

### Root-Scoped Runtime

All runtime reads/writes must be relative to `PIPE_ROOT` unless explicitly configured otherwise.

MUST NOT:

- write to shared `~/.seedpipe` by default
- use global registries
- use caches not keyed by `(pipe_root, runtime_digest)`

MAY:

- use global cache ONLY if keyed by runtime digest + pipe root hash (safe dedupe)

### Artifact Isolation

Each pipe root owns its own:

- `artifacts/`
- `manifest.json` (or `artifacts/manifest.json`)
- `progress.json`
- `defects/`
- `locks/`

No cross-pipe sharing by default.

## Docker Runner (Default)

### Behavior

- Resolve the runtime pin from `seedpipe.lock`
- Ensure the runtime image exists (pull or build)
- Run container with:
  - bind mount `PIPE_ROOT` to `/work`
  - working dir `/work`
  - command: `python -m seedpipe._runtime run /work` (or equivalent internal entry)
- All outputs written under `/work/artifacts` etc.

### Benefits

- per-pipe dependency isolation
- per-pipe seedpipe version pinning
- reproducible runs across machines and time
- safe concurrency across many pipe roots

## Local Runner (Optional)

Used for fast iteration:

- Executes in current Python environment
- Still MUST honor root-scoped IO + locking
- Warn if `seedpipe.lock` specifies a different `seedpipe_version` than installed (but allow override flag)

## Composability: Subpipe as a Stage

Support a first-class stage type:

- `stage_kind`: `"subpipe"`
- `subpipe_root`: `"./pipes/qa"` (path relative to parent pipe root)
- inputs/outputs mapping rules

Semantics:

- Running a parent pipe may invoke child pipes via the same runner mechanism.
- Child pipe executes in its own isolated runtime pin (docker image digest) even if parent differs.

## Concurrency & Locks

- Locks MUST be root-scoped (`PIPE_ROOT/locks`)
- Running two different pipe roots concurrently must never block each other.
- Running the same pipe root concurrently must use a deterministic lock policy (fail fast by default).

## Acceptance Criteria

1. Two pipe roots with different seedpipe versions run successfully in the same host repo.
2. Each writes artifacts only inside its own root.
3. Parent pipe can invoke a subpipe root as a stage without importing its code.
4. Upgrading host’s seedpipe launcher does not break historical pipe roots (because docker pins runtime).
5. A failing pipe does not corrupt or block other pipe roots.

## Migration Notes (from shared-env model)

- Introduce `seedpipe.lock` in each pipe root
- Implement docker runner as default
- Keep local runner for dev convenience, but docker is the reproducibility contract
