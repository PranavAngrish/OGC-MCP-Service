"""Conservative spatial detection for JSON/CSV-like tabular rows."""

from __future__ import annotations

import math
from typing import Any

from ..models import ParsedArtifact
from .geojson import bbox_for_geojson


_LONGITUDE_NAMES = {"longitude", "lon", "lng"}
_LATITUDE_NAMES = {"latitude", "lat"}


def _normalized_name(value: Any) -> str:
    return str(value).strip().casefold()


def _coordinate_columns(columns: list[str]) -> tuple[str, str] | None:
    longitude = [
        column
        for column in columns
        if _normalized_name(column) in _LONGITUDE_NAMES
    ]
    latitude = [
        column
        for column in columns
        if _normalized_name(column) in _LATITUDE_NAMES
    ]
    if len(longitude) == 1 and len(latitude) == 1:
        return longitude[0], latitude[0]
    return None


def _declared_crs_name(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()[:300]
    if isinstance(value, dict):
        properties = value.get("properties")
        if isinstance(properties, dict) and isinstance(properties.get("name"), str):
            return properties["name"].strip()[:300]
        for key in ("name", "id", "srsName"):
            if isinstance(value.get(key), str):
                return value[key].strip()[:300]
    return ""


def _normalized_crs(value: Any) -> tuple[str, str]:
    declared = _declared_crs_name(value)
    if not declared:
        return "OGC:CRS84", "inferred"
    upper = declared.upper()
    if "CRS84" in upper or "4326" in upper:
        return "OGC:CRS84", "declared"
    return declared, "unsupported"


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str):
        try:
            result = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return result if math.isfinite(result) else None


def _issue(
    *,
    issue_id: str,
    kind: str,
    field_path: str,
    question: str,
    why: str,
    observed: Any,
) -> dict[str, Any]:
    return {
        "id": issue_id,
        "kind": kind,
        "fieldPath": field_path,
        "question": question,
        "whyItMatters": why,
        "observedValue": observed,
        "allowFreeText": True,
    }


def _table_artifact(
    rows: list[dict[str, Any]],
    *,
    format_name: str,
    columns: list[str],
    fallback_semantic_type: str,
    warnings: list[str],
    map_reason: str,
    issues: list[dict[str, Any]] | None = None,
) -> ParsedArtifact:
    return ParsedArtifact(
        semantic_type=fallback_semantic_type,
        format=format_name,
        canonical_media_type="application/json",
        canonical_data=rows,
        table_rows=len(rows),
        table_columns=columns,
        preview=rows[:100],
        warnings=warnings,
        map_unavailable_reason=map_reason,
        force_partial=True,
        partial_reason=map_reason,
        clarification_issues=issues or [],
    )


def spatial_table_artifact(
    rows: list[dict[str, Any]],
    *,
    format_name: str,
    columns: list[str],
    declared_crs: Any = None,
    fallback_semantic_type: str = "table",
) -> ParsedArtifact | None:
    """Promote unambiguous lon/lat rows to point GeoJSON.

    ``x``/``y`` columns are deliberately never guessed: without CRS and axis
    semantics they remain a table and carry a structured clarification issue.
    """
    if not rows:
        return None

    coordinates = _coordinate_columns(columns)
    normalized_columns = {_normalized_name(column): column for column in columns}
    longitude_candidates = [
        column
        for column in columns
        if _normalized_name(column) in _LONGITUDE_NAMES
    ]
    latitude_candidates = [
        column
        for column in columns
        if _normalized_name(column) in _LATITUDE_NAMES
    ]

    if coordinates is None:
        if (
            len(longitude_candidates) > 1
            or len(latitude_candidates) > 1
        ):
            observed = [*longitude_candidates, *latitude_candidates]
            reason = (
                "Multiple longitude or latitude aliases are present, so a safe "
                "coordinate-column pairing cannot be selected."
            )
            return _table_artifact(
                rows,
                format_name=format_name,
                columns=columns,
                fallback_semantic_type=fallback_semantic_type,
                warnings=[f"{reason} No map was created."],
                map_reason=reason,
                issues=[
                    _issue(
                        issue_id="spatial-table-coordinate-columns",
                        kind="axis_order",
                        field_path="columns",
                        question=(
                            "Which columns contain longitude and latitude for "
                            "this table?"
                        ),
                        why=reason,
                        observed=observed,
                    )
                ],
            )
        if "x" in normalized_columns and "y" in normalized_columns:
            x_column = normalized_columns["x"]
            y_column = normalized_columns["y"]
            reason = (
                "Columns named x and y are potentially spatial, but their CRS "
                "and axis meaning are ambiguous."
            )
            return _table_artifact(
                rows,
                format_name=format_name,
                columns=columns,
                fallback_semantic_type=fallback_semantic_type,
                warnings=[f"{reason} No coordinate order was guessed."],
                map_reason=reason,
                issues=[
                    _issue(
                        issue_id="spatial-table-axis-order",
                        kind="axis_order",
                        field_path=f"columns.{x_column},{y_column}",
                        question=(
                            "What CRS and axis order do the x and y columns use?"
                        ),
                        why=(
                            "Guessing could swap axes or place features in the "
                            "wrong part of the world."
                        ),
                        observed=[x_column, y_column],
                    )
                ],
            )
        return None

    longitude_column, latitude_column = coordinates
    crs_value, crs_status = _normalized_crs(declared_crs)
    if crs_status == "unsupported":
        reason = (
            f"The table declares CRS '{crs_value}', but spatial-table mapping "
            "currently supports only OGC:CRS84/EPSG:4326 longitude-latitude rows."
        )
        return _table_artifact(
            rows,
            format_name=format_name,
            columns=columns,
            fallback_semantic_type=fallback_semantic_type,
            warnings=[reason],
            map_reason=reason,
            issues=[
                _issue(
                    issue_id="spatial-table-crs",
                    kind="crs",
                    field_path="crs",
                    question=(
                        "Can this table be supplied or reprojected as "
                        "OGC:CRS84/EPSG:4326 longitude-latitude coordinates?"
                    ),
                    why=(
                        "The current CRS cannot be safely relabelled as browser "
                        "longitude and latitude."
                    ),
                    observed=crs_value,
                )
            ],
        )

    features: list[dict[str, Any]] = []
    invalid_rows = 0
    for row in rows:
        longitude = _number(row.get(longitude_column))
        latitude = _number(row.get(latitude_column))
        if (
            longitude is None
            or latitude is None
            or not -180 <= longitude <= 180
            or not -90 <= latitude <= 90
        ):
            invalid_rows += 1
            continue
        feature: dict[str, Any] = {
            "type": "Feature",
            "properties": dict(row),
            "geometry": {
                "type": "Point",
                "coordinates": [longitude, latitude],
            },
        }
        feature_id = row.get("id")
        if isinstance(feature_id, (str, int, float)) and not isinstance(
            feature_id, bool
        ):
            feature["id"] = feature_id
        features.append(feature)

    if not features:
        reason = (
            "Longitude and latitude columns were identified, but no row "
            "contained finite CRS84 coordinates within valid world ranges."
        )
        return _table_artifact(
            rows,
            format_name=format_name,
            columns=columns,
            fallback_semantic_type=fallback_semantic_type,
            warnings=[reason],
            map_reason=reason,
        )

    feature_collection = {"type": "FeatureCollection", "features": features}
    warnings: list[str] = []
    if crs_status == "inferred":
        warnings.append(
            "OGC:CRS84 was inferred from explicit longitude/latitude column names."
        )
    if invalid_rows:
        warnings.append(
            f"{invalid_rows} row(s) were omitted from the spatial preview because "
            "their longitude/latitude values were missing, non-finite, or out of range."
        )
    partial_reason = (
        f"{invalid_rows} row(s) were omitted from the spatial preview."
        if invalid_rows
        else ""
    )
    return ParsedArtifact(
        semantic_type="vector",
        format=f"Spatial {format_name}",
        canonical_media_type="application/geo+json",
        canonical_data=feature_collection,
        feature_count=len(features),
        geometry_types=["Point"],
        bbox=bbox_for_geojson(feature_collection),
        crs_value=crs_value,
        crs_status=crs_status,
        axis_order="xy",
        warnings=warnings,
        transformations=[
            "Longitude/latitude table rows converted to GeoJSON Point features"
        ],
        table_rows=len(rows),
        table_columns=columns,
        force_partial=bool(invalid_rows),
        partial_reason=partial_reason,
    )


def _ambiguous_coordinate_artifact(
    value: Any,
    *,
    format_name: str,
    field_path: str,
    observed: Any,
    reason: str,
) -> ParsedArtifact:
    issue = _issue(
        issue_id="coordinate-value-axis-order",
        kind="axis_order",
        field_path=field_path,
        question="What CRS and axis order does this coordinate value use?",
        why=(
            "A naked numeric pair can represent longitude/latitude, "
            "latitude/longitude, or projected x/y coordinates."
        ),
        observed=observed,
    )
    if isinstance(value, list):
        return ParsedArtifact(
            semantic_type="table",
            format=format_name,
            canonical_media_type="application/json",
            canonical_data=value,
            table_rows=len(value),
            preview=value,
            warnings=[reason],
            map_unavailable_reason=reason,
            force_partial=True,
            partial_reason=reason,
            clarification_issues=[issue],
        )
    return ParsedArtifact(
        semantic_type="document",
        format=format_name,
        canonical_media_type="application/json",
        canonical_data=value,
        preview=value,
        warnings=[reason],
        map_unavailable_reason=reason,
        force_partial=True,
        partial_reason=reason,
        clarification_issues=[issue],
    )


def explicit_coordinate_artifact(value: Any) -> ParsedArtifact | None:
    """Interpret explicit coordinate shapes without guessing naked pair order."""
    if (
        isinstance(value, list)
        and len(value) in {2, 3}
        and all(_number(item) is not None for item in value)
    ):
        return _ambiguous_coordinate_artifact(
            value,
            format_name="JSON coordinate pair",
            field_path="value",
            observed=value,
            reason=(
                "A naked numeric coordinate pair has no declared CRS or axis "
                "order, so no map was created."
            ),
        )
    if not isinstance(value, dict):
        return None

    columns = [str(key) for key in value]
    if _coordinate_columns(columns) is not None:
        return spatial_table_artifact(
            [value],
            format_name="JSON coordinate object",
            columns=columns,
            declared_crs=value.get("crs") or value.get("srs") or value.get("srsName"),
        )

    coordinates = value.get("coordinates")
    if not (
        isinstance(coordinates, list)
        and len(coordinates) in {2, 3}
        and all(_number(item) is not None for item in coordinates)
    ):
        return None

    declared_crs = value.get("crs") or value.get("srs") or value.get("srsName")
    crs_value, crs_status = _normalized_crs(declared_crs)
    axis_value = str(
        value.get("axisOrder") or value.get("axis_order") or ""
    ).strip().casefold()
    xy_orders = {
        "xy",
        "lonlat",
        "longitude-latitude",
        "longitude,latitude",
    }
    yx_orders = {
        "yx",
        "latlon",
        "latitude-longitude",
        "latitude,longitude",
    }
    if (
        not _declared_crs_name(declared_crs)
        or crs_status == "unsupported"
        or axis_value not in xy_orders | yx_orders
    ):
        reason = (
            "The coordinates array is potentially spatial, but it lacks a "
            "supported CRS and explicit axis order."
        )
        if crs_status == "unsupported":
            reason = (
                f"The coordinates array declares unsupported CRS '{crs_value}', "
                "so it cannot be mapped without reprojection."
            )
        return _ambiguous_coordinate_artifact(
            value,
            format_name="JSON coordinate object",
            field_path="coordinates",
            observed={
                "coordinates": coordinates,
                "crs": _declared_crs_name(declared_crs),
                "axisOrder": axis_value,
            },
            reason=reason,
        )

    first = _number(coordinates[0])
    second = _number(coordinates[1])
    assert first is not None and second is not None
    longitude, latitude = (
        (first, second) if axis_value in xy_orders else (second, first)
    )
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        reason = (
            "The declared coordinate pair falls outside valid CRS84 "
            "longitude/latitude ranges."
        )
        return ParsedArtifact(
            semantic_type="document",
            format="JSON coordinate object",
            canonical_media_type="application/json",
            canonical_data=value,
            preview=value,
            warnings=[reason],
            map_unavailable_reason=reason,
            force_partial=True,
            partial_reason=reason,
        )

    excluded = {
        "coordinates",
        "crs",
        "srs",
        "srsName",
        "axisOrder",
        "axis_order",
    }
    properties = {
        key: item for key, item in value.items() if key not in excluded
    }
    feature_collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": properties,
                "geometry": {
                    "type": "Point",
                    "coordinates": [longitude, latitude],
                },
            }
        ],
    }
    return ParsedArtifact(
        semantic_type="vector",
        format="Spatial JSON coordinate object",
        canonical_media_type="application/geo+json",
        canonical_data=feature_collection,
        feature_count=1,
        geometry_types=["Point"],
        bbox=[longitude, latitude, longitude, latitude],
        crs_value="OGC:CRS84",
        crs_status="declared",
        axis_order="xy",
        transformations=[
            "Declared coordinate object converted to a GeoJSON Point feature"
        ],
    )
