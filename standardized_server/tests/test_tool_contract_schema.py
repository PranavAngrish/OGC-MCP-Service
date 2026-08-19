"""Regression tests for the formal OGC API-to-MCP contract document."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


CONTRACT_PATH = Path(__file__).parents[1] / "spec" / "ogc-mcp-tool-contract.json"


def _contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


class ToolContractSchemaTests(unittest.TestCase):
    def test_contract_has_independent_features_and_records_modules(self) -> None:
        contract = _contract()
        modules = {module["id"]: module for module in contract["modules"]}
        tools_by_module: dict[str, set[str]] = {}
        for tool in contract["tools"]:
            tools_by_module.setdefault(tool["module"], set()).add(tool["name"])

        self.assertEqual(
            set(modules["features"]["tools"]),
            tools_by_module["features"],
        )
        self.assertEqual(
            set(modules["records"]["tools"]),
            tools_by_module["records"],
        )
        self.assertEqual(
            modules["features"]["mcp_namespace"],
            "ogc_features_",
        )
        self.assertEqual(
            modules["records"]["mcp_namespace"],
            "ogc_records_",
        )

    def test_every_catalogued_tool_has_a_formal_translation(self) -> None:
        contract = _contract()
        for tool in contract["tools"]:
            with self.subTest(tool=tool["name"]):
                self.assertIn("input_schema", tool)
                self.assertIn("mcp", tool)
                self.assertIn("upstream", tool)
                self.assertIn("result", tool)
                self.assertIn("side_effect", tool)
                self.assertTrue(tool["abstract_operation"])

    def test_embedded_draft_2020_12_schema_validates_contract_and_query_plan(self) -> None:
        try:
            from jsonschema import Draft202012Validator
        except ImportError:  # pragma: no cover - only relevant for minimal runtime installs
            self.skipTest("jsonschema is not installed; install it to validate the contract schema.")

        contract = _contract()
        root_schema = {
            "$schema": contract["$schema"],
            "$defs": contract["$defs"],
            "$ref": "#/$defs/ContractDocument",
        }
        Draft202012Validator.check_schema(root_schema)
        errors = list(Draft202012Validator(root_schema).iter_errors(contract))
        self.assertEqual(errors, [], [error.message for error in errors])

        query_schema = {
            "$schema": contract["$schema"],
            "$defs": contract["$defs"],
            "$ref": "#/$defs/FeatureQueryPlan",
        }
        Draft202012Validator(query_schema).validate(
            {
                "server_id": "features-server",
                "collection_id": "history",
                "filters": [{"property": "name", "operator": "eq", "value": "Example"}],
                "bbox": [4.0, 50.0, 6.0, 53.0],
                "page_size": 100,
                "max_pages": 10,
                "max_items": 1000,
            }
        )

        with self.assertRaises(Exception):
            Draft202012Validator(query_schema).validate(
                {
                    "collection_id": "history",
                    "filters": [{"property": "name", "operator": "unsupported", "value": "Example"}],
                }
            )
