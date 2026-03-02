#!/usr/bin/env python3
"""Compile pipeline.yaml + contracts into generated orchestration code."""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Literal



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

        stage_key_scopes: list[dict[str, Any]] = [{}]
        if stage_foreach is not None:
            if not isinstance(stage_foreach, str):
                raise CompileError(f"pipeline.stages[{idx}].foreach must be a string expression")
            values = _resolve_path_expr(raw, stage_foreach)
            if not isinstance(values, list):
                raise CompileError(f"pipeline.stages[{idx}].foreach must resolve to a list")
            if not isinstance(stage_key, str) or not stage_key:
                raise CompileError(f"pipeline.stages[{idx}].key must be a non-empty string when foreach is set")
            stage_key_scopes = [{stage_key: value} for value in values]

        instance = dict(stage)
        instance["_keys"] = {}
        instance.pop("foreach", None)
        instance.pop("key", None)

        inputs_raw = instance.get("inputs", [])
        outputs_raw = instance.get("outputs", [])
        if not isinstance(inputs_raw, list) or not isinstance(outputs_raw, list):
            raise CompileError(f"pipeline.stages[{idx}].inputs/outputs must be arrays")

        concrete_inputs: list[str] = []
        for key_scope in stage_key_scopes:
            for input_idx, entry in enumerate(inputs_raw):
                if isinstance(entry, str):
                    concrete_inputs.append(_render_template(entry, key_scope))
                    continue
                if not isinstance(entry, dict):
                    raise CompileError(f"pipeline.stages[{idx}].inputs[{input_idx}] must be a string or object")
                family = entry.get("family")
                pattern = entry.get("pattern")
                schema = entry.get("schema")
                if not isinstance(family, str) or not isinstance(pattern, str) or not isinstance(schema, str):
                    raise CompileError(
                        f"pipeline.stages[{idx}] (id='{stage_id}').inputs[{input_idx}] object entries require string 'family', 'pattern', and 'schema'"
                    )
                _ = family, schema
                concrete_inputs.append(_render_template(pattern, key_scope))

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
                    raise CompileError(f"pipeline.stages[{idx}].outputs[{output_idx}] must be a string or object")

                family = entry.get("family")
                pattern = entry.get("pattern")
                schema = entry.get("schema")
                if not isinstance(family, str) or not isinstance(pattern, str):
                    raise CompileError(
                        f"pipeline.stages[{idx}].outputs[{output_idx}] object entries require string 'family' and 'pattern'"
                    )
                if schema is not None and not isinstance(schema, str):
                    raise CompileError(
                        f"pipeline.stages[{idx}].outputs[{output_idx}].schema must be a string when provided"
                    )

                out_foreach = entry.get("foreach")
                out_key = entry.get("key")

                output_key_scopes: list[dict[str, Any]] = [dict(key_scope)]
                if out_foreach is not None:
                    if not isinstance(out_foreach, str):
                        raise CompileError(
                            f"pipeline.stages[{idx}].outputs[{output_idx}].foreach must be a string expression"
                        )
                    values = _resolve_path_expr(raw, out_foreach)
                    if not isinstance(values, list):
                        raise CompileError(
                            f"pipeline.stages[{idx}].outputs[{output_idx}].foreach must resolve to a list"
                        )
                    if not isinstance(out_key, str) or not out_key:
                        raise CompileError(
                            f"pipeline.stages[{idx}].outputs[{output_idx}].key must be a non-empty string"
                        )
                    output_key_scopes = [
                        {
                            **key_scope,
                            out_key: value,
                        }
                        for value in values
                    ]
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

        instance["inputs"] = list(dict.fromkeys(concrete_inputs))
        instance["outputs"] = list(dict.fromkeys(concrete_outputs))
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


def validate_pipeline_structure(pipeline: dict[str, Any]) -> None:
    pipeline_id = pipeline.get("pipeline_id")
    if not isinstance(pipeline_id, str) or not pipeline_id.strip():
        raise CompileError("pipeline.pipeline_id must be a non-empty string")
    pid = pipeline_id

    if pipeline.get("determinism_policy") not in {"strict", "best_effort"}:
        raise CompileError(f"pipeline '{pid}' determinism_policy must be 'strict' or 'best_effort'")
    pipeline_type = pipeline.get("pipeline_type")
    if pipeline_type not in {"straight", "looping"}:
        raise CompileError(f"pipeline '{pid}' pipeline_type must be 'straight' or 'looping'")
    max_loops = pipeline.get("max_loops", 0)
    if not isinstance(max_loops, int) or max_loops < 0:
        raise CompileError(f"pipeline '{pid}' max_loops must be an integer >= 0")

    stages = pipeline.get("stages", [])
    if not stages:
        raise CompileError("pipeline.stages must include at least one stage")

    seen_stage_ids: set[str] = set()
    produced_so_far: set[str] = set()
    reentry_stage_by_name: dict[str, int] = {}
    pending_go_tos: list[tuple[int, str]] = []
    for idx, stage in enumerate(stages):
        sid = stage.get("id")
        if not isinstance(sid, str) or not sid.strip():
            raise CompileError(f"pipeline.stages[{idx}].id must be a non-empty string")
        if sid in seen_stage_ids:
            raise CompileError(f"duplicate stage id: {sid}")
        seen_stage_ids.add(sid)

        mode = stage.get("mode")
        if mode not in {"whole_run", "per_item", "human_required"}:
            raise CompileError(f"pipeline.stages[{idx}].mode must be 'whole_run', 'per_item', or 'human_required'")

        instructions = stage.get("instructions")
        if mode == "human_required":
            if not isinstance(instructions, dict):
                raise CompileError(f"pipeline.stages[{idx}].instructions must be an object when mode='human_required'")
            summary = instructions.get("summary")
            steps = instructions.get("steps")
            done_when = instructions.get("done_when")
            if not isinstance(summary, str) or not summary.strip():
                raise CompileError(
                    f"pipeline.stages[{idx}].instructions.summary must be a non-empty string when mode='human_required'"
                )
            if not isinstance(steps, list) or not steps or any(not isinstance(step, str) or not step.strip() for step in steps):
                raise CompileError(
                    f"pipeline.stages[{idx}].instructions.steps must be a non-empty array of strings when mode='human_required'"
                )
            if not isinstance(done_when, list) or not done_when or any(
                not isinstance(item, str) or not item.strip() for item in done_when
            ):
                raise CompileError(
                    f"pipeline.stages[{idx}].instructions.done_when must be a non-empty array of strings when mode='human_required'"
                )
            troubleshooting = instructions.get("troubleshooting")
            if troubleshooting is not None and (
                not isinstance(troubleshooting, list)
                or any(not isinstance(item, str) or not item.strip() for item in troubleshooting)
            ):
                raise CompileError(
                    f"pipeline.stages[{idx}].instructions.troubleshooting must be an array of strings when provided"
                )
            validation_command = instructions.get("validation_command")
            if validation_command is not None and (
                not isinstance(validation_command, str) or not validation_command.strip()
            ):
                raise CompileError(
                    f"pipeline.stages[{idx}].instructions.validation_command must be a non-empty string when provided"
                )
        elif instructions is not None:
            raise CompileError(
                f"pipeline.stages[{idx}].instructions is only allowed when mode='human_required'"
            )

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

        unresolved = [artifact for artifact in stage_inputs if artifact not in produced_so_far]
        if unresolved and not placeholder:
            unresolved_joined = ", ".join(unresolved)
            raise CompileError(
                f"pipeline.stages[{idx}] has forward/unresolved inputs: {unresolved_joined}; "
                "inputs must be produced by earlier stages"
            )

        if isinstance(reentry, str):
            if reentry in reentry_stage_by_name:
                prior_idx = reentry_stage_by_name[reentry]
                prior_stage_id = stages[prior_idx].get("id", "<unknown>")
                raise CompileError(
                    f"pipeline '{pid}' stage[{idx}] (id='{sid}') reentry '{reentry}' duplicates stage[{prior_idx}] (id='{prior_stage_id}')"
                )
            reentry_stage_by_name[reentry] = idx
        if isinstance(go_to, str):
            pending_go_tos.append((idx, go_to))

        produced_so_far.update(stage_outputs)

    pipeline_type = pipeline["pipeline_type"]
    if pipeline_type == "straight":
        if reentry_stage_by_name or pending_go_tos:
            raise CompileError(
                f"pipeline '{pid}' with type 'straight' does not allow 'reentry' or 'go_to' stage fields"
            )
        if max_loops != 0:
            raise CompileError(f"pipeline '{pid}' with type 'straight' requires max_loops=0")
        return

    if max_loops < 1:
        raise CompileError(f"pipeline '{pid}' with type 'looping' requires max_loops >= 1")
    if not reentry_stage_by_name:
        raise CompileError("pipeline_type 'looping' requires at least one stage with 'reentry'")

    for idx, target in pending_go_tos:
        stage_id = stages[idx].get("id", "<unknown>")
        target_stage_idx = reentry_stage_by_name.get(target)
        if target_stage_idx is None:
            raise CompileError(
                f"pipeline '{pid}' stage[{idx}] (id='{stage_id}') go_to='{target}' references unknown reentry"
            )
        target_stage_id = stages[target_stage_idx].get("id", "<unknown>")
        if target_stage_idx >= idx:
            raise CompileError(
                f"pipeline '{pid}' stage[{idx}] (id='{stage_id}') go_to='{target}' points to stage[{target_stage_idx}] "
                f"(id='{target_stage_id}') which is not earlier"
            )


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


def resolve_artifact_schemas(ir: PipelineIR, contracts: dict[str, dict[str, Any]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for artifact in sorted(ir.artifact_producers):
        if artifact.endswith("items.jsonl") or artifact == "items.jsonl":
            mapping[artifact] = "items_row.schema.json"
        elif artifact.endswith("item_state.jsonl") or artifact == "item_state.jsonl":
            mapping[artifact] = "item_state_row.schema.json"
        elif artifact.endswith("manifest.json") or artifact == "manifest.json":
            mapping[artifact] = "manifest.schema.json"
        else:
            mapping[artifact] = "artifact_ref.schema.json"

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
    return (
        generated_banner(meta)
        + "from __future__ import annotations\n\n"
        + "from typing import Any\n\n"
        + "from seedpipe.runtime.ctx import StageContext\n"
        + "from seedpipe.generated.models import ItemResult\n"
        + (
            f"from seedpipe.src.stages import {stage.stage_id} as impl\n\n"
            if (not stage.placeholder and stage.mode != "human_required")
            else "\n"
        )
        + f"STAGE_ID = {stage.stage_id!r}\n"
        + f"MODE = {stage.mode!r}\n"
        + f"INPUTS = {python_string_list(stage.inputs)}\n"
        + f"OUTPUTS = {python_string_list(stage.outputs)}\n\n"
        + f"def {wrapper_name}({mode_signature})"
        + (" -> None:\n" if stage.mode in {"whole_run", "human_required"} else " -> ItemResult:\n")
        + function_body
    )


def emit_stages_init_py(ir: PipelineIR, meta: dict[str, str]) -> str:
    lines = [generated_banner(meta), "from __future__ import annotations\n\n"]
    for stage in ir.stages:
        lines.append(f"from . import {stage.stage_id}\n")
    lines.append("\n")
    all_exports = ", ".join(repr(stage.stage_id) for stage in ir.stages)
    lines.append(f"__all__ = [{all_exports}]\n")
    return "".join(lines)


def emit_flow_py(ir: PipelineIR, meta: dict[str, str]) -> str:
    stage_ids = [stage.stage_id for stage in ir.stages]
    reentry_to_stage = {stage.reentry: stage.stage_id for stage in ir.stages if isinstance(stage.reentry, str)}
    stage_go_to = {stage.stage_id: stage.go_to for stage in ir.stages if isinstance(stage.go_to, str)}
    imports = "\n".join(
        f"from seedpipe.generated.stages import {sid} as stage_{re.sub(r'[^a-zA-Z0-9_]', '_', sid)}"
        for sid in stage_ids
    )

    call_lines: list[str] = []
    for stage_index, stage in enumerate(ir.stages):
        stage_mod_name = re.sub(r"[^a-zA-Z0-9_]", "_", stage.stage_id)
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

        call_lines.append(
            f"        if (not loop_continue) and ({stage_index} >= cycle_start_index) and (PIPELINE_TYPE == 'looping' or _should_run_stage(manifest=manifest, stage_id={stage.stage_id!r}, stage_index={stage_index}, resume_index=resume_index)):"
        )
        if stage.mode == "human_required":
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
            continue
        call_lines.append(f"            _mark_stage(manifest, stage_id={stage.stage_id!r}, status='running', attempt=attempt)")
        call_lines.append("            try:")
        if stage.mode == "per_item":
            call_lines.append("                stage_failed_item_ids: list[str] = []")
        for invocation_keys, invocation_expected in invocations:
            if stage.mode == "whole_run":
                call_lines.append(
                    f"                ctx = ctx_base.for_stage({stage.stage_id!r}, attempt=attempt, keys={invocation_keys!r}, expected_outputs={invocation_expected!r})"
                )
                call_lines.append(f"                stage_{stage_mod_name}.run_whole(ctx)")
                continue

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

        if stage.mode == "per_item":
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

    return (
        generated_banner(meta)
        + "from __future__ import annotations\n\n"
        + "import argparse\n"
        + "import json\n"
        + "import shutil\n"
        + "from datetime import datetime, timezone\n"
        + "from pathlib import Path\n\n"
        + imports
        + "\n\n"
        + "from seedpipe.runtime.ctx import StageContext\n"
        + "from seedpipe.runtime.items import iter_items_deterministic\n"
        + "from seedpipe.runtime.state import append_item_state_row\n\n"
        + f"PIPELINE_ID = {ir.pipeline_id!r}\n"
        + f"ITEM_UNIT = {ir.item_unit!r}\n"
        + f"DETERMINISM_POLICY = {ir.determinism_policy!r}\n"
        + f"PIPELINE_TYPE = {ir.pipeline_type!r}\n"
        + f"MAX_LOOPS = {ir.max_loops}\n"
        + f"STAGES = {stage_ids!r}\n"
        + f"REENTRY_TO_STAGE = {reentry_to_stage!r}\n"
        + f"STAGE_GO_TO = {stage_go_to!r}\n\n"
        + "RUN_MANIFEST_FILE = '.seedpipe_run_manifest.json'\n"
        + "WAITING_HUMAN_EXIT_CODE = 20\n\n"
        + "def now_rfc3339() -> str:\n"
        + "    return datetime.now(timezone.utc).isoformat()\n\n"
        + "def _read_manifest(run_id: str) -> dict[str, object]:\n"
        + "    path = Path(RUN_MANIFEST_FILE)\n"
        + "    if not path.exists():\n"
        + "        stages = [\n"
        + "            {\n"
        + "                'stage_id': stage_id,\n"
        + "                'status': 'pending',\n"
        + "                'attempt': 0,\n"
        + "                'updated_at': now_rfc3339(),\n"
        + "            }\n"
        + "            for stage_id in STAGES\n"
        + "        ]\n"
        + "        payload = {\n"
        + "            'manifest_version': 'phase1-run-resume-v1',\n"
        + "            'pipeline_id': PIPELINE_ID,\n"
        + "            'run_id': run_id,\n"
        + "            'created_at': now_rfc3339(),\n"
        + "            'updated_at': now_rfc3339(),\n"
        + "            'failure_stage_id': None,\n"
        + "            'loop_iteration': 1,\n"
        + "            'artifact_index': {},\n"
        + "            'active_item_ids': [],\n"
        + "            'item_attempts': {},\n"
        + "            'stages': stages,\n"
        + "        }\n"
        + "        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\\n')\n"
        + "        return payload\n"
        + "    payload = json.loads(path.read_text())\n"
        + "    if not isinstance(payload, dict):\n"
        + "        raise ValueError('run manifest must be a JSON object')\n"
        + "    return payload\n\n"
        + "def _write_manifest(manifest: dict[str, object]) -> None:\n"
        + "    manifest['updated_at'] = now_rfc3339()\n"
        + "    Path(RUN_MANIFEST_FILE).write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\\n')\n\n"
        + "def _task_paths(run_id: str, stage_id: str) -> tuple[Path, Path, Path]:\n"
        + "    run_root = Path('runs') / run_id\n"
        + "    tasks_dir = run_root / 'tasks'\n"
        + "    json_path = tasks_dir / f'{stage_id}.task.json'\n"
        + "    md_path = tasks_dir / f'{stage_id}.md'\n"
        + "    marker_path = run_root / f'WAITING_HUMAN.{stage_id}'\n"
        + "    return json_path, md_path, marker_path\n\n"
        + "def _render_task_packet_markdown(packet: dict[str, object]) -> str:\n"
        + "    lines: list[str] = []\n"
        + "    lines.append(f\"# Task: {packet.get('stage_id', '')}\")\n"
        + "    lines.append('')\n"
        + "    lines.append('## Purpose')\n"
        + "    lines.append(str(packet.get('purpose', '')))\n"
        + "    lines.append('')\n"
        + "    lines.append('## Required Inputs')\n"
        + "    for item in packet.get('required_inputs', []):\n"
        + "        lines.append(f\"- {item}\")\n"
        + "    lines.append('')\n"
        + "    lines.append('## Exact Commands')\n"
        + "    for item in packet.get('exact_commands', []):\n"
        + "        lines.append(f\"- {item}\")\n"
        + "    lines.append('')\n"
        + "    lines.append('## Expected Outputs')\n"
        + "    for item in packet.get('expected_outputs', []):\n"
        + "        lines.append(f\"- {item}\")\n"
        + "    validation_command = packet.get('validation_command')\n"
        + "    if isinstance(validation_command, str) and validation_command:\n"
        + "        lines.append('')\n"
        + "        lines.append('## Validation Command')\n"
        + "        lines.append(f\"`{validation_command}`\")\n"
        + "    lines.append('')\n"
        + "    lines.append('## Done When')\n"
        + "    for item in packet.get('done_when', []):\n"
        + "        lines.append(f\"- {item}\")\n"
        + "    hints = packet.get('troubleshooting', [])\n"
        + "    if isinstance(hints, list) and hints:\n"
        + "        lines.append('')\n"
        + "        lines.append('## Troubleshooting')\n"
        + "        for item in hints:\n"
        + "            lines.append(f\"- {item}\")\n"
        + "    return '\\n'.join(lines) + '\\n'\n\n"
        + "def _mark_waiting_human(manifest: dict[str, object], stage_id: str, attempt: int, waiting_payload: dict[str, object]) -> None:\n"
        + "    for row in _stage_rows(manifest):\n"
        + "        if str(row.get('stage_id', '')) != stage_id:\n"
        + "            continue\n"
        + "        row['status'] = 'waiting_human'\n"
        + "        row['attempt'] = attempt\n"
        + "        row['updated_at'] = now_rfc3339()\n"
        + "        row['waiting_human'] = waiting_payload\n"
        + "        manifest['failure_stage_id'] = None\n"
        + "        _write_manifest(manifest)\n"
        + "        return\n"
        + "    raise ValueError(f'run manifest missing stage row for {stage_id}')\n\n"
        + "def _human_stage_waiting(\n"
        + "    manifest: dict[str, object],\n"
        + "    run_id: str,\n"
        + "    pipe_root: str,\n"
        + "    stage_id: str,\n"
        + "    instructions: dict[str, object],\n"
        + "    required_inputs: list[str],\n"
        + "    expected_outputs: list[dict[str, object]],\n"
        + "    attempt: int,\n"
        + ") -> bool:\n"
        + "    json_path, md_path, marker_path = _task_paths(run_id=run_id, stage_id=stage_id)\n"
        + "    json_path.parent.mkdir(parents=True, exist_ok=True)\n"
        + "    required_inputs = [str(Path(path).as_posix()) for path in required_inputs]\n"
        + "    expected_paths = [str(Path(item.get('path', '')).as_posix()) for item in expected_outputs if isinstance(item, dict) and item.get('path')]\n"
        + "    raw_steps = instructions.get('steps', [])\n"
        + "    raw_done_when = instructions.get('done_when', [])\n"
        + "    troubleshooting = instructions.get('troubleshooting', [])\n"
        + "    scope = {'run_id': run_id, 'stage_id': stage_id}\n"
        + "    def _fmt(text: str) -> str:\n"
        + "        rendered = text\n"
        + "        for key, value in scope.items():\n"
        + "            rendered = rendered.replace('{' + key + '}', str(value))\n"
        + "        return rendered\n"
        + "    packet = {\n"
        + "        'task_id': f'{run_id}:{stage_id}',\n"
        + "        'run_id': run_id,\n"
        + "        'stage_id': stage_id,\n"
        + "        'purpose': _fmt(str(instructions.get('summary', ''))),\n"
        + "        'required_inputs': required_inputs,\n"
        + "        'exact_commands': [_fmt(str(item)) for item in raw_steps if isinstance(item, str)],\n"
        + "        'expected_outputs': expected_paths,\n"
        + "        'validation_command': _fmt(str(instructions.get('validation_command', ''))) if instructions.get('validation_command') else None,\n"
        + "        'done_when': [_fmt(str(item)) for item in raw_done_when if isinstance(item, str)],\n"
        + "        'troubleshooting': [_fmt(str(item)) for item in troubleshooting if isinstance(item, str)],\n"
        + "        'generated_at': now_rfc3339(),\n"
        + "    }\n"
        + "    json_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + '\\n')\n"
        + "    md_path.write_text(_render_task_packet_markdown(packet))\n"
        + "    output_missing = [path for path in expected_paths if not Path(path).exists()]\n"
        + "    validation_error: str | None = None\n"
        + "    if not output_missing:\n"
        + "        try:\n"
        + "            cfg = {'run_id': run_id}\n"
        + "            if pipe_root:\n"
        + "                cfg['_pipe_root'] = pipe_root\n"
        + "            ctx = StageContext.make_base(run_config=cfg).for_stage(stage_id, expected_outputs=expected_outputs)\n"
        + "            outputs_to_validate = [str(item.get('path', '')) for item in expected_outputs if item.get('path')]\n"
        + "            ctx.validate_outputs(stage_id, outputs_to_validate)\n"
        + "            ctx.validate_expected_outputs(stage_id)\n"
        + "        except Exception as exc:\n"
        + "            validation_error = str(exc)\n"
        + "    waiting_payload = {\n"
        + "        'task_id': str(packet['task_id']),\n"
        + "        'task_packet_json': json_path.as_posix(),\n"
        + "        'task_packet_md': md_path.as_posix(),\n"
        + "        'marker_path': marker_path.as_posix(),\n"
        + "        'expected_outputs': expected_paths,\n"
        + "        'validation_status': {\n"
        + "            'missing_outputs': output_missing,\n"
        + "            'error': validation_error,\n"
        + "            'ok': (not output_missing) and (validation_error is None),\n"
        + "        },\n"
        + "        'blocked_at': now_rfc3339(),\n"
        + "    }\n"
        + "    if output_missing or validation_error:\n"
        + "        marker_path.parent.mkdir(parents=True, exist_ok=True)\n"
        + "        marker_path.write_text('waiting_human\\n')\n"
        + "        _mark_waiting_human(manifest=manifest, stage_id=stage_id, attempt=attempt, waiting_payload=waiting_payload)\n"
        + "        return True\n"
        + "    if marker_path.exists():\n"
        + "        marker_path.unlink()\n"
        + "    return False\n\n"
        + "def _stage_rows(manifest: dict[str, object]) -> list[dict[str, object]]:\n"
        + "    rows = manifest.get('stages', [])\n"
        + "    if not isinstance(rows, list):\n"
        + "        raise ValueError('run manifest field stages must be an array')\n"
        + "    typed_rows = [row for row in rows if isinstance(row, dict)]\n"
        + "    if len(typed_rows) != len(rows):\n"
        + "        raise ValueError('run manifest stages entries must be objects')\n"
        + "    return typed_rows\n\n"
        + "def _artifact_index(manifest: dict[str, object]) -> dict[str, str]:\n"
        + "    raw = manifest.get('artifact_index', {})\n"
        + "    if not isinstance(raw, dict):\n"
        + "        raise ValueError('run manifest field artifact_index must be an object')\n"
        + "    out: dict[str, str] = {}\n"
        + "    for key, value in raw.items():\n"
        + "        if not isinstance(key, str) or not isinstance(value, str):\n"
        + "            raise ValueError('run manifest artifact_index entries must be string:string')\n"
        + "        out[key] = value\n"
        + "    return out\n\n"
        + "def _active_item_ids(manifest: dict[str, object]) -> list[str]:\n"
        + "    raw = manifest.get('active_item_ids', [])\n"
        + "    if not isinstance(raw, list):\n"
        + "        return []\n"
        + "    return [str(item_id) for item_id in raw]\n\n"
        + "def _item_attempts(manifest: dict[str, object]) -> dict[str, dict[str, int]]:\n"
        + "    raw = manifest.get('item_attempts', {})\n"
        + "    if not isinstance(raw, dict):\n"
        + "        raw = {}\n"
        + "    out: dict[str, dict[str, int]] = {}\n"
        + "    for stage_id, by_item in raw.items():\n"
        + "        if not isinstance(stage_id, str) or not isinstance(by_item, dict):\n"
        + "            continue\n"
        + "        out[stage_id] = {}\n"
        + "        for item_id, value in by_item.items():\n"
        + "            if not isinstance(item_id, str):\n"
        + "                continue\n"
        + "            try:\n"
        + "                out[stage_id][item_id] = int(value)\n"
        + "            except Exception:\n"
        + "                out[stage_id][item_id] = 0\n"
        + "    return out\n\n"
        + "def _next_item_attempt(manifest: dict[str, object], stage_id: str, item_id: str) -> int:\n"
        + "    attempts = _item_attempts(manifest)\n"
        + "    stage_attempts = attempts.setdefault(stage_id, {})\n"
        + "    current = int(stage_attempts.get(item_id, 0))\n"
        + "    stage_attempts[item_id] = current + 1\n"
        + "    manifest['item_attempts'] = attempts\n"
        + "    return current + 1\n\n"
        + "def _stage_index(stage_id: str) -> int:\n"
        + "    try:\n"
        + "        return STAGES.index(stage_id)\n"
        + "    except ValueError as exc:\n"
        + "        raise ValueError(f'unknown stage id in run manifest: {stage_id}') from exc\n\n"
        + "def _first_incomplete_stage(manifest: dict[str, object]) -> str | None:\n"
        + "    for row in _stage_rows(manifest):\n"
        + "        stage_id = str(row.get('stage_id', ''))\n"
        + "        status = str(row.get('status', 'pending'))\n"
        + "        if status != 'completed':\n"
        + "            return stage_id\n"
        + "    return None\n\n"
        + "def _mark_stage(manifest: dict[str, object], stage_id: str, status: str, attempt: int, error: object | None = None) -> None:\n"
        + "    for row in _stage_rows(manifest):\n"
        + "        if str(row.get('stage_id', '')) != stage_id:\n"
        + "            continue\n"
        + "        row['status'] = status\n"
        + "        row['attempt'] = attempt\n"
        + "        row['updated_at'] = now_rfc3339()\n"
        + "        if error is not None:\n"
        + "            row['error'] = error\n"
        + "        elif 'error' in row:\n"
        + "            del row['error']\n"
        + "        manifest['failure_stage_id'] = stage_id if status == 'failed' else None\n"
        + "        _write_manifest(manifest)\n"
        + "        return\n"
        + "    raise ValueError(f'run manifest missing stage row for {stage_id}')\n\n"
        + "def _register_stage_outputs(manifest: dict[str, object], stage_id: str, loop_iteration: int, outputs: list[str]) -> None:\n"
        + "    if loop_iteration < 1:\n"
        + "        raise ValueError('loop iteration must be >= 1')\n"
        + "    index = _artifact_index(manifest)\n"
        + "    for output_name in outputs:\n"
        + "        rel_path = Path(output_name)\n"
        + "        if rel_path.is_absolute():\n"
        + "            raise ValueError(\n"
        + "                f\"pipeline '{PIPELINE_ID}' stage '{stage_id}' loop snapshot path '{output_name}' must be relative to run dir\"\n"
        + "            )\n"
        + "        if any(part == '..' for part in rel_path.parts):\n"
        + "            raise ValueError(\n"
        + "                f\"pipeline '{PIPELINE_ID}' stage '{stage_id}' loop snapshot path '{output_name}' must not escape run dir\"\n"
        + "            )\n"
        + "        src = rel_path\n"
        + "        if not src.exists():\n"
        + "            raise FileNotFoundError(\n"
        + "                f\"pipeline '{PIPELINE_ID}' stage '{stage_id}' missing output '{output_name}' needed for snapshot\"\n"
        + "            )\n"
        + "        dst = Path(stage_id) / 'loops' / f'{loop_iteration:04d}' / rel_path\n"
        + "        dst.parent.mkdir(parents=True, exist_ok=True)\n"
        + "        shutil.copy2(src, dst)\n"
        + "        index[output_name] = dst.as_posix()\n"
        + "    manifest['artifact_index'] = index\n"
        + "    manifest['loop_iteration'] = loop_iteration\n"
        + "    _write_manifest(manifest)\n\n"
        + "def _ensure_manifest_stages(manifest: dict[str, object]) -> None:\n"
        + "    manifest_stage_ids = [str(row.get('stage_id', '')) for row in _stage_rows(manifest)]\n"
        + "    if manifest_stage_ids != STAGES:\n"
        + "        raise ValueError('run manifest stage order does not match compiled flow')\n\n"
        + "def _resolve_resume_index(run_config: dict[str, object], manifest: dict[str, object]) -> int:\n"
        + "    resume_stage = run_config.get('_resume_stage_id')\n"
        + "    if isinstance(resume_stage, str) and resume_stage:\n"
        + "        return _stage_index(resume_stage)\n"
        + "    failure_stage = manifest.get('failure_stage_id')\n"
        + "    if isinstance(failure_stage, str) and failure_stage:\n"
        + "        return _stage_index(failure_stage)\n"
        + "    first_incomplete = _first_incomplete_stage(manifest)\n"
        + "    if first_incomplete is None:\n"
        + "        return len(STAGES)\n"
        + "    return _stage_index(first_incomplete)\n\n"
        + "def _should_run_stage(manifest: dict[str, object], stage_id: str, stage_index: int, resume_index: int) -> bool:\n"
        + "    if stage_index < resume_index:\n"
        + "        return False\n"
        + "    for row in _stage_rows(manifest):\n"
        + "        if str(row.get('stage_id', '')) != stage_id:\n"
        + "            continue\n"
        + "        return str(row.get('status', 'pending')) != 'completed'\n"
        + "    return True\n\n"
        + "def _resolve_loop_target(stage_id: str) -> str | None:\n"
        + "    go_to = STAGE_GO_TO.get(stage_id)\n"
        + "    if not isinstance(go_to, str) or not go_to:\n"
        + "        return None\n"
        + "    target = REENTRY_TO_STAGE.get(go_to)\n"
        + "    return target if isinstance(target, str) and target else None\n\n"
        + "def _iter_stage_items(ctx: StageContext, items_artifact: str, keys: dict[str, str] | None, active_item_ids: set[str] | None):\n"
        + "    for item in iter_items_deterministic(ctx, items_artifact=items_artifact, keys=keys):\n"
        + "        item_id = str(item.get('item_id', ''))\n"
        + "        if active_item_ids is not None and item_id not in active_item_ids:\n"
        + "            continue\n"
        + "        yield item\n\n"
        + "def run(run_config: dict[str, object], attempt: int = 1) -> int:\n"
        + "    run_id = str(run_config['run_id'])\n"
        + "    run_config.setdefault('_pipe_root', str(Path(__file__).resolve().parents[1]))\n"
        + "    manifest = _read_manifest(run_id)\n"
        + "    _ensure_manifest_stages(manifest)\n"
        + "    loop_iteration_raw = run_config.get('_loop_iteration', manifest.get('loop_iteration', 1))\n"
        + "    loop_iteration = int(loop_iteration_raw) if isinstance(loop_iteration_raw, int) or str(loop_iteration_raw).isdigit() else 1\n"
        + "    if loop_iteration < 1:\n"
        + "        loop_iteration = 1\n"
        + "    active_from_manifest = _active_item_ids(manifest)\n"
        + "    active_from_config = run_config.get('_active_item_ids')\n"
        + "    if isinstance(active_from_config, list):\n"
        + "        active_item_ids = {str(item_id) for item_id in active_from_config}\n"
        + "    elif active_from_manifest:\n"
        + "        active_item_ids = {str(item_id) for item_id in active_from_manifest}\n"
        + "    else:\n"
        + "        active_item_ids = None\n"
        + "    run_config['_loop_iteration'] = loop_iteration\n"
        + "    run_config['_artifact_index'] = _artifact_index(manifest)\n"
        + "    resume_index = _resolve_resume_index(run_config=run_config, manifest=manifest)\n"
        + "    if resume_index >= len(STAGES):\n"
        + "        return 0\n"
        + "    cycle_start_index = resume_index\n"
        + "    while True:\n"
        + "        loop_continue = False\n"
        + "        next_cycle_start_index = cycle_start_index\n"
        + "        next_active_item_ids: list[str] = []\n"
        + "        loop_origin_stage: str | None = None\n"
        + "        run_config['_loop_iteration'] = loop_iteration\n"
        + "        run_config['_active_item_ids'] = sorted(active_item_ids) if active_item_ids is not None else []\n"
        + "        run_config['_artifact_index'] = _artifact_index(manifest)\n"
        + "        ctx_base = StageContext.make_base(run_config=run_config)\n"
        + "\n".join(call_lines)
        + "\n        if loop_continue:\n"
        + "            if PIPELINE_TYPE != 'looping':\n"
        + "                raise RuntimeError(f'loop jump requested in straight pipeline {PIPELINE_ID}')\n"
        + "            if MAX_LOOPS <= 0:\n"
        + "                raise RuntimeError(f'loop jump requested but max_loops is 0 for pipeline {PIPELINE_ID}')\n"
        + "            if loop_iteration >= MAX_LOOPS:\n"
        + "                raise RuntimeError(\n"
        + "                    f'pipeline {PIPELINE_ID} stage {loop_origin_stage or \"<unknown>\"} exceeded max_loops={MAX_LOOPS}'\n"
        + "                )\n"
        + "            loop_iteration += 1\n"
        + "            cycle_start_index = next_cycle_start_index\n"
        + "            active_item_ids = set(next_active_item_ids)\n"
        + "            manifest['active_item_ids'] = sorted(active_item_ids)\n"
        + "            manifest['loop_iteration'] = loop_iteration\n"
        + "            _write_manifest(manifest)\n"
        + "            continue\n"
        + "        manifest['active_item_ids'] = []\n"
        + "        manifest['loop_iteration'] = loop_iteration\n"
        + "        _write_manifest(manifest)\n"
        + "        return 0\n\n"
        + "def main() -> None:\n"
        + "    parser = argparse.ArgumentParser(description='Run generated Seedpipe flow')\n"
        + "    parser.add_argument('--run-id', required=True)\n"
        + "    parser.add_argument('--attempt', type=int, default=1)\n"
        + "    args = parser.parse_args()\n"
        + "    code = run(run_config={'run_id': args.run_id}, attempt=args.attempt)\n"
        + "    raise SystemExit(code)\n\n"
        + "if __name__ == '__main__':\n"
        + "    main()\n"
    )


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

    emitted_hashes: dict[str, str] = {}
    emitted_hashes[str((paths.output_dir / "models.py").as_posix())] = write_file(
        paths.output_dir / "models.py", emit_models_py(contracts, meta)
    )
    emitted_hashes[str((paths.output_dir / "flow.py").as_posix())] = write_file(
        paths.output_dir / "flow.py", emit_flow_py(ir, meta)
    )
    emitted_hashes[str((paths.output_dir / "run_manifest_template.json").as_posix())] = write_file(
        paths.output_dir / "run_manifest_template.json", emit_run_manifest_template(ir)
    )

    for stage in ir.stages:
        path = paths.output_dir / "stages" / f"{stage.stage_id}.py"
        emitted_hashes[str(path.as_posix())] = write_file(path, emit_stage_wrapper(stage, meta))

    stages_init_path = paths.output_dir / "stages" / "__init__.py"
    emitted_hashes[str(stages_init_path.as_posix())] = write_file(stages_init_path, emit_stages_init_py(ir, meta))

    if emit_debug_ir:
        ir_path = paths.output_dir / "ir.json"
        emitted_hashes[str(ir_path.as_posix())] = write_file(ir_path, emit_ir_json(ir))

    report = {
        "compiler_version": COMPILER_VERSION,
        "pipeline_id": ir.pipeline_id,
        "warnings": [],
        "artifact_schema_map": artifact_schema_map,
        "emitted_files": emitted_hashes,
    }
    report_path = paths.output_dir / "compile_report.json"
    emitted_hashes[str(report_path.as_posix())] = write_file(report_path, stable_json(report))

    meta_doc = {
        "compiler_version": COMPILER_VERSION,
        "pipeline_hash": meta["pipeline_hash"],
        "contracts_hash": meta["contracts_hash"],
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "emitted_files": emitted_hashes,
    }
    meta_path = paths.output_dir / "_meta.json"
    emitted_hashes[str(meta_path.as_posix())] = write_file(meta_path, stable_json(meta_doc))

    return {
        "pipeline_id": ir.pipeline_id,
        "output_dir": str(paths.output_dir),
        "files": sorted(emitted_hashes),
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
