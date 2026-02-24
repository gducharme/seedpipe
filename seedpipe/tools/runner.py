from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RunResult:
    workdir: Path
    manifest_path: Path
    manifest: dict[str, Any]


def run_fixture_once(fixture_dir: Path, run_label: str, env_overrides: dict[str, str] | None = None, workdir: Path | None = None) -> RunResult:
    script = fixture_dir / "run_fixture.py"
    if not script.exists():
        raise RuntimeError(f"fixture missing run script: {script}")
    if workdir is None:
        workdir = Path(tempfile.mkdtemp(prefix=f"seedpipe-verify-{run_label}-"))
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    cmd = ["python", str(script), "--fixture-dir", str(fixture_dir), "--workdir", str(workdir), "--run-id", run_label]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"fixture run failed ({proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")
    manifest_path = workdir / "manifest.json"
    if not manifest_path.exists():
        raise RuntimeError("fixture run did not produce manifest.json")
    return RunResult(workdir=workdir, manifest_path=manifest_path, manifest=json.loads(manifest_path.read_text()))


def run_fixture_allow_failure(
    fixture_dir: Path,
    run_label: str,
    env_overrides: dict[str, str] | None = None,
    workdir: Path | None = None,
) -> tuple[int, Path, str]:
    script = fixture_dir / "run_fixture.py"
    if workdir is None:
        workdir = Path(tempfile.mkdtemp(prefix=f"seedpipe-verify-{run_label}-"))
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    cmd = ["python", str(script), "--fixture-dir", str(fixture_dir), "--workdir", str(workdir), "--run-id", run_label]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return proc.returncode, workdir, output.strip()
