from __future__ import annotations

import unittest

from seedpipe.tools.diff import artifact_hashes, diff_manifests, normalize_manifest


class DiffToolsTests(unittest.TestCase):
    def test_normalize_manifest_removes_non_semantic_fields(self) -> None:
        manifest = {
            "run_id": "r1",
            "created_at": "2026-01-01T00:00:00Z",
            "notes": "x",
            "stage_outputs": [],
        }
        normalized = normalize_manifest(manifest)
        self.assertNotIn("run_id", normalized)
        self.assertNotIn("created_at", normalized)
        self.assertNotIn("notes", normalized)

    def test_artifact_hashes_collects_stage_and_final(self) -> None:
        manifest = {
            "stage_outputs": [
                {"stage_id": "ingest", "outputs": [{"name": "items.jsonl", "hash": "sha256:a"}]}
            ],
            "final_outputs": [{"name": "manifest.json", "hash": "sha256:b"}],
        }
        hashes = artifact_hashes(manifest)
        self.assertEqual(hashes["ingest:items.jsonl"], "sha256:a")
        self.assertEqual(hashes["final:manifest.json"], "sha256:b")

    def test_diff_manifests_equal_ignores_run_id_created_at_notes(self) -> None:
        a = {
            "run_id": "r1",
            "created_at": "2026-01-01T00:00:00Z",
            "notes": "n1",
            "stage_outputs": [{"stage_id": "s1", "outputs": [{"name": "x.json", "hash": "sha256:1"}]}],
            "final_outputs": [],
        }
        b = {
            "run_id": "r2",
            "created_at": "2026-01-02T00:00:00Z",
            "notes": "n2",
            "stage_outputs": [{"stage_id": "s1", "outputs": [{"name": "x.json", "hash": "sha256:1"}]}],
            "final_outputs": [],
        }
        diff = diff_manifests(a, b)
        self.assertTrue(diff["equal"])
        self.assertEqual(diff["hash_diff"], [])

    def test_diff_manifests_detects_hash_changes(self) -> None:
        a = {"stage_outputs": [{"stage_id": "s1", "outputs": [{"name": "x.json", "hash": "sha256:1"}]}], "final_outputs": []}
        b = {"stage_outputs": [{"stage_id": "s1", "outputs": [{"name": "x.json", "hash": "sha256:2"}]}], "final_outputs": []}
        diff = diff_manifests(a, b)
        self.assertFalse(diff["equal"])
        self.assertEqual(diff["hash_diff"][0]["artifact"], "s1:x.json")


if __name__ == "__main__":
    unittest.main()
