"""Extract declared process outputs from common OGC result envelopes."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Any

from .models import OutputCandidate


_WRAPPER_KEYS = {
    "value",
    "data",
    "href",
    "url",
    "reference",
    "format",
    "mediaType",
    "type",
    "encoding",
    "title",
    "description",
    "unit",
    "uom",
    "units",
}
_ASYNC_METADATA_KEYS = {
    "jobID",
    "jobId",
    "id",
    "status",
    "message",
    "progress",
    "processID",
    "processId",
    "created",
    "started",
    "finished",
    "links",
}
_MAX_OUTPUT_ID_BASE_LENGTH = 280


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _output_id(value: Any) -> str:
    raw = str(value).strip() or "result"
    if len(raw) <= _MAX_OUTPUT_ID_BASE_LENGTH:
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    prefix_length = _MAX_OUTPUT_ID_BASE_LENGTH - len(digest) - 1
    return f"{raw[:prefix_length]}-{digest}"


def _unit_text(value: Any) -> str:
    return str(value).strip()[:200]


def _media_type(value: Any) -> str:
    if isinstance(value, dict):
        return _text(value.get("mediaType") or value.get("media_type") or value.get("type"))
    return _text(value)


def _units(value: dict[str, Any]) -> list[str]:
    raw = value.get("units", value.get("unit", value.get("uom")))
    if isinstance(raw, str) and raw.strip():
        return [_unit_text(raw)]
    if isinstance(raw, list):
        return [
            _unit_text(item)
            for item in raw[:100]
            if _unit_text(item)
        ]
    if isinstance(raw, dict):
        label = raw.get("symbol") or raw.get("name") or raw.get("id")
        return [_unit_text(label)] if label else []
    return []


def _unwrap(output_id: str, raw: Any) -> OutputCandidate:
    output_id = _output_id(output_id)
    if not isinstance(raw, dict):
        return OutputCandidate(id=output_id, value=raw)

    format_value = raw.get("format")
    declared_media_type = (
        _media_type(format_value)
        or _text(raw.get("mediaType"))
        or (
            _text(raw.get("type"))
            if "/" in _text(raw.get("type"))
            else ""
        )
    )
    href = _text(raw.get("href") or raw.get("url"))
    reference = raw.get("reference")
    if not href and isinstance(reference, str):
        href = reference.strip()
    elif not href and isinstance(reference, dict):
        href = _text(reference.get("href") or reference.get("url"))
        declared_media_type = declared_media_type or _media_type(reference)

    has_value = "value" in raw
    has_data = "data" in raw and set(raw).issubset(_WRAPPER_KEYS)
    value = raw.get("value") if has_value else raw.get("data") if has_data else raw

    # Some servers nest the same transmission wrapper more than once.  Unwrap
    # only explicit value/data envelopes; never recursively search arbitrary
    # feature properties for URLs.
    depth = 0
    while isinstance(value, dict) and depth < 8:
        nested_format = _media_type(value.get("format")) or _text(value.get("mediaType"))
        declared_media_type = nested_format or declared_media_type
        nested_href = _text(value.get("href") or value.get("url"))
        if nested_href and set(value).issubset(_WRAPPER_KEYS):
            href = nested_href
            value = None
            break
        if "value" in value and set(value).issubset(_WRAPPER_KEYS):
            value = value["value"]
            depth += 1
            continue
        if "data" in value and set(value).issubset(_WRAPPER_KEYS):
            value = value["data"]
            depth += 1
            continue
        break

    return OutputCandidate(
        id=output_id,
        value=value,
        href=href,
        title=_text(raw.get("title")) or output_id,
        description=_text(raw.get("description")),
        declared_media_type=declared_media_type,
        encoding=_text(
            (format_value or {}).get("encoding")
            if isinstance(format_value, dict)
            else raw.get("encoding")
        ),
        units=_units(raw),
    )


def _looks_like_geojson(value: dict[str, Any]) -> bool:
    return value.get("type") in {
        "FeatureCollection",
        "Feature",
        "Point",
        "MultiPoint",
        "LineString",
        "MultiLineString",
        "Polygon",
        "MultiPolygon",
        "GeometryCollection",
    }


def _output_mapping(data: Any, requested_output_ids: Iterable[str]) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    outputs = data.get("outputs")
    if isinstance(outputs, dict):
        return outputs
    if isinstance(outputs, list):
        mapped: dict[str, Any] = {}
        for index, item in enumerate(outputs):
            if not isinstance(item, dict):
                mapped[f"output-{index + 1}"] = item
                continue
            output_id = _text(item.get("id") or item.get("identifier")) or f"output-{index + 1}"
            mapped[output_id] = item
        return mapped

    requested = [item for item in requested_output_ids if item]
    if requested:
        selected = {key: data[key] for key in requested if key in data}
        if selected:
            return selected

    if _looks_like_geojson(data):
        return None
    if (
        data.get("type") in {"Coverage", "CoverageCollection"}
        or ("domain" in data and "ranges" in data)
        or isinstance(data.get("tiles"), list)
    ):
        return None
    if set(data).issubset(_ASYNC_METADATA_KEYS) and (
        data.get("status") or data.get("jobID") or data.get("jobId")
    ):
        return {}

    # OGC process result documents are commonly a mapping from advertised
    # output identifier to transmission wrapper.  Treat the top level as that
    # mapping when any value has an explicit wrapper.  Plain JSON objects remain
    # one document, avoiding accidental traversal of arbitrary properties.
    if data and any(
        isinstance(value, dict) and bool(set(value) & _WRAPPER_KEYS)
        for value in data.values()
    ):
        return data
    # OGC API - Processes result documents are mappings from output identifier
    # to value, and primitive values need no transmission wrapper. Without a
    # process description this is indistinguishable from an arbitrary JSON
    # object, so favor the standard result shape while preserving well-known
    # semantic documents above as single outputs.
    return data or None


def extract_outputs(
    data: Any,
    *,
    requested_output_ids: Iterable[str] = (),
    reference_href: str = "",
    response_body: bytes = b"",
    response_content_type: str = "",
    max_outputs: int = 20,
) -> list[OutputCandidate]:
    """Return bounded output candidates without recursive URL discovery."""
    if reference_href:
        return [
            OutputCandidate(
                id="result",
                href=reference_href,
                title="Result",
                declared_media_type="",
                redirect_count=1,
            )
        ]

    mapping = _output_mapping(data, requested_output_ids)
    if mapping is not None:
        return [
            _unwrap(str(output_id), value)
            for output_id, value in list(mapping.items())[:max_outputs]
        ]

    if response_body and response_content_type and "json" not in response_content_type.lower():
        value: Any = response_body
    else:
        value = data
    return [_unwrap("result", value)] if value is not None else []
