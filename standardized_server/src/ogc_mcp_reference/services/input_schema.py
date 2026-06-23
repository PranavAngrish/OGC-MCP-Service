"""Best-effort validation of execute_request inputs against a process description.

OGC API - Processes input schemas can express complex shapes: a oneOf union of
a literal value versus an external href reference, nested object schemas,
arrays of values via maxOccurs, format-qualified values, and so on. A full
JSON Schema validator would risk false positives that block legitimate calls
on auto-generated/complex schemas. This module instead stays conservative and
only flags two classes of problems it can detect with high confidence:

1. A required input (minOccurs >= 1, the OGC default when unspecified) is
   missing entirely from execute_request["inputs"].
2. A literal input value's JSON type obviously conflicts with the declared
   schema "type" (e.g. a string where the schema says "integer").

Reference-style inputs ({"href": ...}), inputs that allow multiple occurrences
(maxOccurs != 1), and inputs whose declared schema cannot be reduced to a
single simple type (oneOf/anyOf/allOf/$ref) are left unchecked on purpose:
skipping is always safer here than a false positive that blocks an otherwise
valid plan.
"""

from __future__ import annotations

from typing import Any, Callable


_JSON_SCHEMA_TYPE_CHECKS: dict[str, Callable[[Any], bool]] = {
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
    "object": lambda value: isinstance(value, dict),
    "array": lambda value: isinstance(value, list),
}


def _is_reference_form(value: Any) -> bool:
    """True for the OGC link/qualified-reference input shape: {"href": ...}."""
    return isinstance(value, dict) and "href" in value


def _simple_schema_type(schema: Any) -> str | None:
    """Return a plain JSON-Schema type string only when the schema is unambiguous."""
    if not isinstance(schema, dict):
        return None
    if any(key in schema for key in ("oneOf", "anyOf", "allOf", "$ref")):
        return None
    schema_type = schema.get("type")
    if isinstance(schema_type, str) and schema_type in _JSON_SCHEMA_TYPE_CHECKS:
        return schema_type
    return None


def _min_occurs(declared: dict[str, Any]) -> int:
    value = declared.get("minOccurs", 1)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 1


def _allows_multiple(declared: dict[str, Any]) -> bool:
    max_occurs = declared.get("maxOccurs", 1)
    if max_occurs == "unbounded":
        return True
    return isinstance(max_occurs, int) and not isinstance(max_occurs, bool) and max_occurs > 1


def validate_execute_inputs(
    process_description: dict[str, Any],
    execute_request: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return unresolved-input issues for an execute_request; empty when none are flagged.

    Args:
        process_description: The raw process description body (the "data"
            field of ogc_processes_describe's result), expected to contain an
            "inputs" object as advertised by OGC API - Processes Core.
        execute_request: The body the caller intends to send to
            POST .../execution.
    """
    declared_inputs = process_description.get("inputs")
    if not isinstance(declared_inputs, dict):
        # Server did not advertise a structured inputs schema; nothing to check.
        return []

    supplied_inputs = execute_request.get("inputs")
    if not isinstance(supplied_inputs, dict):
        supplied_inputs = {}

    issues: list[dict[str, Any]] = []
    for input_id, declared in declared_inputs.items():
        if not isinstance(declared, dict):
            continue

        if input_id not in supplied_inputs:
            if _min_occurs(declared) >= 1:
                issues.append(
                    {
                        "field": f"inputs.{input_id}",
                        "reason": "Required process input is missing from execute_request.",
                        "title": declared.get("title", input_id),
                    }
                )
            continue

        value = supplied_inputs[input_id]
        if _is_reference_form(value) or _allows_multiple(declared):
            continue  # deferred: reference resolution, or list-of-values shape

        expected_type = _simple_schema_type(declared.get("schema"))
        if expected_type is None:
            continue  # complex/union schema: skip rather than risk a false positive

        actual_value = value.get("value") if isinstance(value, dict) and "value" in value else value
        if not _JSON_SCHEMA_TYPE_CHECKS[expected_type](actual_value):
            issues.append(
                {
                    "field": f"inputs.{input_id}",
                    "reason": (
                        f"Process input '{input_id}' expects JSON type "
                        f"'{expected_type}' but a different type was supplied."
                    ),
                    "expected_type": expected_type,
                }
            )

    return issues
