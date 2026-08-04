"""Small bounded parser for OGC WKT core geometry types."""

from __future__ import annotations

import re
from typing import Any

from ..models import ParsedArtifact
from .geojson import bbox_for_geojson, geometry_types_for_geojson


_TOKEN = re.compile(
    r"[A-Za-z]+|[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?|[(),]",
)


class _Tokens:
    def __init__(self, text: str) -> None:
        self.items = _TOKEN.findall(text)
        self.index = 0
        if len(self.items) > 2_000_000:
            raise ValueError("WKT contains too many tokens.")

    def peek(self) -> str:
        return self.items[self.index] if self.index < len(self.items) else ""

    def take(self, expected: str = "") -> str:
        value = self.peek()
        if not value:
            raise ValueError("Unexpected end of WKT.")
        if expected and value.upper() != expected.upper():
            raise ValueError(f"Expected '{expected}' in WKT, found '{value}'.")
        self.index += 1
        return value

    def consume(self, value: str) -> bool:
        if self.peek().upper() == value.upper():
            self.index += 1
            return True
        return False


def _coordinate(tokens: _Tokens) -> list[float]:
    values: list[float] = []
    while tokens.peek() and tokens.peek() not in {",", ")"}:
        token = tokens.take()
        try:
            values.append(float(token))
        except ValueError as exc:
            raise ValueError(f"Invalid coordinate token '{token}' in WKT.") from exc
    if len(values) < 2:
        raise ValueError("WKT coordinate must contain at least two ordinates.")
    return values


def _coordinate_sequence(tokens: _Tokens) -> list[list[float]]:
    tokens.take("(")
    coordinates = [_coordinate(tokens)]
    while tokens.consume(","):
        coordinates.append(_coordinate(tokens))
    tokens.take(")")
    return coordinates


def _polygon_coordinates(tokens: _Tokens) -> list[list[list[float]]]:
    tokens.take("(")
    rings = [_coordinate_sequence(tokens)]
    while tokens.consume(","):
        rings.append(_coordinate_sequence(tokens))
    tokens.take(")")
    return rings


def _parse_geometry(tokens: _Tokens) -> dict[str, Any] | None:
    geometry_type = tokens.take().upper()
    if geometry_type not in {
        "POINT",
        "LINESTRING",
        "POLYGON",
        "MULTIPOINT",
        "MULTILINESTRING",
        "MULTIPOLYGON",
        "GEOMETRYCOLLECTION",
    }:
        raise ValueError(f"Unsupported WKT geometry type '{geometry_type}'.")
    if tokens.peek().upper() in {"Z", "M", "ZM"}:
        tokens.take()
    if tokens.consume("EMPTY"):
        return None
    if geometry_type == "POINT":
        coordinates = _coordinate_sequence(tokens)
        if len(coordinates) != 1:
            raise ValueError("WKT POINT must contain exactly one coordinate.")
        return {"type": "Point", "coordinates": coordinates[0]}
    if geometry_type == "LINESTRING":
        return {"type": "LineString", "coordinates": _coordinate_sequence(tokens)}
    if geometry_type == "POLYGON":
        return {"type": "Polygon", "coordinates": _polygon_coordinates(tokens)}
    if geometry_type == "MULTIPOINT":
        tokens.take("(")
        points: list[list[float]] = []
        while True:
            if tokens.peek() == "(":
                sequence = _coordinate_sequence(tokens)
                if len(sequence) != 1:
                    raise ValueError("Each MULTIPOINT member must be one coordinate.")
                points.append(sequence[0])
            else:
                points.append(_coordinate(tokens))
            if not tokens.consume(","):
                break
        tokens.take(")")
        return {"type": "MultiPoint", "coordinates": points}
    if geometry_type == "MULTILINESTRING":
        tokens.take("(")
        lines = [_coordinate_sequence(tokens)]
        while tokens.consume(","):
            lines.append(_coordinate_sequence(tokens))
        tokens.take(")")
        return {"type": "MultiLineString", "coordinates": lines}
    if geometry_type == "MULTIPOLYGON":
        tokens.take("(")
        polygons = [_polygon_coordinates(tokens)]
        while tokens.consume(","):
            polygons.append(_polygon_coordinates(tokens))
        tokens.take(")")
        return {"type": "MultiPolygon", "coordinates": polygons}

    tokens.take("(")
    geometries: list[dict[str, Any]] = []
    first = _parse_geometry(tokens)
    if first is not None:
        geometries.append(first)
    while tokens.consume(","):
        geometry = _parse_geometry(tokens)
        if geometry is not None:
            geometries.append(geometry)
    tokens.take(")")
    return {"type": "GeometryCollection", "geometries": geometries}


class WktParser:
    name = "wkt-core"

    def supports(self, media_type: str, value: Any) -> bool:
        return media_type in {"text/wkt", "application/wkt"}

    def parse(self, value: Any, media_type: str) -> ParsedArtifact:
        text = value.decode("utf-8") if isinstance(value, bytes) else str(value)
        crs_value = ""
        crs_status = "missing"
        match = re.match(r"^\s*SRID=(\d+)\s*;\s*", text, re.IGNORECASE)
        if match:
            crs_value = f"EPSG:{match.group(1)}"
            crs_status = "declared"
            text = text[match.end() :]
        tokens = _Tokens(text)
        geometry = _parse_geometry(tokens)
        if tokens.peek():
            raise ValueError(f"Unexpected trailing WKT token '{tokens.peek()}'.")
        features = [] if geometry is None else [
            {"type": "Feature", "properties": {}, "geometry": geometry}
        ]
        canonical = {"type": "FeatureCollection", "features": features}
        warnings: list[str] = []
        map_unavailable_reason = ""
        clarification_issues: list[dict[str, Any]] = []
        if not crs_value:
            map_unavailable_reason = (
                "WKT does not declare an SRID/CRS, so its coordinates cannot be "
                "safely placed on a map."
            )
            warnings.append(
                "WKT did not declare an SRID/CRS. No CRS84 assumption or map "
                "preview was made."
            )
            clarification_issues.append(
                {
                    "id": "wkt-crs",
                    "kind": "crs",
                    "fieldPath": "crs",
                    "question": "What CRS/SRID does this WKT geometry use?",
                    "whyItMatters": (
                        "Mapping CRS-less WKT as longitude/latitude could place "
                        "the geometry incorrectly."
                    ),
                    "observedValue": "missing SRID",
                    "allowFreeText": True,
                }
            )
        elif "4326" in crs_value:
            crs_value = "OGC:CRS84"
        elif "3857" in crs_value:
            crs_status = "unsupported"
            warnings.append("EPSG:3857 WKT requires reprojection before map presentation.")
        else:
            crs_status = "unsupported"
            warnings.append(f"{crs_value} requires reprojection before map presentation.")
        return ParsedArtifact(
            semantic_type="vector",
            format="WKT",
            canonical_media_type="application/geo+json",
            canonical_data=canonical,
            feature_count=len(features),
            geometry_types=geometry_types_for_geojson(canonical),
            bbox=bbox_for_geojson(canonical),
            crs_value=crs_value,
            crs_status=crs_status,
            axis_order="xy",
            warnings=warnings,
            transformations=["WKT converted to GeoJSON"],
            map_unavailable_reason=map_unavailable_reason,
            force_partial=bool(map_unavailable_reason),
            partial_reason=map_unavailable_reason,
            clarification_issues=clarification_issues,
            clarification_blocking=bool(clarification_issues),
            clarification_scope="presentation",
        )
