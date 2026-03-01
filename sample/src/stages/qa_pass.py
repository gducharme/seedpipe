from __future__ import annotations

import json
from pathlib import Path

from seedpipe.generated.models import ItemResult


FAIL_ONCE_MARKER = Path(".qa_fail_once_marker")


def run_item(ctx, item: dict[str, object]) -> ItemResult:
    lang = str((ctx.keys or {}).get("lang", "xx"))
    item_id = str(item.get("item_id", ""))
    loop_iteration = int(ctx.run_config.get("_loop_iteration", 1))

    # Deterministic demo failure: fail exactly once for fr/p-001 on first loop.
    if lang == "fr" and item_id == "p-001" and loop_iteration == 1 and not FAIL_ONCE_MARKER.exists():
        FAIL_ONCE_MARKER.write_text("failed-once\n", encoding="utf-8")
        return ItemResult(
            item_id=item_id,
            ok=False,
            error={"code": "qa_retry", "message": "intentional first-pass failure", "source": "stage"},
        )

    output = Path(f"qa/{lang}/rows.jsonl")
    output.parent.mkdir(parents=True, exist_ok=True)
    row = {"item_id": item_id, "lang": lang, "ok": True}
    with output.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")
    return ItemResult(item_id=item_id, ok=True)
