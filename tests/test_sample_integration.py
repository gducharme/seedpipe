from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.compile import CompilePaths, compile_pipeline
from tools.run import run_generated_flow


class SampleIntegrationTests(unittest.TestCase):
    def test_sample_pipeline_golden_run(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        sample_src = repo_root / "sample"

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp) / "sample"
            shutil.copytree(sample_src, workdir)
            inputs_dir = workdir / "artifacts" / "inputs"
            inputs_dir.mkdir(parents=True, exist_ok=True)

            compile_result = compile_pipeline(
                CompilePaths(
                    pipeline_path=workdir / "docs/specs/phase1/pipeline.json",
                    contracts_dir=workdir / "docs/specs/phase1/contracts",
                    output_dir=workdir / "generated",
                )
            )
            self.assertEqual(compile_result["pipeline_id"], "localization-release")

            code = run_generated_flow(
                generated_dir=workdir / "generated",
                run_id="golden-run-001",
                output_dir=workdir / "artifacts/outputs/golden-run-001",
                inputs_dir=inputs_dir,
            )
            self.assertEqual(code, 0)

            run_dir = workdir / "artifacts/outputs/golden-run-001"
            manifest = json.loads((run_dir / "published_manifest.json").read_text())
            self.assertEqual(
                manifest,
                {
                    "pipeline_id": "localization-release",
                    "published_reports": [
                        "qa/fr/report.json",
                        "qa/de/report.json",
                        "qa/es/report.json",
                    ],
                },
            )

            for lang in ("fr", "de", "es"):
                report = json.loads((run_dir / f"qa/{lang}/report.json").read_text())
                self.assertEqual(report["lang"], lang)
                self.assertEqual(report["status"], "pass")
                self.assertEqual(report["checked_items"], 2)


if __name__ == "__main__":
    unittest.main()
