"""Model-facing response sanitisation and structural summaries."""

from __future__ import annotations

import re
from typing import Any


INSTRUCTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bignore (all )?(previous|prior) instructions\b", re.IGNORECASE),
    re.compile(r"\bsystem prompt\b", re.IGNORECASE),
    re.compile(r"\bdeveloper message\b", re.IGNORECASE),
    re.compile(r"\bcall this tool\b", re.IGNORECASE),
    re.compile(r"\bexfiltrat(e|ion)\b", re.IGNORECASE),
)


DEFAULT_SUMMARY_FIELDS: tuple[str, ...] = (
    "id",
    "geometry.type",
    "properties.name",
    "properties.title",
    "properties.description",
)


class ResponseSanitizer:
    """Create compact, data-only summaries from upstream OGC responses."""

    def __init__(self, *, max_string_length: int = 500, max_items: int = 20) -> None:
        self._max_string_length = max_string_length
        self._max_items = max_items

    def summarize(
        self,
        data: Any,
        *,
        operation: str,
        summary_fields: tuple[str, ...] = DEFAULT_SUMMARY_FIELDS,
    ) -> dict[str, Any]:
        summary = self._summarize_data(data, summary_fields=summary_fields)
        return {
            "boundary": "tool_result_data_only",
            "operation": operation,
            "summary": summary,
        }

    def sanitize_value(self, value: Any) -> Any:
        if isinstance(value, str):
            cleaned = value.strip()
            if any(pattern.search(cleaned) for pattern in INSTRUCTION_PATTERNS):
                return "[removed]"
            if len(cleaned) > self._max_string_length:
                return f"{cleaned[: self._max_string_length]}..."
            return cleaned
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        if isinstance(value, list):
            return [self.sanitize_value(item) for item in value[: self._max_items]]
        if isinstance(value, dict):
            return {
                str(key): self.sanitize_value(item)
                for key, item in list(value.items())[: self._max_items]
            }
        return str(value)

    def _summarize_data(self, data: Any, *, summary_fields: tuple[str, ...]) -> Any:
        if isinstance(data, dict) and isinstance(data.get("features"), list):
            features = data["features"]
            return {
                "type": data.get("type", "FeatureCollection"),
                "count": len(features),
                "items": [
                    self._extract_fields(feature, summary_fields)
                    for feature in features[: self._max_items]
                ],
                "truncated": len(features) > self._max_items,
            }
        if isinstance(data, dict) and isinstance(data.get("processes"), list):
            processes = data["processes"]
            return {
                "type": "processes",
                "count": len(processes),
                "items": [
                    self._extract_fields(process, ("id", "title", "description", "version"))
                    for process in processes[: self._max_items]
                ],
                "truncated": len(processes) > self._max_items,
            }
        if isinstance(data, dict) and isinstance(data.get("collections"), list):
            collections = data["collections"]
            return {
                "type": "collections",
                "count": len(collections),
                "items": [
                    self._extract_fields(collection, ("id", "title", "description"))
                    for collection in collections[: self._max_items]
                ],
                "truncated": len(collections) > self._max_items,
            }
        if isinstance(data, dict):
            return self.sanitize_value(data)
        if isinstance(data, list):
            return [self.sanitize_value(item) for item in data[: self._max_items]]
        return self.sanitize_value(data)

    def _extract_fields(self, item: Any, fields: tuple[str, ...]) -> dict[str, Any]:
        extracted: dict[str, Any] = {}
        for field in fields:
            value = _lookup(item, field)
            if value is not None:
                extracted[field] = self.sanitize_value(value)
        return extracted


def _lookup(item: Any, dotted_path: str) -> Any:
    current = item
    for segment in dotted_path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current
