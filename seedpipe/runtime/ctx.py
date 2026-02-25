from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StageContext:
    run_id: str
    stage_id: str | None = None
    attempt: int = 1
    run_dir: Path = Path(".")

    @classmethod
    def make_base(cls, run_id: str, run_dir: Path | None = None) -> "StageContext":
        return cls(run_id=run_id, run_dir=run_dir or Path.cwd())

    def for_stage(self, stage_id: str, attempt: int = 1) -> "StageContext":
        return StageContext(run_id=self.run_id, stage_id=stage_id, attempt=attempt, run_dir=self.run_dir)

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
        return self.run_dir / "artifacts" / name
