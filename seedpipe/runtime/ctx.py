from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StageContext:
    run_config: dict[str, Any]
    run_id: str
    stage_id: str | None = None
    attempt: int = 1
    run_dir: Path = Path(".")

    @classmethod
    def make_base(cls, run_config: dict[str, Any], run_dir: Path | None = None) -> "StageContext":
        run_id = run_config.get("run_id")
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_config must include a non-empty string run_id")
        return cls(run_config=dict(run_config), run_id=run_id, run_dir=run_dir or Path.cwd())

    def for_stage(self, stage_id: str, attempt: int = 1) -> "StageContext":
        return StageContext(
            run_config=self.run_config,
            run_id=self.run_id,
            stage_id=stage_id,
            attempt=attempt,
            run_dir=self.run_dir,
        )

    def validate_inputs(self, stage_id: str, inputs: list[str]) -> None:
        for name in inputs:
            path = self.resolve_artifact(name)
            if not path.exists():
                raise FileNotFoundError(f"required input artifact missing for stage {stage_id}: {path}")

    def validate_outputs(self, stage_id: str, outputs: list[str]) -> None:
        for name in outputs:
            path = self.resolve_artifact(name)
            if not path.exists():
                raise FileNotFoundError(f"required output artifact missing for stage {stage_id}: {path}")

    def resolve_artifact(self, name: str) -> Path:
        path = Path(name)
        if path.is_absolute():
            return path
        if path.parts[:2] == ("artifacts", "inputs"):
            return self.run_dir / path
        return self.run_dir / path
