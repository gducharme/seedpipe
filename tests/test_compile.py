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



    def test_normalize_pipeline_expands_foreach_family_bind_dsl(self) -> None:
        raw = {
            "pipeline_id": "translation-pipeline",
            "item_unit": "paragraph",
            "determinism_policy": "strict",
            "params": {"targets": {"languages": ["fr", "de", "ar"]}},
            "stages": [
                {
                    "id": "translate_pass1",
                    "mode": "whole_run",
                    "inputs": ["paragraphs.jsonl"],
                    "outputs": [
                        {
                            "family": "pass1_translations",
                            "foreach": "params.targets.languages",
                            "as": "lang",
                            "pattern": "pass1_pre/{lang}/paragraphs.jsonl",
                        }
                    ],
                },
                {
                    "id": "translate_pass2",
                    "mode": "whole_run",
                    "foreach": "params.targets.languages",
                    "as": "lang",
                    "inputs": [
                        "paragraphs.jsonl",
                        {"family": "pass1_translations", "bind": "lang"},
                    ],
                    "outputs": [
                        {
                            "family": "pass2_translations",
                            "bind": "lang",
                            "pattern": "pass2_pre/{lang}/paragraphs.jsonl",
                        }
                    ],
                },
            ],
        }

        normalized = normalize_pipeline(raw)

        stages = normalized["stages"]
        self.assertEqual(stages[0]["outputs"], [
            "pass1_pre/fr/paragraphs.jsonl",
            "pass1_pre/de/paragraphs.jsonl",
            "pass1_pre/ar/paragraphs.jsonl",
        ])
        self.assertEqual(stages[1]["id"], "translate_pass2__fr")
        self.assertEqual(stages[1]["inputs"], ["paragraphs.jsonl", "pass1_pre/fr/paragraphs.jsonl"])
        self.assertEqual(stages[2]["id"], "translate_pass2__de")
        self.assertEqual(stages[2]["inputs"], ["paragraphs.jsonl", "pass1_pre/de/paragraphs.jsonl"])
        self.assertEqual(stages[3]["id"], "translate_pass2__ar")
        self.assertEqual(stages[3]["inputs"], ["paragraphs.jsonl", "pass1_pre/ar/paragraphs.jsonl"])

    def test_normalize_pipeline_rejects_unresolved_family_bind(self) -> None:
        raw = {
            "pipeline_id": "p1",
            "stages": [
                {
                    "id": "consumer",
                    "foreach": "params.targets.languages",
                    "as": "lang",
                    "inputs": [{"family": "pass1_translations", "bind": "lang"}],
                    "outputs": ["out.json"],
                }
            ],
            "params": {"targets": {"languages": ["fr"]}},
        }

        with self.assertRaises(CompileError):
            normalize_pipeline(raw)

    def test_load_pipeline_rejects_duplicate_top_level_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline_path = Path(tmpdir) / "pipeline.yaml"
            pipeline_path.write_text(
                """
pipeline_id: p1
stages: []
stages: []
""".strip()
            )

            with self.assertRaisesRegex(CompileError, "duplicate key in pipeline YAML: stages"):
                from tools.compile import load_pipeline

                load_pipeline(pipeline_path)

    def test_normalize_pipeline_rejects_stage_foreach_non_string_expression(self) -> None:
        raw = {
            "pipeline_id": "p1",
            "stages": [{"id": "s1", "foreach": ["bad"], "as": "lang", "outputs": ["x.json"]}],
        }

        with self.assertRaises(CompileError):
            normalize_pipeline(raw)

    def test_normalize_pipeline_rejects_stage_foreach_non_list_resolution(self) -> None:
        raw = {
            "pipeline_id": "p1",
            "params": {"targets": {"languages": "fr"}},
            "stages": [
                {"id": "s1", "foreach": "params.targets.languages", "as": "lang", "outputs": ["x.json"]}
            ],
        }

        with self.assertRaises(CompileError):
            normalize_pipeline(raw)

    def test_normalize_pipeline_rejects_stage_foreach_missing_as(self) -> None:
        raw = {
            "pipeline_id": "p1",
            "params": {"targets": {"languages": ["fr"]}},
            "stages": [{"id": "s1", "foreach": "params.targets.languages", "outputs": ["x.json"]}],
        }

        with self.assertRaises(CompileError):
            normalize_pipeline(raw)

    def test_normalize_pipeline_rejects_output_family_missing_bind_source(self) -> None:
        raw = {
            "pipeline_id": "p1",
            "stages": [
                {
                    "id": "producer",
                    "outputs": [{"family": "f", "pattern": "out/{lang}.json"}],
                }
            ],
        }

        with self.assertRaises(CompileError):
            normalize_pipeline(raw)

    def test_normalize_pipeline_rejects_output_family_bind_out_of_scope(self) -> None:
        raw = {
            "pipeline_id": "p1",
            "stages": [
                {
                    "id": "producer",
                    "outputs": [{"family": "f", "bind": "lang", "pattern": "out/{lang}.json"}],
                }
            ],
        }

        with self.assertRaises(CompileError):
            normalize_pipeline(raw)

    def test_normalize_pipeline_rejects_family_key_conflicts(self) -> None:
        raw = {
            "pipeline_id": "p1",
            "params": {"targets": {"languages": ["fr"]}},
            "stages": [
                {
                    "id": "producer_1",
                    "foreach": "params.targets.languages",
                    "as": "lang",
                    "outputs": [{"family": "f", "bind": "lang", "pattern": "out/{lang}.json"}],
                },
                {
                    "id": "producer_2",
                    "foreach": "params.targets.languages",
                    "as": "lang",
                    "outputs": [{"family": "f", "bind": "lang", "pattern": "other/{lang}.json"}],
                },
            ],
        }

        with self.assertRaises(CompileError):
            normalize_pipeline(raw)

    def test_normalize_pipeline_rejects_template_variable_not_in_scope(self) -> None:
        raw = {
            "pipeline_id": "p1",
            "stages": [{"id": "producer", "outputs": ["out/{lang}.json"]}],
        }

        with self.assertRaises(CompileError):
            normalize_pipeline(raw)

    def test_normalize_pipeline_supports_output_level_foreach(self) -> None:
        raw = {
            "pipeline_id": "p1",
            "params": {"targets": {"languages": ["fr", "de"]}},
            "stages": [
                {
                    "id": "producer",
                    "outputs": [
                        {
                            "family": "f",
                            "foreach": "params.targets.languages",
                            "as": "lang",
                            "pattern": "out/{lang}.json",
                        }
                    ],
                },
                {
                    "id": "consumer",
                    "foreach": "params.targets.languages",
                    "as": "lang",
                    "inputs": [{"family": "f", "bind": "lang"}],
                    "outputs": ["done/{lang}.json"],
                },
            ],
        }

        normalized = normalize_pipeline(raw)
        self.assertEqual(normalized["stages"][0]["outputs"], ["out/fr.json", "out/de.json"])
        self.assertEqual(normalized["stages"][1]["inputs"], ["out/fr.json"])
        self.assertEqual(normalized["stages"][2]["inputs"], ["out/de.json"])
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

    def test_compile_pipeline_supports_placeholder_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pipeline_path = root / "pipeline.yaml"
            contracts_dir = root / "contracts"
            output_dir = root / "generated"
            contracts_dir.mkdir()

            pipeline_path.write_text(
                json.dumps(
                    {
                        "pipeline_id": "phase1-placeholder",
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
                                "id": "future_review",
                                "mode": "whole_run",
                                "placeholder": True,
                                "inputs": ["items.jsonl"],
                                "outputs": ["reviewed.jsonl"],
                            },
                            {
                                "id": "publish",
                                "mode": "whole_run",
                                "inputs": ["reviewed.jsonl"],
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

            compile_pipeline(
                CompilePaths(
                    pipeline_path=pipeline_path,
                    contracts_dir=contracts_dir,
                    output_dir=output_dir,
                )
            )

            placeholder_wrapper = (output_dir / "stages" / "future_review.py").read_text()
            self.assertIn("def run_whole", placeholder_wrapper)
            self.assertNotIn("from seedpipe.src.stages import future_review as impl", placeholder_wrapper)
            self.assertNotIn("ctx.validate_inputs", placeholder_wrapper)
            self.assertNotIn("ctx.validate_outputs", placeholder_wrapper)
            self.assertIn("pass", placeholder_wrapper)

    def test_compile_pipeline_bootstraps_src_stage_impls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pipeline_path = root / "pipeline.yaml"
            contracts_dir = root / "contracts"
            output_dir = root / "generated"
            contracts_dir.mkdir()

            pipeline_path.write_text(
                json.dumps(
                    {
                        "pipeline_id": "phase1-src-bootstrap",
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
                                "id": "transform",
                                "mode": "per_item",
                                "inputs": ["items.jsonl"],
                                "outputs": ["transformed.jsonl"],
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

            compile_pipeline(
                CompilePaths(
                    pipeline_path=pipeline_path,
                    contracts_dir=contracts_dir,
                    output_dir=output_dir,
                )
            )

            self.assertTrue((root / "src" / "__init__.py").exists())
            self.assertTrue((root / "src" / "stages" / "__init__.py").exists())
            self.assertTrue((root / "src" / "stages" / "ingest.py").exists())
            self.assertTrue((root / "src" / "stages" / "transform.py").exists())

            ingest_impl = (root / "src" / "stages" / "ingest.py").read_text()
            transform_impl = (root / "src" / "stages" / "transform.py").read_text()
            self.assertIn("def run_whole", ingest_impl)
            self.assertIn("def run_item", transform_impl)

    def test_compile_pipeline_per_item_uses_stage_input_as_items_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pipeline_path = root / "pipeline.yaml"
            contracts_dir = root / "contracts"
            output_dir = root / "generated"
            contracts_dir.mkdir()

            pipeline_path.write_text(
                json.dumps(
                    {
                        "pipeline_id": "phase1-custom-item-artifact",
                        "item_unit": "paragraph",
                        "determinism_policy": "strict",
                        "stages": [
                            {
                                "id": "source_ingest",
                                "mode": "whole_run",
                                "inputs": [],
                                "outputs": ["paragraphs.jsonl", "manifest.json"],
                            },
                            {
                                "id": "translate_pass1",
                                "mode": "per_item",
                                "inputs": ["paragraphs.jsonl"],
                                "outputs": ["pass1_pre/paragraphs.jsonl"],
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

            compile_pipeline(
                CompilePaths(
                    pipeline_path=pipeline_path,
                    contracts_dir=contracts_dir,
                    output_dir=output_dir,
                )
            )

            flow_text = (output_dir / "flow.py").read_text()
            self.assertIn("items_artifact='paragraphs.jsonl'", flow_text)



if __name__ == "__main__":
    unittest.main()
