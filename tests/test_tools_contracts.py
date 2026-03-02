from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from seedpipe.tools.contracts import TinySchemaValidator, load_schema_store, resolve_contract


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


if __name__ == "__main__":
    unittest.main()
