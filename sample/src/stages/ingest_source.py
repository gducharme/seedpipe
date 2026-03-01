from __future__ import annotations

import json
from pathlib import Path


def run_whole(ctx) -> None:
    _ = ctx
    rows = [
        {"item_id": "p-001", "text": "Hello world."},
        {"item_id": "p-002", "text": "How are you?"},
    ]
    output = Path("items.jsonl")
    output.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
