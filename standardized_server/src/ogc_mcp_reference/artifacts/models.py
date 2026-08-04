"""Internal models and manifest helpers for process output artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SCHEMA_VERSION = "ogc-output-manifest/1"
_MISSING_ARTIFACT_DATA = object()


@dataclass
class OutputCandidate:
    """One process output extracted from an upstream response envelope."""

    id: str
    value: Any = None
    href: str = ""
    title: str = ""
    description: str = ""
    declared_media_type: str = ""
    encoding: str = ""
    units: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    redirect_count: int = 0


@dataclass
class ParsedArtifact:
    """Semantic result returned by a parser adapter."""

    semantic_type: str
    format: str
    canonical_media_type: str = ""
    canonical_data: Any = field(default=_MISSING_ARTIFACT_DATA, repr=False)
    feature_count: int | None = None
    geometry_types: list[str] = field(default_factory=list)
    bbox: list[float] = field(default_factory=list)
    crs_value: str = ""
    crs_status: str = "missing"
    axis_order: str = ""
    warnings: list[str] = field(default_factory=list)
    transformations: list[str] = field(default_factory=list)
    table_rows: int | None = None
    table_columns: list[str] = field(default_factory=list)
    preview: Any = field(default=_MISSING_ARTIFACT_DATA, repr=False)
    map_unavailable_reason: str = ""
    force_partial: bool = False
    partial_reason: str = ""
    clarification_issues: list[dict[str, Any]] = field(default_factory=list)
    clarification_blocking: bool = False
    clarification_scope: str = "interpretation"

    @property
    def has_canonical_data(self) -> bool:
        """Distinguish a real JSON null from an omitted canonical value."""
        return self.canonical_data is not _MISSING_ARTIFACT_DATA

    @property
    def has_preview(self) -> bool:
        """Distinguish a real JSON null preview from an omitted preview."""
        return self.preview is not _MISSING_ARTIFACT_DATA


def retrieval_state(
    *,
    state: str,
    source: str,
    declared_media_type: str = "",
    detected_media_type: str = "",
    size_bytes: int | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"state": state, "source": source}
    if declared_media_type:
        payload["declaredMediaType"] = str(declared_media_type)[:300]
    if detected_media_type:
        payload["detectedMediaType"] = str(detected_media_type)[:300]
    if size_bytes is not None:
        payload["bytes"] = size_bytes
    if error:
        payload["error"] = error
    return payload


def interpretation_state(
    *,
    state: str,
    semantic_type: str = "unknown",
    format_name: str = "",
    crs_value: str = "",
    crs_status: str = "missing",
    axis_order: str = "",
    bbox: list[float] | None = None,
    feature_count: int | None = None,
    geometry_types: list[str] | None = None,
    units: list[str] | None = None,
    warnings: list[str] | None = None,
    table_rows: int | None = None,
    table_columns: list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "state": state,
        "semanticType": semantic_type,
        "crs": {"status": crs_status},
    }
    if format_name:
        payload["format"] = str(format_name)[:300]
    if crs_value:
        payload["crs"]["value"] = str(crs_value)[:300]
    if axis_order:
        payload["crs"]["axisOrder"] = str(axis_order)[:100]
    if bbox:
        payload["bbox"] = bbox
    if feature_count is not None:
        payload["featureCount"] = feature_count
    if geometry_types:
        payload["geometryTypes"] = [
            str(value)[:100] for value in geometry_types
        ]
    if units:
        payload["units"] = [
            {"value": str(value)[:200], "status": "declared"}
            for value in units[:100]
        ]
    if warnings:
        payload["warnings"] = [
            str(warning)[:2000] for warning in warnings[:100]
        ]
    if table_rows is not None:
        payload["rowCount"] = table_rows
    if table_columns:
        payload["columns"] = [
            str(column)[:300] for column in table_columns[:200]
        ]
    return payload
