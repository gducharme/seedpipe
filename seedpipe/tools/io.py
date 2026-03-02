from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


def write_json_object(path: Path, payload: dict[str, Any], *, pretty: bool = True) -> None:
    if pretty:
        content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    else:
        content = json.dumps(payload, sort_keys=True) + "\n"
    path.write_text(content, encoding="utf-8")
