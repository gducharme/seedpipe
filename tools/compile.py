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
DEFAULT_PIPELINE_PATH = Path("spec/phase1/pipeline.yaml")
DEFAULT_CONTRACTS_DIR = Path("spec/phase1/contracts")
ALT_CONTRACTS_DIR = Path("seedpipe/spec/phase1/contracts")
DEFAULT_OUTPUT_DIR = Path("generated")


class CompileError(ValueError):
    """Raised when compilation fails with user-facing diagnostics."""


@dataclasses.dataclass(frozen=True)
class StageIR:
    stage_id: str
    mode: Literal["whole_run", "per_item"]
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    bindings: tuple[tuple[str, str], ...]
    expected_outputs: tuple[dict[str, Any], ...]
    placeholder: bool


@dataclasses.dataclass(frozen=True)
class PipelineIR:
    pipeline_id: str
    item_unit: str
    determinism_policy: Literal["strict", "best_effort"]
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


def _safe_stage_suffix(value: Any) -> str:
    token = re.sub(r"[^a-zA-Z0-9_]", "_", str(value)).strip("_")
    if not token:
        token = "key"
    if token[0].isdigit():
        token = f"k_{token}"
    return token


def expand_pipeline_dsl(raw: dict[str, Any]) -> dict[str, Any]:
    expanded = dict(raw)
    source_stages = expanded.get("stages", [])
    if source_stages is None:
        source_stages = []
    if not isinstance(source_stages, list):
        raise CompileError("pipeline.stages must be an array")

    family_outputs: dict[str, dict[str, str]] = {}
    concrete_stages: list[dict[str, Any]] = []

    for idx, stage in enumerate(source_stages):
        if not isinstance(stage, dict):
            raise CompileError(f"pipeline.stages[{idx}] must be an object")

        stage_id = stage.get("id")
        if not isinstance(stage_id, str) or not stage_id.strip():
            raise CompileError(f"pipeline.stages[{idx}].id must be a non-empty string")

        stage_foreach = stage.get("foreach")
        stage_as = stage.get("as")

        stage_bindings: list[dict[str, Any]] = [{}]
        if stage_foreach is not None:
            if not isinstance(stage_foreach, str):
                raise CompileError(f"pipeline.stages[{idx}].foreach must be a string expression")
            values = _resolve_path_expr(raw, stage_foreach)
            if not isinstance(values, list):
                raise CompileError(f"pipeline.stages[{idx}].foreach must resolve to a list")
            if not isinstance(stage_as, str) or not stage_as:
                raise CompileError(f"pipeline.stages[{idx}].as must be a non-empty string when foreach is set")
            stage_bindings = [{stage_as: value} for value in values]

        for binding in stage_bindings:
            instance = dict(stage)
            instance["_bindings"] = {
                key: str(value)
                for key, value in binding.items()
            }
            if stage_foreach is not None:
                suffix = _safe_stage_suffix(binding[stage_as])
                instance["id"] = f"{stage_id}__{suffix}"
            instance.pop("foreach", None)
            instance.pop("as", None)

            inputs_raw = instance.get("inputs", [])
            outputs_raw = instance.get("outputs", [])
            if not isinstance(inputs_raw, list) or not isinstance(outputs_raw, list):
                raise CompileError(f"pipeline.stages[{idx}].inputs/outputs must be arrays")

            concrete_inputs: list[str] = []
            for input_idx, entry in enumerate(inputs_raw):
                if isinstance(entry, str):
                    concrete_inputs.append(_render_template(entry, binding))
                    continue
                if not isinstance(entry, dict):
                    raise CompileError(f"pipeline.stages[{idx}].inputs[{input_idx}] must be a string or object")
                family = entry.get("family")
                bind = entry.get("bind")
                if not isinstance(family, str) or not isinstance(bind, str):
                    raise CompileError(
                        f"pipeline.stages[{idx}].inputs[{input_idx}] family refs require string 'family' and 'bind'"
                    )
                if bind not in binding:
                    raise CompileError(
                        f"pipeline.stages[{idx}].inputs[{input_idx}] bind variable '{bind}' not in stage scope"
                    )
                key = str(binding[bind])
                family_map = family_outputs.get(family, {})
                if key not in family_map:
                    raise CompileError(
                        f"pipeline.stages[{idx}].inputs[{input_idx}] unresolved family reference: {family}[{key}]"
                    )
                concrete_inputs.append(family_map[key])

            concrete_outputs: list[str] = []
            expected_outputs: list[dict[str, Any]] = []
            for output_idx, entry in enumerate(outputs_raw):
                if isinstance(entry, str):
                    concrete_path = _render_template(entry, binding)
                    concrete_outputs.append(concrete_path)
                    expected_outputs.append(
                        {
                            "pattern": entry,
                            "path": concrete_path,
                            "bindings": dict(sorted((str(k), str(v)) for k, v in binding.items())),
                        }
                    )
                    continue
                if not isinstance(entry, dict):
                    raise CompileError(f"pipeline.stages[{idx}].outputs[{output_idx}] must be a string or object")

                family = entry.get("family")
                pattern = entry.get("pattern")
                if not isinstance(family, str) or not isinstance(pattern, str):
                    raise CompileError(
                        f"pipeline.stages[{idx}].outputs[{output_idx}] family outputs require string 'family' and 'pattern'"
                    )

                out_foreach = entry.get("foreach")
                out_as = entry.get("as")
                out_bind = entry.get("bind")

                output_bindings: list[dict[str, Any]] = [dict(binding)]
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
                    if not isinstance(out_as, str) or not out_as:
                        raise CompileError(
                            f"pipeline.stages[{idx}].outputs[{output_idx}].as must be a non-empty string"
                        )
                    output_bindings = [
                        {
                            **binding,
                            out_as: value,
                        }
                        for value in values
                    ]

                family_map = family_outputs.setdefault(family, {})
                for out_binding in output_bindings:
                    if isinstance(out_bind, str):
                        bind_var = out_bind
                    elif out_foreach is not None and isinstance(out_as, str):
                        bind_var = out_as
                    else:
                        raise CompileError(
                            f"pipeline.stages[{idx}].outputs[{output_idx}] requires 'bind' or foreach/as to select family key"
                        )
                    if bind_var not in out_binding:
                        raise CompileError(
                            f"pipeline.stages[{idx}].outputs[{output_idx}] bind variable '{bind_var}' not in stage scope"
                        )
                    key = str(out_binding[bind_var])
                    path = _render_template(pattern, out_binding)
                    if key in family_map and family_map[key] != path:
                        raise CompileError(
                            f"pipeline.stages[{idx}].outputs[{output_idx}] family '{family}' key '{key}' conflict"
                        )
                    family_map[key] = path
                    concrete_outputs.append(path)
                    expected_outputs.append(
                        {
                            "family": family,
                            "pattern": pattern,
                            "bind": bind_var,
                            "path": path,
                            "bindings": dict(sorted((str(k), str(v)) for k, v in out_binding.items())),
                        }
                    )

            instance["inputs"] = concrete_inputs
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

    if pipeline.get("determinism_policy") not in {"strict", "best_effort"}:
        raise CompileError("pipeline.determinism_policy must be 'strict' or 'best_effort'")

    stages = pipeline.get("stages", [])
    if not stages:
        raise CompileError("pipeline.stages must include at least one stage")

    seen_stage_ids: set[str] = set()
    produced_so_far: set[str] = set()
    for idx, stage in enumerate(stages):
        sid = stage.get("id")
        if not isinstance(sid, str) or not sid.strip():
            raise CompileError(f"pipeline.stages[{idx}].id must be a non-empty string")
        if sid in seen_stage_ids:
            raise CompileError(f"duplicate stage id: {sid}")
        seen_stage_ids.add(sid)

        mode = stage.get("mode")
        if mode not in {"whole_run", "per_item"}:
            raise CompileError(f"pipeline.stages[{idx}].mode must be 'whole_run' or 'per_item'")

        placeholder = stage.get("placeholder")
        if not isinstance(placeholder, bool):
            raise CompileError(f"pipeline.stages[{idx}].placeholder must be a boolean")

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

        produced_so_far.update(stage_outputs)


def build_ir(pipeline: dict[str, Any]) -> PipelineIR:
    stages: list[StageIR] = []
    artifact_producers: dict[str, str] = {}
    for stage in pipeline["stages"]:
        stage_ir = StageIR(
            stage_id=stage["id"],
            mode=stage["mode"],
            inputs=tuple(stage["inputs"]),
            outputs=tuple(stage["outputs"]),
            bindings=tuple(sorted((str(k), str(v)) for k, v in stage.get("_bindings", {}).items())),
            expected_outputs=tuple(stage.get("_expected_outputs", [])),
            placeholder=bool(stage.get("placeholder", False)),
        )
        stages.append(stage_ir)
        for artifact_name in stage_ir.outputs:
            artifact_producers[artifact_name] = stage_ir.stage_id

    return PipelineIR(
        pipeline_id=pipeline["pipeline_id"],
        item_unit=pipeline["item_unit"],
        determinism_policy=pipeline["determinism_policy"],
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
    }
    missing = required - set(contracts)
    if missing:
        missing_names = ", ".join(sorted(missing))
        raise CompileError(f"missing required contracts: {missing_names}")
    return contracts


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


def _stage_impl_stub(stage: StageIR) -> str:
    if stage.mode == "whole_run":
        return (
            "from __future__ import annotations\n\n"
            "\n"
            "def run_whole(ctx) -> None:\n"
            "    _ = ctx\n"
        )
    return (
        "from __future__ import annotations\n\n"
        "from typing import Any\n\n"
        "\n"
        "def run_item(ctx, item: dict[str, Any]) -> None:\n"
        "    _ = (ctx, item)\n"
    )


def ensure_src_stage_impls(project_dir: Path, ir: PipelineIR) -> None:
    src_dir = project_dir / "src"
    stages_dir = src_dir / "stages"
    ensure_package_dir(src_dir)
    ensure_package_dir(stages_dir)

    for stage in ir.stages:
        if stage.placeholder:
            continue
        stage_impl_path = stages_dir / f"{stage.stage_id}.py"
        if not stage_impl_path.exists():
            stage_impl_path.write_text(_stage_impl_stub(stage))


def generated_banner(meta: dict[str, str]) -> str:
    return (
        "# AUTO-GENERATED by seedpipe.tools.compile\n"
        "# DO NOT EDIT. Changes will be overwritten.\n"
        f"# Source: pipeline.yaml hash: {meta['pipeline_hash']}\n"
        f"# Contracts hash: {meta['contracts_hash']}\n\n"
    )


def emit_models_py(contracts: dict[str, dict[str, Any]], meta: dict[str, str]) -> str:
    contracts_json = stable_json(contracts)
    return (
        generated_banner(meta)
        + "from __future__ import annotations\n\n"
        + "from dataclasses import dataclass\n"
        + "import json\n"
        + "from pathlib import Path\n"
        + "from typing import Any\n\n"
        + "@dataclass\n"
        + "class ProducedBy:\n"
        + "    run_id: str\n"
        + "    stage_id: str\n"
        + "    attempt: int = 1\n\n"
        + "@dataclass\n"
        + "class ArtifactRef:\n"
        + "    name: str\n"
        + "    path: str\n"
        + "    hash: str\n"
        + "    schema_version: str\n"
        + "    produced_by: ProducedBy\n"
        + "    bytes: int | None = None\n\n"
        + "@dataclass\n"
        + "class ItemResult:\n"
        + "    item_id: str\n"
        + "    ok: bool\n"
        + "    error: dict[str, Any] | None = None\n\n"
        + f"CONTRACTS: dict[str, dict[str, Any]] = json.loads({contracts_json!r})\n"
        + "\n"
        + "def get_schema(name: str) -> dict[str, Any]:\n"
        + "    if name not in CONTRACTS:\n"
        + "        raise KeyError(f'unknown schema: {name}')\n"
        + "    return CONTRACTS[name]\n"
        + "\n"
        + "def load_json(path: str | Path) -> Any:\n"
        + "    return json.loads(Path(path).read_text())\n"
    )


def python_string_list(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(repr(v) for v in values) + "]"


def emit_stage_wrapper(stage: StageIR, meta: dict[str, str]) -> str:
    mode_fn = "run_whole" if stage.mode == "whole_run" else "run_item"
    wrapper_name = mode_fn
    mode_signature = "ctx: StageContext" if stage.mode == "whole_run" else "ctx: StageContext, item: dict[str, Any]"
    mode_call = "impl.run_whole(ctx)" if stage.mode == "whole_run" else "impl.run_item(ctx, item)"
    item_result_return = (
        "    item_id = item.get('item_id', '')\n"
        "    try:\n"
        f"        {mode_call}\n"
        "        ctx.validate_outputs(STAGE_ID, OUTPUTS)\n"
        "        return ItemResult(item_id=str(item_id), ok=True)\n"
        "    except Exception as exc:\n"
        "        return ItemResult(\n"
        "            item_id=str(item_id),\n"
        "            ok=False,\n"
        "            error={'code': 'stage_exception', 'message': str(exc)},\n"
        "        )\n"
    )
    whole_return = f"    {mode_call}\n" "    ctx.validate_outputs(STAGE_ID, OUTPUTS)\n"
    function_body = (
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
    return (
        generated_banner(meta)
        + "from __future__ import annotations\n\n"
        + "from typing import Any\n\n"
        + "from seedpipe.runtime.ctx import StageContext\n"
        + "from seedpipe.generated.models import ItemResult\n"
        + (
            f"from seedpipe.src.stages import {stage.stage_id} as impl\n\n"
            if not stage.placeholder
            else "\n"
        )
        + f"STAGE_ID = {stage.stage_id!r}\n"
        + f"MODE = {stage.mode!r}\n"
        + f"INPUTS = {python_string_list(stage.inputs)}\n"
        + f"OUTPUTS = {python_string_list(stage.outputs)}\n\n"
        + f"def {wrapper_name}({mode_signature})"
        + (" -> None:\n" if stage.mode == "whole_run" else " -> ItemResult:\n")
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
    imports = "\n".join(
        f"from seedpipe.generated.stages import {sid} as stage_{re.sub(r'[^a-zA-Z0-9_]', '_', sid)}"
        for sid in stage_ids
    )
    call_lines = []
    for stage in ir.stages:
        stage_mod_name = re.sub(r"[^a-zA-Z0-9_]", "_", stage.stage_id)
        invocations: list[tuple[dict[str, str], list[dict[str, Any]]]] = []
        seen_signatures: set[tuple[tuple[tuple[str, str], ...], tuple[str, ...]]] = set()
        for output in stage.expected_outputs:
            output_bindings = {
                str(key): str(value)
                for key, value in output.get("bindings", {}).items()
            }
            if output_bindings and not set(dict(stage.bindings)).issubset(output_bindings.items()):
                continue
            invocation_bindings = output_bindings or dict(stage.bindings)
            invocation_expected = [
                output_item
                for output_item in stage.expected_outputs
                if {
                    str(key): str(value)
                    for key, value in output_item.get("bindings", {}).items()
                } == invocation_bindings
            ]
            signature = (
                tuple(sorted(invocation_bindings.items())),
                tuple(str(item.get("path", "")) for item in invocation_expected),
            )
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            invocations.append((invocation_bindings, invocation_expected))

        if not invocations:
            invocations.append((dict(stage.bindings), list(stage.expected_outputs)))

        for invocation_bindings, invocation_expected in invocations:
            if stage.mode == "whole_run":
                call_lines.append(
                    f"    ctx = ctx_base.for_stage({stage.stage_id!r}, attempt=attempt, bindings={invocation_bindings!r}, expected_outputs={invocation_expected!r})"
                )
                call_lines.append(f"    stage_{stage_mod_name}.run_whole(ctx)")
                continue

            items_artifact = stage.inputs[0] if stage.inputs else "items.jsonl"
            call_lines.append(
                f"    ctx = ctx_base.for_stage({stage.stage_id!r}, attempt=attempt, bindings={invocation_bindings!r}, expected_outputs={invocation_expected!r})"
            )
            call_lines.append(
                f"    for item in iter_items_deterministic(ctx, items_artifact={items_artifact!r}, bindings=ctx.bindings):"
            )
            call_lines.append("        item_id = item['item_id']")
            call_lines.append("        append_item_state_row({")
            call_lines.append("            'run_id': run_id,")
            call_lines.append("            'item_id': item_id,")
            call_lines.append("            'state': 'in_progress',")
            call_lines.append(f"            'stage_id': {stage.stage_id!r},")
            call_lines.append("            'attempt': attempt,")
            call_lines.append("            'updated_at': now_rfc3339(),")
            call_lines.append("        })")
            call_lines.append(f"        res = stage_{stage_mod_name}.run_item(ctx, item)")
            call_lines.append("        if res.ok:")
            call_lines.append("            append_item_state_row({")
            call_lines.append("                'run_id': run_id,")
            call_lines.append("                'item_id': item_id,")
            call_lines.append("                'state': 'succeeded',")
            call_lines.append(f"                'stage_id': {stage.stage_id!r},")
            call_lines.append("                'attempt': attempt,")
            call_lines.append("                'updated_at': now_rfc3339(),")
            call_lines.append("            })")
            call_lines.append("        else:")
            call_lines.append("            append_item_state_row({")
            call_lines.append("                'run_id': run_id,")
            call_lines.append("                'item_id': item_id,")
            call_lines.append("                'state': 'failed',")
            call_lines.append(f"                'stage_id': {stage.stage_id!r},")
            call_lines.append("                'attempt': attempt,")
            call_lines.append("                'error': res.error,")
            call_lines.append("                'updated_at': now_rfc3339(),")
            call_lines.append("            })")

    return (
        generated_banner(meta)
        + "from __future__ import annotations\n\n"
        + "import argparse\n"
        + "from datetime import datetime, timezone\n\n"
        + imports
        + "\n\n"
        + "from seedpipe.runtime.ctx import StageContext\n"
        + "from seedpipe.runtime.items import iter_items_deterministic\n"
        + "from seedpipe.runtime.state import append_item_state_row\n\n"
        + f"PIPELINE_ID = {ir.pipeline_id!r}\n"
        + f"ITEM_UNIT = {ir.item_unit!r}\n"
        + f"DETERMINISM_POLICY = {ir.determinism_policy!r}\n"
        + f"STAGES = {stage_ids!r}\n\n"
        + "def now_rfc3339() -> str:\n"
        + "    return datetime.now(timezone.utc).isoformat()\n\n"
        + "def run(run_config: dict[str, object], attempt: int = 1) -> int:\n"
        + "    run_id = str(run_config['run_id'])\n"
        + "    ctx_base = StageContext.make_base(run_config=run_config)\n"
        + "\n".join(call_lines)
        + "\n    return 0\n\n"
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
    ensure_src_stage_impls(paths.pipeline_path.parent, ir)

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
    if DEFAULT_CONTRACTS_DIR.exists():
        return DEFAULT_CONTRACTS_DIR
    return ALT_CONTRACTS_DIR


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
