#!/usr/bin/env python3
"""Scaffold a minimal Seedpipe spec + contracts layout."""

from __future__ import annotations

import argparse
from pathlib import Path

PIPELINE_TEMPLATE = """pipeline_id: example-pipeline
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
  - id: future_review
    mode: whole_run
    placeholder: true
    inputs:
      - transformed.jsonl
    outputs:
      - reviewed.jsonl
  - id: publish
    mode: whole_run
    inputs:
      - reviewed.jsonl
    outputs:
      - manifest.json
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

TEMPLATES = {
    Path("spec/phase1/pipeline.yaml"): PIPELINE_TEMPLATE,
    Path("spec/phase1/contracts/artifact_ref.schema.json"): ARTIFACT_REF_SCHEMA_TEMPLATE,
    Path("spec/phase1/contracts/item_state_row.schema.json"): ITEM_STATE_SCHEMA_TEMPLATE,
    Path("spec/phase1/contracts/items_row.schema.json"): ITEMS_ROW_SCHEMA_TEMPLATE,
    Path("spec/phase1/contracts/manifest.schema.json"): MANIFEST_SCHEMA_TEMPLATE,
    Path("artifacts/inputs/.gitkeep"): "",
    Path("artifacts/outputs/.gitkeep"): "",
}


def scaffold_project(target_dir: Path, force: bool = False) -> list[Path]:
    created: list[Path] = []
    for relative_path, content in TEMPLATES.items():
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    created = scaffold_project(args.dir, force=args.force)
    print(f"Created {len(created)} files:")
    for path in created:
        print(path)


if __name__ == "__main__":
    main()
