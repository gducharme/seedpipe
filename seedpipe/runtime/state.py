from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def append_item_state_row(row: dict[str, Any], path: Path | None = None) -> None:
    target = path or Path("artifacts") / "item_state.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")
