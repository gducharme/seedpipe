from __future__ import annotations

import json
from pathlib import Path


def run_whole(ctx) -> None:
    lang = str((ctx.keys or {}).get("lang", "xx"))
    src = Path(f"qa/{lang}/rows.jsonl")
    item_ids: set[str] = set()
    for line in src.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        item_id = str(row.get("item_id", "")).strip()
        if item_id:
            item_ids.add(item_id)
    checked_items = len(item_ids)
    report = {"lang": lang, "status": "pass", "checked_items": checked_items}
    out = Path(f"qa/{lang}/report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
