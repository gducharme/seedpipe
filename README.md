# seedpipe

`seedpipe` can be installed directly from a local checkout without publishing to PyPI.

## Install from a local path

From another project, add this repository as a local dependency:

```bash
python -m pip install /path/to/seedpipe
```

For editable development installs:

```bash
python -m pip install -e /path/to/seedpipe
```

## What gets installed

- `seedpipe` package.
- `tools` package (including `tools.compile` and `tools.scaffold`).
- `seedpipe-compile` CLI entrypoint.
- `seedpipe-scaffold` CLI entrypoint.
- `seedpipe-run` CLI entrypoint.

After install, you can run:

```bash
seedpipe-compile --help
seedpipe-scaffold --help
seedpipe-run --help
```

Or import in Python:

```python
from tools.compile import compile_pipeline, CompilePaths
from tools.scaffold import scaffold_project
```

## Start a new project with scaffold

To bootstrap a minimal Seedpipe layout in your current directory:

```bash
seedpipe-scaffold
```

This creates:

- `spec/phase1/pipeline.yaml`
- `spec/phase1/contracts/*.schema.json`
- `artifacts/inputs/.gitkeep`
- `artifacts/outputs/.gitkeep`

To scaffold somewhere else:

```bash
seedpipe-scaffold --dir /path/to/your/project
```

Use `--force` to overwrite an existing scaffold.

## Simple pipeline example

The scaffold command writes this starter pipeline:

```yaml
pipeline_id: example-pipeline
item_unit: item
determinism_policy: strict
stages:
  - id: ingest
    mode: whole_run
    inputs: []
    outputs:
      - items.jsonl
  - id: transform
    mode: per_item
    inputs:
      - items.jsonl
    outputs:
      - transformed.jsonl
  - id: publish
    mode: whole_run
    inputs:
      - transformed.jsonl
    outputs:
      - manifest.json
```

## Compile a pipeline specification

Run the compiler against a pipeline file and contracts directory:

```bash
seedpipe-compile \
  --pipeline ./spec/phase1/pipeline.yaml \
  --contracts-dir ./spec/phase1/contracts \
  --output-dir ./generated
```

This generates orchestration/runtime code and metadata in `./generated`.

If your repository uses the default layout (`spec/phase1/pipeline.yaml`,
`spec/phase1/contracts`, `generated`), run:

```bash
python -m tools.compile
```

This command compiles the pipeline using defaults and refreshes everything under `generated/`.

You can also use the installed entrypoint:

```bash
seedpipe-compile
```

## Run a compiled pipeline

After compiling, execute the generated flow with:

```bash
seedpipe-run --run-id my-run-001
```

By default this loads `generated/flow.py`, creates a run directory at
`./artifacts/outputs/<run-id>`, and executes the flow from inside that run directory.

Use:
- `--generated-dir` when compiled flow code lives somewhere other than `./generated`.
- `--inputs-dir` to set the consumable input root (default: `./artifacts/inputs`).
- `--output-dir` to override the run output directory.
- `--attempt` to set a non-default retry attempt number.

`seedpipe-run` will error if the run output directory already exists (including the default `./artifacts/outputs/<run-id>` path), and will error if the inputs directory does not exist.

## Use the compiler from Python

```python
from pathlib import Path
from tools.compile import CompilePaths, compile_pipeline

result = compile_pipeline(
    CompilePaths(
        pipeline_path=Path("spec/phase1/pipeline.yaml"),
        contracts_dir=Path("spec/phase1/contracts"),
        output_dir=Path("generated"),
    )
)

print(result["pipeline_id"], result["output_dir"])
```
