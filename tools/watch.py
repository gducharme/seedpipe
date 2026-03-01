#!/usr/bin/env python3
"""Filesystem inbox watcher for auto-triggering Seedpipe runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from tools.run import run_generated_flow

READY_MARKER = "_READY"
STATUS_DIR = Path("watcher")
EVENTS_FILE = STATUS_DIR / "events.ndjson"
STATUS_FILE = STATUS_DIR / "status.json"
OUTBOX_PUBLISH_MARKER = ".seedpipe_outbox_published.json"


@dataclass(frozen=True)
class WatchConfig:
    pipeline: str
    inbox_root: Path
    outbox_root: Path
    poll_seconds: int
    runner: str
    once: bool
    max_concurrent: int
    stale_claim_seconds: int
    generated_dir: Path
    outputs_root: Path
    inputs_root: Path
    pipe_root: Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _append_event(pipe_root: Path, payload: dict[str, Any]) -> None:
    path = pipe_root / EVENTS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _write_status(pipe_root: Path, payload: dict[str, Any]) -> None:
    path = pipe_root / STATUS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _hash_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _hash_dir(path: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(p for p in path.rglob("*") if p.is_file())
    for file_path in files:
        rel = file_path.relative_to(path).as_posix().encode("utf-8")
        digest.update(rel)
        digest.update(b"\0")
        digest.update(_hash_file(file_path).encode("utf-8"))
    return digest.hexdigest()


def _safe_move(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    source.replace(dest)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


def _bundle_paths(inbox_root: Path, pipeline_id: str) -> list[Path]:
    pipeline_dir = inbox_root / pipeline_id
    if not pipeline_dir.exists():
        return []
    return sorted(
        [
            p
            for p in pipeline_dir.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        ]
    )


def _discover_pipelines(inbox_root: Path) -> list[str]:
    if not inbox_root.exists():
        return []
    return sorted([p.name for p in inbox_root.iterdir() if p.is_dir() and not p.name.startswith(".")])


def _validate_bundle(bundle_dir: Path, pipeline_id: str) -> tuple[bool, str]:
    ready = bundle_dir / READY_MARKER
    if not ready.exists():
        return False, "bundle is not ready"
    manifest_path = bundle_dir / "manifest.json"
    if not manifest_path.exists():
        return False, "missing manifest.json"
    payload_dir = bundle_dir / "payload"
    if not payload_dir.exists() or not payload_dir.is_dir():
        return False, "missing payload/ directory"
    try:
        manifest = _load_json(manifest_path)
    except Exception as exc:
        return False, f"invalid manifest.json: {exc}"
    manifest_pipeline = str(manifest.get("pipeline_id", "")).strip()
    if manifest_pipeline and manifest_pipeline != pipeline_id:
        return False, "manifest pipeline_id does not match inbox pipeline"
    manifest_bundle = str(manifest.get("bundle_id", "")).strip()
    if manifest_bundle and manifest_bundle != bundle_dir.name:
        return False, "manifest bundle_id does not match bundle directory"
    return True, ""


def _reclaim_stale_claims(config: WatchConfig, pipeline_id: str) -> None:
    claimed_dir = config.inbox_root / pipeline_id / ".claimed"
    if not claimed_dir.exists():
        return
    now = time.time()
    for claim in claimed_dir.iterdir():
        if not claim.is_dir():
            continue
        claim_file = claim / ".claim.json"
        age_seconds = now - claim.stat().st_mtime
        if claim_file.exists():
            try:
                metadata = _load_json(claim_file)
                claimed_at = str(metadata.get("claimed_at", ""))
                if claimed_at:
                    claimed_dt = datetime.fromisoformat(claimed_at.replace("Z", "+00:00"))
                    age_seconds = now - claimed_dt.timestamp()
            except Exception:
                pass
        if age_seconds < config.stale_claim_seconds:
            continue
        original_name = claim.name.split(".", 1)[0]
        restore_target = config.inbox_root / pipeline_id / original_name
        if restore_target.exists():
            _safe_move(claim, config.inbox_root / pipeline_id / ".rejected" / claim.name)
            _append_event(
                config.pipe_root,
                {
                    "ts": _utc_now(),
                    "event": "stale_claim_rejected",
                    "pipeline_id": pipeline_id,
                    "claim": str(claim),
                    "reason": "restore_target_exists",
                },
            )
            continue
        _safe_move(claim, restore_target)
        _append_event(
            config.pipe_root,
            {
                "ts": _utc_now(),
                "event": "stale_claim_requeued",
                "pipeline_id": pipeline_id,
                "bundle_id": restore_target.name,
            },
        )


def _claim_bundle(config: WatchConfig, pipeline_id: str, bundle_dir: Path, watcher_id: str) -> Path | None:
    claimed_target = config.inbox_root / pipeline_id / ".claimed" / f"{bundle_dir.name}.{watcher_id}"
    try:
        _safe_move(bundle_dir, claimed_target)
    except FileNotFoundError:
        return None
    except OSError:
        return None
    claim_payload = {
        "watcher_id": watcher_id,
        "claimed_at": _utc_now(),
        "source_path": str(config.inbox_root / pipeline_id / bundle_dir.name),
        "pipeline_id": pipeline_id,
        "bundle_id": bundle_dir.name,
    }
    (claimed_target / ".claim.json").write_text(json.dumps(claim_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _append_event(config.pipe_root, {"ts": _utc_now(), "event": "claimed", **claim_payload})
    return claimed_target


def _reject_claim(config: WatchConfig, pipeline_id: str, claim_dir: Path, reason: str) -> None:
    target = config.inbox_root / pipeline_id / ".rejected" / claim_dir.name
    _safe_move(claim_dir, target)
    (target / ".reason.json").write_text(
        json.dumps({"rejected_at": _utc_now(), "reason": reason}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _append_event(
        config.pipe_root,
        {"ts": _utc_now(), "event": "rejected", "pipeline_id": pipeline_id, "bundle_id": target.name, "reason": reason},
    )


def _materialize_inputs(config: WatchConfig, run_id: str, claim_dir: Path) -> Path:
    target = config.inputs_root / run_id
    if target.exists():
        return target
    payload_dir = claim_dir / "payload"
    target.mkdir(parents=True, exist_ok=False)
    for child in payload_dir.iterdir():
        destination = target / child.name
        if child.is_dir():
            if os.name != "nt":
                try:
                    os.symlink(child.resolve(), destination, target_is_directory=True)
                    continue
                except OSError:
                    pass
            shutil.copytree(child, destination)
        else:
            shutil.copy2(child, destination)
    return target


def _effective_runner(config: WatchConfig, lock_payload: dict[str, Any] | None) -> str:
    if config.runner in {"docker", "local"}:
        return config.runner
    if lock_payload is not None:
        runner = str(lock_payload.get("runner", "")).strip()
        if runner in {"docker", "local"}:
            return runner
    return "docker"


def _load_seedpipe_lock(pipe_root: Path) -> dict[str, Any] | None:
    lock_path = pipe_root / "seedpipe.lock"
    if not lock_path.exists():
        return None
    payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return payload
    return None


def _docker_image(lock_payload: dict[str, Any] | None) -> str | None:
    if lock_payload is None:
        return None
    runtime = lock_payload.get("runtime")
    if isinstance(runtime, dict):
        image = runtime.get("image")
        if isinstance(image, str) and image.strip():
            return image.strip()
    return None


def _compute_run_id(pipeline_id: str, claim_dir: Path, unix_ts: int) -> str:
    payload_hash = _hash_dir(claim_dir / "payload")
    return f"{pipeline_id}_{int(unix_ts)}_{payload_hash[:12]}"


def publish_outbox_bundle(
    outbox_root: Path,
    downstream_pipeline: str,
    producer_run_id: str,
    producer_stage_id: str,
    artifacts: list[Path],
    run_config: dict[str, Any] | None = None,
    work_manifest: Path | None = None,
) -> Path:
    hash_input = hashlib.sha256()
    for artifact in sorted(artifacts):
        hash_input.update(artifact.name.encode("utf-8"))
        hash_input.update(_hash_file(artifact).encode("utf-8"))
    bundle_id = f"{producer_run_id}_{producer_stage_id}_{hash_input.hexdigest()[:12]}"
    bundle_dir = outbox_root / downstream_pipeline / bundle_id
    payload_dir = bundle_dir / "payload"
    payload_dir.mkdir(parents=True, exist_ok=False)
    artifact_rows: list[dict[str, str]] = []
    for artifact in artifacts:
        destination = payload_dir / artifact.name
        shutil.copy2(artifact, destination)
        artifact_rows.append({"path": f"payload/{artifact.name}", "sha256": _hash_file(destination)})
    if work_manifest is not None and work_manifest.exists() and work_manifest.is_file():
        manifest_dest = payload_dir / "work_manifest.json"
        shutil.copy2(work_manifest, manifest_dest)
        artifact_rows.append({"path": "payload/work_manifest.json", "sha256": _hash_file(manifest_dest)})
    manifest = {
        "bundle_id": bundle_id,
        "pipeline_id": downstream_pipeline,
        "created_at_utc": _utc_now(),
        "producer_run_id": producer_run_id,
        "producer_stage_id": producer_stage_id,
        "artifacts": artifact_rows,
    }
    (bundle_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (bundle_dir / "run_config.json").write_text(json.dumps(run_config or {}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (bundle_dir / READY_MARKER).write_text("", encoding="utf-8")
    return bundle_dir


def _run_local(
    config: WatchConfig,
    run_id: str,
    inputs_dir: Path,
    run_config: dict[str, Any],
) -> int:
    return run_generated_flow(
        generated_dir=config.generated_dir,
        run_id=run_id,
        output_dir=config.outputs_root / run_id,
        inputs_dir=inputs_dir,
        run_config=run_config,
    )


def _run_docker(
    config: WatchConfig,
    run_id: str,
    run_config: dict[str, Any],
    image: str,
) -> int:
    if shutil.which("docker") is None:
        raise RuntimeError("docker runner requested but docker is not available")
    runtime_dir = config.pipe_root / ".seedpipe_watch_runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    config_path = runtime_dir / f"{run_id}.run_config.json"
    config_path.write_text(json.dumps(run_config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{config.pipe_root.resolve()}:/work",
        "-w",
        "/work",
        image,
        "python",
        "-m",
        "tools.run",
        "--run-id",
        run_id,
        "--generated-dir",
        "/work/generated",
        "--inputs-dir",
        f"/work/artifacts/inputs/{run_id}",
        "--output-dir",
        f"/work/artifacts/outputs/{run_id}",
        "--run-config-file",
        f"/work/.seedpipe_watch_runtime/{config_path.name}",
    ]
    completed = subprocess.run(command, cwd=config.pipe_root, check=False)
    return int(completed.returncode)


def _invoke_runner(
    config: WatchConfig,
    run_id: str,
    inputs_dir: Path,
    run_config: dict[str, Any],
) -> tuple[int, str]:
    lock_payload = _load_seedpipe_lock(config.pipe_root)
    desired = _effective_runner(config, lock_payload)
    if desired == "docker":
        image = _docker_image(lock_payload)
        if image and shutil.which("docker") is not None:
            return _run_docker(config, run_id, run_config, image), "docker"
        return _run_local(config, run_id, inputs_dir, run_config), "local"
    return _run_local(config, run_id, inputs_dir, run_config), "local"


def _publish_from_claim(
    config: WatchConfig,
    claim_dir: Path,
    run_id: str,
    run_config: dict[str, Any],
) -> list[str]:
    manifest = _load_json(claim_dir / "manifest.json")
    downstreams = manifest.get("downstreams", [])
    publish_paths = manifest.get("publish_artifacts", [])
    if not isinstance(downstreams, list) or not isinstance(publish_paths, list):
        return []
    outputs_dir = config.outputs_root / run_id
    published: list[str] = []
    artifacts: list[Path] = []
    for value in publish_paths:
        if not isinstance(value, str) or not value.strip():
            continue
        candidate = outputs_dir / value
        if candidate.exists() and candidate.is_file():
            artifacts.append(candidate)
    if not artifacts:
        return []
    for downstream in downstreams:
        if not isinstance(downstream, str) or not downstream.strip():
            continue
        bundle_dir = publish_outbox_bundle(
            outbox_root=config.outbox_root,
            downstream_pipeline=downstream.strip(),
            producer_run_id=run_id,
            producer_stage_id="watch_publish",
            artifacts=artifacts,
            run_config=run_config,
            work_manifest=config.outputs_root / run_id / ".seedpipe_run_manifest.json",
        )
        published.append(str(bundle_dir))
    return published


def _is_run_completed(manifest: dict[str, Any]) -> bool:
    rows = manifest.get("stages")
    if not isinstance(rows, list) or not rows:
        return False
    for row in rows:
        if not isinstance(row, dict):
            return False
        if str(row.get("status", "")).strip() != "completed":
            return False
    return True


def _publish_completed_run_to_outbox(config: WatchConfig, run_dir: Path) -> list[str]:
    publish_marker = run_dir / OUTBOX_PUBLISH_MARKER
    if publish_marker.exists():
        return []
    manifest_path = run_dir / ".seedpipe_run_manifest.json"
    if not manifest_path.exists():
        return []
    manifest = _load_json(manifest_path)
    if not _is_run_completed(manifest):
        return []
    run_id = str(manifest.get("run_id", "")).strip()
    pipeline_id = str(manifest.get("pipeline_id", "")).strip()
    rows = manifest.get("stages")
    if not isinstance(rows, list) or not rows:
        return []
    last_stage = rows[-1]
    if not isinstance(last_stage, dict):
        return []
    final_stage_id = str(last_stage.get("stage_id", "")).strip()
    if not run_id or not pipeline_id or not final_stage_id:
        return []

    artifact_index = manifest.get("artifact_index", {})
    if not isinstance(artifact_index, dict):
        artifact_index = {}
    artifacts: list[Path] = []
    prefix = f"{final_stage_id}/loops/"
    for concrete in artifact_index.values():
        if not isinstance(concrete, str) or not concrete.startswith(prefix):
            continue
        candidate = run_dir / concrete
        if candidate.exists() and candidate.is_file():
            artifacts.append(candidate)
    if not artifacts:
        return []
    artifacts = sorted(set(artifacts))
    bundle = publish_outbox_bundle(
        outbox_root=config.outbox_root,
        downstream_pipeline=pipeline_id,
        producer_run_id=run_id,
        producer_stage_id=final_stage_id,
        artifacts=artifacts,
        run_config={"run_id": run_id, "pipeline_id": pipeline_id},
        work_manifest=manifest_path,
    )
    publish_marker.write_text(
        json.dumps({"published_at": _utc_now(), "bundles": [str(bundle)]}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _append_event(
        config.pipe_root,
        {
            "ts": _utc_now(),
            "event": "outbox_published",
            "run_id": run_id,
            "pipeline_id": pipeline_id,
            "bundle": str(bundle),
        },
    )
    return [str(bundle)]


def _scan_completed_runs_for_outbox(config: WatchConfig) -> int:
    if not config.outputs_root.exists():
        return 0
    published = 0
    for run_dir in sorted(config.outputs_root.iterdir()):
        if not run_dir.is_dir():
            continue
        published += len(_publish_completed_run_to_outbox(config, run_dir))
    return published


def _process_claim(config: WatchConfig, pipeline_id: str, claim_dir: Path) -> int:
    try:
        run_config = {}
        run_config_path = claim_dir / "run_config.json"
        if run_config_path.exists():
            run_config = _load_json(run_config_path)
        trigger_payload: dict[str, Any] = {"type": "filesystem", "source_bundle": claim_dir.name, "claimed_at": _utc_now()}
        trigger_path = claim_dir / "trigger.json"
        if trigger_path.exists():
            trigger_payload["payload"] = _load_json(trigger_path)
        claim_payload = _load_json(claim_dir / ".claim.json")
        claimed_at = str(claim_payload.get("claimed_at", ""))
        claim_ts = int(datetime.fromisoformat(claimed_at.replace("Z", "+00:00")).timestamp()) if claimed_at else int(time.time())
        run_id = _compute_run_id(pipeline_id, claim_dir, claim_ts)
        inputs_dir = _materialize_inputs(config, run_id, claim_dir)
        effective_run_config = dict(run_config)
        effective_run_config["run_id"] = run_id
        effective_run_config["trigger"] = trigger_payload
        code, backend = _invoke_runner(config, run_id, inputs_dir, effective_run_config)
        _append_event(
            config.pipe_root,
            {
                "ts": _utc_now(),
                "event": "run_finished",
                "pipeline_id": pipeline_id,
                "bundle_id": claim_dir.name,
                "run_id": run_id,
                "runtime_backend": backend,
                "exit_code": code,
            },
        )
        if code == 0:
            published = _publish_from_claim(config, claim_dir, run_id, effective_run_config)
            _append_event(
                config.pipe_root,
                {"ts": _utc_now(), "event": "published", "run_id": run_id, "count": len(published), "bundles": published},
            )
            _publish_completed_run_to_outbox(config, config.outputs_root / run_id)
            done_dir = config.inbox_root / pipeline_id / ".done" / claim_dir.name
            _safe_move(claim_dir, done_dir)
        return code
    except Exception as exc:
        _reject_claim(config, pipeline_id, claim_dir, f"processing error: {exc}")
        return 1


def _scan_once(config: WatchConfig, watcher_id: str) -> int:
    pipelines = _discover_pipelines(config.inbox_root) if config.pipeline == "all" else [config.pipeline]
    had_failure = False
    processed = 0
    for pipeline_id in pipelines:
        _reclaim_stale_claims(config, pipeline_id)
        bundles = _bundle_paths(config.inbox_root, pipeline_id)
        for bundle in bundles[: max(1, config.max_concurrent)]:
            valid, reason = _validate_bundle(bundle, pipeline_id)
            if not valid:
                if reason == "bundle is not ready":
                    continue
                _reject_claim(config, pipeline_id, bundle, reason)
                had_failure = True
                continue
            claim = _claim_bundle(config, pipeline_id, bundle, watcher_id)
            if claim is None:
                continue
            processed += 1
            code = _process_claim(config, pipeline_id, claim)
            if code != 0:
                had_failure = True
    published_completed_runs = _scan_completed_runs_for_outbox(config)
    _write_status(
        config.pipe_root,
        {
            "watcher_id": watcher_id,
            "last_scan_utc": _utc_now(),
            "pipelines": pipelines,
            "processed": processed,
            "published_completed_runs": published_completed_runs,
            "had_failure": had_failure,
        },
    )
    if had_failure:
        return 1
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Watch inbox bundles and auto-run Seedpipe pipelines")
    parser.add_argument("--pipeline", default="all", help="Pipeline to watch (default: all)")
    parser.add_argument("--inbox-root", type=Path, default=Path("inbox"), help="Inbox root (default: ./inbox)")
    parser.add_argument("--outbox-root", type=Path, default=Path("outbox"), help="Outbox root (default: ./outbox)")
    parser.add_argument("--poll-seconds", type=int, default=5, help="Polling interval in seconds (default: 5)")
    parser.add_argument("--runner", choices=["docker", "local", "auto"], default="auto", help="Runner backend (default: auto)")
    parser.add_argument("--once", action="store_true", help="Run a single scan and exit")
    parser.add_argument("--max-concurrent", type=int, default=1, help="Maximum bundles per pipeline scan (default: 1)")
    parser.add_argument("--stale-claim-seconds", type=int, default=900, help="Stale claim reclaim threshold (default: 900)")
    parser.add_argument("--generated-dir", type=Path, default=Path("generated"), help="Generated flow directory (default: ./generated)")
    parser.add_argument(
        "--outputs-root",
        type=Path,
        default=Path("artifacts") / "outputs",
        help="Run outputs root (default: ./artifacts/outputs)",
    )
    parser.add_argument(
        "--inputs-root",
        type=Path,
        default=Path("artifacts") / "inputs",
        help="Run inputs root (default: ./artifacts/inputs)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = WatchConfig(
        pipeline=args.pipeline,
        inbox_root=args.inbox_root,
        outbox_root=args.outbox_root,
        poll_seconds=max(1, int(args.poll_seconds)),
        runner=args.runner,
        once=bool(args.once),
        max_concurrent=max(1, int(args.max_concurrent)),
        stale_claim_seconds=max(1, int(args.stale_claim_seconds)),
        generated_dir=args.generated_dir,
        outputs_root=args.outputs_root,
        inputs_root=args.inputs_root,
        pipe_root=Path.cwd(),
    )
    watcher_id = f"{socket.gethostname()}-{os.getpid()}"
    fatal = False
    exit_code = 0
    try:
        while True:
            code = _scan_once(config, watcher_id)
            exit_code = max(exit_code, code)
            if config.once:
                break
            time.sleep(config.poll_seconds)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        _append_event(config.pipe_root, {"ts": _utc_now(), "event": "fatal", "error": str(exc)})
        fatal = True
    raise SystemExit(2 if fatal else exit_code)


if __name__ == "__main__":
    main()
