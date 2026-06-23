from __future__ import annotations

import unittest

from ogc_mcp_reference.services.input_schema import validate_execute_inputs


DELAUNAY_DESCRIPTION = {
    "id": "Delaunay",
    "inputs": {
        "InputPoints": {
            "title": "Input points",
            "minOccurs": 1,
            "maxOccurs": 1,
            "schema": {
                "oneOf": [
                    {"type": "string", "contentMediaType": "text/xml"},
                    {"type": "object", "format": "geojson-feature-collection"},
                ]
            },
        },
        "Tolerance": {
            "title": "Tolerance",
            "minOccurs": 0,
            "maxOccurs": 1,
            "schema": {"type": "number"},
        },
    },
}


class ValidateExecuteInputsTests(unittest.TestCase):
    def test_missing_required_input_is_flagged(self) -> None:
        issues = validate_execute_inputs(DELAUNAY_DESCRIPTION, {"inputs": {}})
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["field"], "inputs.InputPoints")

    def test_optional_missing_input_is_not_flagged(self) -> None:
        issues = validate_execute_inputs(
            DELAUNAY_DESCRIPTION,
            {"inputs": {"InputPoints": {"href": "https://example.org/points"}}},
        )
        self.assertEqual(issues, [])

    def test_reference_form_input_skips_type_check(self) -> None:
        issues = validate_execute_inputs(
            DELAUNAY_DESCRIPTION,
            {
                "inputs": {
                    "InputPoints": {"href": "https://example.org/points", "type": "text/xml"},
                    "Tolerance": "not-a-number",
                }
            },
        )
        # Tolerance has a simple "number" schema and a literal string was
        # supplied: this should be the only flagged issue.
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["field"], "inputs.Tolerance")
        self.assertEqual(issues[0]["expected_type"], "number")

    def test_union_schema_is_not_type_checked(self) -> None:
        # InputPoints uses oneOf, so even a clearly-wrong literal type for it
        # is intentionally left unchecked to avoid false positives.
        issues = validate_execute_inputs(
            DELAUNAY_DESCRIPTION,
            {"inputs": {"InputPoints": 12345}},
        )
        self.assertEqual(issues, [])

    def test_valid_literal_input_passes(self) -> None:
        issues = validate_execute_inputs(
            DELAUNAY_DESCRIPTION,
            {
                "inputs": {
                    "InputPoints": {"href": "https://example.org/points"},
                    "Tolerance": 0.5,
                }
            },
        )
        self.assertEqual(issues, [])

    def test_qualified_value_form_is_unwrapped_before_type_check(self) -> None:
        issues = validate_execute_inputs(
            DELAUNAY_DESCRIPTION,
            {
                "inputs": {
                    "InputPoints": {"href": "https://example.org/points"},
                    "Tolerance": {"value": "oops", "mediaType": "text/plain"},
                }
            },
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["field"], "inputs.Tolerance")

    def test_multi_occurrence_input_skips_type_check(self) -> None:
        description = {
            "inputs": {
                "Layers": {
                    "minOccurs": 1,
                    "maxOccurs": "unbounded",
                    "schema": {"type": "string"},
                }
            }
        }
        issues = validate_execute_inputs(description, {"inputs": {"Layers": ["a", "b", "c"]}})
        self.assertEqual(issues, [])

    def test_no_declared_inputs_schema_skips_validation(self) -> None:
        issues = validate_execute_inputs({"id": "Unknown"}, {"inputs": {"anything": 1}})
        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
