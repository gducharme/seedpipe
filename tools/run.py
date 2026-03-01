#!/usr/bin/env python3
"""Run compiled Seedpipe flow from a generated output directory."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DEFAULT_GENERATED_DIR = Path("generated")
DEFAULT_INPUTS_DIR = Path("artifacts") / "inputs"
DEFAULT_OUTPUTS_ROOT = Path("artifacts") / "outputs"
RUN_MANIFEST_TEMPLATE = "run_manifest_template.json"
RUN_MANIFEST_NAME = ".seedpipe_run_manifest.json"


def _mount_generated_package(generated_dir: Path) -> None:
    import seedpipe  # noqa: F401

    package_name = "seedpipe.generated"
    package_path = str(generated_dir.resolve())
    package = sys.modules.get(package_name)
    if package is None:
        package = types.ModuleType(package_name)
        package.__path__ = [package_path]  # type: ignore[attr-defined]
        package.__package__ = package_name
        sys.modules[package_name] = package
        return

    existing_paths = list(getattr(package, "__path__", []))
    if package_path not in existing_paths:
        package.__path__ = [package_path, *existing_paths]  # type: ignore[attr-defined]


def _mount_local_src_package(pipe_root: Path) -> None:
    package_name = "seedpipe.src"
    src_dir = pipe_root / "src"
    if not src_dir.exists() or not src_dir.is_dir():
        return

    package_path = str(src_dir.resolve())
    package = sys.modules.get(package_name)
    if package is None:
        package = types.ModuleType(package_name)
        package.__path__ = [package_path]  # type: ignore[attr-defined]
        package.__package__ = package_name
        sys.modules[package_name] = package
        return

    existing_paths = list(getattr(package, "__path__", []))
    if package_path not in existing_paths:
        package.__path__ = [package_path, *existing_paths]  # type: ignore[attr-defined]


def _purge_generated_modules() -> None:
    for module_name in list(sys.modules):
        if module_name == "seedpipe.generated" or module_name.startswith("seedpipe.generated."):
            sys.modules.pop(module_name, None)


@contextmanager
def _pushd(target_dir: Path) -> Iterator[None]:
    previous_dir = Path.cwd()
    os.chdir(target_dir)
    try:
        yield
    finally:
        os.chdir(previous_dir)


def _default_run_output_dir(run_id: str) -> Path:
    return DEFAULT_OUTPUTS_ROOT / run_id


def _mount_inputs(run_output_dir: Path, inputs_dir: Path) -> None:
    target = run_output_dir / "artifacts" / "inputs"
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    resolved_inputs = inputs_dir.resolve()
    try:
        os.symlink(resolved_inputs, target, target_is_directory=True)
    except OSError:
        shutil.copytree(resolved_inputs, target)


def _manifest_path(run_output_dir: Path) -> Path:
    return run_output_dir / RUN_MANIFEST_NAME


def _read_json_file(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"manifest must be a JSON object: {path}")
    return payload


def _write_json_file(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _seed_run_manifest(generated_dir: Path, run_output_dir: Path, run_id: str, stage_ids: list[str], pipeline_id: str) -> dict[str, object]:
    template_path = generated_dir / RUN_MANIFEST_TEMPLATE
    if template_path.exists():
        manifest = _read_json_file(template_path)
    else:
        manifest = {
            "manifest_version": "phase1-run-resume-v1",
            "pipeline_id": pipeline_id,
            "run_id": "",
            "failure_stage_id": None,
            "stages": [{"stage_id": stage_id, "status": "pending", "attempt": 0} for stage_id in stage_ids],
        }

    manifest["run_id"] = run_id
    if "pipeline_id" not in manifest:
        manifest["pipeline_id"] = pipeline_id
    if "failure_stage_id" not in manifest:
        manifest["failure_stage_id"] = None
    _write_json_file(_manifest_path(run_output_dir), manifest)
    return manifest


def _load_or_seed_manifest(
    generated_dir: Path,
    run_output_dir: Path,
    run_id: str,
    stage_ids: list[str],
    pipeline_id: str,
) -> dict[str, object]:
    path = _manifest_path(run_output_dir)
    if path.exists():
        return _read_json_file(path)
    return _seed_run_manifest(generated_dir, run_output_dir, run_id, stage_ids, pipeline_id)


def _stage_rows(manifest: dict[str, object]) -> list[dict[str, object]]:
    rows = manifest.get("stages", [])
    if not isinstance(rows, list):
        raise ValueError("run manifest field stages must be an array")
    typed = [row for row in rows if isinstance(row, dict)]
    if len(typed) != len(rows):
        raise ValueError("run manifest stages entries must be objects")
    return typed


def _all_stages_completed(manifest: dict[str, object]) -> bool:
    rows = _stage_rows(manifest)
    return bool(rows) and all(str(row.get("status", "")) == "completed" for row in rows)


def _resume_stage_from_manifest(manifest: dict[str, object]) -> str | None:
    failure_stage = manifest.get("failure_stage_id")
    if isinstance(failure_stage, str) and failure_stage:
        return failure_stage
    for row in _stage_rows(manifest):
        stage_id = str(row.get("stage_id", "")).strip()
        status = str(row.get("status", "pending"))
        if stage_id and status != "completed":
            return stage_id
    return None


def run_generated_flow(
    generated_dir: Path,
    run_id: str | None = None,
    attempt: int = 1,
    output_dir: Path | None = None,
    inputs_dir: Path = DEFAULT_INPUTS_DIR,
    run_config: dict[str, object] | None = None,
) -> int:
    flow_path = generated_dir / "flow.py"
    if not flow_path.exists():
        raise FileNotFoundError(f"generated flow module not found: {flow_path}")

    if not inputs_dir.exists() or not inputs_dir.is_dir():
        raise FileNotFoundError(f"inputs directory not found: {inputs_dir}")


    effective_run_config = dict(run_config or {})
    if run_id is not None:
        effective_run_config.setdefault('run_id', run_id)

    effective_run_id = effective_run_config.get('run_id')
    if not isinstance(effective_run_id, str) or not effective_run_id.strip():
        raise ValueError('run_config must include a non-empty string run_id')
    run_output_dir = output_dir if output_dir is not None else _default_run_output_dir(effective_run_id)
    preexisting_run_dir = run_output_dir.exists()
    if not preexisting_run_dir:
        run_output_dir.mkdir(parents=True, exist_ok=False)
    _mount_inputs(run_output_dir, inputs_dir)

    _purge_generated_modules()
    _mount_generated_package(generated_dir)
    _mount_local_src_package(generated_dir.parent)

    flow = importlib.import_module("seedpipe.generated.flow")
    stage_ids = list(getattr(flow, "STAGES", []))
    if not stage_ids:
        if preexisting_run_dir:
            raise FileExistsError(f"refusing to overwrite existing run directory: {run_output_dir}")
        with _pushd(run_output_dir):
            return int(flow.run(run_config=effective_run_config, attempt=attempt))
    pipeline_id = str(getattr(flow, "PIPELINE_ID", "pipeline"))

    manifest = _load_or_seed_manifest(
        generated_dir=generated_dir,
        run_output_dir=run_output_dir,
        run_id=effective_run_id,
        stage_ids=stage_ids,
        pipeline_id=pipeline_id,
    )
    if preexisting_run_dir:
        if _all_stages_completed(manifest):
            raise FileExistsError(f"refusing to rerun completed run directory: {run_output_dir}")
        resume_stage_id = _resume_stage_from_manifest(manifest)
        if resume_stage_id:
            effective_run_config.setdefault("_resume_stage_id", resume_stage_id)

    with _pushd(run_output_dir):
        return int(flow.run(run_config=effective_run_config, attempt=attempt))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run generated Seedpipe flow")
    run_group = parser.add_mutually_exclusive_group(required=True)
    run_group.add_argument("--run-id", help="Unique run identifier")
    run_group.add_argument("--resume", help="Resume an existing run by run identifier")
    parser.add_argument("--attempt", type=int, default=1, help="Attempt number (default: 1)")
    parser.add_argument(
        "--generated-dir",
        type=Path,
        default=DEFAULT_GENERATED_DIR,
        help="Directory containing compiled flow code (default: ./generated)",
    )
    parser.add_argument(
        "--inputs-dir",
        type=Path,
        default=DEFAULT_INPUTS_DIR,
        help="Consumable input directory (default: ./artifacts/inputs)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Run output directory (default: ./artifacts/outputs/<run-id>)",
    )
    parser.add_argument(
        "--run-config-file",
        type=Path,
        default=None,
        help="Optional JSON file with run_config values (merged with CLI run-id/resume)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_id = args.run_id if isinstance(args.run_id, str) and args.run_id else args.resume
    run_config: dict[str, object] | None = None
    if args.run_config_file is not None:
        payload = json.loads(args.run_config_file.read_text())
        if not isinstance(payload, dict):
            raise ValueError(f"run config file must be a JSON object: {args.run_config_file}")
        run_config = payload
    code = run_generated_flow(
        generated_dir=args.generated_dir,
        run_id=run_id,
        attempt=args.attempt,
        output_dir=args.output_dir,
        inputs_dir=args.inputs_dir,
        run_config=run_config,
    )
    raise SystemExit(code)


if __name__ == "__main__":
    main()
