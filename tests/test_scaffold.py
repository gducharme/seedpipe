from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.compile import CompilePaths, compile_pipeline
from tools.scaffold import scaffold_project


class ScaffoldTests(unittest.TestCase):
    def test_scaffold_writes_files_and_compiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            created = scaffold_project(root)

            self.assertTrue((root / "spec/phase1/pipeline.yaml").exists())
            self.assertTrue((root / "agents.markdown").exists())
            self.assertTrue((root / "spec/phase1/contracts/manifest.schema.json").exists())
            self.assertTrue((root / "agents-readme.markdown").exists())
            self.assertTrue((root / "artifacts/inputs/.gitkeep").exists())
            self.assertTrue((root / "artifacts/outputs/.gitkeep").exists())
            self.assertTrue((root / "src" / "stages" / "ingest.py").exists())
            self.assertTrue((root / "src" / "stages" / "transform.py").exists())
            self.assertTrue((root / "src" / "stages" / "publish.py").exists())
            self.assertGreaterEqual(len(created), 13)

            result = compile_pipeline(
                CompilePaths(
                    pipeline_path=root / "spec/phase1/pipeline.yaml",
                    contracts_dir=root / "spec/phase1/contracts",
                    output_dir=root / "generated",
                )
            )
            self.assertEqual(result["pipeline_id"], "example-pipeline")
            self.assertTrue((root / "generated/flow.py").exists())

    def test_scaffold_refuses_overwrite_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scaffold_project(root)
            with self.assertRaises(FileExistsError):
                scaffold_project(root)


if __name__ == "__main__":
    unittest.main()
