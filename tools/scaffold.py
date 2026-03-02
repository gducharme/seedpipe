#!/usr/bin/env python3
"""Scaffold a minimal Seedpipe spec + contracts layout."""

from __future__ import annotations

import argparse
from importlib import metadata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

PIPELINE_TEMPLATE = """pipeline_id: example-pipeline
item_unit: item
determinism_policy: strict
stages:
  - id: ingest
    mode: whole_run
    inputs: []
    outputs:
      - family: items
        pattern: items.jsonl
        schema: items_row.schema.json
  - id: transform
    mode: per_item
    inputs:
      - family: items
        pattern: items.jsonl
        schema: items_row.schema.json
    outputs:
      - family: transformed
        pattern: transformed.jsonl
        schema: transformed_row.schema.json
  - id: future_review
    mode: whole_run
    placeholder: true
    inputs:
      - family: transformed
        pattern: transformed.jsonl
        schema: transformed_row.schema.json
    outputs:
      - family: reviewed
        pattern: reviewed.jsonl
        schema: reviewed_row.schema.json
  - id: publish
    mode: whole_run
    inputs:
      - family: reviewed
        pattern: reviewed.jsonl
        schema: reviewed_row.schema.json
    outputs:
      - family: manifest
        pattern: manifest.json
        schema: manifest.schema.json
"""

LOOP_PIPELINE_TEMPLATE = """pipeline_id: example-pipeline-loop
item_unit: item
determinism_policy: strict
pipeline_type: looping
max_loops: 3
stages:
  - id: ingest
    mode: whole_run
    inputs: []
    outputs:
      - family: items
        pattern: items.jsonl
        schema: items_row.schema.json
  - id: seed
    mode: per_item
    inputs:
      - family: items
        pattern: items.jsonl
        schema: items_row.schema.json
    outputs:
      - family: seeded
        pattern: seeded.jsonl
        schema: items_row.schema.json
    reentry: retry_seed
  - id: transform
    mode: per_item
    inputs:
      - family: seeded
        pattern: seeded.jsonl
        schema: items_row.schema.json
    outputs:
      - family: transformed
        pattern: transformed.jsonl
        schema: transformed_row.schema.json
    go_to: retry_seed
  - id: publish
    mode: whole_run
    inputs:
      - family: transformed
        pattern: transformed.jsonl
        schema: transformed_row.schema.json
    outputs:
      - family: manifest
        pattern: manifest.json
        schema: manifest.schema.json
"""

ARTIFACT_REF_SCHEMA_TEMPLATE = """{
  \"$schema\": \"https://json-schema.org/draft/2020-12/schema\",
  \"$id\": \"seedpipe://spec/phase1/contracts/artifact_ref.schema.json\",
  \"title\": \"ArtifactRef\",
  \"type\": \"object\",
  \"additionalProperties\": false,
  \"required\": [\"name\", \"path\", \"hash\", \"schema_version\", \"produced_by\"],
  \"properties\": {
    \"name\": { \"type\": \"string\", \"minLength\": 1 },
    \"path\": { \"type\": \"string\", \"minLength\": 1 },
    \"hash\": { \"type\": \"string\", \"pattern\": \"^[a-z0-9]+:[0-9a-f]{8,}$\" },
    \"schema_version\": { \"type\": \"string\", \"minLength\": 1 },
    \"produced_by\": {
      \"type\": \"object\",
      \"additionalProperties\": false,
      \"required\": [\"run_id\", \"stage_id\"],
      \"properties\": {
        \"run_id\": { \"type\": \"string\", \"minLength\": 1 },
        \"stage_id\": { \"type\": \"string\", \"minLength\": 1 },
        \"attempt\": { \"type\": \"integer\", \"minimum\": 1 }
      }
    }
  }
}
"""

ITEM_STATE_SCHEMA_TEMPLATE = """{
  \"$schema\": \"https://json-schema.org/draft/2020-12/schema\",
  \"$id\": \"seedpipe://spec/phase1/contracts/item_state_row.schema.json\",
  \"title\": \"ItemStateRow\",
  \"type\": \"object\",
  \"additionalProperties\": false,
  \"required\": [\"run_id\", \"item_id\", \"state\", \"updated_at\"],
  \"properties\": {
    \"run_id\": { \"type\": \"string\", \"minLength\": 1 },
    \"item_id\": { \"type\": \"string\", \"minLength\": 1 },
    \"state\": {
      \"type\": \"string\",
      \"enum\": [\"pending\", \"in_progress\", \"succeeded\", \"failed\", \"skipped\", \"quarantined\"]
    },
    \"updated_at\": { \"type\": \"string\", \"format\": \"date-time\" }
  }
}
"""

ITEMS_ROW_SCHEMA_TEMPLATE = """{
  \"$schema\": \"https://json-schema.org/draft/2020-12/schema\",
  \"$id\": \"seedpipe://spec/phase1/contracts/items_row.schema.json\",
  \"title\": \"ItemsRow\",
  \"type\": \"object\",
  \"additionalProperties\": true,
  \"required\": [\"item_id\"],
  \"properties\": {
    \"item_id\": { \"type\": \"string\", \"minLength\": 1 }
  }
}
"""

MANIFEST_SCHEMA_TEMPLATE = """{
  \"$schema\": \"https://json-schema.org/draft/2020-12/schema\",
  \"$id\": \"seedpipe://spec/phase1/contracts/manifest.schema.json\",
  \"title\": \"SeedpipeRunManifest\",
  \"type\": \"object\",
  \"additionalProperties\": false,
  \"required\": [
    \"manifest_version\", \"run_id\", \"pipeline_id\", \"code_version\", \"config_hash\", \"inputs\", \"stage_outputs\", \"created_at\"
  ],
  \"properties\": {
    \"manifest_version\": { \"type\": \"string\", \"const\": \"phase1-v0\" },
    \"run_id\": { \"type\": \"string\", \"minLength\": 1 },
    \"pipeline_id\": { \"type\": \"string\", \"minLength\": 1 },
    \"code_version\": { \"type\": \"string\", \"minLength\": 1 },
    \"config_hash\": { \"type\": \"string\", \"pattern\": \"^[a-z0-9]+:[0-9a-f]{8,}$\" },
    \"created_at\": { \"type\": \"string\", \"format\": \"date-time\" },
    \"inputs\": { \"type\": \"array\", \"items\": { \"$ref\": \"seedpipe://spec/phase1/contracts/artifact_ref.schema.json\" } },
    \"stage_outputs\": {
      \"type\": \"array\",
      \"items\": {
        \"type\": \"object\",
        \"additionalProperties\": false,
        \"required\": [\"stage_id\", \"outputs\"],
        \"properties\": {
          \"stage_id\": { \"type\": \"string\", \"minLength\": 1 },
          \"outputs\": {
            \"type\": \"array\",
            \"items\": { \"$ref\": \"seedpipe://spec/phase1/contracts/artifact_ref.schema.json\" }
          }
        }
      }
    }
  }
}
"""

METRICS_CONTRACT_SCHEMA_TEMPLATE = """{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Metrics Contract",
  "description": "Schema for function-level metrics artifacts",
  "type": "object",
  "additionalProperties": false,
  "required": ["function_id", "metric_name", "value", "unit", "timestamp", "run_id", "producer"],
  "properties": {
    "function_id": { "type": "string", "description": "Stable identifier for the function being measured" },
    "metric_name": {
      "type": "string",
      "description": "Name of the metric being reported",
      "enum": ["latency", "cost", "success_count", "failure_count", "quality_rating"]
    },
    "value": { "type": "number", "description": "Numeric value of the metric" },
    "unit": {
      "type": "string",
      "description": "Unit of measurement (must be one of: ms, USD, count, 1-5)",
      "enum": ["ms", "USD", "count", "1-5"]
    },
    "timestamp": { "type": "string", "format": "date-time", "description": "ISO 8601 timestamp when metric was recorded" },
    "run_id": { "type": "string", "description": "Run ID this metric belongs to" },
    "producer": { "type": "string", "description": "Identifier of the agent or system producing this metric" }
  }
}
"""




STAGE_ITEMS_ROW_SCHEMA_TEMPLATE = """{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": true,
  "required": ["item_id"],
  "properties": {
    "item_id": { "type": "string", "minLength": 1 }
  }
}
"""

STAGE_SEEDED_ROW_SCHEMA_TEMPLATE = """{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": true,
  "required": ["item_id"],
  "properties": {
    "item_id": { "type": "string", "minLength": 1 }
  }
}
"""

STAGE_TRANSFORMED_ROW_SCHEMA_TEMPLATE = """{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": true,
  "required": ["item_id", "transformed"],
  "properties": {
    "item_id": { "type": "string", "minLength": 1 },
    "transformed": { "type": "boolean" }
  }
}
"""

STAGE_REVIEWED_ROW_SCHEMA_TEMPLATE = """{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": true,
  "required": ["item_id", "transformed"],
  "properties": {
    "item_id": { "type": "string", "minLength": 1 },
    "transformed": { "type": "boolean" }
  }
}
"""

STAGE_MANIFEST_SCHEMA_TEMPLATE = """{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": true,
  "required": ["pipeline_id"],
  "properties": {
    "pipeline_id": { "type": "string", "minLength": 1 }
  }
}
"""

def _load_agents_readme_template() -> str:
    readme_path = REPO_ROOT / "README.md"
    if readme_path.exists():
        return readme_path.read_text()
    try:
        package_metadata = metadata.metadata("seedpipe")
    except metadata.PackageNotFoundError:
        package_metadata = None
    if package_metadata is not None:
        description = package_metadata.get_payload().strip()
        if description:
            return f"{description}\n"
    return "# Seedpipe\n\nProject README was unavailable at scaffold time.\n"

BASE_TEMPLATES = {
    Path("agents.markdown"): """# Seedpipe agent guide

- Never edit files under `generated/`; they are compiler output and will be overwritten.
- Put hand-written stage logic in `src/stages/*.py`.
- If pipeline structure changes, update `docs/specs/phase1/pipeline.yaml` and re-run `seedpipe-compile`.
- Keep contract schemas in `docs/specs/phase1/contracts/` in sync with artifact formats.
- `artifacts/inputs/` should contain the artifacts required to start a run.
- `artifacts/outputs/<run_id>/` should contain stage artifacts for that specific run ID.
- CLI entrypoints may be unavailable until installation; use `python -m tools.scaffold|compile|run` from a checkout.
- Use `seedpipe-scaffold --loop` to generate a loop-enabled starter pipeline with `pipeline_type: looping`, `max_loops`, and `reentry`/`go_to` stage wiring.

## Practical implementation notes

- After stage-order edits in `docs/specs/phase1/pipeline.yaml`, use a new `run-id`. Reusing an old run ID can fail with `ValueError: run manifest stage order does not match compiled flow`.
- Runtime schema validation loads declared output payloads as JSON. Declaring `.txt`, `.md`, or `.csv` outputs with schemas can fail at JSON parsing.
- Preferred output pattern:
  - Keep machine-contract outputs in JSON artifacts declared in `pipeline.yaml`.
  - Write human-readable `.md` or `.csv` as side artifacts from stage code unless wrapped in JSON.
- Side artifacts are a convenience layer; the canonical contract should stay in JSON for downstream stage consumption.
- In loop pipelines, prefer returning `ItemResult(ok=False, error=...)` for business-rule failures in `run_item` and let runtime route failed cohorts through `go_to` reentry.
- For narrative diagnostics, keep explicit lanes:
  - `run_document_diagnostics` for document-level metrics.
  - `run_paragraph_diagnostics` for paragraph-level metrics.
  - `run_hybrid_diagnostics` for global baseline plus local anchors.
  - Merge lanes in `merge_report` into a stable bundle contract.

## Fast debug checklist

- Compile failures:
  - Confirm every object-form input/output defines `family`, `pattern`, and `schema`.
  - Confirm schema files exist under `spec/stages/<stage_id>/...`.
- Run failures:
  - Confirm stage code writes every declared output artifact.
  - Confirm produced output payload shape matches declared stage schema.
  - Use a new `run-id` after stage-graph edits.
""",
    Path("docs/specs/phase1/contracts/artifact_ref.schema.json"): ARTIFACT_REF_SCHEMA_TEMPLATE,
    Path("docs/specs/phase1/contracts/item_state_row.schema.json"): ITEM_STATE_SCHEMA_TEMPLATE,
    Path("docs/specs/phase1/contracts/items_row.schema.json"): ITEMS_ROW_SCHEMA_TEMPLATE,
    Path("docs/specs/phase1/contracts/manifest.schema.json"): MANIFEST_SCHEMA_TEMPLATE,
    Path("docs/specs/phase1/contracts/metrics_contract.schema.json"): METRICS_CONTRACT_SCHEMA_TEMPLATE,
    Path("spec/stages/ingest/items_row.schema.json"): STAGE_ITEMS_ROW_SCHEMA_TEMPLATE,
    Path("spec/stages/seed/items_row.schema.json"): STAGE_SEEDED_ROW_SCHEMA_TEMPLATE,
    Path("spec/stages/transform/transformed_row.schema.json"): STAGE_TRANSFORMED_ROW_SCHEMA_TEMPLATE,
    Path("spec/stages/future_review/reviewed_row.schema.json"): STAGE_REVIEWED_ROW_SCHEMA_TEMPLATE,
    Path("spec/stages/publish/manifest.schema.json"): STAGE_MANIFEST_SCHEMA_TEMPLATE,
    Path("artifacts/inputs/.gitkeep"): "",
    Path("artifacts/outputs/.gitignore"): "*\n!.gitignore\n",
    Path("inbox/.gitkeep"): "",
    Path("outbox/.gitkeep"): "",
    Path("Dockerfile"): """FROM python:3.12-slim

WORKDIR /workspace

COPY . /workspace

RUN pip install --no-cache-dir -e .

CMD ["sh", "-lc", "seedpipe-compile && seedpipe-watch --pipeline all --poll-seconds 5 --inbox-root /inbox --inputs-root /artifacts/inputs --outputs-root /artifacts/outputs --outbox-root /workspace/outbox"]
""",
    Path("docker-compose.yml"): """version: "3.9"
services:
  seedpipe:
    build:
      context: .
      dockerfile: Dockerfile
    working_dir: /workspace
    volumes:
      - ./:/workspace
      - ./artifacts:/artifacts
      - ./inbox:/inbox
    command:
      - sh
      - -lc
      - seedpipe-compile && seedpipe-watch --pipeline all --poll-seconds 5 --inbox-root /inbox --inputs-root /artifacts/inputs --outputs-root /artifacts/outputs --outbox-root /workspace/outbox
""",
    Path("src/__init__.py"): "",
    Path("src/stages/__init__.py"): "",
    Path("src/stages/ingest.py"): """from __future__ import annotations

import json
from pathlib import Path


def run_whole(ctx) -> None:
    _ = ctx
    rows = [{"item_id": "item-001"}]
    payload = "".join(json.dumps(row) + "\\n" for row in rows)
    Path("artifacts/items.jsonl").write_text(payload)
""",
    Path("src/stages/transform.py"): """from __future__ import annotations

import json
from pathlib import Path


def run_item(ctx, item: dict[str, object]) -> None:
    _ = ctx
    output = Path("artifacts/transformed.jsonl")
    transformed = {"item_id": item.get("item_id", ""), "transformed": True}
    with output.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(transformed) + "\\n")
""",
    Path("src/stages/seed.py"): """from __future__ import annotations

import json
from pathlib import Path


def run_item(ctx, item: dict[str, object]) -> None:
    _ = ctx
    output = Path("seeded.jsonl")
    seeded = {"item_id": item.get("item_id", "")}
    with output.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(seeded) + "\\n")
""",
    Path("src/stages/publish.py"): """from __future__ import annotations

import json
from pathlib import Path


def run_whole(ctx) -> None:
    Path("artifacts/manifest.json").write_text(json.dumps({"pipeline_id": "example-pipeline"}))
""",
}


def scaffold_project(target_dir: Path, force: bool = False, loop: bool = False) -> list[Path]:
    pipeline_template = LOOP_PIPELINE_TEMPLATE if loop else PIPELINE_TEMPLATE
    templates = {
        Path("agents-readme.markdown"): _load_agents_readme_template(),
        **BASE_TEMPLATES,
        Path("docs/specs/phase1/pipeline.yaml"): pipeline_template,
    }
    created: list[Path] = []
    for relative_path, content in templates.items():
        output_path = target_dir / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists() and not force:
            raise FileExistsError(f"refusing to overwrite existing file: {output_path}")
        output_path.write_text(content)
        created.append(output_path)
    return created


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scaffold a minimal Seedpipe project layout")
    parser.add_argument("--dir", type=Path, default=Path.cwd(), help="Target directory (default: current directory)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing scaffold files")
    parser.add_argument("--loop", action="store_true", help="Generate a loop-enabled starter pipeline")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    created = scaffold_project(args.dir, force=args.force, loop=args.loop)
    print(f"Created {len(created)} files:")
    for path in created:
        print(path)


if __name__ == "__main__":
    main()
