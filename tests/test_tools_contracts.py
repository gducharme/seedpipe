from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

<<<<<<< HEAD
from seedpipe.tools.contracts import (
    RecursiveSchemaValidator,
    TinySchemaValidator,
    load_schema_store,
    resolve_contract,
    validate_ticket_status_transition,
)


class TinySchemaValidatorTests(unittest.TestCase):
    def test_validates_required_and_additional_properties(self) -> None:
        schema = {
            "type": "object",
            "required": ["id"],
            "properties": {"id": {"type": "string"}},
            "additionalProperties": False,
        }
        validator = TinySchemaValidator({})
        issues = validator.validate({"extra": 1}, schema)
        messages = [i.message for i in issues]
        self.assertIn("required property missing", messages)
        self.assertIn("additional property not allowed", messages)

    def test_validates_refs_and_enum(self) -> None:
        schemas = {
            "seedpipe://test/inner": {
                "type": "object",
                "properties": {"kind": {"type": "string", "enum": ["a", "b"]}},
                "required": ["kind"],
            }
        }
        validator = TinySchemaValidator(schemas)
        issues = validator.validate({"kind": "c"}, {"$ref": "seedpipe://test/inner"})
        self.assertTrue(any(i.message == "value not in enum" for i in issues))


class ContractStoreTests(unittest.TestCase):
    def test_load_schema_store_and_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "artifact_ref.schema.json").write_text(
                json.dumps({"$id": "seedpipe://spec/phase1/contracts/artifact_ref.schema.json", "type": "object"})
            )
            (root / "artifact_contracts.yaml").write_text(
                """
items.jsonl:
  kind: jsonl
  row_schema: items_row.schema.json
manifest.json:
  kind: json
  schema: manifest.schema.json
""".strip()
            )
            schemas, mapping = load_schema_store(root)
            self.assertIn("seedpipe://spec/phase1/contracts/artifact_ref.schema.json", schemas)
            self.assertEqual(mapping["items.jsonl"]["kind"], "jsonl")

    def test_resolve_contract(self) -> None:
        mapping = {
            "items.jsonl": {"kind": "jsonl", "row_schema": "items_row.schema.json"},
            "manifest.json": {"kind": "json", "schema": "manifest.schema.json"},
        }
        self.assertEqual(resolve_contract("items.jsonl", mapping, ""), ("jsonl", "items_row.schema.json"))
        self.assertEqual(resolve_contract("manifest.json", mapping, ""), ("json", "manifest.schema.json"))
        self.assertEqual(
            resolve_contract("custom.json", {}, "seedpipe://spec/phase1/contracts/custom.schema.json"),
            ("json", "seedpipe://spec/phase1/contracts/custom.schema.json"),
        )
        self.assertIsNone(resolve_contract("unknown", {}, "v1"))


class TicketStatusTransitionTests(unittest.TestCase):
    def test_valid_transition_ready_to_in_progress(self) -> None:
        issues = validate_ticket_status_transition("ready", "in_progress")
        self.assertEqual(len(issues), 0)

    def test_valid_transition_implemented_to_approved(self) -> None:
        issues = validate_ticket_status_transition("implemented", "approved")
        self.assertEqual(len(issues), 0)

    def test_valid_transition_approved_to_closed(self) -> None:
        issues = validate_ticket_status_transition("approved", "closed")
        self.assertEqual(len(issues), 0)

    def test_valid_transition_closed_to_reopened(self) -> None:
        issues = validate_ticket_status_transition("closed", "reopened")
        self.assertEqual(len(issues), 0)

    def test_invalid_transition_ready_to_approved(self) -> None:
        issues = validate_ticket_status_transition("ready", "approved")
        self.assertTrue(len(issues) > 0)
        self.assertIn("invalid status transition", issues[0].message)

    def test_invalid_transition_closed_to_in_progress(self) -> None:
        issues = validate_ticket_status_transition("closed", "in_progress")
        self.assertTrue(len(issues) > 0)
        self.assertIn("invalid status transition", issues[0].message)

    def test_invalid_status_value(self) -> None:
        issues = validate_ticket_status_transition(None, "invalid_status")
        self.assertTrue(len(issues) > 0)
        self.assertIn("invalid status", issues[0].message)

    def test_no_previous_status_is_valid(self) -> None:
        issues = validate_ticket_status_transition(None, "ready")
        self.assertEqual(len(issues), 0)


class RecursiveSchemaValidatorTests(unittest.TestCase):
    def test_reports_missing_required_and_type_issues(self) -> None:
        validator = RecursiveSchemaValidator()
        schema = {
            "type": "object",
            "required": ["id", "count"],
            "properties": {
                "id": {"type": "string"},
                "count": {"type": "integer"},
            },
        }

        issues = validator.validate({"id": 123}, schema)

        self.assertTrue(any("root: missing required field 'count'" in issue for issue in issues))
        self.assertTrue(any("id: expected string, got int" in issue for issue in issues))

    def test_reports_enum_violation_in_nested_property(self) -> None:
        validator = RecursiveSchemaValidator()
        schema = {
            "type": "object",
            "properties": {
                "metric_name": {"type": "string", "enum": ["latency", "cost"]},
            },
        }

        issues = validator.validate({"metric_name": "quality"}, schema)

        self.assertTrue(any("metric_name: value 'quality' not in enum ['latency', 'cost']" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()
