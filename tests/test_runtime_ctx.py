from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from seedpipe.runtime.ctx import StageContext


class StageContextSchemaValidationTests(unittest.TestCase):
    def test_validate_expected_outputs_enforces_jsonl_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "artifacts" / "outputs" / "run-1"
            run_dir.mkdir(parents=True)

            schema_dir = root / "spec" / "stages" / "ingest"
            schema_dir.mkdir(parents=True)
            (schema_dir / "rows.schema.json").write_text(
                json.dumps(
                    {
                        "type": "object",
                        "required": ["item_id"],
                        "properties": {"item_id": {"type": "string", "minLength": 1}},
                        "additionalProperties": True,
                    }
                )
            )
            (run_dir / "rows.jsonl").write_text('{"item_id":"ok"}\n')

            base = StageContext.make_base(run_config={"run_id": "run-1", "_pipe_root": str(root)}, run_dir=run_dir)
            ctx = base.for_stage(
                "ingest",
                expected_outputs=[{"path": "rows.jsonl", "schema": "rows.schema.json"}],
            )
            ctx.validate_expected_outputs("ingest")

    def test_validate_expected_outputs_raises_on_schema_violation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "artifacts" / "outputs" / "run-2"
            run_dir.mkdir(parents=True)

            schema_dir = root / "spec" / "stages" / "publish"
            schema_dir.mkdir(parents=True)
            (schema_dir / "manifest.schema.json").write_text(
                json.dumps(
                    {
                        "type": "object",
                        "required": ["pipeline_id"],
                        "properties": {"pipeline_id": {"type": "string", "minLength": 1}},
                        "additionalProperties": True,
                    }
                )
            )
            (run_dir / "manifest.json").write_text(json.dumps({"wrong": True}))

            base = StageContext.make_base(run_config={"run_id": "run-2", "_pipe_root": str(root)}, run_dir=run_dir)
            ctx = base.for_stage(
                "publish",
                expected_outputs=[{"path": "manifest.json", "schema": "manifest.schema.json"}],
            )
            with self.assertRaises(ValueError):
                ctx.validate_expected_outputs("publish")

    def test_resolve_artifact_prefers_manifest_artifact_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "artifacts" / "outputs" / "run-3"
            run_dir.mkdir(parents=True)
            staged_path = run_dir / "transform" / "loops" / "0001" / "rows.jsonl"
            staged_path.parent.mkdir(parents=True)
            staged_path.write_text('{"item_id":"ok"}\n')

            base = StageContext.make_base(
                run_config={
                    "run_id": "run-3",
                    "_pipe_root": str(root),
                    "_artifact_index": {"rows.jsonl": "transform/loops/0001/rows.jsonl"},
                },
                run_dir=run_dir,
            )
            ctx = base.for_stage("publish")
            self.assertEqual(ctx.resolve_artifact("rows.jsonl"), staged_path)

    def test_resolve_artifact_uses_live_output_path_for_current_stage_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "artifacts" / "outputs" / "run-4"
            run_dir.mkdir(parents=True)
            indexed_path = run_dir / "transform" / "loops" / "0001" / "manifest.json"
            indexed_path.parent.mkdir(parents=True)
            indexed_path.write_text("{}")
            live_output = run_dir / "manifest.json"
            live_output.write_text("{}")

            base = StageContext.make_base(
                run_config={
                    "run_id": "run-4",
                    "_pipe_root": str(root),
                    "_artifact_index": {"manifest.json": "transform/loops/0001/manifest.json"},
                },
                run_dir=run_dir,
            )
            ctx = base.for_stage("publish", expected_outputs=[{"path": "manifest.json"}])
            self.assertEqual(ctx.resolve_artifact("manifest.json"), live_output)


if __name__ == "__main__":
    unittest.main()
