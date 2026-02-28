from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from seedpipe.tools.contracts import TinySchemaValidator


@dataclass(frozen=True)
class StageContext:
    run_config: dict[str, Any]
    run_id: str
    stage_id: str | None = None
    attempt: int = 1
    run_dir: Path = Path(".")
    keys: dict[str, str] | None = None
    expected_outputs: list[dict[str, Any]] | None = None

    def _artifact_index(self) -> dict[str, str]:
        raw = self.run_config.get("_artifact_index", {})
        if not isinstance(raw, dict):
            return {}
        out: dict[str, str] = {}
        for key, value in raw.items():
            if isinstance(key, str) and isinstance(value, str):
                out[key] = value
        return out

    def _current_output_names(self) -> set[str]:
        # Track the outputs currently being written so we resolve live paths during validation.
        names: set[str] = set()
        for output in self.expected_outputs or []:
            path = output.get("path")
            if isinstance(path, str) and path:
                names.add(path)
        return names

    def _project_root(self) -> Path:
        configured = self.run_config.get("_pipe_root")
        if isinstance(configured, str) and configured.strip():
            return Path(configured)
        return self.run_dir.parent.parent

    def _load_stage_schema(self, stage_id: str, schema_name: str) -> dict[str, Any]:
        schema_path = self._project_root() / "spec" / "stages" / stage_id / schema_name
        if not schema_path.exists():
            raise FileNotFoundError(
                f"schema not found for stage {stage_id}: {schema_path}"
            )
        payload = json.loads(schema_path.read_text())
        if not isinstance(payload, dict):
            raise ValueError(f"schema is not a JSON object: {schema_path}")
        return payload

    def _validate_output_schema(self, stage_id: str, artifact_path: Path, schema_name: str) -> None:
        schema = self._load_stage_schema(stage_id, schema_name)
        validator = TinySchemaValidator({})
        if artifact_path.suffix == ".jsonl":
            for line_no, line in enumerate(artifact_path.read_text().splitlines(), start=1):
                if not line.strip():
                    continue
                value = json.loads(line)
                issues = validator.validate(value, schema)
                if issues:
                    issue = issues[0]
                    raise ValueError(
                        f"schema validation failed for stage {stage_id} output {artifact_path} line {line_no}"
                        f" at {issue.pointer}: {issue.message}"
                    )
            return

        value = json.loads(artifact_path.read_text())
        issues = validator.validate(value, schema)
        if issues:
            issue = issues[0]
            raise ValueError(
                f"schema validation failed for stage {stage_id} output {artifact_path}"
                f" at {issue.pointer}: {issue.message}"
            )

    @classmethod
    def make_base(cls, run_config: dict[str, Any], run_dir: Path | None = None) -> "StageContext":
        run_id = run_config.get("run_id")
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_config must include a non-empty string run_id")
        return cls(run_config=dict(run_config), run_id=run_id, run_dir=run_dir or Path.cwd())

    def for_stage(
        self,
        stage_id: str,
        attempt: int = 1,
        keys: dict[str, str] | None = None,
        expected_outputs: list[dict[str, Any]] | None = None,
    ) -> "StageContext":
        return StageContext(
            run_config=self.run_config,
            run_id=self.run_id,
            stage_id=stage_id,
            attempt=attempt,
            run_dir=self.run_dir,
            keys=dict(keys or {}),
            expected_outputs=[dict(item) for item in (expected_outputs or [])],
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

    def validate_expected_outputs(self, stage_id: str) -> None:
        outputs = self.expected_outputs or []
        explicit = [str(item.get("path", "")) for item in outputs if item.get("path")]
        self.validate_outputs(stage_id, explicit)
        for output in outputs:
            schema_name = output.get("schema")
            path = output.get("path")
            if not isinstance(schema_name, str) or not schema_name:
                continue
            if not isinstance(path, str) or not path:
                continue
            self._validate_output_schema(stage_id, self.resolve_artifact(path), schema_name)

    def resolve_artifact(self, name: str) -> Path:
        path = Path(name)
        if path.is_absolute():
            return path
        # Current stage output checks should resolve the live in-run artifact path.
        if name in self._current_output_names():
            return self.run_dir / path
        index = self._artifact_index()
        concrete = index.get(name)
        if isinstance(concrete, str) and concrete.strip():
            concrete_path = Path(concrete)
            if concrete_path.is_absolute():
                return concrete_path
            return self.run_dir / concrete_path
        if path.parts[:2] == ("artifacts", "inputs"):
            return self.run_dir / path
        return self.run_dir / path
