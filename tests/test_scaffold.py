from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.compile import CompilePaths, compile_pipeline
from tools.scaffold import scaffold_project


class ScaffoldTests(unittest.TestCase):
    def test_scaffold_writes_files_and_compiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            created = scaffold_project(root)

            self.assertTrue((root / "docs/specs/phase1/pipeline.yaml").exists())
            self.assertTrue((root / "agents.markdown").exists())
            self.assertTrue((root / "docs/specs/phase1/contracts/manifest.schema.json").exists())
            self.assertTrue((root / "spec/stages/ingest/items_row.schema.json").exists())
            self.assertTrue((root / "spec/stages/transform/transformed_row.schema.json").exists())
            self.assertTrue((root / "spec/stages/future_review/reviewed_row.schema.json").exists())
            self.assertTrue((root / "spec/stages/publish/manifest.schema.json").exists())
            agents_text = (root / "agents.markdown").read_text()
            self.assertIn("Practical implementation notes", agents_text)
            self.assertIn("run manifest stage order does not match compiled flow", agents_text)
            self.assertIn("Fast debug checklist", agents_text)
            self.assertTrue((root / "agents-readme.markdown").exists())
            self.assertTrue((root / "artifacts/inputs/.gitkeep").exists())
            outputs_gitignore = root / "artifacts/outputs/.gitignore"
            self.assertTrue(outputs_gitignore.exists())
            self.assertEqual(outputs_gitignore.read_text(), "*\n!.gitignore\n")
            self.assertTrue((root / "Dockerfile").exists())
            self.assertTrue((root / "docker-compose.yml").exists())
            self.assertTrue((root / "inbox/.gitkeep").exists())
            self.assertTrue((root / "outbox/.gitkeep").exists())
            self.assertTrue((root / "src" / "stages" / "ingest.py").exists())
            self.assertTrue((root / "src" / "stages" / "transform.py").exists())
            self.assertTrue((root / "src" / "stages" / "publish.py").exists())
            self.assertGreaterEqual(len(created), 17)

            result = compile_pipeline(
                CompilePaths(
                    pipeline_path=root / "docs/specs/phase1/pipeline.yaml",
                    contracts_dir=root / "docs/specs/phase1/contracts",
                    output_dir=root / "generated",
                )
            )
            self.assertEqual(result["pipeline_id"], "example-pipeline")
            self.assertTrue((root / "generated/flow.py").exists())

    def test_scaffold_agents_readme_uses_runtime_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_repo = Path(tmp) / "fake-seedpipe"
            fake_repo.mkdir(parents=True, exist_ok=True)
            expected = "# Synthetic README\n\nCopied at runtime.\n"
            (fake_repo / "README.md").write_text(expected)

            root = Path(tmp) / "project"
            with patch("tools.scaffold.REPO_ROOT", fake_repo):
                scaffold_project(root)

            self.assertEqual((root / "agents-readme.markdown").read_text(), expected)

    def test_scaffold_refuses_overwrite_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scaffold_project(root)
            with self.assertRaises(FileExistsError):
                scaffold_project(root)

    def test_scaffold_loop_mode_writes_loop_pipeline_and_compiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scaffold_project(root, loop=True)

            pipeline_text = (root / "docs/specs/phase1/pipeline.yaml").read_text()
            self.assertIn("pipeline_type: looping", pipeline_text)
            self.assertIn("max_loops: 3", pipeline_text)
            self.assertTrue((root / "src" / "stages" / "seed.py").exists())

            result = compile_pipeline(
                CompilePaths(
                    pipeline_path=root / "docs/specs/phase1/pipeline.yaml",
                    contracts_dir=root / "docs/specs/phase1/contracts",
                    output_dir=root / "generated",
                )
            )
            self.assertEqual(result["pipeline_id"], "example-pipeline-loop")
            flow_text = (root / "generated" / "flow.py").read_text()
            self.assertIn("PIPELINE_TYPE = 'looping'", flow_text)
            self.assertIn("MAX_LOOPS = 3", flow_text)


if __name__ == "__main__":
    unittest.main()
