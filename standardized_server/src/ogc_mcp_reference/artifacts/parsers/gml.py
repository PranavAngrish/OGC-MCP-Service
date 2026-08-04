"""Hardened, dependency-free parser for common GML geometry encodings."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from ..models import ParsedArtifact
from .geojson import (
    bbox_for_geojson,
    crs84_coordinates_valid,
    geometry_types_for_geojson,
)


_FORBIDDEN_XML = re.compile(
    rb"<!\s*(?:DOCTYPE|ENTITY)|<\s*(?:xi:include|xinclude)\b",
    re.IGNORECASE,
)
_GEOMETRY_NAMES = {
    "Point",
    "MultiPoint",
    "LineString",
    "Curve",
    "MultiLineString",
    "MultiCurve",
    "Polygon",
    "Surface",
    "MultiPolygon",
    "MultiSurface",
    "GeometryCollection",
    "MultiGeometry",
}
_CONTAINER_NAMES = {
    "featureMember",
    "member",
    "featureMembers",
}
_MAX_FEATURES = 100_000
_MAX_COORDINATE_TUPLES = 1_000_000
_MAX_PROPERTY_TEXT = 100_000


def _local(element_or_tag: ET.Element | str) -> str:
    tag = element_or_tag.tag if isinstance(element_or_tag, ET.Element) else element_or_tag
    return tag.rsplit("}", 1)[-1].split(":", 1)[-1]


def _safe_root(value: Any) -> ET.Element:
    raw = value if isinstance(value, bytes) else str(value).encode("utf-8")
    if _FORBIDDEN_XML.search(raw):
        raise ValueError(
            "XML with DTD, entity declarations, or XInclude is not permitted."
        )
    if len(raw) > 10_000_000:
        raise ValueError("XML artifact exceeds the parser safety limit.")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid XML/GML: {exc}.") from exc
    count = 0
    stack: list[tuple[ET.Element, int]] = [(root, 1)]
    while stack:
        element, depth = stack.pop()
        count += 1
        if count > 200_000:
            raise ValueError("XML artifact contains too many elements.")
        if depth > 128:
            raise ValueError("XML artifact nesting is too deep.")
        stack.extend((child, depth + 1) for child in element)
    return root


def _numbers(text: str) -> list[float]:
    try:
        return [float(item) for item in re.split(r"[\s,]+", text.strip()) if item]
    except ValueError as exc:
        raise ValueError("GML coordinate contains a non-numeric value.") from exc


def _coordinate_nodes(element: ET.Element) -> tuple[list[list[float]], str]:
    for child in element.iter():
        name = _local(child)
        if name == "coordinates" and child.text:
            tuple_separator = child.attrib.get("ts", " ")
            coordinate_separator = child.attrib.get("cs", ",")
            tuples = [
                item for item in child.text.strip().split(tuple_separator) if item.strip()
            ]
            coordinates = [
                [float(number) for number in item.strip().split(coordinate_separator)[:3]]
                for item in tuples
            ]
            return coordinates, "xy"
        if name == "posList" and child.text:
            values = _numbers(child.text)
            dimension = int(
                child.attrib.get("srsDimension")
                or child.attrib.get("dimension")
                or element.attrib.get("srsDimension")
                or 2
            )
            if dimension < 2 or len(values) % dimension:
                raise ValueError("GML posList does not match its coordinate dimension.")
            return [
                values[index : index + dimension]
                for index in range(0, len(values), dimension)
            ], "declared"
        if name == "pos" and child.text:
            return [_numbers(child.text)], "declared"

    coordinate_pairs: list[list[float]] = []
    for coord in element.iter():
        if _local(coord) != "coord":
            continue
        x = next((child.text for child in coord if _local(child) == "X"), None)
        y = next((child.text for child in coord if _local(child) == "Y"), None)
        z = next((child.text for child in coord if _local(child) == "Z"), None)
        if x is not None and y is not None:
            coordinate_pairs.append(
                [float(x), float(y)] + ([float(z)] if z is not None else [])
            )
    return coordinate_pairs, "xy"


def _first_descendant(element: ET.Element, names: set[str]) -> ET.Element | None:
    return next((child for child in element.iter() if _local(child) in names), None)


def _direct_geometry_members(element: ET.Element) -> list[ET.Element]:
    members: list[ET.Element] = []
    for child in element:
        if _local(child) in _GEOMETRY_NAMES:
            members.append(child)
            continue
        geometry = _first_descendant(child, _GEOMETRY_NAMES)
        if geometry is not None:
            members.append(geometry)
    return members


def _parse_geometry(element: ET.Element) -> tuple[dict[str, Any], set[str]]:
    name = _local(element)
    if name == "Point":
        coordinates, axis = _coordinate_nodes(element)
        if not coordinates:
            raise ValueError("GML Point has no coordinates.")
        return {"type": "Point", "coordinates": coordinates[0]}, {axis}
    if name in {"LineString", "Curve"}:
        coordinates, axis = _coordinate_nodes(element)
        if not coordinates:
            raise ValueError(f"GML {name} has no coordinates.")
        return {"type": "LineString", "coordinates": coordinates}, {axis}
    if name in {"Polygon", "Surface"}:
        rings: list[list[list[float]]] = []
        axis_hints: set[str] = set()
        boundary_names = {
            "exterior",
            "outerBoundaryIs",
            "interior",
            "innerBoundaryIs",
        }
        for boundary in element:
            if _local(boundary) not in boundary_names:
                continue
            ring = _first_descendant(boundary, {"LinearRing", "Ring"})
            if ring is None:
                continue
            coordinates, ring_axis = _coordinate_nodes(ring)
            if coordinates:
                rings.append(coordinates)
                axis_hints.add(ring_axis)
        if not rings:
            coordinates, axis = _coordinate_nodes(element)
            if coordinates:
                rings.append(coordinates)
                axis_hints.add(axis)
        if not rings:
            raise ValueError(f"GML {name} has no rings.")
        return {"type": "Polygon", "coordinates": rings}, axis_hints

    collection_type = {
        "MultiPoint": "MultiPoint",
        "MultiLineString": "MultiLineString",
        "MultiCurve": "MultiLineString",
        "MultiPolygon": "MultiPolygon",
        "MultiSurface": "MultiPolygon",
        "GeometryCollection": "GeometryCollection",
        "MultiGeometry": "GeometryCollection",
    }.get(name)
    if collection_type:
        geometries: list[dict[str, Any]] = []
        axis_hints: set[str] = set()
        for member in _direct_geometry_members(element):
            geometry, member_axes = _parse_geometry(member)
            geometries.append(geometry)
            axis_hints.update(member_axes)
        if not geometries:
            raise ValueError(f"GML {name} has no geometry members.")
        if collection_type == "GeometryCollection":
            return {
                "type": collection_type,
                "geometries": geometries,
            }, axis_hints
        multi_coordinates: list[Any] = []
        for geometry in geometries:
            if "coordinates" not in geometry:
                raise ValueError(f"GML {name} member has no coordinates.")
            multi_coordinates.append(geometry["coordinates"])
        return {
            "type": collection_type,
            "coordinates": multi_coordinates,
        }, axis_hints
    raise ValueError(f"Unsupported GML geometry type '{name}'.")


def _scalar(text: str | None) -> Any:
    if text is None:
        return None
    value = text.strip()
    if len(value) > _MAX_PROPERTY_TEXT:
        raise ValueError("GML property text exceeds the parser safety limit.")
    if not value:
        return ""
    if value.casefold() in {"true", "false"}:
        return value.casefold() == "true"
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def _feature_from_member(
    member: ET.Element,
) -> tuple[dict[str, Any], set[str], ET.Element]:
    feature_element = (
        next(iter(member), member)
        if _local(member) in _CONTAINER_NAMES
        else member
    )
    geometry_element = _first_descendant(feature_element, _GEOMETRY_NAMES)
    if geometry_element is None:
        raise ValueError("GML feature has no supported geometry.")
    geometry, axis_hints = _parse_geometry(geometry_element)
    properties: dict[str, Any] = {}
    for child in feature_element:
        if child is geometry_element or _first_descendant(child, _GEOMETRY_NAMES) is not None:
            continue
        if _local(child) in {"boundedBy"}:
            continue
        properties[_local(child)] = _scalar(child.text)
    feature_id = (
        feature_element.attrib.get("{http://www.opengis.net/gml}id")
        or feature_element.attrib.get("fid")
        or ""
    )
    feature: dict[str, Any] = {
        "type": "Feature",
        "properties": properties,
        "geometry": geometry,
    }
    if feature_id:
        feature["id"] = feature_id
    return feature, axis_hints, geometry_element


def _geometry_crs_values(
    element: ET.Element,
    inherited_crs: str = "",
) -> tuple[list[str], set[str]]:
    declared = element.attrib.get("srsName", "").strip()
    effective = declared or inherited_crs
    explicit = {declared} if declared else set()
    if _local(element) in {
        "MultiPoint",
        "MultiLineString",
        "MultiCurve",
        "MultiPolygon",
        "MultiSurface",
        "GeometryCollection",
        "MultiGeometry",
    }:
        values: list[str] = []
        for member in _direct_geometry_members(element):
            member_values, member_explicit = _geometry_crs_values(member, effective)
            values.extend(member_values)
            explicit.update(member_explicit)
        return values or [effective], explicit
    return [effective], explicit


def _crs_family(value: str) -> str:
    upper = value.strip().upper()
    if "CRS84" in upper:
        return "crs84"
    if "4326" in upper:
        return "epsg4326"
    return upper


def _epsg4326_axis_policy(value: str) -> str:
    upper = value.upper()
    return "yx" if "URN:" in upper or "/DEF/CRS/" in upper else "xy"


def _crs_metadata(
    effective_values: list[str],
    explicit_values: set[str],
    axis_hints: set[str],
) -> tuple[str, str, str, list[str], bool, str]:
    warnings: list[str] = []
    cleaned = [value.strip() for value in effective_values]
    missing_count = sum(not value for value in cleaned)
    declared_values = [value for value in cleaned if value]
    if not declared_values:
        reason = "GML output does not consistently declare a CRS for its geometries."
        warnings.append(reason)
        return "", "missing", "", warnings, False, reason
    if missing_count:
        reason = (
            f"{missing_count} GML geometry member(s) do not declare or inherit a CRS."
        )
        warnings.append(f"{reason} No map was prepared.")
        return declared_values[0], "unsupported", "", warnings, False, reason

    all_declared = [*declared_values, *explicit_values]
    families = {_crs_family(value) for value in all_declared if value}
    if len(families) != 1:
        reason = (
            "GML geometries declare mixed CRS values: "
            + ", ".join(sorted(set(all_declared)))[:1500]
            + "."
        )
        warnings.append(f"{reason} No map was prepared.")
        return declared_values[0], "unsupported", "", warnings, False, reason

    family = next(iter(families))
    if family == "crs84":
        return "OGC:CRS84", "declared", "xy", warnings, False, ""
    if family == "epsg4326":
        axis_policies = {
            _epsg4326_axis_policy(value)
            for value in all_declared
            if _crs_family(value) == "epsg4326"
        }
        if len(axis_policies) != 1:
            reason = (
                "EPSG:4326 GML members use declaration forms with inconsistent "
                "axis-order semantics."
            )
            warnings.append(f"{reason} No map was prepared.")
            return declared_values[0], "unsupported", "", warnings, False, reason
        policy = next(iter(axis_policies))
        meaningful_hints = {hint for hint in axis_hints if hint}
        if policy == "yx" and meaningful_hints == {"declared", "xy"}:
            reason = (
                "EPSG:4326 GML members mix authority-axis pos/posList coordinates "
                "with explicitly x/y coordinate encodings."
            )
            warnings.append(f"{reason} No global axis swap is safe.")
            return declared_values[0], "unsupported", "", warnings, False, reason
        if policy == "yx" and meaningful_hints == {"declared"}:
            warnings.append(
                "EPSG:4326 GML authority axis order was normalized from y/x "
                "to GeoJSON x/y."
            )
            return (
                "OGC:CRS84",
                "declared",
                "yx-normalized-to-xy",
                warnings,
                True,
                "",
            )
        return "OGC:CRS84", "declared", "xy", warnings, False, ""

    normalized = declared_values[0]
    upper = normalized.upper()
    if "3857" in upper:
        warnings.append(
            "EPSG:3857 geometry was parsed but is not reprojected by the dependency-free parser."
        )
        reason = "EPSG:3857 requires reprojection before browser mapping."
        return "EPSG:3857", "unsupported", "xy", warnings, False, reason
    reason = f"CRS '{normalized}' has no safe map reprojection adapter."
    warnings.append(
        f"CRS '{normalized}' was parsed but no safe map reprojection is available."
    )
    return normalized, "unsupported", "", warnings, False, reason


def _swap_geometry_xy(geometry: dict[str, Any]) -> None:
    if geometry.get("type") == "GeometryCollection":
        for item in geometry.get("geometries", []):
            _swap_geometry_xy(item)
        return

    def swap(value: Any) -> Any:
        if (
            isinstance(value, list)
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            return [value[1], value[0], *value[2:]]
        if isinstance(value, list):
            return [swap(item) for item in value]
        return value

    geometry["coordinates"] = swap(geometry.get("coordinates"))


def _is_feature_member(element: ET.Element) -> bool:
    name = _local(element)
    if name == "featureMember":
        return True
    if name != "member":
        return False
    first_child = next(iter(element), None)
    return first_child is not None and _local(first_child) not in _GEOMETRY_NAMES


class GmlParser:
    name = "gml-core"

    def supports(self, media_type: str, value: Any) -> bool:
        return media_type in {"application/gml+xml", "text/gml"}

    def parse(self, value: Any, media_type: str) -> ParsedArtifact:
        root = _safe_root(value)
        feature_collection: dict[str, Any]
        effective_crs: list[str] = []
        explicit_crs: set[str] = set()
        axis_hints: set[str] = set()
        member_failures: list[str] = []
        members = [
            element
            for element in root.iter()
            if _is_feature_member(element)
        ]
        if len(members) > _MAX_FEATURES:
            raise ValueError("GML artifact contains too many features.")
        if not members and _local(root) in _GEOMETRY_NAMES:
            geometry, geometry_axes = _parse_geometry(root)
            axis_hints.update(geometry_axes)
            values, declarations = _geometry_crs_values(root)
            effective_crs.extend(values)
            explicit_crs.update(declarations)
            feature_collection = {
                "type": "FeatureCollection",
                "features": [{"type": "Feature", "properties": {}, "geometry": geometry}],
            }
        else:
            # featureMembers can contain multiple feature elements without
            # individual featureMember wrappers.
            container: ET.Element | None = None
            if not members:
                container = next(
                    (element for element in root.iter() if _local(element) == "featureMembers"),
                    None,
                )
                members = list(container) if container is not None else []
            if len(members) > _MAX_FEATURES:
                raise ValueError("GML artifact contains too many features.")
            features: list[dict[str, Any]] = []
            collection_crs = (
                (container.attrib.get("srsName", "") if container is not None else "")
                or root.attrib.get("srsName", "")
            ).strip()
            if collection_crs:
                explicit_crs.add(collection_crs)
            for index, member in enumerate(members, start=1):
                try:
                    feature, feature_axes, geometry_element = _feature_from_member(
                        member
                    )
                except ValueError as exc:
                    member_failures.append(f"member {index}: {str(exc)[:300]}")
                    continue
                features.append(feature)
                axis_hints.update(feature_axes)
                values, declarations = _geometry_crs_values(
                    geometry_element,
                    collection_crs,
                )
                effective_crs.extend(values)
                explicit_crs.update(declarations)
            if not features:
                detail = (
                    " " + "; ".join(member_failures[:5])
                    if member_failures
                    else ""
                )
                raise ValueError(
                    "GML document contains no supported feature geometries."
                    + detail
                )
            feature_collection = {"type": "FeatureCollection", "features": features}

        coordinate_count = _coordinate_count(feature_collection)
        if coordinate_count > _MAX_COORDINATE_TUPLES:
            raise ValueError("GML artifact contains too many coordinate tuples.")

        (
            crs_value,
            crs_status,
            axis_order,
            warnings,
            swap_xy,
            map_unavailable_reason,
        ) = _crs_metadata(effective_crs, explicit_crs, axis_hints)
        transformations = ["GML converted to GeoJSON"]
        if swap_xy:
            for feature in feature_collection.get("features", []):
                if isinstance(feature, dict) and isinstance(feature.get("geometry"), dict):
                    _swap_geometry_xy(feature["geometry"])
            transformations.append("EPSG:4326 authority axis order normalized to x/y")
        closed_rings = _close_polygon_rings(feature_collection)
        if closed_rings:
            warnings.append(
                f"{closed_rings} open polygon ring(s) were closed during canonicalization."
            )
            transformations.append("Open polygon rings closed")
        if crs_status == "declared" and not crs84_coordinates_valid(
            feature_collection
        ):
            crs_status = "unsupported"
            crs_value = next(
                (value.strip() for value in effective_crs if value.strip()),
                crs_value,
            )
            map_unavailable_reason = (
                "GML coordinates are invalid for normalized OGC:CRS84 geometry."
            )
            warnings.append(
                "Normalized GML contains invalid, non-finite, structurally unsafe, "
                "or out-of-range CRS84 coordinates. No map was prepared."
            )
        if member_failures:
            failure_summary = (
                f"Skipped {len(member_failures)} GML member(s) that could not be "
                "safely interpreted: "
                + "; ".join(member_failures[:5])
            )
            warnings.append(failure_summary[:2000])
            map_unavailable_reason = (
                "The GML result was only partially interpreted because one or "
                "more advertised members were skipped."
            )
        return ParsedArtifact(
            semantic_type="vector",
            format="GML",
            canonical_media_type="application/geo+json",
            canonical_data=feature_collection,
            feature_count=len(feature_collection["features"]),
            geometry_types=geometry_types_for_geojson(feature_collection),
            bbox=bbox_for_geojson(feature_collection),
            crs_value=crs_value,
            crs_status=crs_status,
            axis_order=axis_order,
            warnings=warnings,
            transformations=transformations,
            map_unavailable_reason=map_unavailable_reason,
            force_partial=bool(member_failures),
            partial_reason=(
                "One or more GML members were omitted from the canonical preview."
                if member_failures
                else ""
            ),
        )


def _coordinate_count(value: Any) -> int:
    if (
        isinstance(value, list)
        and len(value) >= 2
        and isinstance(value[0], (int, float))
        and isinstance(value[1], (int, float))
    ):
        return 1
    if isinstance(value, list):
        return sum(_coordinate_count(item) for item in value)
    if isinstance(value, dict):
        if value.get("type") == "GeometryCollection":
            return sum(_coordinate_count(item) for item in value.get("geometries", []))
        if "coordinates" in value:
            return _coordinate_count(value["coordinates"])
        return sum(_coordinate_count(item) for item in value.values())
    return 0


def _close_polygon_rings(value: Any) -> int:
    closed = 0
    if isinstance(value, dict):
        value_type = value.get("type")
        if value_type == "Polygon":
            for ring in value.get("coordinates", []):
                if isinstance(ring, list) and ring and ring[0] != ring[-1]:
                    ring.append(list(ring[0]))
                    closed += 1
        elif value_type == "MultiPolygon":
            for polygon in value.get("coordinates", []):
                for ring in polygon:
                    if isinstance(ring, list) and ring and ring[0] != ring[-1]:
                        ring.append(list(ring[0]))
                        closed += 1
        elif value_type == "GeometryCollection":
            for geometry in value.get("geometries", []):
                closed += _close_polygon_rings(geometry)
        else:
            for item in value.values():
                closed += _close_polygon_rings(item)
    elif isinstance(value, list):
        for item in value:
            closed += _close_polygon_rings(item)
    return closed
