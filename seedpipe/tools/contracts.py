from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from seedpipe.tools.types import ArtifactKind


@dataclass(frozen=True)
class ValidationIssue:
    pointer: str
    message: str


class TinySchemaValidator:
    """Small JSON-schema subset validator for Phase 1 contracts."""

    def __init__(self, schemas_by_id: dict[str, dict[str, Any]]):
        self._schemas_by_id = schemas_by_id

    def validate(self, value: Any, schema: dict[str, Any], pointer: str = "") -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if "$ref" in schema:
            ref = schema["$ref"]
            target = self._schemas_by_id.get(ref)
            if target is None:
                return [ValidationIssue(pointer=pointer or "/", message=f"unknown schema ref: {ref}")]
            return self.validate(value, target, pointer)

        expected_type = schema.get("type")
        if expected_type == "object":
            if not isinstance(value, dict):
                return [ValidationIssue(pointer=pointer or "/", message="expected object")]
            props = schema.get("properties", {})
            required = schema.get("required", [])
            for key in required:
                if key not in value:
                    issues.append(ValidationIssue(pointer=f"{pointer}/{key}" or "/", message="required property missing"))
            additional = schema.get("additionalProperties", True)
            if additional is False:
                for key in value:
                    if key not in props:
                        issues.append(ValidationIssue(pointer=f"{pointer}/{key}" or "/", message="additional property not allowed"))
            for key, sub in props.items():
                if key in value:
                    issues.extend(self.validate(value[key], sub, f"{pointer}/{key}"))
        elif expected_type == "array":
            if not isinstance(value, list):
                return [ValidationIssue(pointer=pointer or "/", message="expected array")]
            min_items = schema.get("minItems")
            if isinstance(min_items, int) and len(value) < min_items:
                issues.append(ValidationIssue(pointer=pointer or "/", message=f"expected at least {min_items} items"))
            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                for idx, item in enumerate(value):
                    issues.extend(self.validate(item, item_schema, f"{pointer}/{idx}"))
        elif expected_type == "string":
            if not isinstance(value, str):
                return [ValidationIssue(pointer=pointer or "/", message="expected string")]
            min_len = schema.get("minLength")
            if isinstance(min_len, int) and len(value) < min_len:
                issues.append(ValidationIssue(pointer=pointer or "/", message=f"minLength {min_len} violated"))
            max_len = schema.get("maxLength")
            if isinstance(max_len, int) and len(value) > max_len:
                issues.append(ValidationIssue(pointer=pointer or "/", message=f"maxLength {max_len} violated"))
            pattern = schema.get("pattern")
            if isinstance(pattern, str) and re.match(pattern, value) is None:
                issues.append(ValidationIssue(pointer=pointer or "/", message=f"pattern mismatch: {pattern}"))
            if schema.get("format") == "date-time":
                try:
                    dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    issues.append(ValidationIssue(pointer=pointer or "/", message="invalid RFC3339 timestamp"))
        elif expected_type == "boolean":
            if not isinstance(value, bool):
                return [ValidationIssue(pointer=pointer or "/", message="expected boolean")]

        elif expected_type == "integer":
            if not isinstance(value, int):
                return [ValidationIssue(pointer=pointer or "/", message="expected integer")]
            minimum = schema.get("minimum")
            if isinstance(minimum, int) and value < minimum:
                issues.append(ValidationIssue(pointer=pointer or "/", message=f"minimum {minimum} violated"))

        if "enum" in schema and value not in schema["enum"]:
            issues.append(ValidationIssue(pointer=pointer or "/", message="value not in enum"))
        if "const" in schema and value != schema["const"]:
            issues.append(ValidationIssue(pointer=pointer or "/", message="value does not match const"))
        return issues


class RecursiveSchemaValidator:
    """Generic recursive schema checker for simple JSON-schema-like dicts."""

    def validate(self, data: Any, schema: dict[str, Any], path: list[str] | None = None) -> list[str]:
        active_path = path or []
        issues: list[str] = []
        path_str = ".".join(active_path) if active_path else "root"

        if "type" in schema:
            expected_type = schema["type"]
            if expected_type == "string" and not isinstance(data, str):
                issues.append(f"{path_str}: expected string, got {type(data).__name__}")
            elif expected_type == "number" and not isinstance(data, (int, float)):
                issues.append(f"{path_str}: expected number, got {type(data).__name__}")
            elif expected_type == "integer" and not isinstance(data, int):
                issues.append(f"{path_str}: expected integer, got {type(data).__name__}")
            elif expected_type == "boolean" and not isinstance(data, bool):
                issues.append(f"{path_str}: expected boolean, got {type(data).__name__}")
            elif expected_type == "array" and not isinstance(data, list):
                issues.append(f"{path_str}: expected array, got {type(data).__name__}")
            elif expected_type == "object" and not isinstance(data, dict):
                issues.append(f"{path_str}: expected object, got {type(data).__name__}")

        if "enum" in schema and data not in schema["enum"]:
            issues.append(f"{path_str}: value {data!r} not in enum {schema['enum']}")

        if isinstance(data, dict) and "properties" in schema:
            for prop_name, prop_schema in schema["properties"].items():
                if prop_name in data:
                    issues.extend(self.validate(data[prop_name], prop_schema, active_path + [prop_name]))

        if isinstance(data, dict) and "required" in schema:
            for req_field in schema["required"]:
                if req_field not in data:
                    issues.append(f"{path_str}: missing required field '{req_field}'")

        return issues


def _parse_simple_yaml(path: Path) -> dict[str, dict[str, str]]:
    mapping: dict[str, dict[str, str]] = {}
    current: str | None = None
    for raw in path.read_text().splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" ") and line.endswith(":"):
            current = line[:-1]
            mapping[current] = {}
            continue
        if current is None:
            continue
        stripped = line.strip()
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        mapping[current][key.strip()] = value.strip()
    return mapping


def load_schema_store(contracts_dir: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, str]]]:
    schemas: dict[str, dict[str, Any]] = {}
    for schema_file in sorted(contracts_dir.glob("*.schema.json")):
        schema = json.loads(schema_file.read_text())
        sid = schema.get("$id")
        if isinstance(sid, str):
            schemas[sid] = schema
    mapping_file = contracts_dir / "artifact_contracts.yaml"
    mapping = _parse_simple_yaml(mapping_file) if mapping_file.exists() else {}
    return schemas, mapping


def resolve_contract(artifact_name: str, mapping: dict[str, dict[str, str]], schema_version: str) -> tuple[ArtifactKind, str] | None:
    if artifact_name in mapping:
        cfg = mapping[artifact_name]
        kind = cfg.get("kind", "")
        if kind == "json":
            return ("json", cfg.get("schema", ""))
        if kind == "jsonl":
            return ("jsonl", cfg.get("row_schema", ""))
    if schema_version.startswith("seedpipe://"):
        return ("json", schema_version)
    return None


CANONICAL_TICKET_STATUSES = ["ready", "in_progress", "implemented", "qa_failed", "approved", "rejected", "closed", "reopened"]

VALID_TICKET_STATUS_TRANSITIONS: dict[str, list[str]] = {
    "ready": ["in_progress"],
    "in_progress": ["implemented", "rejected"],
    "implemented": ["qa_failed", "approved"],
    "qa_failed": ["in_progress", "rejected"],
    "approved": ["closed", "reopened"],
    "rejected": ["in_progress", "closed"],
    "closed": ["reopened"],
    "reopened": ["in_progress", "closed"],
}


def validate_ticket_status_transition(
    previous_status: str | None,
    new_status: str,
) -> list[ValidationIssue]:
    """Validate a ticket status transition is allowed."""
    issues: list[ValidationIssue] = []

    if new_status not in CANONICAL_TICKET_STATUSES:
        issues.append(ValidationIssue(pointer="/status", message=f"invalid status: {new_status}"))
        return issues

    if previous_status is not None:
        if previous_status not in CANONICAL_TICKET_STATUSES:
            issues.append(ValidationIssue(pointer="/previous_status", message=f"invalid previous_status: {previous_status}"))
            return issues

        valid_next = VALID_TICKET_STATUS_TRANSITIONS.get(previous_status, [])
        if new_status not in valid_next:
            issues.append(
                ValidationIssue(
                    pointer="/status",
                    message=f"invalid status transition from '{previous_status}' to '{new_status}'. Allowed: {valid_next}",
                )
            )

    return issues


def validate_ticket_row(row: dict[str, Any]) -> list[ValidationIssue]:
    """Validate a ticket row against the canonical ticket contract."""
    validator = TinySchemaValidator({})
    schema_path = Path(__file__).parent.parent.parent / "docs" / "specs" / "phase1" / "contracts" / "ticket_row.schema.json"
    if not schema_path.exists():
        return [ValidationIssue(pointer="/", message="ticket_row.schema.json not found")]

    schema = json.loads(schema_path.read_text())
    issues = validator.validate(row, schema)

    if "previous_status" in row and "status" in row:
        transition_issues = validate_ticket_status_transition(row.get("previous_status"), row.get("status", ""))
        issues.extend(transition_issues)

    return issues
