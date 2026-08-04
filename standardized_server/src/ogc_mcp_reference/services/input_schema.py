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

import re
from typing import Any, Callable


_JSON_SCHEMA_TYPE_CHECKS: dict[str, Callable[[Any], bool]] = {
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
    "object": lambda value: isinstance(value, dict),
    "array": lambda value: isinstance(value, list),
}

_UNIT_KEYS = {
    "unit",
    "units",
    "uom",
    "unitofmeasure",
    "unitofmeasurement",
    "x-ogc-unit",
}
_KNOWN_UNIT = re.compile(
    r"\b(?:"
    r"millimet(?:er|re)s?|centimet(?:er|re)s?|met(?:er|re)s?|"
    r"kilomet(?:er|re)s?|km|cm|mm|"
    r"feet|foot|ft|yards?|miles?|nautical\s+miles?|"
    r"degrees?|radians?|pixels?|"
    r"milliseconds?|seconds?|minutes?|hours?|days?|"
    r"hectares?|acres?|square\s+\w+|cubic\s+\w+"
    r")\b",
    re.IGNORECASE,
)
_UNIT_BEARING_QUANTITY = re.compile(
    r"(?:distance|radius|buffer|length|width|height|area|resolution|"
    r"cell\s*size|pixel\s*size|tolerance|elevation|altitude|depth|"
    r"duration|interval)",
    re.IGNORECASE,
)
_ASSUMED_ORIGINS = {"assumed", "inferred", "default"}


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


def _actual_value(value: Any) -> Any:
    return value.get("value") if isinstance(value, dict) and "value" in value else value


def _context_for(
    input_context: dict[str, Any],
    input_id: str,
) -> dict[str, Any]:
    candidate = input_context.get(input_id, input_context.get(f"inputs.{input_id}", {}))
    return candidate if isinstance(candidate, dict) else {}


def _explicit_value_unit(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    for key, candidate in value.items():
        normalized = str(key).replace("_", "").replace("-", "").casefold()
        if normalized in {item.replace("-", "") for item in _UNIT_KEYS}:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
            if isinstance(candidate, dict):
                label = candidate.get("symbol") or candidate.get("name") or candidate.get("id")
                if isinstance(label, str) and label.strip():
                    return label.strip()
    return ""


def _declared_unit(value: Any, *, depth: int = 0) -> str:
    """Return a conservatively advertised unit from one process input description."""
    if depth > 5:
        return ""
    if isinstance(value, dict):
        for key, candidate in value.items():
            normalized = str(key).replace("_", "").replace("-", "").casefold()
            if normalized in {item.replace("-", "") for item in _UNIT_KEYS}:
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
                if isinstance(candidate, dict):
                    label = candidate.get("symbol") or candidate.get("name") or candidate.get("id")
                    if isinstance(label, str) and label.strip():
                        return label.strip()
        for key in ("title", "description"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                match = _KNOWN_UNIT.search(candidate)
                if match:
                    return match.group(0)
        for candidate in value.values():
            found = _declared_unit(candidate, depth=depth + 1)
            if found:
                return found
    elif isinstance(value, list):
        for candidate in value[:100]:
            found = _declared_unit(candidate, depth=depth + 1)
            if found:
                return found
    return ""


def _requires_unit(input_id: str, declared: dict[str, Any], value: Any) -> bool:
    schema_type = _simple_schema_type(declared.get("schema"))
    actual = _actual_value(value)
    if schema_type not in {"number", "integer"}:
        return False
    if not isinstance(actual, (int, float)) or isinstance(actual, bool):
        return False
    description = " ".join(
        str(item)
        for item in (
            input_id,
            declared.get("title", ""),
            declared.get("description", ""),
        )
    )
    return bool(_UNIT_BEARING_QUANTITY.search(description))


def _unit_issue(
    input_id: str,
    declared: dict[str, Any],
    observed_value: Any,
) -> dict[str, Any]:
    field = f"inputs.{input_id}"
    title = str(declared.get("title") or input_id)
    return {
        "id": f"unit-{input_id}",
        "field": field,
        "kind": "unit",
        "title": title,
        "reason": (
            "This numeric spatial parameter needs a unit, but the process "
            "description does not advertise one and no user-confirmed unit "
            "context was supplied."
        ),
        "question": (
            f"What unit should be associated with '{title}'? If the service's "
            "native unit is genuinely unknown, do you explicitly accept that "
            "uncertainty for this execution?"
        ),
        "why_it_matters": (
            "The same numeric value can represent very different real-world "
            "distances or areas in metres, kilometres, degrees, pixels, or an "
            "undocumented server-native unit."
        ),
        "observed_value": observed_value,
        "options": [
            {
                "value": "server-native-unspecified",
                "label": "Accept the server's unspecified native unit",
                "consequence": (
                    "The exact real-world magnitude may remain unknown and will "
                    "be reported as an explicit caveat."
                ),
            }
        ],
        "allow_free_text": True,
        "resolution": (
            "Call ogc_proxy_update_plan with input_context_json containing this "
            "input ID, origin='user', the stated unit (or "
            "'server-native-unspecified'), and confirmed=true."
        ),
    }


def _assumption_issue(
    input_id: str,
    declared: dict[str, Any],
    observed_value: Any,
    context: dict[str, Any],
) -> dict[str, Any]:
    title = str(declared.get("title") or input_id)
    origin = str(context.get("origin") or "assumed")
    return {
        "id": f"assumption-{input_id}",
        "field": f"inputs.{input_id}",
        "kind": "input",
        "title": title,
        "reason": (
            f"The value was marked as {origin} and has not been explicitly "
            "confirmed by the user."
        ),
        "question": f"Should '{title}' use the proposed value shown below?",
        "why_it_matters": (
            "Executing an inferred or defaulted value without acknowledgement "
            "would bypass the human-in-the-loop assumption check."
        ),
        "observed_value": observed_value,
        "allow_free_text": True,
        "resolution": (
            "After the user confirms or replaces the value, call "
            "ogc_proxy_update_plan with the corrected execute_request and "
            "input_context_json marking this input confirmed=true."
        ),
    }


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
    input_context: dict[str, Any] | None = None,
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
    context_by_input = input_context if isinstance(input_context, dict) else {}

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
        context = _context_for(context_by_input, str(input_id))
        actual_value = _actual_value(value)
        origin = str(context.get("origin") or "").casefold()
        if origin in _ASSUMED_ORIGINS and context.get("confirmed") is not True:
            issues.append(
                _assumption_issue(str(input_id), declared, actual_value, context)
            )

        if _is_reference_form(value) or _allows_multiple(declared):
            continue  # deferred: reference resolution, or list-of-values shape

        expected_type = _simple_schema_type(declared.get("schema"))
        if expected_type is not None and not _JSON_SCHEMA_TYPE_CHECKS[expected_type](actual_value):
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
            continue

        if (
            _requires_unit(str(input_id), declared, value)
            and not _declared_unit(declared)
            and not _explicit_value_unit(value)
        ):
            contextual_unit = context.get("unit")
            context_confirms_unit = (
                isinstance(contextual_unit, str)
                and bool(contextual_unit.strip())
                and context.get("confirmed") is True
            )
            if not context_confirms_unit:
                issues.append(
                    _unit_issue(str(input_id), declared, actual_value)
                )

    return issues
