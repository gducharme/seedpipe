from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from seedpipe.runtime.ctx import StageContext


class StageContextTests(unittest.TestCase):
    def test_resolve_artifact_defaults_to_run_root_for_relative_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            ctx = StageContext.make_base(run_config={"run_id": "r-1"}, run_dir=run_dir)
            self.assertEqual(ctx.resolve_artifact("paragraphs.jsonl"), run_dir / "paragraphs.jsonl")

    def test_resolve_artifact_keeps_explicit_artifacts_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            ctx = StageContext.make_base(run_config={"run_id": "r-1"}, run_dir=run_dir)
            self.assertEqual(ctx.resolve_artifact("artifacts/items.jsonl"), run_dir / "artifacts" / "items.jsonl")


if __name__ == "__main__":
    unittest.main()
