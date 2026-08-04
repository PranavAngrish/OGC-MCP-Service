"""Bounded media-type and representation detection."""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit


def normalize_media_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()


def _extension_media_type(href: str) -> str:
    suffix = PurePosixPath(urlsplit(href).path).suffix.lower()
    return {
        ".geojson": "application/geo+json",
        ".json": "application/json",
        ".jsonfg": "application/vnd.ogc.fg+json",
        ".gml": "application/gml+xml",
        ".xml": "application/xml",
        ".wkt": "text/wkt",
        ".csv": "text/csv",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".mvt": "application/vnd.mapbox-vector-tile",
        ".pbf": "application/vnd.mapbox-vector-tile",
        ".nc": "application/x-netcdf",
    }.get(suffix, "")


def _json_semantic_media_type(value: Any) -> str:
    if not isinstance(value, dict):
        return "application/json"
    value_type = str(value.get("type", ""))
    if value_type in {
        "FeatureCollection",
        "Feature",
        "Point",
        "MultiPoint",
        "LineString",
        "MultiLineString",
        "Polygon",
        "MultiPolygon",
        "GeometryCollection",
    }:
        return "application/geo+json"
    if value_type in {"Coverage", "CoverageCollection"} or (
        "domain" in value and "ranges" in value
    ):
        return "application/prs.coverage+json"
    if "tiles" in value and isinstance(value["tiles"], list):
        return "application/vnd.mapbox.tilejson+json"
    return "application/json"


_WKT_PREFIX = re.compile(
    r"^\s*(?:SRID=\d+\s*;\s*)?"
    r"(?:POINT|LINESTRING|POLYGON|MULTIPOINT|MULTILINESTRING|"
    r"MULTIPOLYGON|GEOMETRYCOLLECTION)\s*(?:Z|M|ZM)?\s*(?:\(|EMPTY)",
    re.IGNORECASE,
)


def detect_media_type(
    value: Any,
    *,
    declared_media_type: str = "",
    http_content_type: str = "",
    href: str = "",
) -> tuple[str, list[str]]:
    """Detect the actual representation, preserving declared-type conflicts."""
    declared = normalize_media_type(declared_media_type)
    http_type = normalize_media_type(http_content_type)
    hint = declared or http_type or _extension_media_type(href)
    warnings: list[str] = []

    if isinstance(value, (dict, list, int, float, bool)) or value is None:
        detected = _json_semantic_media_type(value)
    else:
        raw = value if isinstance(value, bytes) else str(value).encode("utf-8", errors="replace")
        text = raw[:8192].decode("utf-8", errors="replace").lstrip()
        lowered = text.lower()
        if raw.startswith((b"II*\x00", b"MM\x00*")):
            detected = "image/tiff"
        elif raw.startswith(b"\x89PNG\r\n\x1a\n"):
            detected = "image/png"
        elif raw.startswith(b"\xff\xd8\xff"):
            detected = "image/jpeg"
        elif text.startswith(("{", "[")):
            try:
                detected = _json_semantic_media_type(json.loads(text))
            except json.JSONDecodeError:
                detected = hint or "text/plain"
        elif text.startswith("<"):
            if "opengis.net/gml" in lowered or "<gml:" in lowered:
                detected = "application/gml+xml"
            else:
                detected = "application/xml"
        elif _WKT_PREFIX.match(text):
            detected = "text/wkt"
        elif hint:
            detected = hint
        else:
            detected = "text/plain"

    # Generic JSON/XML declarations legitimately contain a more specific
    # nested representation, so report refinement rather than a mismatch.
    generic_refinements = {
        ("application/json", "application/geo+json"),
        ("application/json", "application/prs.coverage+json"),
        ("application/json", "application/vnd.mapbox.tilejson+json"),
        ("application/xml", "application/gml+xml"),
        ("text/xml", "application/gml+xml"),
    }
    if declared and declared != detected and (declared, detected) not in generic_refinements:
        warnings.append(
            f"Declared media type '{declared}' differs from detected type '{detected}'."
        )
    if http_type and http_type != detected and (http_type, detected) not in generic_refinements:
        # HTML redirect bodies are intentionally superseded when their
        # Location is resolved; this function only sees the resolved value.
        warnings.append(
            f"HTTP Content-Type '{http_type}' differs from detected type '{detected}'."
        )
    return detected, warnings
