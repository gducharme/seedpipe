from __future__ import annotations

import json
from typing import Any


def normalize_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    copy = json.loads(json.dumps(manifest))
    copy.pop("created_at", None)
    copy.pop("notes", None)
    copy.pop("run_id", None)
    return copy


def artifact_hashes(manifest: dict[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for stage in manifest.get("stage_outputs", []):
        stage_id = stage.get("stage_id", "")
        for artifact in stage.get("outputs", []):
            name = artifact.get("name", "")
            values[f"{stage_id}:{name}"] = artifact.get("hash", "")
    for artifact in manifest.get("final_outputs", []):
        name = artifact.get("name", "")
        values[f"final:{name}"] = artifact.get("hash", "")
    return values


def diff_manifests(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    ah = artifact_hashes(a)
    bh = artifact_hashes(b)
    hash_diff: list[dict[str, str]] = []
    for key in sorted(set(ah) | set(bh)):
        if ah.get(key) != bh.get(key):
            hash_diff.append({"artifact": key, "hash_a": ah.get(key, "<missing>"), "hash_b": bh.get(key, "<missing>")})
    an = normalize_manifest(a)
    bn = normalize_manifest(b)
    semantic_equal = an == bn and not hash_diff
    return {
        "equal": semantic_equal,
        "hash_diff": hash_diff,
        "manifest_keys": sorted(set(an) | set(bn)),
    }
