from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.watch import (
    READY_MARKER,
    WatchConfig,
    _compute_run_id,
    _scan_once,
    _validate_bundle_result,
    publish_outbox_bundle,
)


class WatchCommandTests(unittest.TestCase):
    def _base_config(self, root: Path, *, stale_claim_seconds: int = 900) -> WatchConfig:
        return WatchConfig(
            pipeline="all",
            inbox_root=root / "inbox",
            outbox_root=root / "outbox",
            poll_seconds=1,
            runner="local",
            once=True,
            max_concurrent=1,
            stale_claim_seconds=stale_claim_seconds,
            generated_dir=root / "generated",
            outputs_root=root / "artifacts" / "outputs",
            inputs_root=root / "artifacts" / "inputs",
            pipe_root=root,
        )

    def _write_minimal_flow(self, root: Path) -> None:
        generated = root / "generated"
        generated.mkdir(parents=True, exist_ok=True)
        (generated / "flow.py").write_text(
            """
from pathlib import Path

def run(run_config: dict[str, object], attempt: int = 1) -> int:
    Path("manifest.json").write_text("{\\"ok\\": true}\\n")
    Path("published.txt").write_text(str(run_config["run_id"]))
    return 0
""".strip()
        )

    def _write_bundle(self, root: Path, pipeline: str, bundle: str, *, with_ready: bool = True) -> Path:
        bundle_dir = root / "inbox" / pipeline / bundle
        payload = bundle_dir / "payload"
        payload.mkdir(parents=True, exist_ok=True)
        (payload / "items.jsonl").write_text('{"item_id":"i-1"}\n')
        (bundle_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "bundle_id": bundle,
                    "pipeline_id": pipeline,
                    "created_at_utc": "2026-03-01T00:00:00Z",
                    "artifacts": [{"path": "payload/items.jsonl", "sha256": "0" * 64}],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        if with_ready:
            (bundle_dir / READY_MARKER).write_text("")
        return bundle_dir

    def test_scan_once_processes_ready_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_minimal_flow(root)
            self._write_bundle(root, "demo", "b-1")
            config = self._base_config(root)

            code = _scan_once(config, "watcher-1")

            self.assertEqual(code, 0)
            done_root = root / "inbox" / "demo" / ".done"
            done_entries = list(done_root.iterdir())
            self.assertEqual(len(done_entries), 1)
            run_dirs = list((root / "artifacts" / "outputs").iterdir())
            self.assertEqual(len(run_dirs), 1)
            self.assertTrue((run_dirs[0] / "published.txt").exists())
            self.assertTrue((root / "watcher" / "events.ndjson").exists())

    def test_scan_once_ignores_not_ready_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_minimal_flow(root)
            self._write_bundle(root, "demo", "b-1", with_ready=False)
            config = self._base_config(root)

            code = _scan_once(config, "watcher-1")

            self.assertEqual(code, 0)
            self.assertFalse((root / "artifacts" / "outputs").exists())

    def test_invalid_bundle_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_minimal_flow(root)
            bundle = self._write_bundle(root, "demo", "b-1")
            (bundle / "manifest.json").unlink()
            config = self._base_config(root)

            code = _scan_once(config, "watcher-1")

            self.assertEqual(code, 1)
            rejected = root / "inbox" / "demo" / ".rejected"
            self.assertEqual(len(list(rejected.iterdir())), 1)

    def test_validate_bundle_result_reports_pipeline_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = self._write_bundle(root, "demo", "b-1")
            (bundle / "manifest.json").write_text(
                json.dumps(
                    {
                        "bundle_id": "b-1",
                        "pipeline_id": "other-pipe",
                        "created_at_utc": "2026-03-01T00:00:00Z",
                        "artifacts": [{"path": "payload/items.jsonl", "sha256": "0" * 64}],
                    }
                )
                + "\n"
            )

            result = _validate_bundle_result(bundle, "demo")

            self.assertFalse(result.ok)
            self.assertIsNotNone(result.failure)
            self.assertEqual(result.failure.code, "pipeline_mismatch")

    def test_validate_bundle_result_reports_bundle_id_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = self._write_bundle(root, "demo", "b-1")
            (bundle / "manifest.json").write_text(
                json.dumps(
                    {
                        "bundle_id": "wrong-id",
                        "pipeline_id": "demo",
                        "created_at_utc": "2026-03-01T00:00:00Z",
                        "artifacts": [{"path": "payload/items.jsonl", "sha256": "0" * 64}],
                    }
                )
                + "\n"
            )

            result = _validate_bundle_result(bundle, "demo")

            self.assertFalse(result.ok)
            self.assertIsNotNone(result.failure)
            self.assertEqual(result.failure.code, "bundle_id_mismatch")

    def test_run_id_is_deterministic_for_same_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claim = root / "claim"
            payload = claim / "payload"
            payload.mkdir(parents=True)
            (payload / "items.jsonl").write_text('{"item_id":"i-1"}\n')
            (claim / "manifest.json").write_text(
                json.dumps({"bundle_id": "b-1", "pipeline_id": "demo", "created_at_utc": "t", "artifacts": []}) + "\n"
            )
            first = _compute_run_id("demo", claim, 1709251200)
            second = _compute_run_id("demo", claim, 1709251200)

            self.assertEqual(first, second)
            self.assertTrue(first.startswith("demo_1709251200_"))

    def test_stale_claim_is_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_minimal_flow(root)
            config = self._base_config(root, stale_claim_seconds=1)
            claim = root / "inbox" / "demo" / ".claimed" / "b-1.watcher"
            (claim / "payload").mkdir(parents=True, exist_ok=True)
            (claim / "payload" / "items.jsonl").write_text('{"item_id":"i-1"}\n')
            (claim / "manifest.json").write_text(
                json.dumps(
                    {"bundle_id": "b-1", "pipeline_id": "demo", "created_at_utc": "t", "artifacts": []},
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )
            (claim / READY_MARKER).write_text("")
            (claim / ".claim.json").write_text(
                json.dumps(
                    {
                        "watcher_id": "old",
                        "claimed_at": "2000-01-01T00:00:00Z",
                        "source_path": "x",
                        "pipeline_id": "demo",
                        "bundle_id": "b-1",
                    }
                )
            )
            code = _scan_once(config, "watcher-2")
            self.assertEqual(code, 0)
            self.assertTrue((root / "inbox" / "demo" / ".done").exists())

    def test_publish_outbox_bundle_writes_ready_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "artifact.txt"
            artifact.write_text("hello")
            work_manifest = root / ".seedpipe_run_manifest.json"
            work_manifest.write_text('{"run_id":"run-1"}\n')

            target = publish_outbox_bundle(
                outbox_root=root / "outbox",
                downstream_pipeline="next-pipe",
                producer_run_id="run-1",
                producer_stage_id="publish",
                artifacts=[artifact],
                run_config={"x": 1},
                work_manifest=work_manifest,
            )

            self.assertTrue((target / READY_MARKER).exists())
            self.assertTrue((target / "manifest.json").exists())
            self.assertTrue((target / "payload" / "artifact.txt").exists())
            self.assertTrue((target / "payload" / "work_manifest.json").exists())

    def test_scan_once_publishes_completed_run_outputs_to_outbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._base_config(root)
            run_dir = root / "artifacts" / "outputs" / "run-1"
            final_artifact = run_dir / "publish" / "loops" / "0001" / "published_manifest.json"
            final_artifact.parent.mkdir(parents=True, exist_ok=True)
            final_artifact.write_text('{"ok": true}\n')
            (run_dir / ".seedpipe_run_manifest.json").write_text(
                json.dumps(
                    {
                        "manifest_version": "phase1-run-resume-v1",
                        "pipeline_id": "demo",
                        "run_id": "run-1",
                        "failure_stage_id": None,
                        "artifact_index": {
                            "published_manifest.json": "publish/loops/0001/published_manifest.json",
                        },
                        "stages": [
                            {"stage_id": "ingest", "status": "completed", "attempt": 1},
                            {"stage_id": "publish", "status": "completed", "attempt": 1},
                        ],
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )

            code = _scan_once(config, "watcher-1")

            self.assertEqual(code, 0)
            self.assertTrue((run_dir / ".seedpipe_outbox_published.json").exists())
            published_roots = list((root / "outbox" / "demo").iterdir())
            self.assertEqual(len(published_roots), 1)
            self.assertTrue((published_roots[0] / "_READY").exists())
            self.assertTrue((published_roots[0] / "payload" / "work_manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
