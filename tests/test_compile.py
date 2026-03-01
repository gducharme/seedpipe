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
        self.assertEqual(normalized["pipeline_type"], "straight")
        self.assertEqual(normalized["max_loops"], 0)
        self.assertEqual(normalized["stages"][0]["inputs"], [])
        self.assertEqual(normalized["stages"][0]["mode"], "whole_run")



    def test_normalize_pipeline_expands_foreach_family_key_dsl(self) -> None:
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
                            "key": "lang",
                            "pattern": "pass1_pre/{lang}/paragraphs.jsonl",
                            "schema": "paragraphs.schema.json",
                        }
                    ],
                },
                {
                    "id": "translate_pass2",
                    "mode": "whole_run",
                    "foreach": "params.targets.languages",
                    "key": "lang",
                    "inputs": [
                        "paragraphs.jsonl",
                        {"family": "pass1_translations", "pattern": "pass1_pre/{lang}/paragraphs.jsonl", "schema": "paragraphs.schema.json"},
                    ],
                    "outputs": [
                        {
                            "family": "pass2_translations",
                            "key": "lang",
                            "pattern": "pass2_pre/{lang}/paragraphs.jsonl",
                            "schema": "paragraphs.schema.json",
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
        self.assertEqual(stages[1]["id"], "translate_pass2")
        self.assertEqual(
            stages[1]["inputs"],
            [
                "paragraphs.jsonl",
                "pass1_pre/fr/paragraphs.jsonl",
                "pass1_pre/de/paragraphs.jsonl",
                "pass1_pre/ar/paragraphs.jsonl",
            ],
        )

    def test_normalize_pipeline_rejects_input_pattern_template_variable_not_in_scope(self) -> None:
        raw = {
            "pipeline_id": "p1",
            "stages": [
                {
                    "id": "consumer",
                    "foreach": "params.targets.languages",
                    "key": "lang",
                    "inputs": [{"family": "pass1_translations", "pattern": "pass1_pre/{region}/paragraphs.jsonl", "schema": "paragraphs.schema.json"}],
                    "outputs": ["out.json"],
                }
            ],
            "params": {"targets": {"languages": ["fr"]}},
        }

        with self.assertRaises(CompileError):
            normalize_pipeline(raw)


    def test_normalize_pipeline_reports_stage_id_for_invalid_family_ref_shape(self) -> None:
        raw = {
            "pipeline_id": "p1",
            "stages": [
                {
                    "id": "consumer",
                    "inputs": [{"family": "pass1_translations"}],
                    "outputs": ["out.json"],
                }
            ],
        }

        with self.assertRaisesRegex(CompileError, r"pipeline\.stages\[0\] \(id='consumer'\)\.inputs\[0\]"):
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
            "stages": [{"id": "s1", "foreach": ["bad"], "key": "lang", "outputs": ["x.json"]}],
        }

        with self.assertRaises(CompileError):
            normalize_pipeline(raw)

    def test_normalize_pipeline_rejects_stage_foreach_non_list_resolution(self) -> None:
        raw = {
            "pipeline_id": "p1",
            "params": {"targets": {"languages": "fr"}},
            "stages": [
                {"id": "s1", "foreach": "params.targets.languages", "key": "lang", "outputs": ["x.json"]}
            ],
        }

        with self.assertRaises(CompileError):
            normalize_pipeline(raw)

    def test_normalize_pipeline_rejects_stage_foreach_missing_key(self) -> None:
        raw = {
            "pipeline_id": "p1",
            "params": {"targets": {"languages": ["fr"]}},
            "stages": [{"id": "s1", "foreach": "params.targets.languages", "outputs": ["x.json"]}],
        }

        with self.assertRaises(CompileError):
            normalize_pipeline(raw)

    def test_normalize_pipeline_allows_output_object_missing_schema(self) -> None:
        raw = {
            "pipeline_id": "p1",
            "stages": [
                {
                    "id": "producer",
                    "outputs": [{"family": "f", "pattern": "out.json"}],
                }
            ],
        }

        normalized = normalize_pipeline(raw)
        expected_outputs = normalized["stages"][0]["_expected_outputs"]
        self.assertEqual(expected_outputs[0]["path"], "out.json")
        self.assertNotIn("schema", expected_outputs[0])

    def test_normalize_pipeline_rejects_output_object_non_string_schema(self) -> None:
        raw = {
            "pipeline_id": "p1",
            "stages": [
                {
                    "id": "producer",
                    "outputs": [{"family": "f", "pattern": "out.json", "schema": 123}],
                }
            ],
        }

        with self.assertRaises(CompileError):
            normalize_pipeline(raw)

    def test_normalize_pipeline_rejects_output_family_key_out_of_scope(self) -> None:
        raw = {
            "pipeline_id": "p1",
            "stages": [
                {
                    "id": "producer",
                    "outputs": [{"family": "f", "key": "lang", "pattern": "out/{lang}.json", "schema": "artifact_ref.schema.json"}],
                }
            ],
        }

        with self.assertRaises(CompileError):
            normalize_pipeline(raw)

    def test_normalize_pipeline_allows_reusing_family_with_different_patterns(self) -> None:
        raw = {
            "pipeline_id": "p1",
            "params": {"targets": {"languages": ["fr"]}},
            "stages": [
                {
                    "id": "producer_1",
                    "foreach": "params.targets.languages",
                    "key": "lang",
                    "outputs": [{"family": "f", "key": "lang", "pattern": "out/{lang}.json", "schema": "artifact_ref.schema.json"}],
                },
                {
                    "id": "producer_2",
                    "foreach": "params.targets.languages",
                    "key": "lang",
                    "outputs": [{"family": "f", "key": "lang", "pattern": "other/{lang}.json", "schema": "artifact_ref.schema.json"}],
                },
            ],
        }

        normalized = normalize_pipeline(raw)
        self.assertEqual(normalized["stages"][0]["outputs"], ["out/fr.json"])
        self.assertEqual(normalized["stages"][1]["outputs"], ["other/fr.json"])

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
                            "key": "lang",
                            "pattern": "out/{lang}.json",
                            "schema": "artifact_ref.schema.json",
                        }
                    ],
                },
                {
                    "id": "consumer",
                    "foreach": "params.targets.languages",
                    "key": "lang",
                    "inputs": [{"family": "f", "pattern": "out/{lang}.json", "schema": "artifact_ref.schema.json"}],
                    "outputs": ["done/{lang}.json"],
                },
            ],
        }

        normalized = normalize_pipeline(raw)
        self.assertEqual(normalized["stages"][0]["outputs"], ["out/fr.json", "out/de.json"])
        self.assertEqual(
            normalized["stages"][0]["_expected_outputs"],
            [
                {
                    "family": "f",
                    "pattern": "out/{lang}.json",
                    "schema": "artifact_ref.schema.json",
                    "path": "out/fr.json",
                    "keys": {"lang": "fr"},
                },
                {
                    "family": "f",
                    "pattern": "out/{lang}.json",
                    "schema": "artifact_ref.schema.json",
                    "path": "out/de.json",
                    "keys": {"lang": "de"},
                },
            ],
        )
        self.assertEqual(normalized["stages"][1]["inputs"], ["out/fr.json", "out/de.json"])

    def test_normalize_pipeline_uses_internal_keys_metadata_not_bindings(self) -> None:
        raw = {
            "pipeline_id": "p1",
            "params": {"targets": {"languages": ["fr"]}},
            "stages": [
                {
                    "id": "translate",
                    "foreach": "params.targets.languages",
                    "key": "lang",
                    "inputs": ["items.jsonl"],
                    "outputs": ["translated/{lang}.jsonl"],
                }
            ],
        }

        normalized = normalize_pipeline(raw)

        stage = normalized["stages"][0]
        self.assertEqual(stage["_keys"], {})
        self.assertNotIn("_bindings", stage)

    def test_validate_pipeline_structure_rejects_forward_references(self) -> None:
        normalized = {
            "pipeline_id": "p1",
            "item_unit": "item",
            "determinism_policy": "strict",
            "pipeline_type": "straight",
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
                    "placeholder": False,
                    "inputs": [],
                    "outputs": ["items.jsonl"],
                },
            ],
        }

        with self.assertRaises(CompileError):
            validate_pipeline_structure(normalized)

    def test_validate_pipeline_structure_allows_placeholder_forward_references(self) -> None:
        normalized = {
            "pipeline_id": "p1",
            "item_unit": "item",
            "determinism_policy": "strict",
            "pipeline_type": "straight",
            "stages": [
                {
                    "id": "ingest",
                    "mode": "whole_run",
                    "placeholder": False,
                    "inputs": [],
                    "outputs": ["items.jsonl"],
                },
                {
                    "id": "future_step",
                    "mode": "whole_run",
                    "placeholder": True,
                    "inputs": ["future/items_enriched.jsonl"],
                    "outputs": ["future/items_reviewed.jsonl"],
                },
            ],
        }

        validate_pipeline_structure(normalized)

    def test_validate_pipeline_structure_rejects_unknown_pipeline_type(self) -> None:
        normalized = {
            "pipeline_id": "p1",
            "item_unit": "item",
            "determinism_policy": "strict",
            "pipeline_type": "zigzag",
            "stages": [
                {"id": "s1", "mode": "whole_run", "placeholder": False, "inputs": [], "outputs": ["x.json"]},
            ],
        }

        with self.assertRaisesRegex(CompileError, "pipeline 'p1' pipeline_type"):
            validate_pipeline_structure(normalized)

    def test_validate_pipeline_structure_rejects_invalid_max_loops(self) -> None:
        normalized = {
            "pipeline_id": "p1",
            "item_unit": "item",
            "determinism_policy": "strict",
            "pipeline_type": "straight",
            "max_loops": -1,
            "stages": [
                {"id": "s1", "mode": "whole_run", "placeholder": False, "inputs": [], "outputs": ["x.json"]},
            ],
        }
        with self.assertRaisesRegex(CompileError, "pipeline 'p1' max_loops"):
            validate_pipeline_structure(normalized)

    def test_validate_pipeline_structure_rejects_straight_with_nonzero_max_loops(self) -> None:
        normalized = {
            "pipeline_id": "p1",
            "item_unit": "item",
            "determinism_policy": "strict",
            "pipeline_type": "straight",
            "max_loops": 1,
            "stages": [
                {"id": "s1", "mode": "whole_run", "placeholder": False, "inputs": [], "outputs": ["x.json"]},
            ],
        }
        with self.assertRaisesRegex(CompileError, "requires max_loops=0"):
            validate_pipeline_structure(normalized)

    def test_validate_pipeline_structure_rejects_looping_with_zero_max_loops(self) -> None:
        normalized = {
            "pipeline_id": "p1",
            "item_unit": "item",
            "determinism_policy": "strict",
            "pipeline_type": "looping",
            "max_loops": 0,
            "stages": [
                {"id": "s1", "mode": "whole_run", "placeholder": False, "inputs": [], "outputs": ["x.json"], "reentry": "start"},
            ],
        }
        with self.assertRaisesRegex(CompileError, "requires max_loops >= 1"):
            validate_pipeline_structure(normalized)

    def test_validate_pipeline_structure_rejects_straight_with_loop_fields(self) -> None:
        normalized = {
            "pipeline_id": "p1",
            "item_unit": "item",
            "determinism_policy": "strict",
            "pipeline_type": "straight",
            "stages": [
                {"id": "s1", "mode": "whole_run", "placeholder": False, "inputs": [], "outputs": ["x.json"], "reentry": "start"},
            ],
        }

        with self.assertRaisesRegex(CompileError, "does not allow 'reentry' or 'go_to' stage fields"):
            validate_pipeline_structure(normalized)

    def test_validate_pipeline_structure_rejects_looping_without_reentry(self) -> None:
        normalized = {
            "pipeline_id": "p1",
            "item_unit": "item",
            "determinism_policy": "strict",
            "pipeline_type": "looping",
            "max_loops": 2,
            "stages": [
                {"id": "s1", "mode": "whole_run", "placeholder": False, "inputs": [], "outputs": ["x.json"]},
            ],
        }

        with self.assertRaisesRegex(CompileError, "requires at least one stage with 'reentry'"):
            validate_pipeline_structure(normalized)

    def test_validate_pipeline_structure_rejects_duplicate_reentry(self) -> None:
        normalized = {
            "pipeline_id": "p1",
            "item_unit": "item",
            "determinism_policy": "strict",
            "pipeline_type": "looping",
            "max_loops": 2,
            "stages": [
                {"id": "s1", "mode": "whole_run", "placeholder": False, "inputs": [], "outputs": ["x.json"], "reentry": "start"},
                {"id": "s2", "mode": "whole_run", "placeholder": False, "inputs": ["x.json"], "outputs": ["y.json"], "reentry": "start"},
            ],
        }

        with self.assertRaisesRegex(CompileError, "duplicates"):
            validate_pipeline_structure(normalized)

    def test_validate_pipeline_structure_rejects_go_to_unknown_reentry(self) -> None:
        normalized = {
            "pipeline_id": "p1",
            "item_unit": "item",
            "determinism_policy": "strict",
            "pipeline_type": "looping",
            "max_loops": 2,
            "stages": [
                {"id": "s1", "mode": "whole_run", "placeholder": False, "inputs": [], "outputs": ["x.json"], "reentry": "start"},
                {"id": "s2", "mode": "whole_run", "placeholder": False, "inputs": ["x.json"], "outputs": ["y.json"], "go_to": "missing"},
            ],
        }

        with self.assertRaisesRegex(CompileError, "unknown reentry"):
            validate_pipeline_structure(normalized)

    def test_validate_pipeline_structure_rejects_go_to_non_backward_target(self) -> None:
        normalized = {
            "pipeline_id": "p1",
            "item_unit": "item",
            "determinism_policy": "strict",
            "pipeline_type": "looping",
            "max_loops": 2,
            "stages": [
                {"id": "s1", "mode": "whole_run", "placeholder": False, "inputs": [], "outputs": ["x.json"], "go_to": "finish"},
                {"id": "s2", "mode": "whole_run", "placeholder": False, "inputs": ["x.json"], "outputs": ["y.json"], "reentry": "finish"},
            ],
        }

        with self.assertRaisesRegex(CompileError, r"go_to='finish'.*not earlier"):
            validate_pipeline_structure(normalized)

    def test_validate_pipeline_structure_allows_looping_with_backward_go_to(self) -> None:
        normalized = {
            "pipeline_id": "p1",
            "item_unit": "item",
            "determinism_policy": "strict",
            "pipeline_type": "looping",
            "max_loops": 2,
            "stages": [
                {"id": "s1", "mode": "whole_run", "placeholder": False, "inputs": [], "outputs": ["x.json"], "reentry": "start"},
                {"id": "s2", "mode": "whole_run", "placeholder": False, "inputs": ["x.json"], "outputs": ["y.json"], "go_to": "start"},
            ],
        }

        validate_pipeline_structure(normalized)

    def test_validate_pipeline_structure_rejects_non_string_reentry_and_go_to(self) -> None:
        normalized = {
            "pipeline_id": "p1",
            "item_unit": "item",
            "determinism_policy": "strict",
            "pipeline_type": "looping",
            "max_loops": 2,
            "stages": [
                {"id": "s1", "mode": "whole_run", "placeholder": False, "inputs": [], "outputs": ["x.json"], "reentry": 123},
            ],
        }
        with self.assertRaisesRegex(CompileError, "reentry must be a non-empty string"):
            validate_pipeline_structure(normalized)

        normalized["stages"][0]["reentry"] = "start"
        normalized["stages"].append(
            {"id": "s2", "mode": "whole_run", "placeholder": False, "inputs": ["x.json"], "outputs": ["y.json"], "go_to": 42}
        )
        with self.assertRaisesRegex(CompileError, "go_to must be a non-empty string"):
            validate_pipeline_structure(normalized)

    def test_validate_pipeline_structure_accepts_human_required_with_instructions(self) -> None:
        normalized = {
            "pipeline_id": "p1",
            "item_unit": "item",
            "determinism_policy": "strict",
            "pipeline_type": "straight",
            "max_loops": 0,
            "stages": [
                {"id": "ingest", "mode": "whole_run", "placeholder": False, "inputs": [], "outputs": ["items.jsonl"]},
                {
                    "id": "align_quotes",
                    "mode": "human_required",
                    "placeholder": False,
                    "inputs": ["items.jsonl"],
                    "outputs": ["quote_map.json"],
                    "instructions": {
                        "summary": "Align quotes and anchors for mapping.",
                        "steps": ["python scripts/build_quote_map.py --in runs/{run_id}/items.jsonl --out runs/{run_id}/quote_map.json"],
                        "done_when": ["validate_quote_map exits 0"],
                        "validation_command": "python scripts/validate_quote_map.py runs/{run_id}/quote_map.json",
                    },
                },
            ],
        }

        validate_pipeline_structure(normalized)

    def test_validate_pipeline_structure_rejects_human_required_missing_instructions(self) -> None:
        normalized = {
            "pipeline_id": "p1",
            "item_unit": "item",
            "determinism_policy": "strict",
            "pipeline_type": "straight",
            "max_loops": 0,
            "stages": [
                {"id": "ingest", "mode": "whole_run", "placeholder": False, "inputs": [], "outputs": ["items.jsonl"]},
                {
                    "id": "align_quotes",
                    "mode": "human_required",
                    "placeholder": False,
                    "inputs": ["items.jsonl"],
                    "outputs": ["quote_map.json"],
                },
            ],
        }

        with self.assertRaisesRegex(CompileError, "instructions must be an object"):
            validate_pipeline_structure(normalized)

    def test_build_ir_captures_artifact_producers(self) -> None:
        pipeline = {
            "pipeline_id": "p1",
            "item_unit": "item",
            "determinism_policy": "strict",
            "pipeline_type": "straight",
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
        self.assertEqual(ir.pipeline_type, "straight")
        self.assertEqual(ir.stages[1].mode, "per_item")
        self.assertIsNone(ir.stages[0].reentry)
        self.assertIsNone(ir.stages[0].go_to)
        self.assertEqual(ir.artifact_producers["items.jsonl"], "ingest")
        self.assertEqual(ir.artifact_producers["transformed.jsonl"], "transform")

    def test_build_ir_preserves_loop_metadata(self) -> None:
        pipeline = {
            "pipeline_id": "p1",
            "item_unit": "item",
            "determinism_policy": "strict",
            "pipeline_type": "looping",
            "max_loops": 2,
            "stages": [
                {"id": "s1", "mode": "whole_run", "inputs": [], "outputs": ["x.json"], "reentry": "start"},
                {"id": "s2", "mode": "whole_run", "inputs": ["x.json"], "outputs": ["y.json"], "go_to": "start"},
            ],
        }

        ir = build_ir(pipeline)
        self.assertEqual(ir.pipeline_type, "looping")
        self.assertEqual(ir.stages[0].reentry, "start")
        self.assertIsNone(ir.stages[0].go_to)
        self.assertEqual(ir.stages[1].go_to, "start")

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
            self.assertTrue((output_dir / "run_manifest_template.json").exists())
            self.assertTrue((output_dir / "stages" / "ingest.py").exists())
            self.assertTrue((output_dir / "stages" / "__init__.py").exists())

            flow_text = (output_dir / "flow.py").read_text()
            self.assertIn("append_item_state_row", flow_text)
            self.assertIn("RUN_MANIFEST_FILE", flow_text)
            self.assertIn("_resolve_resume_index", flow_text)
            self.assertIn("def _register_stage_outputs", flow_text)
            self.assertIn("loops", flow_text)

            ingest_wrapper = (output_dir / "stages" / "ingest.py").read_text()
            self.assertIn("def run_whole", ingest_wrapper)

            stages_init = (output_dir / "stages" / "__init__.py").read_text()
            self.assertIn("__all__", stages_init)

            compile_report = json.loads((output_dir / "compile_report.json").read_text())
            self.assertEqual(
                compile_report["artifact_schema_map"]["published_manifest.json"],
                "manifest.schema.json",
            )
            self.assertTrue(
                any(path.endswith("/run_manifest_template.json") for path in compile_report["emitted_files"])
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

    def test_compile_pipeline_does_not_bootstrap_src_stage_impls(self) -> None:
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

            self.assertFalse((root / "src").exists())

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


    def test_compile_pipeline_does_not_emit_binding_metadata_in_ir_or_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pipeline_path = root / "pipeline.yaml"
            contracts_dir = root / "contracts"
            output_dir = root / "generated"
            contracts_dir.mkdir()

            pipeline_path.write_text(
                json.dumps(
                    {
                        "pipeline_id": "phase1-keys-no-bindings",
                        "item_unit": "item",
                        "determinism_policy": "strict",
                        "params": {"targets": {"languages": ["fr"]}},
                        "stages": [
                            {
                                "id": "ingest",
                                "mode": "whole_run",
                                "inputs": [],
                                "outputs": ["items.jsonl"],
                            },
                            {
                                "id": "translate",
                                "mode": "per_item",
                                "foreach": "params.targets.languages",
                                "key": "lang",
                                "inputs": ["items.jsonl"],
                                "outputs": ["translated/{lang}.jsonl"],
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
            self.assertNotIn("_bindings", flow_text)

            ir_text = (output_dir / "ir.json").read_text()
            self.assertNotIn("_bindings", ir_text)

    def test_compile_pipeline_emits_stage_keys_to_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pipeline_path = root / "pipeline.yaml"
            contracts_dir = root / "contracts"
            output_dir = root / "generated"
            contracts_dir.mkdir()

            pipeline_path.write_text(
                json.dumps(
                    {
                        "pipeline_id": "phase1-keys",
                        "item_unit": "item",
                        "determinism_policy": "strict",
                        "params": {"targets": {"languages": ["fr"]}},
                        "stages": [
                            {
                                "id": "ingest",
                                "mode": "whole_run",
                                "inputs": [],
                                "outputs": ["items.jsonl"],
                            },
                            {
                                "id": "translate",
                                "mode": "per_item",
                                "foreach": "params.targets.languages",
                                "key": "lang",
                                "inputs": ["items.jsonl"],
                                "outputs": ["translated/{lang}.jsonl"],
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
            self.assertIn("keys={}", flow_text)
            self.assertIn("_iter_stage_items(ctx, items_artifact='items.jsonl', keys=ctx.keys, active_item_ids=active_item_ids)", flow_text)
            self.assertIn("translated/fr.jsonl", flow_text)
            self.assertIn("run_config.setdefault('_pipe_root'", flow_text)

            stage_wrapper = (output_dir / "stages" / "translate.py").read_text()
            self.assertIn("ctx.validate_expected_outputs(STAGE_ID)", stage_wrapper)

            ir = json.loads((output_dir / "ir.json").read_text())
            translate_stage = next(stage for stage in ir["stages"] if stage["stage_id"] == "translate")
            self.assertEqual(translate_stage["keys"], [])
            self.assertEqual(
                translate_stage["expected_outputs"],
                [
                    {
                        "keys": {"lang": "fr"},
                        "path": "translated/fr.jsonl",
                        "pattern": "translated/{lang}.jsonl",
                    }
                ],
            )

    def test_compile_pipeline_whole_run_wrapper_uses_expected_output_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pipeline_path = root / "pipeline.yaml"
            contracts_dir = root / "contracts"
            output_dir = root / "generated"
            contracts_dir.mkdir()

            pipeline_path.write_text(
                json.dumps(
                    {
                        "pipeline_id": "phase1-whole-run-expected-outputs",
                        "item_unit": "item",
                        "determinism_policy": "strict",
                        "stages": [
                            {
                                "id": "transform",
                                "mode": "whole_run",
                                "inputs": [],
                                "outputs": [
                                    {
                                        "family": "transformed_rewrites",
                                        "pattern": "transforms/transformed.jsonl",
                                        "schema": "transformed_rewrites.schema.json",
                                    }
                                ],
                            },
                            {
                                "id": "reviewer_pass",
                                "mode": "whole_run",
                                "inputs": [
                                    {
                                        "family": "transformed_rewrites",
                                        "pattern": "transforms/transformed.jsonl",
                                        "schema": "transformed_rewrites.schema.json",
                                    }
                                ],
                                "outputs": [
                                    {
                                        "family": "reviewed_rewrites",
                                        "pattern": "review/reviewed.jsonl",
                                        "schema": "reviewed_rewrites.schema.json",
                                    },
                                    {
                                        "family": "review_summary",
                                        "pattern": "review/review_summary.json",
                                        "schema": "review_summary.schema.json",
                                    },
                                ],
                            },
                            {
                                "id": "publish",
                                "mode": "whole_run",
                                "inputs": [
                                    {
                                        "family": "reviewed_rewrites",
                                        "pattern": "review/reviewed.jsonl",
                                        "schema": "reviewed_rewrites.schema.json",
                                    },
                                    {
                                        "family": "review_summary",
                                        "pattern": "review/review_summary.json",
                                        "schema": "review_summary.schema.json",
                                    },
                                ],
                                "outputs": [
                                    {
                                        "family": "manifest",
                                        "pattern": "manifest.json",
                                        "schema": "manifest.schema.json",
                                    }
                                ],
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
                "transformed_rewrites.schema.json": {"type": "object"},
                "reviewed_rewrites.schema.json": {"type": "object"},
                "review_summary.schema.json": {"type": "object"},
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

            publish_wrapper = (output_dir / "stages" / "publish.py").read_text()
            self.assertIn("INPUTS = ['review/reviewed.jsonl', 'review/review_summary.json']", publish_wrapper)
            self.assertIn(
                "outputs_to_validate = [str(item.get('path', '')) for item in (ctx.expected_outputs or []) if item.get('path')] or OUTPUTS",
                publish_wrapper,
            )
            self.assertIn("ctx.validate_expected_outputs(STAGE_ID)", publish_wrapper)

    def test_compile_pipeline_emits_loop_metadata_to_ir_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pipeline_path = root / "pipeline.yaml"
            contracts_dir = root / "contracts"
            output_dir = root / "generated"
            contracts_dir.mkdir()

            pipeline_path.write_text(
                json.dumps(
                    {
                        "pipeline_id": "phase1-loop-metadata",
                        "item_unit": "item",
                        "determinism_policy": "strict",
                        "pipeline_type": "looping",
                        "max_loops": 2,
                        "stages": [
                            {
                                "id": "ingest",
                                "mode": "whole_run",
                                "inputs": [],
                                "outputs": ["items.jsonl"],
                                "reentry": "start",
                            },
                            {
                                "id": "review",
                                "mode": "whole_run",
                                "inputs": ["items.jsonl"],
                                "outputs": ["reviewed.jsonl"],
                                "go_to": "start",
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

            ir = json.loads((output_dir / "ir.json").read_text())
            self.assertEqual(ir["pipeline_type"], "looping")
            self.assertEqual(ir["stages"][0]["reentry"], "start")
            self.assertIsNone(ir["stages"][0]["go_to"])
            self.assertEqual(ir["stages"][1]["go_to"], "start")


if __name__ == "__main__":
    unittest.main()
