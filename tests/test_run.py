from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr
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


def run(run_id: str, attempt: int = 1) -> int:
    marker = Path('marker.txt')
    marker.write_text(f"{run_id}:{attempt}")
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

    def test_run_generated_flow_uses_default_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated_dir = root / "generated"
            generated_dir.mkdir()
            (root / "artifacts" / "inputs").mkdir(parents=True)
            (generated_dir / "flow.py").write_text(
                """
from pathlib import Path


def run(run_id: str, attempt: int = 1) -> int:
    Path('ran.txt').write_text(run_id)
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

    def test_run_generated_flow_errors_if_run_id_dir_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated_dir = root / "generated"
            generated_dir.mkdir()
            inputs_dir = root / "artifacts" / "inputs"
            inputs_dir.mkdir(parents=True)
            (generated_dir / "flow.py").write_text("def run(run_id: str, attempt: int = 1) -> int:\n    return 0\n")
            output_dir = root / "artifacts" / "outputs" / "existing-run"
            output_dir.mkdir(parents=True)

            with self.assertRaises(FileExistsError):
                run_generated_flow(generated_dir=generated_dir, run_id="existing-run", output_dir=output_dir, inputs_dir=inputs_dir)

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
            (generated_dir / "flow.py").write_text("def run(run_id: str, attempt: int = 1) -> int:\n    return 0\n")

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
    Path('artifacts/items.jsonl').write_text('{\"item_id\": \"i-1\"}\\n')
""".strip()
            )

            (generated_dir / "flow.py").write_text(
                """
from seedpipe.generated.stages import ingest
from seedpipe.runtime.ctx import StageContext


def run(run_id: str, attempt: int = 1) -> int:
    ctx = StageContext.make_base(run_id=run_id).for_stage('ingest', attempt=attempt)
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
            self.assertTrue((output_dir / "artifacts" / "items.jsonl").exists())



    def test_run_generated_flow_emits_debug_diagnostics_for_missing_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated_dir = root / "generated"
            generated_dir.mkdir()
            inputs_dir = root / "artifacts" / "inputs"
            inputs_dir.mkdir(parents=True)
            (inputs_dir / "items.jsonl").write_text('{"item_id":"i-1"}\n')
            (generated_dir / "flow.py").write_text(
                """
def run(run_id: str, attempt: int = 1) -> int:
    raise FileNotFoundError(2, 'No such file or directory', 'artifacts/outputs/7/artifacts/word_frequency_report.json')
""".strip()
            )

            output_dir = root / "artifacts" / "outputs" / "demo-run"
            stderr = io.StringIO()
            with self.assertRaises(FileNotFoundError):
                with redirect_stderr(stderr):
                    run_generated_flow(
                        generated_dir=generated_dir,
                        run_id="demo-run",
                        attempt=2,
                        output_dir=output_dir,
                        inputs_dir=inputs_dir,
                    )

            report = stderr.getvalue()
            self.assertIn("[seedpipe-run] run failed; collecting diagnostics", report)
            self.assertIn("run artifacts outputs", report)
            self.assertIn("word_frequency_report.json", report)
            self.assertIn("traceback:", report)


if __name__ == "__main__":
    unittest.main()
