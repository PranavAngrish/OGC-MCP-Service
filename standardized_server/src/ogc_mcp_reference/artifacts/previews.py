"""Bounded, renderer-safe previews for canonical output artifacts."""

from __future__ import annotations

import json
from typing import Any


MAX_PREVIEW_BYTES = 100_000
MAX_TABLE_PREVIEW_ROWS = 100
MAX_GEOJSON_PREVIEW_FEATURES = 500


def serialized_size(value: Any) -> int:
    """Return the compact UTF-8 JSON size used by :class:`ArtifactStore`."""
    return len(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def _bounded_text_wrapper(encoded: str, max_bytes: int) -> dict[str, Any]:
    """Return a bounded diagnostic preview without cutting a JSON structure."""
    sample_length = min(len(encoded), 20_000)
    while sample_length:
        preview = {"preview": encoded[:sample_length], "truncated": True}
        if serialized_size(preview) <= max_bytes:
            return preview
        sample_length //= 2
    return {"preview": "", "truncated": True}


def bounded_json_preview(
    value: Any,
    *,
    max_bytes: int = MAX_PREVIEW_BYTES,
    max_items: int = MAX_TABLE_PREVIEW_ROWS,
) -> Any:
    """Bound arbitrary JSON while retaining complete list items when possible.

    Table rows are never sliced into invalid fragments. Oversized rows are
    omitted and later rows may still be included when they fit the remaining
    budget. Non-list documents fall back to a bounded textual diagnostic.
    """
    if max_bytes <= 0:
        return None
    try:
        if serialized_size(value) <= max_bytes and (
            not isinstance(value, list) or len(value) <= max_items
        ):
            return value
    except (TypeError, ValueError):
        return None

    if isinstance(value, list):
        preview: list[Any] = []
        for item in value[: max(max_items * 4, max_items)]:
            if len(preview) >= max_items:
                break
            candidate = [*preview, item]
            try:
                if serialized_size(candidate) <= max_bytes:
                    preview.append(item)
            except (TypeError, ValueError):
                continue
        return preview

    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return None
    return _bounded_text_wrapper(encoded, max_bytes)


def bounded_geojson_preview(
    value: Any,
    *,
    max_bytes: int = MAX_PREVIEW_BYTES,
    max_features: int = MAX_GEOJSON_PREVIEW_FEATURES,
) -> dict[str, Any]:
    """Build a bounded FeatureCollection containing only whole features.

    Individual features that cannot fit are skipped instead of being sliced,
    ensuring that every retained feature remains valid JSON/GeoJSON input for
    a renderer. The caller decides whether an empty bounded preview is
    drawable.
    """
    features = value.get("features") if isinstance(value, dict) else None
    if not isinstance(features, list):
        return {"type": "FeatureCollection", "features": []}

    preview: dict[str, Any] = {"type": "FeatureCollection", "features": []}
    for feature in features[: max(max_features * 4, max_features)]:
        if len(preview["features"]) >= max_features:
            break
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            continue
        candidate = {
            "type": "FeatureCollection",
            "features": [*preview["features"], feature],
        }
        try:
            if serialized_size(candidate) <= max_bytes:
                preview["features"].append(feature)
        except (TypeError, ValueError):
            continue
    return preview
