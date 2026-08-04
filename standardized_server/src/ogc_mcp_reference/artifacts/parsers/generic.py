"""Adapters for tables, scalars, documents, images, rasters and tiles."""

from __future__ import annotations

import csv
import io
from typing import Any

from ..models import ParsedArtifact
from ..previews import bounded_json_preview
from .spatial_table import explicit_coordinate_artifact, spatial_table_artifact


def _columns(rows: list[Any]) -> list[str]:
    found: list[str] = []
    for row in rows[:1000]:
        if not isinstance(row, dict):
            continue
        for key in row:
            if key not in found:
                found.append(str(key))
    return found[:200]


def _is_timeseries(rows: list[Any]) -> bool:
    time_fields = {"time", "timestamp", "datetime", "date"}
    return bool(rows) and all(
        isinstance(row, dict)
        and any(str(key).casefold() in time_fields for key in row)
        for row in rows[:100]
    )


class GenericParser:
    name = "generic"

    def supports(self, media_type: str, value: Any) -> bool:
        return True

    def parse(self, value: Any, media_type: str) -> ParsedArtifact:
        if media_type == "application/prs.coverage+json" or (
            isinstance(value, dict) and "domain" in value and "ranges" in value
        ):
            return ParsedArtifact(
                semantic_type="coverage",
                format="CoverageJSON",
                canonical_media_type="application/prs.coverage+json",
                canonical_data=value,
                preview=bounded_json_preview(value),
            )
        if media_type == "application/vnd.mapbox.tilejson+json" or (
            isinstance(value, dict) and isinstance(value.get("tiles"), list)
        ):
            return ParsedArtifact(
                semantic_type="tiles",
                format="TileJSON",
                canonical_media_type="application/vnd.mapbox.tilejson+json",
                canonical_data=value,
                bbox=_tilejson_bbox(value),
                preview=bounded_json_preview(value),
            )
        if media_type in {
            "application/vnd.mapbox-vector-tile",
            "application/x-protobuf",
        }:
            return ParsedArtifact(semantic_type="tiles", format="Vector tiles")
        if media_type in {
            "image/tiff",
            "image/geotiff",
            "image/x-geotiff",
            "application/geotiff",
            "application/x-netcdf",
            "application/x-hdf",
        }:
            return ParsedArtifact(semantic_type="raster", format=media_type)
        if media_type.startswith("image/"):
            return ParsedArtifact(semantic_type="image", format=media_type)
        explicit_coordinate = explicit_coordinate_artifact(value)
        if explicit_coordinate is not None:
            return explicit_coordinate
        if media_type == "text/csv":
            text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
            rows = list(csv.DictReader(io.StringIO(text)))
            columns = _columns(rows)
            spatial = spatial_table_artifact(
                rows,
                format_name="CSV",
                columns=columns,
            )
            if spatial is not None:
                return spatial
            return ParsedArtifact(
                semantic_type="table",
                format="CSV",
                canonical_media_type="application/json",
                canonical_data=rows,
                table_rows=len(rows),
                table_columns=columns,
                preview=rows[:100],
            )
        if isinstance(value, list):
            if all(isinstance(row, dict) for row in value):
                semantic_type = "timeseries" if _is_timeseries(value) else "table"
                columns = _columns(value)
                spatial = spatial_table_artifact(
                    value,
                    format_name="JSON table",
                    columns=columns,
                    fallback_semantic_type=semantic_type,
                )
                if spatial is not None:
                    return spatial
                return ParsedArtifact(
                    semantic_type=semantic_type,
                    format="JSON table",
                    canonical_media_type="application/json",
                    canonical_data=value,
                    table_rows=len(value),
                    table_columns=columns,
                    preview=value[:100],
                )
            return ParsedArtifact(
                semantic_type="table",
                format="JSON array",
                canonical_media_type="application/json",
                canonical_data=value,
                table_rows=len(value),
                preview=value[:100],
            )
        if isinstance(value, (str, int, float, bool)) or value is None:
            if isinstance(value, (int, float, bool)) or value is None:
                return ParsedArtifact(
                    semantic_type="scalar",
                    format="JSON scalar",
                    canonical_media_type="application/json",
                    canonical_data=value,
                    preview=value,
                )
            if media_type in {"text/plain", "text/html", "application/xml", "text/xml"}:
                return ParsedArtifact(
                    semantic_type="document",
                    format=media_type,
                    canonical_media_type="text/plain",
                    preview=value[:20_000],
                )
        if isinstance(value, dict):
            rows = value.get("rows")
            if isinstance(rows, list) and all(
                isinstance(row, dict) for row in rows
            ):
                semantic_type = "timeseries" if _is_timeseries(rows) else "table"
                columns = _columns(rows)
                declared_crs = (
                    value.get("crs")
                    or value.get("srs")
                    or value.get("srsName")
                )
                spatial = spatial_table_artifact(
                    rows,
                    format_name="JSON table",
                    columns=columns,
                    declared_crs=declared_crs,
                    fallback_semantic_type=semantic_type,
                )
                if spatial is not None:
                    return spatial
                return ParsedArtifact(
                    semantic_type=semantic_type,
                    format="JSON table",
                    canonical_media_type="application/json",
                    canonical_data=rows,
                    table_rows=len(rows),
                    table_columns=columns,
                    preview=rows[:100],
                )
            # A one-key primitive object is best presented as a metric; larger
            # objects remain documents so their field relationships are kept.
            if len(value) == 1 and isinstance(
                next(iter(value.values())), (str, int, float, bool, type(None))
            ):
                return ParsedArtifact(
                    semantic_type="scalar",
                    format="JSON scalar object",
                    canonical_media_type="application/json",
                    canonical_data=value,
                    preview=value,
                )
            return ParsedArtifact(
                semantic_type="document",
                format="JSON document",
                canonical_media_type="application/json",
                canonical_data=value,
                preview=bounded_json_preview(value),
            )
        return ParsedArtifact(semantic_type="binary", format=media_type or "binary")


def _tilejson_bbox(value: Any) -> list[float]:
    bounds = value.get("bounds") if isinstance(value, dict) else None
    if (
        isinstance(bounds, list)
        and len(bounds) == 4
        and all(isinstance(item, (int, float)) for item in bounds)
    ):
        return [float(item) for item in bounds]
    return []
