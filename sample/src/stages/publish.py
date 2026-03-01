from __future__ import annotations

import json
from pathlib import Path


def run_whole(ctx) -> None:
    _ = ctx
    manifest = {
        "pipeline_id": "localization-release",
        "published_reports": [
            "qa/fr/report.json",
            "qa/de/report.json",
            "qa/es/report.json",
        ],
    }
    Path("published_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
