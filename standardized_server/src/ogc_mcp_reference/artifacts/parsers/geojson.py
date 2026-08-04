"""GeoJSON validation and metadata extraction."""

from __future__ import annotations

import math
from typing import Any

from ..models import ParsedArtifact


GEOMETRY_TYPES = {
    "Point",
    "MultiPoint",
    "LineString",
    "MultiLineString",
    "Polygon",
    "MultiPolygon",
    "GeometryCollection",
}


def _numeric_pairs(value: Any):
    if (
        isinstance(value, (list, tuple))
        and len(value) >= 2
        and isinstance(value[0], (int, float))
        and not isinstance(value[0], bool)
        and isinstance(value[1], (int, float))
        and not isinstance(value[1], bool)
    ):
        x, y = float(value[0]), float(value[1])
        if math.isfinite(x) and math.isfinite(y):
            yield x, y
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _numeric_pairs(item)


def bbox_for_geojson(value: Any) -> list[float]:
    pairs: list[tuple[float, float]] = []

    def visit(item: Any) -> None:
        if not isinstance(item, dict):
            return
        item_type = item.get("type")
        if item_type == "FeatureCollection":
            for feature in item.get("features", []):
                visit(feature)
        elif item_type == "Feature":
            visit(item.get("geometry"))
        elif item_type == "GeometryCollection":
            for geometry in item.get("geometries", []):
                visit(geometry)
        elif item_type in GEOMETRY_TYPES:
            pairs.extend(_numeric_pairs(item.get("coordinates")))

    visit(value)
    if not pairs:
        return []
    xs, ys = zip(*pairs)
    return [min(xs), min(ys), max(xs), max(ys)]


def geometry_types_for_geojson(value: Any) -> list[str]:
    found: set[str] = set()

    def visit(item: Any) -> None:
        if not isinstance(item, dict):
            return
        item_type = item.get("type")
        if item_type == "FeatureCollection":
            for feature in item.get("features", []):
                visit(feature)
        elif item_type == "Feature":
            visit(item.get("geometry"))
        elif item_type == "GeometryCollection":
            found.add("GeometryCollection")
            for geometry in item.get("geometries", []):
                visit(geometry)
        elif item_type in GEOMETRY_TYPES:
            found.add(str(item_type))

    visit(value)
    return sorted(found)


def crs84_coordinates_valid(value: Any) -> bool:
    """Return false when GeoJSON structure or any coordinate is unsafe to map."""

    def position_valid(position: Any) -> bool:
        if (
            not isinstance(position, (list, tuple))
            or len(position) < 2
            or not isinstance(position[0], (int, float))
            or isinstance(position[0], bool)
            or not isinstance(position[1], (int, float))
            or isinstance(position[1], bool)
        ):
            return False
        longitude = float(position[0])
        latitude = float(position[1])
        return (
            math.isfinite(longitude)
            and math.isfinite(latitude)
            and -180 <= longitude <= 180
            and -90 <= latitude <= 90
        )

    def line_valid(line: Any, *, minimum: int) -> bool:
        return (
            isinstance(line, (list, tuple))
            and len(line) >= minimum
            and all(position_valid(position) for position in line)
        )

    def ring_valid(ring: Any) -> bool:
        return (
            line_valid(ring, minimum=4)
            and list(ring[0][:2]) == list(ring[-1][:2])
        )

    def geometry_valid(geometry: Any) -> bool:
        if not isinstance(geometry, dict):
            return False
        geometry_type = geometry.get("type")
        coordinates = geometry.get("coordinates")
        if geometry_type == "Point":
            return position_valid(coordinates)
        if geometry_type == "MultiPoint":
            return line_valid(coordinates, minimum=1)
        if geometry_type == "LineString":
            return line_valid(coordinates, minimum=2)
        if geometry_type == "MultiLineString":
            return (
                isinstance(coordinates, (list, tuple))
                and bool(coordinates)
                and all(line_valid(line, minimum=2) for line in coordinates)
            )
        if geometry_type == "Polygon":
            return (
                isinstance(coordinates, (list, tuple))
                and bool(coordinates)
                and all(ring_valid(ring) for ring in coordinates)
            )
        if geometry_type == "MultiPolygon":
            return (
                isinstance(coordinates, (list, tuple))
                and bool(coordinates)
                and all(
                    isinstance(polygon, (list, tuple))
                    and bool(polygon)
                    and all(ring_valid(ring) for ring in polygon)
                    for polygon in coordinates
                )
            )
        if geometry_type == "GeometryCollection":
            geometries = geometry.get("geometries")
            return isinstance(geometries, list) and all(
                geometry_valid(item) for item in geometries
            )
        return False

    def feature_valid(feature: Any) -> bool:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            return False
        geometry = feature.get("geometry")
        return geometry is None or geometry_valid(geometry)

    value_type = value.get("type") if isinstance(value, dict) else None
    if value_type == "FeatureCollection":
        features = value.get("features")
        return isinstance(features, list) and all(
            feature_valid(feature) for feature in features
        )
    if value_type == "Feature":
        return feature_valid(value)
    return geometry_valid(value)


def _as_feature_collection(value: dict[str, Any]) -> dict[str, Any]:
    value_type = value.get("type")
    if value_type == "FeatureCollection":
        return value
    if value_type == "Feature":
        return {"type": "FeatureCollection", "features": [value]}
    if value_type in GEOMETRY_TYPES:
        return {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {}, "geometry": value}],
        }
    raise ValueError("JSON value is not a GeoJSON feature or geometry.")


class GeoJsonParser:
    name = "geojson"

    def supports(self, media_type: str, value: Any) -> bool:
        if media_type in {
            "application/geo+json",
            "application/vnd.ogc.fg+json",
        }:
            return True
        return isinstance(value, dict) and value.get("type") in (
            GEOMETRY_TYPES | {"Feature", "FeatureCollection"}
        )

    def parse(self, value: Any, media_type: str) -> ParsedArtifact:
        if not isinstance(value, dict):
            raise ValueError("GeoJSON output must be a JSON object.")
        feature_collection = _as_feature_collection(value)
        features = feature_collection.get("features")
        if not isinstance(features, list):
            raise ValueError("GeoJSON FeatureCollection.features must be an array.")

        crs_value = "OGC:CRS84"
        crs_status = "inferred"
        warnings: list[str] = []
        declared_crs = feature_collection.get("crs")
        if isinstance(declared_crs, dict):
            properties = declared_crs.get("properties")
            if isinstance(properties, dict) and isinstance(properties.get("name"), str):
                crs_value = properties["name"]
                crs_status = "declared"
                if "4326" in crs_value.upper() or "CRS84" in crs_value.upper():
                    crs_value = "OGC:CRS84"
                else:
                    crs_status = "unsupported"
                    warnings.append(
                        "GeoJSON declares a non-CRS84 CRS; map presentation requires reprojection."
                    )
        bbox = bbox_for_geojson(feature_collection)
        if (
            crs_status != "unsupported"
            and bbox
            and (
                bbox[0] < -180
                or bbox[2] > 180
                or bbox[1] < -90
                or bbox[3] > 90
            )
        ):
            crs_status = "unsupported"
            warnings.append(
                "GeoJSON coordinates fall outside the CRS84 longitude/latitude "
                "range; no map preview was prepared."
            )
        elif crs_status != "unsupported" and not crs84_coordinates_valid(
            feature_collection
        ):
            crs_status = "unsupported"
            warnings.append(
                "GeoJSON contains invalid or non-finite CRS84 coordinate tuples; "
                "no map preview was prepared."
            )
        return ParsedArtifact(
            semantic_type="vector",
            format="GeoJSON",
            canonical_media_type="application/geo+json",
            canonical_data=feature_collection,
            feature_count=len(features),
            geometry_types=geometry_types_for_geojson(feature_collection),
            bbox=bbox,
            crs_value=crs_value,
            crs_status=crs_status,
            axis_order="xy",
            warnings=warnings,
        )
