from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from tools.compile import CompilePaths, compile_pipeline
from tools.run import run_generated_flow



class RunCommandTests(unittest.TestCase):
    def test_run_generated_flow_executes_compiled_flow_in_run_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated_dir = root / "generated"
            generated_dir.mkdir()
            inputs_dir = root / "artifacts" / "inputs"
            inputs_dir.mkdir(parents=True)
            (inputs_dir / "items.jsonl").write_text('{"item_id":"i-1"}\n')
            (generated_dir / "flow.py").write_text(
                """
from pathlib import Path


def run(run_config: dict[str, object], attempt: int = 1) -> int:
    marker = Path('marker.txt')
    marker.write_text(f"{run_config['run_id']}:{attempt}")
    assert Path('artifacts/inputs/items.jsonl').exists()
    return 0
""".strip()
            )

            output_dir = root / "artifacts" / "outputs" / "demo-run"
            code = run_generated_flow(
                generated_dir=generated_dir,
                run_id="demo-run",
                attempt=2,
                output_dir=output_dir,
                inputs_dir=inputs_dir,
            )

            self.assertEqual(code, 0)
            self.assertEqual((output_dir / "marker.txt").read_text(), "demo-run:2")

    def test_run_generated_flow_passes_flexible_run_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated_dir = root / "generated"
            generated_dir.mkdir()
            inputs_dir = root / "artifacts" / "inputs"
            inputs_dir.mkdir(parents=True)
            (generated_dir / "flow.py").write_text(
                """
from pathlib import Path


def run(run_config: dict[str, object], attempt: int = 1) -> int:
    Path('config.txt').write_text(f"{run_config['run_id']}:{run_config['trace_id']}:{attempt}")
    return 0
""".strip()
            )

            output_dir = root / "artifacts" / "outputs" / "configured-run"
            code = run_generated_flow(
                generated_dir=generated_dir,
                attempt=4,
                output_dir=output_dir,
                inputs_dir=inputs_dir,
                run_config={"run_id": "configured-run", "trace_id": "t-1"},
            )

            self.assertEqual(code, 0)
            self.assertEqual((output_dir / "config.txt").read_text(), "configured-run:t-1:4")

    def test_run_generated_flow_uses_default_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated_dir = root / "generated"
            generated_dir.mkdir()
            (root / "artifacts" / "inputs").mkdir(parents=True)
            (generated_dir / "flow.py").write_text(
                """
from pathlib import Path


def run(run_config: dict[str, object], attempt: int = 1) -> int:
    Path('ran.txt').write_text(str(run_config['run_id']))
    return 0
""".strip()
            )

            cwd = Path.cwd()
            try:
                os.chdir(root)
                code = run_generated_flow(generated_dir=generated_dir, run_id="default-run")
            finally:
                os.chdir(cwd)

            self.assertEqual(code, 0)
            self.assertEqual((root / "artifacts" / "outputs" / "default-run" / "ran.txt").read_text(), "default-run")

    def test_run_generated_flow_errors_if_run_id_dir_exists_and_manifest_is_completed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated_dir = root / "generated"
            generated_dir.mkdir()
            inputs_dir = root / "artifacts" / "inputs"
            inputs_dir.mkdir(parents=True)
            (generated_dir / "flow.py").write_text("def run(run_config: dict[str, object], attempt: int = 1) -> int:\n    return 0\n")
            (generated_dir / "run_manifest_template.json").write_text(
                json.dumps(
                    {
                        "manifest_version": "phase1-run-resume-v1",
                        "pipeline_id": "p1",
                        "run_id": "",
                        "failure_stage_id": None,
                        "stages": [{"stage_id": "ingest", "status": "completed", "attempt": 1}],
                    }
                )
            )
            output_dir = root / "artifacts" / "outputs" / "existing-run"
            output_dir.mkdir(parents=True)
            (output_dir / ".seedpipe_run_manifest.json").write_text(
                json.dumps(
                    {
                        "manifest_version": "phase1-run-resume-v1",
                        "pipeline_id": "p1",
                        "run_id": "existing-run",
                        "failure_stage_id": None,
                        "stages": [{"stage_id": "ingest", "status": "completed", "attempt": 1}],
                    }
                )
            )

            with self.assertRaises(FileExistsError):
                run_generated_flow(generated_dir=generated_dir, run_id="existing-run", output_dir=output_dir, inputs_dir=inputs_dir)

    def test_run_generated_flow_resumes_existing_incomplete_run_from_failure_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated_dir = root / "generated"
            generated_dir.mkdir()
            inputs_dir = root / "artifacts" / "inputs"
            inputs_dir.mkdir(parents=True)
            (generated_dir / "flow.py").write_text(
                """
from pathlib import Path

PIPELINE_ID = "p1"
STAGES = ["ingest", "publish"]


def run(run_config: dict[str, object], attempt: int = 1) -> int:
    Path("resume.txt").write_text(str(run_config.get("_resume_stage_id", "")))
    return 0
""".strip()
            )
            (generated_dir / "run_manifest_template.json").write_text(
                json.dumps(
                    {
                        "manifest_version": "phase1-run-resume-v1",
                        "pipeline_id": "p1",
                        "run_id": "",
                        "failure_stage_id": None,
                        "stages": [
                            {"stage_id": "ingest", "status": "pending", "attempt": 0},
                            {"stage_id": "publish", "status": "pending", "attempt": 0},
                        ],
                    }
                )
            )

            output_dir = root / "artifacts" / "outputs" / "resume-run"
            output_dir.mkdir(parents=True)
            (output_dir / ".seedpipe_run_manifest.json").write_text(
                json.dumps(
                    {
                        "manifest_version": "phase1-run-resume-v1",
                        "pipeline_id": "p1",
                        "run_id": "resume-run",
                        "failure_stage_id": "publish",
                        "stages": [
                            {"stage_id": "ingest", "status": "completed", "attempt": 1},
                            {"stage_id": "publish", "status": "failed", "attempt": 1},
                        ],
                    }
                )
            )

            code = run_generated_flow(
                generated_dir=generated_dir,
                run_id="resume-run",
                output_dir=output_dir,
                inputs_dir=inputs_dir,
            )

            self.assertEqual(code, 0)
            self.assertEqual((output_dir / "resume.txt").read_text(), "publish")

    def test_run_generated_flow_requires_compiled_flow_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            generated_dir = Path(tmp) / "generated"
            generated_dir.mkdir()
            with self.assertRaises(FileNotFoundError):
                run_generated_flow(generated_dir=generated_dir, run_id="missing")

    def test_run_generated_flow_requires_inputs_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated_dir = root / "generated"
            generated_dir.mkdir()
            (generated_dir / "flow.py").write_text("def run(run_config: dict[str, object], attempt: int = 1) -> int:\n    return 0\n")

            with self.assertRaises(FileNotFoundError):
                run_generated_flow(generated_dir=generated_dir, run_id="missing-inputs", inputs_dir=root / "does-not-exist")

    def test_run_generated_flow_mounts_local_src_package_for_stage_impls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated_dir = root / "generated"
            generated_stages_dir = generated_dir / "stages"
            generated_stages_dir.mkdir(parents=True)
            inputs_dir = root / "artifacts" / "inputs"
            inputs_dir.mkdir(parents=True)
            (inputs_dir / "items.jsonl").write_text('{"item_id":"i-1"}\n')

            src_stages_dir = root / "src" / "stages"
            src_stages_dir.mkdir(parents=True)
            (src_stages_dir / "ingest.py").write_text(
                """
from pathlib import Path


def run_whole(ctx) -> None:
    Path('items.jsonl').write_text('{\"item_id\": \"i-1\"}\\n')
""".strip()
            )

            (generated_dir / "flow.py").write_text(
                """
from seedpipe.generated.stages import ingest
from seedpipe.runtime.ctx import StageContext


def run(run_config: dict[str, object], attempt: int = 1) -> int:
    ctx = StageContext.make_base(run_config=run_config).for_stage('ingest', attempt=attempt)
    ingest.run_whole(ctx)
    return 0
""".strip()
            )
            (generated_stages_dir / "__init__.py").write_text("from . import ingest\n")
            (generated_stages_dir / "ingest.py").write_text(
                """
from seedpipe.runtime.ctx import StageContext
from seedpipe.src.stages import ingest as impl


def run_whole(ctx: StageContext) -> None:
    impl.run_whole(ctx)
    ctx.validate_outputs('ingest', ['items.jsonl'])
""".strip()
            )

            output_dir = root / "artifacts" / "outputs" / "demo-run"
            code = run_generated_flow(
                generated_dir=generated_dir,
                run_id="demo-run",
                attempt=2,
                output_dir=output_dir,
                inputs_dir=inputs_dir,
            )

            self.assertEqual(code, 0)
            self.assertTrue((output_dir / "items.jsonl").exists())

    def test_run_generated_flow_looping_reruns_failed_items_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated_dir = root / "generated"
            contracts_dir = root / "contracts"
            contracts_dir.mkdir()
            pipeline_path = root / "pipeline.yaml"
            inputs_dir = root / "artifacts" / "inputs"
            inputs_dir.mkdir(parents=True)

            pipeline_path.write_text(
                json.dumps(
                    {
                        "pipeline_id": "looping-pipe",
                        "item_unit": "item",
                        "determinism_policy": "strict",
                        "pipeline_type": "looping",
                        "max_loops": 2,
                        "stages": [
                            {"id": "ingest", "mode": "whole_run", "inputs": [], "outputs": ["items.jsonl"]},
                            {
                                "id": "seed",
                                "mode": "per_item",
                                "inputs": ["items.jsonl"],
                                "outputs": ["seed.marker"],
                                "reentry": "retry_seed",
                            },
                            {
                                "id": "work",
                                "mode": "per_item",
                                "inputs": ["items.jsonl"],
                                "outputs": [],
                                "go_to": "retry_seed",
                            },
                            {
                                "id": "publish",
                                "mode": "whole_run",
                                "inputs": [],
                                "outputs": ["manifest.json"],
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
                    output_dir=generated_dir,
                )
            )

            src_stages_dir = root / "src" / "stages"
            src_stages_dir.mkdir(parents=True)
            (src_stages_dir / "ingest.py").write_text(
                """
import json
from pathlib import Path


def run_whole(ctx) -> None:
    rows = [{"item_id": "a"}, {"item_id": "b"}]
    Path("items.jsonl").write_text("".join(json.dumps(row) + "\\n" for row in rows))
""".strip()
            )
            (src_stages_dir / "seed.py").write_text(
                """
from pathlib import Path


def run_item(ctx, item):
    with Path("seed.log").open("a", encoding="utf-8") as fh:
        fh.write(str(item.get("item_id", "")) + "\\n")
    Path("seed.marker").write_text("ok")
""".strip()
            )
            (src_stages_dir / "work.py").write_text(
                """
import json
from pathlib import Path
from seedpipe.generated.models import ItemResult


def run_item(ctx, item):
    item_id = str(item.get("item_id", ""))
    Path("work.marker").write_text("ok")
    marker = Path(f".work_fail_once_{item_id}.marker")
    if item_id == "b" and not marker.exists():
        marker.write_text("failed-once")
        return ItemResult(item_id=item_id, ok=False, error={"code": "business_rule_failed", "message": "retry", "source": "stage"})
    return ItemResult(item_id=item_id, ok=True)
""".strip()
            )
            (src_stages_dir / "publish.py").write_text(
                """
import json
from pathlib import Path


def run_whole(ctx) -> None:
    Path("manifest.json").write_text(json.dumps({"count": 1}))
""".strip()
            )

            output_dir = root / "artifacts" / "outputs" / "loop-run"
            code = run_generated_flow(
                generated_dir=generated_dir,
                run_id="loop-run",
                output_dir=output_dir,
                inputs_dir=inputs_dir,
            )

            self.assertEqual(code, 0)
            manifest = json.loads((output_dir / ".seedpipe_run_manifest.json").read_text())
            self.assertIsInstance(manifest.get("loop_iteration"), int)
            self.assertGreaterEqual(int(manifest.get("loop_iteration", 0)), 1)

    def test_run_generated_flow_loop_errors_after_max_loops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated_dir = root / "generated"
            contracts_dir = root / "contracts"
            contracts_dir.mkdir()
            pipeline_path = root / "pipeline.yaml"
            inputs_dir = root / "artifacts" / "inputs"
            inputs_dir.mkdir(parents=True)

            pipeline_path.write_text(
                json.dumps(
                    {
                        "pipeline_id": "looping-pipe-fail",
                        "item_unit": "item",
                        "determinism_policy": "strict",
                        "pipeline_type": "looping",
                        "max_loops": 2,
                        "stages": [
                            {"id": "ingest", "mode": "whole_run", "inputs": [], "outputs": ["items.jsonl"]},
                            {
                                "id": "seed",
                                "mode": "per_item",
                                "inputs": ["items.jsonl"],
                                "outputs": ["seed.marker"],
                                "reentry": "retry_seed",
                            },
                            {
                                "id": "work",
                                "mode": "per_item",
                                "inputs": ["items.jsonl"],
                                "outputs": ["fails.jsonl"],
                                "go_to": "retry_seed",
                            },
                            {
                                "id": "publish",
                                "mode": "whole_run",
                                "inputs": ["fails.jsonl"],
                                "outputs": ["manifest.json"],
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
                    output_dir=generated_dir,
                )
            )

            src_stages_dir = root / "src" / "stages"
            src_stages_dir.mkdir(parents=True)
            (src_stages_dir / "ingest.py").write_text(
                """
import json
from pathlib import Path


def run_whole(ctx) -> None:
    Path("items.jsonl").write_text(json.dumps({"item_id": "solo"}))
""".strip()
            )
            (src_stages_dir / "work.py").write_text(
                """
from seedpipe.generated.models import ItemResult


def run_item(ctx, item):
    with open("fails.jsonl", "a", encoding="utf-8") as fh:
        fh.write("{\\"item_id\\": \\"%s\\", \\"ok\\": false}\\n" % str(item.get("item_id", "")))
    return ItemResult(item_id=str(item.get("item_id", "")), ok=False, error={"code": "fail", "message": "always fails", "source": "stage"})
""".strip()
            )
            (src_stages_dir / "seed.py").write_text(
                """
from pathlib import Path


def run_item(ctx, item):
    Path("seed.marker").write_text("ok")
""".strip()
            )
            (src_stages_dir / "publish.py").write_text(
                """
from pathlib import Path


def run_whole(ctx) -> None:
    Path("manifest.json").write_text("done")
""".strip()
            )

            with self.assertRaises(RuntimeError) as cm:
                run_generated_flow(
                    generated_dir=generated_dir,
                    run_id="looping-pipe-fail",
                    output_dir=root / "artifacts" / "outputs" / "looping-pipe-fail",
                    inputs_dir=inputs_dir,
                )

            self.assertIn("looping-pipe-fail", str(cm.exception))
            self.assertIn("exceeded max_loops", str(cm.exception))
            manifest = json.loads(
                (root / "artifacts" / "outputs" / "looping-pipe-fail" / ".seedpipe_run_manifest.json").read_text()
            )
            self.assertEqual(manifest.get("loop_iteration"), 2)
            self.assertIn("failure_stage_id", manifest)

    def test_run_generated_flow_straight_pipeline_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated_dir = root / "generated"
            contracts_dir = root / "contracts"
            contracts_dir.mkdir()
            pipeline_path = root / "pipeline.yaml"
            inputs_dir = root / "artifacts" / "inputs"
            inputs_dir.mkdir(parents=True)

            pipeline_path.write_text(
                json.dumps(
                    {
                        "pipeline_id": "default-pipe",
                        "item_unit": "item",
                        "determinism_policy": "strict",
                        "stages": [
                            {"id": "ingest", "mode": "whole_run", "inputs": [], "outputs": ["items.jsonl"]},
                            {
                                "id": "publish",
                                "mode": "whole_run",
                                "inputs": ["items.jsonl"],
                                "outputs": ["manifest.json"],
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
                    output_dir=generated_dir,
                )
            )

            src_stages_dir = root / "src" / "stages"
            src_stages_dir.mkdir(parents=True)
            (src_stages_dir / "ingest.py").write_text(
                """
from pathlib import Path


def run_whole(ctx) -> None:
    Path("items.jsonl").write_text("dummy")
""".strip()
            )
            (src_stages_dir / "publish.py").write_text(
                """
import json
from pathlib import Path


def run_whole(ctx) -> None:
    Path("manifest.json").write_text(json.dumps({"pipeline_id": "default-pipe"}))
""".strip()
            )

            output_dir = root / "artifacts" / "outputs" / "default-pipe"
            code = run_generated_flow(
                generated_dir=generated_dir,
                run_id="default-pipe",
                output_dir=output_dir,
                inputs_dir=inputs_dir,
            )

            self.assertEqual(code, 0)
            self.assertTrue((output_dir / "manifest.json").exists())

    def test_run_generated_flow_pauses_and_resumes_human_required_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated_dir = root / "generated"
            contracts_dir = root / "contracts"
            contracts_dir.mkdir()
            pipeline_path = root / "pipeline.yaml"
            inputs_dir = root / "artifacts" / "inputs"
            inputs_dir.mkdir(parents=True)

            pipeline_path.write_text(
                json.dumps(
                    {
                        "pipeline_id": "human-required-pipe",
                        "item_unit": "item",
                        "determinism_policy": "strict",
                        "stages": [
                            {"id": "ingest", "mode": "whole_run", "inputs": [], "outputs": ["items.jsonl"]},
                            {
                                "id": "align_quotes",
                                "mode": "human_required",
                                "inputs": ["items.jsonl"],
                                "outputs": ["quote_map.json"],
                                "instructions": {
                                    "summary": "Align quotes and anchors for mapping.",
                                    "steps": [
                                        "Run: python scripts/build_quote_map.py --in runs/{run_id}/items.jsonl --out runs/{run_id}/quote_map.json",
                                        "Open quote_map.json and fix any 'AMBIGUOUS' entries",
                                    ],
                                    "done_when": ["validate_quote_map exits 0"],
                                    "validation_command": "python scripts/validate_quote_map.py runs/{run_id}/quote_map.json",
                                },
                            },
                            {"id": "publish", "mode": "whole_run", "inputs": ["quote_map.json"], "outputs": ["manifest.json"]},
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
                    output_dir=generated_dir,
                )
            )

            src_stages_dir = root / "src" / "stages"
            src_stages_dir.mkdir(parents=True)
            (src_stages_dir / "ingest.py").write_text(
                """
import json
from pathlib import Path


def run_whole(ctx) -> None:
    Path("items.jsonl").write_text(json.dumps({"item_id": "1"}) + "\\n")
""".strip()
            )
            (src_stages_dir / "publish.py").write_text(
                """
import json
from pathlib import Path


def run_whole(ctx) -> None:
    Path("manifest.json").write_text(json.dumps({"status": "ok"}))
""".strip()
            )

            output_dir = root / "artifacts" / "outputs" / "human-required-run"
            code = run_generated_flow(
                generated_dir=generated_dir,
                run_id="human-required-run",
                output_dir=output_dir,
                inputs_dir=inputs_dir,
            )
            self.assertEqual(code, 20)

            task_json = output_dir / "runs" / "human-required-run" / "tasks" / "align_quotes.task.json"
            task_md = output_dir / "runs" / "human-required-run" / "tasks" / "align_quotes.md"
            marker = output_dir / "runs" / "human-required-run" / "WAITING_HUMAN.align_quotes"
            self.assertTrue(task_json.exists())
            self.assertTrue(task_md.exists())
            self.assertTrue(marker.exists())

            manifest = json.loads((output_dir / ".seedpipe_run_manifest.json").read_text())
            align_row = [row for row in manifest["stages"] if row["stage_id"] == "align_quotes"][0]
            self.assertEqual(align_row["status"], "waiting_human")

            (output_dir / "quote_map.json").write_text(json.dumps({"quotes": []}))
            code_resume = run_generated_flow(
                generated_dir=generated_dir,
                run_id="human-required-run",
                output_dir=output_dir,
                inputs_dir=inputs_dir,
            )
            self.assertEqual(code_resume, 0)
            self.assertFalse(marker.exists())
            self.assertTrue((output_dir / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
