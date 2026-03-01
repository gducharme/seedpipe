from __future__ import annotations

import json
from pathlib import Path


def run_item(ctx, item: dict[str, object]) -> None:
    lang = str((ctx.keys or {}).get("lang", "xx"))
    output = Path(f"pass1_pre/{lang}/paragraphs.jsonl")
    output.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "item_id": str(item.get("item_id", "")),
        "lang": lang,
        "text": f"draft({lang}): {item.get('text', '')}",
    }
    with output.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")
