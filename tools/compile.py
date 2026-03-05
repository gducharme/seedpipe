#!/usr/bin/env python3
"""Compile pipeline.yaml + contracts into generated orchestration code."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import dataclasses
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import textwrap
from typing import Any, Literal

from tools.compile_flow_templates import _FLOW_RUN_PREFIX, _FLOW_RUN_SUFFIX, _FLOW_RUNTIME_HELPERS


COMPILER_VERSION = "phase1-mvp"
DEFAULT_PIPELINE_PATH = Path("docs/specs/phase1/pipeline.yaml")
DEFAULT_CONTRACTS_DIR = Path("docs/specs/phase1/contracts")
DEFAULT_OUTPUT_DIR = Path("generated")


class CompileError(ValueError):
    """Raised when compilation fails with user-facing diagnostics."""


@dataclasses.dataclass(frozen=True)
class StageIR:
    stage_id: str
    mode: Literal["whole_run", "per_item", "human_required"]
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    keys: tuple[tuple[str, str], ...]
    expected_outputs: tuple[dict[str, Any], ...]
    instructions: dict[str, Any] | None
    placeholder: bool
    reentry: str | None
    go_to: str | None


@dataclasses.dataclass(frozen=True)
class PipelineIR:
    pipeline_id: str
    item_unit: str
    determinism_policy: Literal["strict", "best_effort"]
    pipeline_type: Literal["straight", "looping"]
    max_loops: int
    stages: tuple[StageIR, ...]
    artifact_producers: dict[str, str]


@dataclasses.dataclass(frozen=True)
class CompilePaths:
    pipeline_path: Path
    contracts_dir: Path
    output_dir: Path


def sha256_file(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def sha256_directory(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def stable_json(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


class CodeBuilder:
    def __init__(self) -> None:
        self._parts: list[str] = []

    def line(self, text: str = "") -> None:
        self._parts.append(text + "\n")

    def add(self, text: str) -> None:
        self._parts.append(text)

    def render(self) -> str:
        return "".join(self._parts)


def load_pipeline(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise CompileError(f"pipeline file not found: {path}")
    text = path.read_text()
    try:
        import yaml  # type: ignore

        class _UniqueKeyLoader(yaml.SafeLoader):
            pass

        def _construct_mapping(loader: Any, node: Any, deep: bool = False) -> dict[str, Any]:
            loader.flatten_mapping(node)
            mapping: dict[str, Any] = {}
            for key_node, value_node in node.value:
                key = loader.construct_object(key_node, deep=deep)
                if key in mapping:
                    raise CompileError(f"duplicate key in pipeline YAML: {key}")
                mapping[key] = loader.construct_object(value_node, deep=deep)
            return mapping

        _UniqueKeyLoader.add_constructor(  # type: ignore[attr-defined]
            yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
            _construct_mapping,
        )

        data = yaml.load(text, Loader=_UniqueKeyLoader)
    except ModuleNotFoundError:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise CompileError("pipeline must be a YAML object")
    return data


def _resolve_path_expr(root: dict[str, Any], expr: str) -> Any:
    parts = expr.split(".")
    cursor: Any = root
    for part in parts:
        if not isinstance(cursor, dict) or part not in cursor:
            raise CompileError(f"unable to resolve expression: {expr}")
        cursor = cursor[part]
    return cursor


def _render_template(value: str, scope: dict[str, Any]) -> str:
    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in scope:
            raise CompileError(f"template variable '{key}' not found in stage scope")
        return str(scope[key])

    return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", _replace, value)


def _resolve_stage_key_scopes(
    raw: dict[str, Any],
    stage_idx: int,
    stage_foreach: Any,
    stage_key: Any,
) -> list[dict[str, Any]]:
    if stage_foreach is None:
        return [{}]
    if not isinstance(stage_foreach, str):
        raise CompileError(f"pipeline.stages[{stage_idx}].foreach must be a string expression")
    values = _resolve_path_expr(raw, stage_foreach)
    if not isinstance(values, list):
        raise CompileError(f"pipeline.stages[{stage_idx}].foreach must resolve to a list")
    if not isinstance(stage_key, str) or not stage_key:
        raise CompileError(f"pipeline.stages[{stage_idx}].key must be a non-empty string when foreach is set")
    return [{stage_key: value} for value in values]


def _expand_stage_inputs(
    *,
    raw: dict[str, Any],
    stage_idx: int,
    stage_id: str,
    inputs_raw: list[Any],
    stage_key_scopes: list[dict[str, Any]],
) -> list[str]:
    concrete_inputs: list[str] = []
    for key_scope in stage_key_scopes:
        for input_idx, entry in enumerate(inputs_raw):
            if isinstance(entry, str):
                concrete_inputs.append(_render_template(entry, key_scope))
                continue
            if not isinstance(entry, dict):
                raise CompileError(f"pipeline.stages[{stage_idx}].inputs[{input_idx}] must be a string or object")
            family = entry.get("family")
            pattern = entry.get("pattern")
            schema = entry.get("schema")
            if not isinstance(family, str) or not isinstance(pattern, str) or not isinstance(schema, str):
                raise CompileError(
                    f"pipeline.stages[{stage_idx}] (id='{stage_id}').inputs[{input_idx}] object entries require string 'family', 'pattern', and 'schema'"
                )
            _ = family, schema
            concrete_inputs.append(_render_template(pattern, key_scope))
    return list(dict.fromkeys(concrete_inputs))


def _resolve_output_key_scopes(
    *,
    raw: dict[str, Any],
    stage_idx: int,
    output_idx: int,
    entry: dict[str, Any],
    base_scope: dict[str, Any],
) -> list[dict[str, Any]]:
    out_foreach = entry.get("foreach")
    out_key = entry.get("key")
    output_key_scopes: list[dict[str, Any]] = [dict(base_scope)]
    if out_foreach is not None:
        if not isinstance(out_foreach, str):
            raise CompileError(
                f"pipeline.stages[{stage_idx}].outputs[{output_idx}].foreach must be a string expression"
            )
        values = _resolve_path_expr(raw, out_foreach)
        if not isinstance(values, list):
            raise CompileError(
                f"pipeline.stages[{stage_idx}].outputs[{output_idx}].foreach must resolve to a list"
            )
        if not isinstance(out_key, str) or not out_key:
            raise CompileError(
                f"pipeline.stages[{stage_idx}].outputs[{output_idx}].key must be a non-empty string"
            )
        output_key_scopes = [{**base_scope, out_key: value} for value in values]
    return output_key_scopes


def _expand_stage_outputs(
    *,
    raw: dict[str, Any],
    stage_idx: int,
    outputs_raw: list[Any],
    stage_key_scopes: list[dict[str, Any]],
) -> tuple[list[str], list[dict[str, Any]]]:
    concrete_outputs: list[str] = []
    expected_outputs: list[dict[str, Any]] = []
    for key_scope in stage_key_scopes:
        for output_idx, entry in enumerate(outputs_raw):
            if isinstance(entry, str):
                concrete_path = _render_template(entry, key_scope)
                concrete_outputs.append(concrete_path)
                expected_outputs.append(
                    {
                        "pattern": entry,
                        "path": concrete_path,
                        "keys": dict(sorted((str(k), str(v)) for k, v in key_scope.items())),
                    }
                )
                continue
            if not isinstance(entry, dict):
                raise CompileError(f"pipeline.stages[{stage_idx}].outputs[{output_idx}] must be a string or object")

            family = entry.get("family")
            pattern = entry.get("pattern")
            schema = entry.get("schema")
            if not isinstance(family, str) or not isinstance(pattern, str):
                raise CompileError(
                    f"pipeline.stages[{stage_idx}].outputs[{output_idx}] object entries require string 'family' and 'pattern'"
                )
            if schema is not None and not isinstance(schema, str):
                raise CompileError(
                    f"pipeline.stages[{stage_idx}].outputs[{output_idx}].schema must be a string when provided"
                )

            output_key_scopes = _resolve_output_key_scopes(
                raw=raw,
                stage_idx=stage_idx,
                output_idx=output_idx,
                entry=entry,
                base_scope=key_scope,
            )
            for output_key_scope in output_key_scopes:
                path = _render_template(pattern, output_key_scope)
                concrete_outputs.append(path)
                expected_outputs.append(
                    {
                        "family": family,
                        "pattern": pattern,
                        "path": path,
                        "keys": dict(sorted((str(k), str(v)) for k, v in output_key_scope.items())),
                        **({"schema": schema} if isinstance(schema, str) else {}),
                    }
                )
    return list(dict.fromkeys(concrete_outputs)), expected_outputs


def expand_pipeline_dsl(raw: dict[str, Any]) -> dict[str, Any]:
    expanded = dict(raw)
    source_stages = expanded.get("stages", [])
    if source_stages is None:
        source_stages = []
    if not isinstance(source_stages, list):
        raise CompileError("pipeline.stages must be an array")

    concrete_stages: list[dict[str, Any]] = []

    for idx, stage in enumerate(source_stages):
        if not isinstance(stage, dict):
            raise CompileError(f"pipeline.stages[{idx}] must be an object")

        stage_id = stage.get("id")
        if not isinstance(stage_id, str) or not stage_id.strip():
            raise CompileError(f"pipeline.stages[{idx}].id must be a non-empty string")

        stage_foreach = stage.get("foreach")
        stage_key = stage.get("key")
        stage_key_scopes = _resolve_stage_key_scopes(raw, idx, stage_foreach, stage_key)

        instance = dict(stage)
        instance["_keys"] = {}
        instance.pop("foreach", None)
        instance.pop("key", None)

        inputs_raw = instance.get("inputs", [])
        outputs_raw = instance.get("outputs", [])
        if not isinstance(inputs_raw, list) or not isinstance(outputs_raw, list):
            raise CompileError(f"pipeline.stages[{idx}].inputs/outputs must be arrays")

        instance["inputs"] = _expand_stage_inputs(
            raw=raw,
            stage_idx=idx,
            stage_id=stage_id,
            inputs_raw=inputs_raw,
            stage_key_scopes=stage_key_scopes,
        )
        concrete_outputs, expected_outputs = _expand_stage_outputs(
            raw=raw,
            stage_idx=idx,
            outputs_raw=outputs_raw,
            stage_key_scopes=stage_key_scopes,
        )
        instance["outputs"] = concrete_outputs
        instance["_expected_outputs"] = expected_outputs
        concrete_stages.append(instance)

    expanded["stages"] = concrete_stages
    return expanded


def normalize_pipeline(raw: dict[str, Any]) -> dict[str, Any]:
    normalized = expand_pipeline_dsl(raw)
    normalized.setdefault("pipeline_id", "pipeline")
    normalized.setdefault("item_unit", "item")
    normalized.setdefault("determinism_policy", "strict")
    normalized.setdefault("pipeline_type", "straight")
    normalized.setdefault("max_loops", 0)
    stages = normalized.get("stages", [])
    if stages is None:
        stages = []
    if not isinstance(stages, list):
        raise CompileError("pipeline.stages must be an array")
    normalized_stages = []
    for idx, stage in enumerate(stages):
        if not isinstance(stage, dict):
            raise CompileError(f"pipeline.stages[{idx}] must be an object")
        s = dict(stage)
        s.setdefault("inputs", [])
        s.setdefault("outputs", [])
        s.setdefault("mode", "whole_run")
        s.setdefault("placeholder", False)
        normalized_stages.append(s)
    normalized["stages"] = normalized_stages
    return normalized


@dataclasses.dataclass
class _PipelineValidationContext:
    pipeline: dict[str, Any]
    pipeline_id: str
    pipeline_type: str
    max_loops: int
    stages: list[dict[str, Any]]
    seen_stage_ids: set[str] = dataclasses.field(default_factory=set)
    produced_so_far: set[str] = dataclasses.field(default_factory=set)
    reentry_stage_by_name: dict[str, int] = dataclasses.field(default_factory=dict)
    pending_go_tos: list[tuple[int, str]] = dataclasses.field(default_factory=list)


def _validate_pipeline_top_level(pipeline: dict[str, Any]) -> _PipelineValidationContext:
    pipeline_id = pipeline.get("pipeline_id")
    if not isinstance(pipeline_id, str) or not pipeline_id.strip():
        raise CompileError("pipeline.pipeline_id must be a non-empty string")
    if pipeline.get("determinism_policy") not in {"strict", "best_effort"}:
        raise CompileError(f"pipeline '{pipeline_id}' determinism_policy must be 'strict' or 'best_effort'")
    pipeline_type = pipeline.get("pipeline_type")
    if pipeline_type not in {"straight", "looping"}:
        raise CompileError(f"pipeline '{pipeline_id}' pipeline_type must be 'straight' or 'looping'")
    max_loops = pipeline.get("max_loops", 0)
    if not isinstance(max_loops, int) or max_loops < 0:
        raise CompileError(f"pipeline '{pipeline_id}' max_loops must be an integer >= 0")

    stages = pipeline.get("stages", [])
    if not stages:
        raise CompileError("pipeline.stages must include at least one stage")
    if not isinstance(stages, list):
        raise CompileError("pipeline.stages must include at least one stage")

    return _PipelineValidationContext(
        pipeline=pipeline,
        pipeline_id=pipeline_id,
        pipeline_type=pipeline_type,
        max_loops=max_loops,
        stages=stages,
    )


def _validate_human_required_instructions(mode: Any, instructions: Any, stage_index: int) -> None:
    if mode == "human_required":
        if not isinstance(instructions, dict):
            raise CompileError(f"pipeline.stages[{stage_index}].instructions must be an object when mode='human_required'")
        summary = instructions.get("summary")
        steps = instructions.get("steps")
        done_when = instructions.get("done_when")
        if not isinstance(summary, str) or not summary.strip():
            raise CompileError(
                f"pipeline.stages[{stage_index}].instructions.summary must be a non-empty string when mode='human_required'"
            )
        if not isinstance(steps, list) or not steps or any(not isinstance(step, str) or not step.strip() for step in steps):
            raise CompileError(
                f"pipeline.stages[{stage_index}].instructions.steps must be a non-empty array of strings when mode='human_required'"
            )
        if not isinstance(done_when, list) or not done_when or any(
            not isinstance(item, str) or not item.strip() for item in done_when
        ):
            raise CompileError(
                f"pipeline.stages[{stage_index}].instructions.done_when must be a non-empty array of strings when mode='human_required'"
            )
        troubleshooting = instructions.get("troubleshooting")
        if troubleshooting is not None and (
            not isinstance(troubleshooting, list) or any(not isinstance(item, str) or not item.strip() for item in troubleshooting)
        ):
            raise CompileError(
                f"pipeline.stages[{stage_index}].instructions.troubleshooting must be an array of strings when provided"
            )
        validation_command = instructions.get("validation_command")
        if validation_command is not None and (not isinstance(validation_command, str) or not validation_command.strip()):
            raise CompileError(
                f"pipeline.stages[{stage_index}].instructions.validation_command must be a non-empty string when provided"
            )
        return
    if instructions is not None:
        raise CompileError(f"pipeline.stages[{stage_index}].instructions is only allowed when mode='human_required'")


def _validate_stage_rows(ctx: _PipelineValidationContext) -> None:
    for idx, stage in enumerate(ctx.stages):
        sid = stage.get("id")
        if not isinstance(sid, str) or not sid.strip():
            raise CompileError(f"pipeline.stages[{idx}].id must be a non-empty string")
        if sid in ctx.seen_stage_ids:
            raise CompileError(f"duplicate stage id: {sid}")
        ctx.seen_stage_ids.add(sid)

        mode = stage.get("mode")
        if mode not in {"whole_run", "per_item", "human_required"}:
            raise CompileError(f"pipeline.stages[{idx}].mode must be 'whole_run', 'per_item', or 'human_required'")

        _validate_human_required_instructions(mode=mode, instructions=stage.get("instructions"), stage_index=idx)

        placeholder = stage.get("placeholder")
        if not isinstance(placeholder, bool):
            raise CompileError(f"pipeline.stages[{idx}].placeholder must be a boolean")

        reentry = stage.get("reentry")
        if reentry is not None and (not isinstance(reentry, str) or not reentry.strip()):
            raise CompileError(f"pipeline.stages[{idx}].reentry must be a non-empty string when provided")
        go_to = stage.get("go_to")
        if go_to is not None and (not isinstance(go_to, str) or not go_to.strip()):
            raise CompileError(f"pipeline.stages[{idx}].go_to must be a non-empty string when provided")

        for field in ("inputs", "outputs"):
            if not isinstance(stage.get(field), list):
                raise CompileError(f"pipeline.stages[{idx}].{field} must be an array")

        stage_inputs = stage.get("inputs", [])
        stage_outputs = stage.get("outputs", [])
        for name in stage_inputs + stage_outputs:
            if not isinstance(name, str) or not name.strip():
                raise CompileError(f"pipeline.stages[{idx}] contains non-string artifact in inputs/outputs")

        unresolved = [artifact for artifact in stage_inputs if artifact not in ctx.produced_so_far]
        if unresolved and not placeholder:
            unresolved_joined = ", ".join(unresolved)
            raise CompileError(
                f"pipeline.stages[{idx}] has forward/unresolved inputs: {unresolved_joined}; "
                "inputs must be produced by earlier stages"
            )

        if isinstance(reentry, str):
            if reentry in ctx.reentry_stage_by_name:
                prior_idx = ctx.reentry_stage_by_name[reentry]
                prior_stage_id = ctx.stages[prior_idx].get("id", "<unknown>")
                raise CompileError(
                    f"pipeline '{ctx.pipeline_id}' stage[{idx}] (id='{sid}') reentry '{reentry}' duplicates stage[{prior_idx}] (id='{prior_stage_id}')"
                )
            ctx.reentry_stage_by_name[reentry] = idx
        if isinstance(go_to, str):
            ctx.pending_go_tos.append((idx, go_to))

        ctx.produced_so_far.update(stage_outputs)


def _validate_loop_semantics(ctx: _PipelineValidationContext) -> None:
    if ctx.pipeline_type == "straight":
        if ctx.reentry_stage_by_name or ctx.pending_go_tos:
            raise CompileError(
                f"pipeline '{ctx.pipeline_id}' with type 'straight' does not allow 'reentry' or 'go_to' stage fields"
            )
        if ctx.max_loops != 0:
            raise CompileError(f"pipeline '{ctx.pipeline_id}' with type 'straight' requires max_loops=0")
        return

    if ctx.max_loops < 1:
        raise CompileError(f"pipeline '{ctx.pipeline_id}' with type 'looping' requires max_loops >= 1")
    if not ctx.reentry_stage_by_name:
        raise CompileError("pipeline_type 'looping' requires at least one stage with 'reentry'")

    for idx, target in ctx.pending_go_tos:
        stage_id = ctx.stages[idx].get("id", "<unknown>")
        target_stage_idx = ctx.reentry_stage_by_name.get(target)
        if target_stage_idx is None:
            raise CompileError(
                f"pipeline '{ctx.pipeline_id}' stage[{idx}] (id='{stage_id}') go_to='{target}' references unknown reentry"
            )
        target_stage_id = ctx.stages[target_stage_idx].get("id", "<unknown>")
        if target_stage_idx >= idx:
            raise CompileError(
                f"pipeline '{ctx.pipeline_id}' stage[{idx}] (id='{stage_id}') go_to='{target}' points to stage[{target_stage_idx}] "
                f"(id='{target_stage_id}') which is not earlier"
            )


def validate_pipeline_structure(pipeline: dict[str, Any]) -> None:
    ctx = _validate_pipeline_top_level(pipeline)
    validators = [_validate_stage_rows, _validate_loop_semantics]
    for validator in validators:
        validator(ctx)


def build_ir(pipeline: dict[str, Any]) -> PipelineIR:
    stages: list[StageIR] = []
    artifact_producers: dict[str, str] = {}
    for stage in pipeline["stages"]:
        stage_ir = StageIR(
            stage_id=stage["id"],
            mode=stage["mode"],
            inputs=tuple(stage["inputs"]),
            outputs=tuple(stage["outputs"]),
            keys=tuple(sorted((str(k), str(v)) for k, v in stage.get("_keys", {}).items())),
            expected_outputs=tuple(stage.get("_expected_outputs", [])),
            instructions=stage.get("instructions"),
            placeholder=bool(stage.get("placeholder", False)),
            reentry=stage.get("reentry"),
            go_to=stage.get("go_to"),
        )
        stages.append(stage_ir)
        for artifact_name in stage_ir.outputs:
            artifact_producers[artifact_name] = stage_ir.stage_id

    return PipelineIR(
        pipeline_id=pipeline["pipeline_id"],
        item_unit=pipeline["item_unit"],
        determinism_policy=pipeline["determinism_policy"],
        pipeline_type=pipeline["pipeline_type"],
        max_loops=int(pipeline.get("max_loops", 0)),
        stages=tuple(stages),
        artifact_producers=artifact_producers,
    )


def load_contracts(paths: CompilePaths) -> dict[str, dict[str, Any]]:
    contract_candidates = sorted(paths.contracts_dir.glob("*.schema.json"))
    if not contract_candidates:
        raise CompileError(f"no contracts found in {paths.contracts_dir}")

    contracts: dict[str, dict[str, Any]] = {}
    for schema_path in contract_candidates:
        contracts[schema_path.name] = json.loads(schema_path.read_text())

    required = {
        "manifest.schema.json",
        "artifact_ref.schema.json",
        "item_state_row.schema.json",
        "items_row.schema.json",
        "metrics_contract.schema.json",
    }
    missing = required - set(contracts)
    if missing:
        missing_names = ", ".join(sorted(missing))
        raise CompileError(f"missing required contracts: {missing_names}")

    _validate_metrics_contract_schema(contracts["metrics_contract.schema.json"])
    return contracts


def _validate_metrics_contract_schema(schema: dict[str, Any]) -> None:
    if not isinstance(schema, dict):
        raise CompileError("metrics_contract.schema.json must be a JSON object")
    if schema.get("type") != "object":
        raise CompileError("metrics_contract.schema.json must declare type=object")

    required_fields = {"function_id", "metric_name", "value", "unit", "timestamp", "run_id", "producer"}
    schema_required = set(schema.get("required", []))
    missing_required = required_fields - schema_required
    if missing_required:
        missing = ", ".join(sorted(missing_required))
        raise CompileError(f"metrics_contract.schema.json missing required field declarations: {missing}")

    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise CompileError("metrics_contract.schema.json must declare properties object")

    for field in required_fields:
        if field not in properties:
            raise CompileError(f"metrics_contract.schema.json missing property definition: {field}")

    metric_name = properties.get("metric_name", {})
    metric_enum = set(metric_name.get("enum", [])) if isinstance(metric_name, dict) else set()
    required_metrics = {"latency", "cost", "success_count", "failure_count", "quality_rating"}
    missing_metrics = required_metrics - metric_enum
    if missing_metrics:
        missing = ", ".join(sorted(missing_metrics))
        raise CompileError(f"metrics_contract.schema.json missing required metric names: {missing}")


@dataclasses.dataclass(frozen=True)
class ArtifactSchemaSpec:
    schema_name: str
    predicate: Callable[[str], bool]

    def matches(self, artifact_name: str) -> bool:
        return bool(self.predicate(artifact_name))


def _artifact_schema_specs() -> tuple[ArtifactSchemaSpec, ...]:
    return (
        ArtifactSchemaSpec(
            schema_name="items_row.schema.json",
            predicate=lambda artifact: artifact.endswith("items.jsonl") or artifact == "items.jsonl",
        ),
        ArtifactSchemaSpec(
            schema_name="item_state_row.schema.json",
            predicate=lambda artifact: artifact.endswith("item_state.jsonl") or artifact == "item_state.jsonl",
        ),
        ArtifactSchemaSpec(
            schema_name="manifest.schema.json",
            predicate=lambda artifact: artifact.endswith("manifest.json") or artifact == "manifest.json",
        ),
        ArtifactSchemaSpec(
            schema_name="artifact_ref.schema.json",
            predicate=lambda artifact: True,
        ),
    )


def resolve_artifact_schemas(ir: PipelineIR, contracts: dict[str, dict[str, Any]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    specs = _artifact_schema_specs()
    for artifact in sorted(ir.artifact_producers):
        for spec in specs:
            if spec.matches(artifact):
                mapping[artifact] = spec.schema_name
                break

    missing = sorted({schema for schema in mapping.values() if schema not in contracts})
    if missing:
        raise CompileError(f"resolved schema(s) not found in contracts dir: {', '.join(missing)}")

    return mapping



def ensure_package_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    init = path / "__init__.py"
    if not init.exists():
        init.write_text("\n")


def generated_banner(meta: dict[str, str]) -> str:
    return (
        "# AUTO-GENERATED by seedpipe.tools.compile\n"
        "# DO NOT EDIT. Changes will be overwritten.\n"
        f"# Source: pipeline.yaml hash: {meta['pipeline_hash']}\n"
        f"# Contracts hash: {meta['contracts_hash']}\n\n"
    )


def emit_models_py(contracts: dict[str, dict[str, Any]], meta: dict[str, str]) -> str:
    contracts_json = stable_json(contracts)
    body = """from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

@dataclass
class ProducedBy:
    run_id: str
    stage_id: str
    attempt: int = 1

@dataclass
class ArtifactRef:
    name: str
    path: str
    hash: str
    schema_version: str
    produced_by: ProducedBy
    bytes: int | None = None

@dataclass
class ItemResult:
    item_id: str
    ok: bool
    error: dict[str, Any] | None = None

CONTRACTS: dict[str, dict[str, Any]] = json.loads({contracts_json})

def get_schema(name: str) -> dict[str, Any]:
    if name not in CONTRACTS:
        raise KeyError(f'unknown schema: {{name}}')
    return CONTRACTS[name]

def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text())
"""
    return generated_banner(meta) + body.format(contracts_json=repr(contracts_json))


def python_string_list(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(repr(v) for v in values) + "]"


def _stage_module_name(stage_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", stage_id)


def _collect_stage_invocations(stage: StageIR) -> list[tuple[dict[str, str], list[dict[str, Any]]]]:
    invocations: list[tuple[dict[str, str], list[dict[str, Any]]]] = []
    seen_signatures: set[tuple[tuple[tuple[str, str], ...], tuple[str, ...]]] = set()
    for output in stage.expected_outputs:
        output_keys = {str(key): str(value) for key, value in output.get("keys", {}).items()}
        if output_keys and not set(dict(stage.keys)).issubset(output_keys.items()):
            continue
        invocation_keys = output_keys or dict(stage.keys)
        invocation_expected = [
            output_item
            for output_item in stage.expected_outputs
            if {str(key): str(value) for key, value in output_item.get("keys", {}).items()} == invocation_keys
        ]
        signature = (
            tuple(sorted(invocation_keys.items())),
            tuple(str(item.get("path", "")) for item in invocation_expected),
        )
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        invocations.append((invocation_keys, invocation_expected))
    if not invocations:
        invocations.append((dict(stage.keys), list(stage.expected_outputs)))
    return invocations


def _append_human_required_stage_lines(call_lines: list[str], stage: StageIR) -> None:
    call_lines.append("            try:")
    call_lines.append(
        f"                ctx = ctx_base.for_stage({stage.stage_id!r}, attempt=attempt, keys={dict(stage.keys)!r}, expected_outputs={list(stage.expected_outputs)!r})"
    )
    call_lines.append(f"                ctx.validate_inputs(ctx.stage_id or '', {python_string_list(stage.inputs)})")
    call_lines.append(
        f"                waiting = _human_stage_waiting(manifest=manifest, run_id=run_id, pipe_root=str(run_config.get('_pipe_root', '')), stage_id={stage.stage_id!r}, instructions={stage.instructions!r}, required_inputs={list(stage.inputs)!r}, expected_outputs={list(stage.expected_outputs)!r}, attempt=attempt)"
    )
    call_lines.append("                if waiting:")
    call_lines.append("                    return WAITING_HUMAN_EXIT_CODE")
    call_lines.append(
        f"                _register_stage_outputs(manifest=manifest, stage_id={stage.stage_id!r}, loop_iteration=loop_iteration, outputs={python_string_list(stage.outputs)})"
    )
    call_lines.append("                run_config['_artifact_index'] = _artifact_index(manifest)")
    call_lines.append("                ctx_base = StageContext.make_base(run_config=run_config)")
    call_lines.append(f"                _mark_stage(manifest, stage_id={stage.stage_id!r}, status='completed', attempt=attempt)")
    call_lines.append("            except Exception as exc:")
    call_lines.append(
        f"                _mark_stage(manifest, stage_id={stage.stage_id!r}, status='failed', attempt=attempt, error={{'message': str(exc)}})"
    )
    call_lines.append("                raise")


def _append_whole_run_stage_invocation_lines(
    call_lines: list[str],
    stage: StageIR,
    stage_mod_name: str,
    invocation_keys: dict[str, str],
    invocation_expected: list[dict[str, Any]],
) -> None:
    call_lines.append(
        f"                ctx = ctx_base.for_stage({stage.stage_id!r}, attempt=attempt, keys={invocation_keys!r}, expected_outputs={invocation_expected!r})"
    )
    call_lines.append(f"                stage_{stage_mod_name}.run_whole(ctx)")


def _append_per_item_stage_invocation_lines(
    call_lines: list[str],
    stage: StageIR,
    stage_mod_name: str,
    invocation_keys: dict[str, str],
    invocation_expected: list[dict[str, Any]],
) -> None:
    items_artifact = stage.inputs[0] if stage.inputs else "items.jsonl"
    call_lines.append(
        f"                ctx = ctx_base.for_stage({stage.stage_id!r}, attempt=attempt, keys={invocation_keys!r}, expected_outputs={invocation_expected!r})"
    )
    call_lines.append(
        f"                for item in _iter_stage_items(ctx, items_artifact={items_artifact!r}, keys=ctx.keys, active_item_ids=active_item_ids):"
    )
    call_lines.append("                    item_id = str(item.get('item_id', ''))")
    call_lines.append("                    item_attempt = _next_item_attempt(manifest, stage_id=ctx.stage_id or '', item_id=item_id)")
    call_lines.append("                    append_item_state_row({")
    call_lines.append("                        'run_id': run_id,")
    call_lines.append("                        'item_id': item_id,")
    call_lines.append("                        'state': 'in_progress',")
    call_lines.append(f"                        'stage_id': {stage.stage_id!r},")
    call_lines.append("                        'attempt': item_attempt,")
    call_lines.append("                        'loop_iteration': loop_iteration,")
    call_lines.append("                        'updated_at': now_rfc3339(),")
    call_lines.append("                    })")
    call_lines.append(f"                    res = stage_{stage_mod_name}.run_item(ctx, item)")
    call_lines.append("                    if res.ok:")
    call_lines.append("                        append_item_state_row({")
    call_lines.append("                            'run_id': run_id,")
    call_lines.append("                            'item_id': item_id,")
    call_lines.append("                            'state': 'succeeded',")
    call_lines.append(f"                            'stage_id': {stage.stage_id!r},")
    call_lines.append("                            'attempt': item_attempt,")
    call_lines.append("                            'loop_iteration': loop_iteration,")
    call_lines.append("                            'updated_at': now_rfc3339(),")
    call_lines.append("                        })")
    call_lines.append("                        continue")
    call_lines.append("                    err = res.error if isinstance(res.error, dict) else {'code': 'stage_failed', 'message': str(res.error)}")
    call_lines.append("                    failure_source = str(err.get('source', 'stage'))")
    call_lines.append("                    append_item_state_row({")
    call_lines.append("                        'run_id': run_id,")
    call_lines.append("                        'item_id': item_id,")
    call_lines.append("                        'state': 'failed',")
    call_lines.append(f"                        'stage_id': {stage.stage_id!r},")
    call_lines.append("                        'attempt': item_attempt,")
    call_lines.append("                        'loop_iteration': loop_iteration,")
    call_lines.append("                        'error': err,")
    call_lines.append("                        'failure_source': failure_source,")
    call_lines.append("                        'updated_at': now_rfc3339(),")
    call_lines.append("                    })")
    call_lines.append("                    stage_failed_item_ids.append(item_id)")


def _append_per_item_failure_routing_lines(call_lines: list[str], stage: StageIR) -> None:
    call_lines.append("                if stage_failed_item_ids:")
    call_lines.append(f"                    loop_target = _resolve_loop_target({stage.stage_id!r})")
    call_lines.append("                    if PIPELINE_TYPE == 'looping' and loop_target is not None:")
    call_lines.append("                        next_cycle_start_index = _stage_index(loop_target)")
    call_lines.append("                        next_active_item_ids = sorted(set(stage_failed_item_ids))")
    call_lines.append("                        loop_continue = True")
    call_lines.append(f"                        loop_origin_stage = {stage.stage_id!r}")
    call_lines.append("                    else:")
    call_lines.append(
        f"                        raise RuntimeError(f'stage {stage.stage_id} failed for items: {{sorted(set(stage_failed_item_ids))}}')"
    )


def _append_stage_completion_lines(call_lines: list[str], stage: StageIR) -> None:
    call_lines.append(
        f"                _register_stage_outputs(manifest=manifest, stage_id={stage.stage_id!r}, loop_iteration=loop_iteration, outputs={python_string_list(stage.outputs)})"
    )
    call_lines.append("                run_config['_artifact_index'] = _artifact_index(manifest)")
    call_lines.append("                ctx_base = StageContext.make_base(run_config=run_config)")
    call_lines.append(f"                _mark_stage(manifest, stage_id={stage.stage_id!r}, status='completed', attempt=attempt)")


def _append_stage_exception_lines(call_lines: list[str], stage: StageIR) -> None:
    call_lines.append("            except Exception as exc:")
    call_lines.append(
        f"                _mark_stage(manifest, stage_id={stage.stage_id!r}, status='failed', attempt=attempt, error={{'message': str(exc)}})"
    )
    call_lines.append("                raise")


def _emit_human_required_stage_lines(
    call_lines: list[str],
    stage: StageIR,
    stage_mod_name: str,
    invocations: list[tuple[dict[str, str], list[dict[str, Any]]]],
) -> None:
    _ = stage_mod_name, invocations
    _append_human_required_stage_lines(call_lines, stage)


def _emit_stage_with_try_block(
    call_lines: list[str],
    stage: StageIR,
    body_emitter: Callable[[], None],
) -> None:
    call_lines.append(f"            _mark_stage(manifest, stage_id={stage.stage_id!r}, status='running', attempt=attempt)")
    call_lines.append("            try:")
    body_emitter()
    _append_stage_completion_lines(call_lines, stage)
    _append_stage_exception_lines(call_lines, stage)


def _emit_whole_run_stage_lines(
    call_lines: list[str],
    stage: StageIR,
    stage_mod_name: str,
    invocations: list[tuple[dict[str, str], list[dict[str, Any]]]],
) -> None:
    def _emit_body() -> None:
        for invocation_keys, invocation_expected in invocations:
            _append_whole_run_stage_invocation_lines(
                call_lines,
                stage,
                stage_mod_name,
                invocation_keys,
                invocation_expected,
            )

    _emit_stage_with_try_block(call_lines, stage, _emit_body)


def _emit_per_item_stage_lines(
    call_lines: list[str],
    stage: StageIR,
    stage_mod_name: str,
    invocations: list[tuple[dict[str, str], list[dict[str, Any]]]],
) -> None:
    def _emit_body() -> None:
        call_lines.append("                stage_failed_item_ids: list[str] = []")
        for invocation_keys, invocation_expected in invocations:
            _append_per_item_stage_invocation_lines(
                call_lines,
                stage,
                stage_mod_name,
                invocation_keys,
                invocation_expected,
            )
        _append_per_item_failure_routing_lines(call_lines, stage)

    _emit_stage_with_try_block(call_lines, stage, _emit_body)


def _stage_mode_emitters() -> dict[str, Any]:
    return {
        "human_required": _emit_human_required_stage_lines,
        "whole_run": _emit_whole_run_stage_lines,
        "per_item": _emit_per_item_stage_lines,
    }


def emit_stage_wrapper(stage: StageIR, meta: dict[str, str]) -> str:
    mode_fn = "run_whole" if stage.mode in {"whole_run", "human_required"} else "run_item"
    wrapper_name = mode_fn
    mode_signature = "ctx: StageContext" if stage.mode in {"whole_run", "human_required"} else "ctx: StageContext, item: dict[str, Any]"
    mode_call = "impl.run_whole(ctx)" if stage.mode in {"whole_run", "human_required"} else "impl.run_item(ctx, item)"
    validate_outputs_call = (
        "    outputs_to_validate = [str(item.get('path', '')) for item in (ctx.expected_outputs or []) if item.get('path')] or OUTPUTS\n"
        "    ctx.validate_outputs(STAGE_ID, outputs_to_validate)\n"
        "    ctx.validate_expected_outputs(STAGE_ID)\n"
    )
    item_result_return = (
        "    item_id = item.get('item_id', '')\n"
        "    try:\n"
        f"        stage_result = {mode_call}\n"
        "    except Exception as exc:\n"
        "        return ItemResult(\n"
        "            item_id=str(item_id),\n"
        "            ok=False,\n"
        "            error={'code': 'stage_exception', 'message': str(exc), 'source': 'stage'},\n"
        "        )\n"
        "    if isinstance(stage_result, ItemResult):\n"
        "        if not stage_result.ok:\n"
        "            err = stage_result.error or {'code': 'stage_failed', 'message': 'stage returned failure'}\n"
        "            if isinstance(err, dict):\n"
        "                err = dict(err)\n"
        "                err.setdefault('source', 'stage')\n"
        "            return ItemResult(item_id=str(item_id), ok=False, error=err)\n"
        "        item_id = stage_result.item_id or str(item_id)\n"
        "    try:\n"
        "        outputs_to_validate = [str(item.get('path', '')) for item in (ctx.expected_outputs or []) if item.get('path')] or OUTPUTS\n"
        "        ctx.validate_outputs(STAGE_ID, outputs_to_validate)\n"
        "        ctx.validate_expected_outputs(STAGE_ID)\n"
        "    except Exception as exc:\n"
        "        return ItemResult(\n"
        "            item_id=str(item_id),\n"
        "            ok=False,\n"
        "            error={'code': 'runtime_validation', 'message': str(exc), 'source': 'runtime'},\n"
        "        )\n"
        "    if isinstance(stage_result, ItemResult):\n"
        "        return ItemResult(item_id=str(item_id), ok=True)\n"
        "    return ItemResult(item_id=str(item_id), ok=True)\n"
    )
    whole_return = f"    {mode_call}\n" + validate_outputs_call
    function_body = (
        "    pass\n"
        if stage.mode == "human_required"
        else (
            "    pass\n"
            if stage.placeholder and stage.mode == "whole_run"
        else (
            "    item_id = item.get('item_id', '')\n"
            "    return ItemResult(item_id=str(item_id), ok=True)\n"
            if stage.placeholder and stage.mode == "per_item"
            else "    ctx.validate_inputs(STAGE_ID, INPUTS)\n"
            + (whole_return if stage.mode == "whole_run" else item_result_return)
        )
        )
    )
    b = CodeBuilder()
    b.add(generated_banner(meta))
    b.line("from __future__ import annotations")
    b.line()
    b.line("from typing import Any")
    b.line()
    b.line("from seedpipe.runtime.ctx import StageContext")
    b.line("from seedpipe.generated.models import ItemResult")
    if not stage.placeholder and stage.mode != "human_required":
        b.line(f"from seedpipe.src.stages import {stage.stage_id} as impl")
    b.line()
    b.line(f"STAGE_ID = {stage.stage_id!r}")
    b.line(f"MODE = {stage.mode!r}")
    b.line(f"INPUTS = {python_string_list(stage.inputs)}")
    b.line(f"OUTPUTS = {python_string_list(stage.outputs)}")
    b.line()
    signature = " -> None:" if stage.mode in {"whole_run", "human_required"} else " -> ItemResult:"
    b.line(f"def {wrapper_name}({mode_signature}){signature}")
    b.add(function_body)
    return b.render()


def emit_stages_init_py(ir: PipelineIR, meta: dict[str, str]) -> str:
    b = CodeBuilder()
    b.add(generated_banner(meta))
    b.line("from __future__ import annotations")
    b.line()
    for stage in ir.stages:
        b.line(f"from . import {stage.stage_id}")
    b.line()
    all_exports = ", ".join(repr(stage.stage_id) for stage in ir.stages)
    b.line(f"__all__ = [{all_exports}]")
    return b.render()


def emit_flow_py(ir: PipelineIR, meta: dict[str, str]) -> str:
    stage_ids = [stage.stage_id for stage in ir.stages]
    reentry_to_stage = {stage.reentry: stage.stage_id for stage in ir.stages if isinstance(stage.reentry, str)}
    stage_go_to = {stage.stage_id: stage.go_to for stage in ir.stages if isinstance(stage.go_to, str)}
    stage_emitters = _stage_mode_emitters()

    call_lines: list[str] = []
    for stage_index, stage in enumerate(ir.stages):
        stage_mod_name = _stage_module_name(stage.stage_id)
        invocations = _collect_stage_invocations(stage)

        call_lines.append(
            f"        if (not loop_continue) and ({stage_index} >= cycle_start_index) and (PIPELINE_TYPE == 'looping' or _should_run_stage(manifest=manifest, stage_id={stage.stage_id!r}, stage_index={stage_index}, resume_index=resume_index)):"
        )
        stage_emitters[stage.mode](call_lines, stage, stage_mod_name, invocations)

    b = CodeBuilder()
    b.add(generated_banner(meta))
    b.line("from __future__ import annotations")
    b.line()
    b.line("import argparse")
    b.line("import json")
    b.line("import shutil")
    b.line("from datetime import datetime, timezone")
    b.line("from pathlib import Path")
    b.line()
    for sid in stage_ids:
        b.line(f"from seedpipe.generated.stages import {sid} as stage_{_stage_module_name(sid)}")
    b.line()
    b.line("from seedpipe.runtime.ctx import StageContext")
    b.line("from seedpipe.runtime.items import iter_items_deterministic")
    b.line("from seedpipe.runtime.state import append_item_state_row")
    b.line()
    b.line(f"PIPELINE_ID = {ir.pipeline_id!r}")
    b.line(f"ITEM_UNIT = {ir.item_unit!r}")
    b.line(f"DETERMINISM_POLICY = {ir.determinism_policy!r}")
    b.line(f"PIPELINE_TYPE = {ir.pipeline_type!r}")
    b.line(f"MAX_LOOPS = {ir.max_loops}")
    b.line(f"STAGES = {stage_ids!r}")
    b.line(f"REENTRY_TO_STAGE = {reentry_to_stage!r}")
    b.line(f"STAGE_GO_TO = {stage_go_to!r}")
    b.line()
    b.line("RUN_MANIFEST_FILE = '.seedpipe_run_manifest.json'")
    b.line("WAITING_HUMAN_EXIT_CODE = 20")
    b.line()
    b.add(textwrap.dedent(_FLOW_RUNTIME_HELPERS).lstrip("\n"))
    b.add(textwrap.dedent(_FLOW_RUN_PREFIX).lstrip("\n"))
    for line in call_lines:
        b.line(line)
    b.add(textwrap.dedent(_FLOW_RUN_SUFFIX).lstrip("\n"))
    return b.render()


def emit_run_manifest_template(ir: PipelineIR) -> str:
    stage_rows = [
        {
            "stage_id": stage.stage_id,
            "status": "pending",
            "attempt": 0,
            "updated_at": "1970-01-01T00:00:00+00:00",
        }
        for stage in ir.stages
    ]
    payload = {
        "manifest_version": "phase1-run-resume-v1",
        "pipeline_id": ir.pipeline_id,
        "run_id": "",
        "created_at": "1970-01-01T00:00:00+00:00",
        "updated_at": "1970-01-01T00:00:00+00:00",
        "failure_stage_id": None,
        "loop_iteration": 1,
        "artifact_index": {},
        "stages": stage_rows,
    }
    return stable_json(payload)


def emit_ir_json(ir: PipelineIR) -> str:
    return stable_json(dataclasses.asdict(ir))


def write_file(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"


@dataclasses.dataclass
class CompiledArtifactWriter:
    output_dir: Path
    emitted_hashes: dict[str, str] = dataclasses.field(default_factory=dict)

    def emit(self, path: Path, content: str) -> None:
        self.emitted_hashes[str(path.as_posix())] = write_file(path, content)

    def emit_core_files(self, ir: PipelineIR, contracts: dict[str, dict[str, Any]], meta: dict[str, str]) -> None:
        self.emit(self.output_dir / "models.py", emit_models_py(contracts, meta))
        self.emit(self.output_dir / "flow.py", emit_flow_py(ir, meta))
        self.emit(self.output_dir / "run_manifest_template.json", emit_run_manifest_template(ir))

    def emit_stage_files(self, ir: PipelineIR, meta: dict[str, str]) -> None:
        for stage in ir.stages:
            self.emit(self.output_dir / "stages" / f"{stage.stage_id}.py", emit_stage_wrapper(stage, meta))
        self.emit(self.output_dir / "stages" / "__init__.py", emit_stages_init_py(ir, meta))

    def emit_debug_ir(self, ir: PipelineIR) -> None:
        self.emit(self.output_dir / "ir.json", emit_ir_json(ir))

    def emit_reports(
        self,
        *,
        ir: PipelineIR,
        artifact_schema_map: dict[str, str],
        meta: dict[str, str],
    ) -> None:
        report = {
            "compiler_version": COMPILER_VERSION,
            "pipeline_id": ir.pipeline_id,
            "warnings": [],
            "artifact_schema_map": artifact_schema_map,
            "emitted_files": self.emitted_hashes,
        }
        self.emit(self.output_dir / "compile_report.json", stable_json(report))

        meta_doc = {
            "compiler_version": COMPILER_VERSION,
            "pipeline_hash": meta["pipeline_hash"],
            "contracts_hash": meta["contracts_hash"],
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "emitted_files": self.emitted_hashes,
        }
        self.emit(self.output_dir / "_meta.json", stable_json(meta_doc))


def compile_pipeline(paths: CompilePaths, *, emit_debug_ir: bool = True) -> dict[str, Any]:
    raw = load_pipeline(paths.pipeline_path)
    normalized = normalize_pipeline(raw)
    validate_pipeline_structure(normalized)
    ir = build_ir(normalized)

    contracts = load_contracts(paths)
    artifact_schema_map = resolve_artifact_schemas(ir, contracts)

    paths.output_dir.mkdir(parents=True, exist_ok=True)
    ensure_package_dir(paths.output_dir)
    ensure_package_dir(paths.output_dir / "stages")

    contract_paths = sorted(paths.contracts_dir.glob("*.schema.json"))
    meta = {
        "pipeline_hash": sha256_file(paths.pipeline_path),
        "contracts_hash": sha256_directory(contract_paths),
    }

    writer = CompiledArtifactWriter(output_dir=paths.output_dir)
    writer.emit_core_files(ir, contracts, meta)
    writer.emit_stage_files(ir, meta)
    if emit_debug_ir:
        writer.emit_debug_ir(ir)
    writer.emit_reports(ir=ir, artifact_schema_map=artifact_schema_map, meta=meta)

    return {
        "pipeline_id": ir.pipeline_id,
        "output_dir": str(paths.output_dir),
        "files": sorted(writer.emitted_hashes),
    }


def pick_contracts_dir(cli_dir: Path | None) -> Path:
    if cli_dir is not None:
        return cli_dir
    return DEFAULT_CONTRACTS_DIR


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compile Seedpipe Phase-1 pipeline into generated code")
    parser.add_argument("--pipeline", type=Path, default=DEFAULT_PIPELINE_PATH)
    parser.add_argument("--contracts-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--no-ir", action="store_true", help="Disable emitted generated/ir.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = CompilePaths(
        pipeline_path=args.pipeline,
        contracts_dir=pick_contracts_dir(args.contracts_dir),
        output_dir=args.output_dir,
    )
    result = compile_pipeline(paths, emit_debug_ir=not args.no_ir)
    print(stable_json(result), end="")


if __name__ == "__main__":
    main()
