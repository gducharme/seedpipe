#!/usr/bin/env python3
"""Run compiled Seedpipe flow from a generated output directory."""

from __future__ import annotations

import argparse
import importlib
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
    target.parent.mkdir(parents=True, exist_ok=True)
    resolved_inputs = inputs_dir.resolve()
    try:
        os.symlink(resolved_inputs, target, target_is_directory=True)
    except OSError:
        shutil.copytree(resolved_inputs, target)


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
    if run_output_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing run directory: {run_output_dir}")
    run_output_dir.mkdir(parents=True, exist_ok=False)
    _mount_inputs(run_output_dir, inputs_dir)

    _purge_generated_modules()
    _mount_generated_package(generated_dir)
    _mount_local_src_package(generated_dir.parent)

    flow = importlib.import_module("seedpipe.generated.flow")
    with _pushd(run_output_dir):
        return int(flow.run(run_config=effective_run_config, attempt=attempt))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run generated Seedpipe flow")
    parser.add_argument("--run-id", required=True, help="Unique run identifier")
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    code = run_generated_flow(
        generated_dir=args.generated_dir,
        run_id=args.run_id,
        attempt=args.attempt,
        output_dir=args.output_dir,
        inputs_dir=args.inputs_dir,
    )
    raise SystemExit(code)


if __name__ == "__main__":
    main()
