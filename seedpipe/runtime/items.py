from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from .ctx import StageContext


def iter_items_deterministic(ctx: StageContext, items_artifact: str = "items.jsonl") -> Iterator[dict[str, Any]]:
    path = ctx.resolve_artifact(items_artifact)
    if not path.exists():
        raise FileNotFoundError(f"items artifact not found: {path}")

    rows: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError("each items.jsonl row must be a JSON object")
        rows.append(row)

    rows.sort(key=lambda row: str(row.get("item_id", "")))
    yield from rows
