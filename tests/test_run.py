from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
