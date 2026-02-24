from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path


def h(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def ref(run_id: str, stage_id: str, name: str, path: Path, schema_version: str) -> dict:
    return {
        "name": name,
        "path": str(path.relative_to(path.parent.parent)),
        "hash": h(path),
        "schema_version": schema_version,
        "produced_by": {"run_id": run_id, "stage_id": stage_id, "attempt": 1},
        "bytes": path.stat().st_size,
    }


def maybe_crash(workdir: Path, stage_id: str, phase: str) -> None:
    target = os.environ.get("SEEDPIPE_CRASH_AT", "")
    once = os.environ.get("SEEDPIPE_CRASH_ONCE") == "1"
    marker = workdir / ".crashed_once"
    if once and marker.exists():
        return
    if target == f"stage:{stage_id}:{phase}":
        if once:
            marker.write_text("1")
        raise RuntimeError("InjectedCrash")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-dir", required=True)
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    fixture_dir = Path(args.fixture_dir)
    workdir = Path(args.workdir)
    artifacts = workdir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    run_id = args.run_id
    items_src = fixture_dir / "inputs" / "items.jsonl"
    items_dst = artifacts / "items.jsonl"
    items_dst.write_bytes(items_src.read_bytes())

    stage_outputs = [
        {
            "stage_id": "ingest",
            "outputs": [
                ref(run_id, "ingest", "items.jsonl", items_dst, "seedpipe://spec/phase1/contracts/items_row.schema.json")
            ],
        }
    ]

    maybe_crash(workdir, "validate", "before_commit")
    validation = artifacts / "validation.json"
    validation.write_text(json.dumps({"ok": True, "item_count": 2}, sort_keys=True) + "\n")
    stage_outputs.append(
        {
            "stage_id": "validate",
            "outputs": [
                ref(run_id, "validate", "validation.json", validation, "seedpipe://spec/phase1/contracts/validation.schema.json")
            ],
        }
    )

    manifest = {
        "manifest_version": "phase1-v0",
        "run_id": run_id,
        "pipeline_id": "phase1-seed-minimal",
        "pipeline_spec_hash": "sha256:" + hashlib.sha256((fixture_dir / "pipeline.yaml").read_bytes()).hexdigest(),
        "code_version": "phase1-fixture-v0",
        "config_hash": "sha256:" + hashlib.sha256(b"default").hexdigest(),
        "determinism_policy": "strict",
        "inputs": [
            ref(run_id, "ingest", "items.jsonl", items_dst, "seedpipe://spec/phase1/contracts/items_row.schema.json")
        ],
        "stage_outputs": stage_outputs,
        "final_outputs": [
            ref(run_id, "validate", "validation.json", validation, "seedpipe://spec/phase1/contracts/validation.schema.json")
        ],
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    (workdir / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        if str(exc) == "InjectedCrash":
            raise SystemExit(42)
        raise
