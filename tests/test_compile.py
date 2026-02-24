from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.compile import CompileError, CompilePaths, build_ir, compile_pipeline, normalize_pipeline, validate_pipeline_structure


class CompilePipelineTests(unittest.TestCase):
    def test_normalize_pipeline_applies_defaults(self) -> None:
        raw = {
            "pipeline_id": "p1",
            "stages": [
                {"id": "ingest", "outputs": ["items.jsonl"]},
            ],
        }

        normalized = normalize_pipeline(raw)

        self.assertEqual(normalized["item_unit"], "item")
        self.assertEqual(normalized["determinism_policy"], "strict")
        self.assertEqual(normalized["stages"][0]["inputs"], [])
        self.assertEqual(normalized["stages"][0]["mode"], "whole_run")

    def test_validate_pipeline_structure_rejects_forward_references(self) -> None:
        normalized = {
            "pipeline_id": "p1",
            "item_unit": "item",
            "determinism_policy": "strict",
            "stages": [
                {
                    "id": "transform",
                    "mode": "whole_run",
                    "inputs": ["items.jsonl"],
                    "outputs": ["transformed.jsonl"],
                },
                {
                    "id": "ingest",
                    "mode": "whole_run",
                    "inputs": [],
                    "outputs": ["items.jsonl"],
                },
            ],
        }

        with self.assertRaises(CompileError):
            validate_pipeline_structure(normalized)

    def test_build_ir_captures_artifact_producers(self) -> None:
        pipeline = {
            "pipeline_id": "p1",
            "item_unit": "item",
            "determinism_policy": "strict",
            "stages": [
                {"id": "ingest", "mode": "whole_run", "inputs": [], "outputs": ["items.jsonl"]},
                {
                    "id": "transform",
                    "mode": "per_item",
                    "inputs": ["items.jsonl"],
                    "outputs": ["transformed.jsonl"],
                },
            ],
        }

        ir = build_ir(pipeline)

        self.assertEqual(ir.pipeline_id, "p1")
        self.assertEqual(ir.stages[1].mode, "per_item")
        self.assertEqual(ir.artifact_producers["items.jsonl"], "ingest")
        self.assertEqual(ir.artifact_producers["transformed.jsonl"], "transform")

    def test_compile_pipeline_emits_expected_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pipeline_path = root / "pipeline.yaml"
            contracts_dir = root / "contracts"
            output_dir = root / "generated"
            contracts_dir.mkdir()

            pipeline_path.write_text(
                json.dumps(
                    {
                        "pipeline_id": "phase1-default",
                        "item_unit": "item",
                        "determinism_policy": "strict",
                        "stages": [
                            {
                                "id": "ingest",
                                "mode": "whole_run",
                                "inputs": [],
                                "outputs": ["items.jsonl"],
                            },
                            {
                                "id": "publish",
                                "mode": "whole_run",
                                "inputs": ["items.jsonl"],
                                "outputs": ["published_manifest.json"],
                            },
                        ],
                    }
                )
            )

            contracts = {
                "artifact_ref.schema.json": {"type": "object"},
                "item_state_row.schema.json": {"type": "object"},
                "items_row.schema.json": {"type": "object"},
                "manifest.schema.json": {"type": "object"},
            }
            for name, payload in contracts.items():
                (contracts_dir / name).write_text(json.dumps(payload))

            result = compile_pipeline(
                CompilePaths(
                    pipeline_path=pipeline_path,
                    contracts_dir=contracts_dir,
                    output_dir=output_dir,
                )
            )

            self.assertEqual(result["pipeline_id"], "phase1-default")
            self.assertTrue((output_dir / "flow.py").exists())
            self.assertTrue((output_dir / "models.py").exists())
            self.assertTrue((output_dir / "stages" / "ingest.py").exists())
            self.assertTrue((output_dir / "stages" / "__init__.py").exists())

            flow_text = (output_dir / "flow.py").read_text()
            self.assertIn("append_item_state_row", flow_text)

            ingest_wrapper = (output_dir / "stages" / "ingest.py").read_text()
            self.assertIn("def run_whole", ingest_wrapper)

            stages_init = (output_dir / "stages" / "__init__.py").read_text()
            self.assertIn("__all__", stages_init)

            compile_report = json.loads((output_dir / "compile_report.json").read_text())
            self.assertEqual(
                compile_report["artifact_schema_map"]["published_manifest.json"],
                "manifest.schema.json",
            )


if __name__ == "__main__":
    unittest.main()
