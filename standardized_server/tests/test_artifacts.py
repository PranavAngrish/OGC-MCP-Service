from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from ogc_mcp_reference.artifacts import ArtifactStore, OutputArtifactPipeline
from ogc_mcp_reference.artifacts.previews import MAX_PREVIEW_BYTES
from ogc_mcp_reference.errors import TransportError
from ogc_mcp_reference.models import OgcResponse
from ogc_mcp_reference.modules.processes import ProcessesService
from ogc_mcp_reference.services.store import InMemoryStore
from ogc_mcp_reference.transport import OgcHttpClient, OutputResolutionBudget
from helpers import build_registry


COMPACT_GML = """<?xml version="1.0" encoding="utf-8"?>
<ogr:FeatureCollection xmlns:ogr="http://ogr.maptools.org/"
 xmlns:gml="http://www.opengis.net/gml">
 <gml:featureMember>
  <ogr:Result fid="Result.0">
   <ogr:geometryProperty>
    <gml:Polygon srsName="EPSG:4326">
     <gml:outerBoundaryIs><gml:LinearRing>
      <gml:coordinates>-99.7,49.9 -95.7,49.9 -95.7,54.8 -99.7,54.8</gml:coordinates>
     </gml:LinearRing></gml:outerBoundaryIs>
    </gml:Polygon>
   </ogr:geometryProperty>
   <ogr:id>1</ogr:id>
   <ogr:name>Lake Winnipeg</ogr:name>
  </ogr:Result>
 </gml:featureMember>
</ogr:FeatureCollection>"""


def _response(
    data,
    *,
    content_type: str = "application/json",
    status: int = 200,
    location: str = "",
    path: str = "/jobs/42/results",
) -> OgcResponse:
    body = (
        json.dumps(data).encode("utf-8")
        if "json" in content_type and not isinstance(data, bytes)
        else data.encode("utf-8")
        if isinstance(data, str)
        else data
        if isinstance(data, bytes)
        else b""
    )
    headers = {"location": location} if location else {}
    return OgcResponse(
        server_id="test",
        method="GET",
        path=path,
        status_code=status,
        headers=headers,
        content_type=content_type,
        data=data,
        body=body,
    )


def _pipeline(registry, handler=None):
    client = OgcHttpClient(
        transport=httpx.MockTransport(handler)
        if handler is not None
        else httpx.MockTransport(lambda _: httpx.Response(500))
    )
    store = ArtifactStore(store=InMemoryStore())
    return OutputArtifactPipeline(client=client, store=store), store


def _assert_manifest_schema(test_case: unittest.TestCase, manifest: dict) -> None:
    try:
        import jsonschema
    except ImportError:
        return
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "spec"
        / "ogc-output-manifest.schema.json"
    )
    jsonschema.Draft7Validator(
        json.loads(schema_path.read_text(encoding="utf-8"))
    ).validate(manifest)
    test_case.assertLessEqual(len(manifest["outputs"]), 100)


def _assert_clarification_schema(request: dict) -> None:
    try:
        import jsonschema
    except ImportError:
        return
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "spec"
        / "ogc-clarification-request.schema.json"
    )
    jsonschema.Draft7Validator(
        json.loads(schema_path.read_text(encoding="utf-8"))
    ).validate(request)


class ArtifactInterpretationTests(unittest.TestCase):
    def test_geolabs_json_wrapper_with_nested_gml_becomes_canonical_geojson(self) -> None:
        registry = build_registry()
        pipeline, store = _pipeline(registry)
        upstream = {
            "Result": {
                "value": COMPACT_GML,
                "format": {"mediaType": "text/xml", "encoding": "utf-8"},
            }
        }

        manifest = pipeline.build(
            _response(upstream),
            server=registry.get(service="processes"),
            operation="jobs.get_results",
            job_id="42",
        )

        self.assertEqual(manifest["schemaVersion"], "ogc-output-manifest/1")
        self.assertEqual(manifest["overallState"], "ready")
        self.assertEqual(manifest["execution"]["state"], "succeeded")
        self.assertEqual(manifest["execution"]["jobId"], "42")
        self.assertEqual(len(manifest["outputs"]), 1)
        output = manifest["outputs"][0]
        self.assertEqual(output["id"], "Result")
        self.assertEqual(output["retrieval"]["declaredMediaType"], "text/xml")
        self.assertEqual(output["retrieval"]["detectedMediaType"], "application/gml+xml")
        self.assertEqual(output["interpretation"]["semanticType"], "vector")
        self.assertEqual(output["interpretation"]["featureCount"], 1)
        self.assertEqual(output["interpretation"]["geometryTypes"], ["Polygon"])
        self.assertEqual(output["interpretation"]["bbox"], [-99.7, 49.9, -95.7, 54.8])
        self.assertEqual(output["interpretation"]["crs"]["value"], "OGC:CRS84")
        map_presentation = next(
            item for item in output["presentations"] if item["kind"] == "map"
        )
        self.assertEqual(map_presentation["state"], "ready")
        canonical = next(
            item for item in output["representations"] if item["role"] == "canonical"
        )
        self.assertEqual(canonical["mediaType"], "application/geo+json")
        self.assertNotIn("data", canonical)
        stored = store.retrieve(canonical["handle"])
        self.assertIsNotNone(stored)
        polygon = stored["data"]["features"][0]["geometry"]["coordinates"][0]
        self.assertEqual(polygon[0], polygon[-1], "Open GML polygon ring must be closed")

        _assert_manifest_schema(self, manifest)

    def test_multiple_outputs_get_independent_semantics_and_presentations(self) -> None:
        registry = build_registry()
        pipeline, _ = _pipeline(registry)
        data = {
            "outputs": {
                "points": {
                    "value": {
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "properties": {"name": "A"},
                                "geometry": {"type": "Point", "coordinates": [7, 52]},
                            }
                        ],
                    },
                    "format": {"mediaType": "application/geo+json"},
                },
                "count": {"value": 1, "unit": "features"},
                "rows": {
                    "value": [{"name": "A", "score": 3}, {"name": "B", "score": 4}],
                    "format": {"mediaType": "application/json"},
                },
                "minimum": 2,
                "maximum": 9,
            }
        }

        manifest = pipeline.build(
            _response(data),
            server=registry.get(service="processes"),
            operation="processes.execute",
            process_id="Example",
        )

        by_id = {item["id"]: item for item in manifest["outputs"]}
        self.assertEqual(
            set(by_id),
            {"points", "count", "rows", "minimum", "maximum"},
        )
        self.assertEqual(by_id["points"]["interpretation"]["semanticType"], "vector")
        self.assertEqual(by_id["count"]["interpretation"]["semanticType"], "scalar")
        self.assertEqual(
            by_id["count"]["interpretation"]["units"],
            [{"value": "features", "status": "declared"}],
        )
        self.assertEqual(by_id["rows"]["interpretation"]["semanticType"], "table")
        self.assertEqual(by_id["rows"]["interpretation"]["rowCount"], 2)
        self.assertEqual(by_id["minimum"]["interpretation"]["semanticType"], "scalar")

    def test_gml_missing_mixed_unsupported_or_invalid_crs_is_never_map_ready(
        self,
    ) -> None:
        registry = build_registry()
        pipeline, _ = _pipeline(registry)
        cases = {
            "missing": """
                <gml:Point xmlns:gml="http://www.opengis.net/gml">
                  <gml:coordinates>7,52</gml:coordinates>
                </gml:Point>
            """,
            "unsupported": """
                <gml:Point xmlns:gml="http://www.opengis.net/gml"
                           srsName="EPSG:3857">
                  <gml:coordinates>779236,6800125</gml:coordinates>
                </gml:Point>
            """,
            "invalid-crs84-coordinate": """
                <gml:Point xmlns:gml="http://www.opengis.net/gml"
                           srsName="EPSG:4326">
                  <gml:coordinates>700,520</gml:coordinates>
                </gml:Point>
            """,
            "mixed": """
                <ogr:FeatureCollection xmlns:ogr="http://ogr.maptools.org/"
                                       xmlns:gml="http://www.opengis.net/gml">
                  <gml:featureMember>
                    <ogr:Result><ogr:geometry>
                      <gml:Point srsName="EPSG:4326">
                        <gml:coordinates>7,52</gml:coordinates>
                      </gml:Point>
                    </ogr:geometry></ogr:Result>
                  </gml:featureMember>
                  <gml:featureMember>
                    <ogr:Result><ogr:geometry>
                      <gml:Point srsName="EPSG:3857">
                        <gml:coordinates>779236,6800125</gml:coordinates>
                      </gml:Point>
                    </ogr:geometry></ogr:Result>
                  </gml:featureMember>
                </ogr:FeatureCollection>
            """,
            "mixed-geometry-collection": """
                <gml:MultiGeometry xmlns:gml="http://www.opengis.net/gml"
                                   srsName="EPSG:4326">
                  <gml:geometryMember>
                    <gml:Point>
                      <gml:coordinates>7,52</gml:coordinates>
                    </gml:Point>
                  </gml:geometryMember>
                  <gml:geometryMember>
                    <gml:Point srsName="EPSG:3857">
                      <gml:coordinates>779236,6800125</gml:coordinates>
                    </gml:Point>
                  </gml:geometryMember>
                </gml:MultiGeometry>
            """,
        }

        for name, gml in cases.items():
            with self.subTest(name):
                manifest = pipeline.build(
                    _response(gml, content_type="application/gml+xml"),
                    server=registry.get(service="processes"),
                    operation="jobs.get_results",
                )
                output = manifest["outputs"][0]
                map_presentation = next(
                    item
                    for item in output["presentations"]
                    if item["kind"] == "map"
                )
                download = next(
                    item
                    for item in output["presentations"]
                    if item["kind"] == "download"
                )
                self.assertEqual(map_presentation["state"], "unavailable")
                self.assertEqual(download["state"], "ready")
                self.assertNotEqual(output["status"], "ready")
                self.assertTrue(output.get("warnings"))
                _assert_manifest_schema(self, manifest)

    def test_gml_skipped_members_are_explicit_and_disable_mapping(self) -> None:
        registry = build_registry()
        pipeline, _ = _pipeline(registry)
        gml = """
            <ogr:FeatureCollection xmlns:ogr="http://ogr.maptools.org/"
                                   xmlns:gml="http://www.opengis.net/gml">
              <gml:featureMember>
                <ogr:Result><ogr:geometry>
                  <gml:Point srsName="EPSG:4326">
                    <gml:coordinates>7,52</gml:coordinates>
                  </gml:Point>
                </ogr:geometry></ogr:Result>
              </gml:featureMember>
              <gml:featureMember>
                <ogr:Result><ogr:name>Missing geometry</ogr:name></ogr:Result>
              </gml:featureMember>
            </ogr:FeatureCollection>
        """
        manifest = pipeline.build(
            _response(gml, content_type="application/gml+xml"),
            server=registry.get(service="processes"),
            operation="jobs.get_results",
        )
        output = manifest["outputs"][0]
        map_presentation = next(
            item for item in output["presentations"] if item["kind"] == "map"
        )
        table_presentation = next(
            item for item in output["presentations"] if item["kind"] == "table"
        )
        self.assertEqual(map_presentation["state"], "unavailable")
        self.assertIn("partially interpreted", map_presentation["reason"])
        self.assertEqual(table_presentation["state"], "partial")
        self.assertEqual(output["status"], "partial")
        self.assertTrue(
            any("Skipped 1 GML member" in warning for warning in output["warnings"])
        )
        self.assertTrue(
            any(
                item["kind"] == "download" and item["state"] == "ready"
                for item in output["presentations"]
            )
        )
        _assert_manifest_schema(self, manifest)

    def test_consistent_valid_epsg4326_gml_normalizes_axis_and_crs84(self) -> None:
        registry = build_registry()
        pipeline, store = _pipeline(registry)
        gml = """
            <gml:Point xmlns:gml="http://www.opengis.net/gml"
                       srsName="urn:ogc:def:crs:EPSG::4326">
              <gml:pos>52 7</gml:pos>
            </gml:Point>
        """
        manifest = pipeline.build(
            _response(gml, content_type="application/gml+xml"),
            server=registry.get(service="processes"),
            operation="jobs.get_results",
        )
        output = manifest["outputs"][0]
        self.assertEqual(
            output["interpretation"]["crs"],
            {
                "status": "declared",
                "value": "OGC:CRS84",
                "axisOrder": "yx-normalized-to-xy",
            },
        )
        map_presentation = next(
            item for item in output["presentations"] if item["kind"] == "map"
        )
        self.assertEqual(map_presentation["state"], "ready")
        canonical = next(
            item
            for item in output["representations"]
            if item["role"] == "canonical"
        )
        coordinates = store.retrieve(canonical["handle"])["data"]["features"][0][
            "geometry"
        ]["coordinates"]
        self.assertEqual(coordinates, [7.0, 52.0])
        _assert_manifest_schema(self, manifest)

    def test_spatial_json_and_csv_tables_get_geojson_map_and_table_previews(
        self,
    ) -> None:
        registry = build_registry()
        pipeline, store = _pipeline(registry)
        cases = [
            (
                _response(
                    {
                        "outputs": {
                            "locations": {
                                "value": [
                                    {
                                        "name": "A",
                                        "longitude": 7.1,
                                        "latitude": 52.1,
                                    },
                                    {
                                        "name": "B",
                                        "longitude": "8.2",
                                        "latitude": "53.2",
                                    },
                                ],
                                "mediaType": "application/json",
                            }
                        }
                    }
                ),
                "locations",
            ),
            (
                _response(
                    "name,lon,lat\nA,7.1,52.1\nB,8.2,53.2\n",
                    content_type="text/csv",
                ),
                "result",
            ),
        ]

        for response, expected_id in cases:
            with self.subTest(expected_id):
                manifest = pipeline.build(
                    response,
                    server=registry.get(service="processes"),
                    operation="jobs.get_results",
                )
                output = manifest["outputs"][0]
                self.assertEqual(output["id"], expected_id)
                self.assertEqual(
                    output["interpretation"]["semanticType"],
                    "vector",
                )
                self.assertEqual(output["interpretation"]["featureCount"], 2)
                self.assertEqual(
                    output["interpretation"]["crs"]["value"],
                    "OGC:CRS84",
                )
                presentations = {
                    item["kind"]: item for item in output["presentations"]
                }
                self.assertEqual(presentations["map"]["state"], "ready")
                self.assertEqual(presentations["table"]["state"], "ready")
                preview = next(
                    item
                    for item in output["representations"]
                    if item["role"] == "preview"
                )
                canonical = next(
                    item
                    for item in output["representations"]
                    if item["role"] == "canonical"
                )
                self.assertEqual(
                    presentations["map"]["artifactRef"],
                    preview["handle"],
                )
                self.assertEqual(
                    presentations["table"]["artifactRef"],
                    preview["handle"],
                )
                self.assertNotEqual(preview["handle"], canonical["handle"])
                stored = store.retrieve(canonical["handle"])["data"]
                self.assertEqual(stored["type"], "FeatureCollection")
                self.assertEqual(
                    stored["features"][0]["geometry"]["coordinates"],
                    [7.1, 52.1],
                )
                _assert_manifest_schema(self, manifest)

    def test_spatial_table_declared_crs_and_invalid_rows_are_truthful(self) -> None:
        registry = build_registry()
        pipeline, _ = _pipeline(registry)
        manifest = pipeline.build(
            _response(
                {
                    "outputs": {
                        "locations": {
                            "value": {
                                "crs": "EPSG:4326",
                                "rows": [
                                    {"name": "valid", "lon": 7, "lat": 52},
                                    {"name": "invalid", "lon": 700, "lat": 520},
                                ],
                            },
                            "mediaType": "application/json",
                        }
                    }
                }
            ),
            server=registry.get(service="processes"),
            operation="jobs.get_results",
        )
        output = manifest["outputs"][0]
        self.assertEqual(output["interpretation"]["semanticType"], "vector")
        self.assertEqual(output["interpretation"]["featureCount"], 1)
        self.assertEqual(
            output["interpretation"]["crs"],
            {"status": "declared", "value": "OGC:CRS84", "axisOrder": "xy"},
        )
        self.assertEqual(output["status"], "partial")
        presentations = {item["kind"]: item for item in output["presentations"]}
        self.assertEqual(presentations["map"]["state"], "partial")
        self.assertEqual(presentations["table"]["state"], "partial")
        self.assertTrue(
            any("1 row(s) were omitted" in warning for warning in output["warnings"])
        )
        _assert_manifest_schema(self, manifest)

    def test_ambiguous_xy_or_unsupported_table_crs_never_guesses_a_map(
        self,
    ) -> None:
        registry = build_registry()
        pipeline, _ = _pipeline(registry)
        cases = {
            "xy": [
                {"name": "A", "x": 7, "y": 52},
                {"name": "B", "x": 8, "y": 53},
            ],
            "unsupported-crs": {
                "crs": "EPSG:3857",
                "rows": [
                    {"name": "A", "longitude": 779236, "latitude": 6800125}
                ],
            },
        }
        for output_id, value in cases.items():
            with self.subTest(output_id):
                manifest = pipeline.build(
                    _response(
                        {
                            "outputs": {
                                output_id: {
                                    "value": value,
                                    "mediaType": "application/json",
                                }
                            }
                        }
                    ),
                    server=registry.get(service="processes"),
                    operation="jobs.get_results",
                )
                output = manifest["outputs"][0]
                self.assertIn(
                    output["interpretation"]["semanticType"],
                    {"table", "timeseries"},
                )
                self.assertEqual(
                    output["interpretation"]["state"],
                    "ambiguous",
                )
                presentations = {
                    item["kind"]: item for item in output["presentations"]
                }
                self.assertEqual(presentations["table"]["state"], "ready")
                self.assertEqual(presentations["map"]["state"], "unavailable")
                self.assertNotIn("artifactRef", presentations["map"])
                self.assertTrue(output.get("warnings"))
                clarification = output["clarificationRequest"]
                self.assertFalse(clarification["blocking"])
                self.assertEqual(clarification["scope"], "interpretation")
                _assert_clarification_schema(clarification)
                _assert_manifest_schema(self, manifest)

    def test_explicit_coordinate_shapes_require_unambiguous_order_and_crs(
        self,
    ) -> None:
        registry = build_registry()
        pipeline, store = _pipeline(registry)
        cases = {
            "named": {
                "value": {"name": "A", "longitude": 7, "latitude": 52},
                "maps": True,
                "coordinates": [7.0, 52.0],
            },
            "declared-array": {
                "value": {
                    "name": "B",
                    "coordinates": [52, 7],
                    "crs": "EPSG:4326",
                    "axisOrder": "yx",
                },
                "maps": True,
                "coordinates": [7.0, 52.0],
            },
            "naked-array": {
                "value": [7, 52],
                "maps": False,
            },
            "undeclared-object": {
                "value": {"coordinates": [7, 52]},
                "maps": False,
            },
        }
        for output_id, case in cases.items():
            with self.subTest(output_id):
                manifest = pipeline.build(
                    _response(
                        {
                            "outputs": {
                                output_id: {
                                    "value": case["value"],
                                    "mediaType": "application/json",
                                }
                            }
                        }
                    ),
                    server=registry.get(service="processes"),
                    operation="jobs.get_results",
                )
                output = manifest["outputs"][0]
                presentations = {
                    item["kind"]: item for item in output["presentations"]
                }
                if case["maps"]:
                    self.assertEqual(
                        output["interpretation"]["semanticType"],
                        "vector",
                    )
                    self.assertEqual(presentations["map"]["state"], "ready")
                    canonical = next(
                        item
                        for item in output["representations"]
                        if item["role"] == "canonical"
                    )
                    coordinates = store.retrieve(canonical["handle"])["data"][
                        "features"
                    ][0]["geometry"]["coordinates"]
                    self.assertEqual(coordinates, case["coordinates"])
                else:
                    self.assertEqual(presentations["map"]["state"], "unavailable")
                    self.assertNotIn("artifactRef", presentations["map"])
                    self.assertEqual(
                        output["interpretation"]["state"],
                        "ambiguous",
                    )
                    _assert_clarification_schema(output["clarificationRequest"])
                _assert_manifest_schema(self, manifest)

    def test_wkt_coverage_tiles_raster_and_unknown_are_identified(self) -> None:
        registry = build_registry()
        pipeline, _ = _pipeline(registry)
        cases = [
            ("wkt", "SRID=4326;POINT (7 52)", "text/wkt", "vector"),
            (
                "coverage",
                {"type": "Coverage", "domain": {}, "ranges": {}},
                "application/prs.coverage+json",
                "coverage",
            ),
            (
                "tiles",
                {"tilejson": "3.0.0", "tiles": ["https://tiles.example/{z}/{x}/{y}.pbf"]},
                "application/vnd.mapbox.tilejson+json",
                "tiles",
            ),
            ("raster", b"II*\x00fake", "image/tiff", "raster"),
            ("binary", b"\x00\x01\x02", "application/octet-stream", "binary"),
        ]
        for output_id, value, media_type, expected in cases:
            with self.subTest(output_id):
                response = (
                    _response(value, content_type=media_type)
                    if isinstance(value, bytes)
                    else _response(
                        {"outputs": {output_id: {"value": value, "mediaType": media_type}}}
                    )
                )
                manifest = pipeline.build(
                    response,
                    server=registry.get(service="processes"),
                    operation="jobs.get_results",
                )
                self.assertEqual(
                    manifest["outputs"][0]["interpretation"]["semanticType"],
                    expected,
                )
        self.assertEqual(manifest["overallState"], "partial")

    def test_crsless_wkt_requires_presentation_clarification(self) -> None:
        registry = build_registry()
        pipeline, _ = _pipeline(registry)
        manifest = pipeline.build(
            _response("POINT (78.1 30.2)", content_type="text/wkt"),
            server=registry.get(service="processes"),
            operation="jobs.get_results",
        )
        output = manifest["outputs"][0]
        self.assertEqual(output["interpretation"]["crs"]["status"], "missing")
        self.assertEqual(output["interpretation"]["state"], "ambiguous")
        map_presentation = next(
            item for item in output["presentations"] if item["kind"] == "map"
        )
        download = next(
            item for item in output["presentations"] if item["kind"] == "download"
        )
        self.assertEqual(map_presentation["state"], "unavailable")
        self.assertNotIn("artifactRef", map_presentation)
        self.assertEqual(download["state"], "ready")
        clarification = output["clarificationRequest"]
        self.assertTrue(clarification["blocking"])
        self.assertEqual(clarification["scope"], "presentation")
        self.assertEqual(clarification["issues"][0]["kind"], "crs")
        _assert_clarification_schema(clarification)
        _assert_manifest_schema(self, manifest)

        declared = pipeline.build(
            _response(
                "SRID=4326;POINT (78.1 30.2)",
                content_type="text/wkt",
            ),
            server=registry.get(service="processes"),
            operation="jobs.get_results",
        )
        declared_map = next(
            item
            for item in declared["outputs"][0]["presentations"]
            if item["kind"] == "map"
        )
        self.assertEqual(declared_map["state"], "ready")
        self.assertNotIn("clarificationRequest", declared["outputs"][0])
        _assert_manifest_schema(self, declared)

    def test_malicious_gml_is_retrieved_but_not_parsed(self) -> None:
        registry = build_registry()
        pipeline, _ = _pipeline(registry)
        malicious = """<!DOCTYPE x [<!ENTITY leak SYSTEM "file:///etc/passwd">]>
<gml:Point xmlns:gml="http://www.opengis.net/gml"><gml:coordinates>&leak;</gml:coordinates></gml:Point>"""
        data = {
            "Result": {
                "value": malicious,
                "format": {"mediaType": "application/gml+xml"},
            }
        }

        manifest = pipeline.build(
            _response(data),
            server=registry.get(service="processes"),
            operation="jobs.get_results",
        )
        output = manifest["outputs"][0]
        self.assertEqual(output["retrieval"]["state"], "retrieved")
        self.assertEqual(output["interpretation"]["state"], "failed")
        self.assertEqual(output["status"], "failed")
        self.assertEqual(manifest["overallState"], "partial")
        self.assertIn("DTD", output["interpretation"]["error"]["message"])
        self.assertTrue(
            any(item["kind"] == "download" and item["state"] == "ready"
                for item in output["presentations"])
        )

    def test_async_submission_is_pending_not_a_fake_output(self) -> None:
        registry = build_registry()
        pipeline, _ = _pipeline(registry)
        manifest = pipeline.build(
            _response(
                {"jobID": "abc", "status": "accepted"},
                status=201,
                location="/jobs/abc",
                path="/processes/Example/execution",
            ),
            server=registry.get(service="processes"),
            operation="processes.execute",
            process_id="Example",
        )
        self.assertEqual(manifest["execution"]["state"], "submitted")
        self.assertEqual(manifest["overallState"], "pending")
        self.assertEqual(manifest["outputs"], [])

    def test_async_submission_without_tracking_handle_is_terminally_unavailable(
        self,
    ) -> None:
        registry = build_registry()
        pipeline, _ = _pipeline(registry)
        manifest = pipeline.build(
            _response(
                {"status": "accepted"},
                status=202,
                path="/processes/Example/execution",
            ),
            server=registry.get(service="processes"),
            operation="processes.execute",
            process_id="Example",
        )
        self.assertEqual(manifest["execution"]["state"], "submitted")
        self.assertEqual(
            manifest["execution"]["trackingState"],
            "unavailable",
        )
        self.assertEqual(
            manifest["execution"]["trackingError"]["code"],
            "async_job_untrackable",
        )
        self.assertEqual(manifest["overallState"], "unavailable")
        self.assertEqual(manifest["outputs"], [])
        self.assertTrue(manifest["warnings"])
        _assert_manifest_schema(self, manifest)

    def test_invalid_or_non_crs84_geojson_never_claims_map_readiness(self) -> None:
        registry = build_registry()
        pipeline, _ = _pipeline(registry)
        cases = {
            "projected": {
                "type": "FeatureCollection",
                "crs": {
                    "type": "name",
                    "properties": {"name": "EPSG:3857"},
                },
                "features": [
                    {
                        "type": "Feature",
                        "properties": {},
                        "geometry": {"type": "Point", "coordinates": [10, 10]},
                    }
                ],
            },
            "invalid-coordinate": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {},
                        "geometry": {
                            "type": "Point",
                            "coordinates": [7, "not-a-latitude"],
                        },
                    }
                ],
            },
            "invalid-ring": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[0, 0], [1, 0], [1, 1]]],
                        },
                    }
                ],
            },
            "null-geometry": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"name": "not drawable"},
                        "geometry": None,
                    }
                ],
            },
        }

        for output_id, value in cases.items():
            with self.subTest(output_id):
                manifest = pipeline.build(
                    _response(
                        {
                            "outputs": {
                                output_id: {
                                    "value": value,
                                    "mediaType": "application/geo+json",
                                }
                            }
                        }
                    ),
                    server=registry.get(service="processes"),
                    operation="jobs.get_results",
                )
                output = manifest["outputs"][0]
                map_presentation = next(
                    item
                    for item in output["presentations"]
                    if item["kind"] == "map"
                )
                self.assertEqual(map_presentation["state"], "unavailable")
                self.assertNotEqual(output["status"], "ready")
                _assert_manifest_schema(self, manifest)

    def test_large_table_and_vector_use_separate_bounded_previews(self) -> None:
        registry = build_registry()
        pipeline, store = _pipeline(registry)
        rows = [
            {"index": index, "payload": f"row-{index}-" + ("x" * 4_000)}
            for index in range(400)
        ]
        features = [
            {
                "type": "Feature",
                "id": index,
                "properties": {
                    "index": index,
                    "payload": f"feature-{index}-" + ("y" * 2_000),
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(index % 170), float(index % 80)],
                },
            }
            for index in range(300)
        ]
        manifest = pipeline.build(
            _response(
                {
                    "outputs": {
                        "large-table": {
                            "value": rows,
                            "mediaType": "application/json",
                        },
                        "large-vector": {
                            "value": {
                                "type": "FeatureCollection",
                                "features": features,
                            },
                            "mediaType": "application/geo+json",
                        },
                    }
                }
            ),
            server=registry.get(service="processes"),
            operation="jobs.get_results",
        )

        for output in manifest["outputs"]:
            by_role = {
                representation["role"]: representation
                for representation in output["representations"]
            }
            self.assertIn("canonical", by_role)
            self.assertIn("preview", by_role)
            self.assertNotEqual(
                by_role["canonical"]["handle"],
                by_role["preview"]["handle"],
            )
            self.assertGreater(
                by_role["canonical"]["sizeBytes"],
                by_role["preview"]["sizeBytes"],
            )
            self.assertLessEqual(
                by_role["preview"]["sizeBytes"],
                MAX_PREVIEW_BYTES,
            )
            self.assertTrue(by_role["preview"]["truncated"])
            self.assertTrue(
                any("truncated" in warning.casefold() for warning in output["warnings"])
            )
            self.assertTrue(
                any(
                    "preview truncated" in transformation.casefold()
                    for transformation in output["provenance"]["transformations"]
                )
            )
            preview_record = store.retrieve(by_role["preview"]["handle"])
            self.assertIsNotNone(preview_record)
            renderer_presentations = [
                item
                for item in output["presentations"]
                if item["kind"] != "download" and item["state"] in {"ready", "partial"}
            ]
            self.assertTrue(renderer_presentations)
            self.assertTrue(
                all(
                    item["artifactRef"] == by_role["preview"]["handle"]
                    for item in renderer_presentations
                )
            )

        table_output = manifest["outputs"][0]
        table_preview = store.retrieve(
            next(
                item["handle"]
                for item in table_output["representations"]
                if item["role"] == "preview"
            )
        )
        self.assertIsInstance(table_preview["data"], list)
        self.assertLess(len(table_preview["data"]), len(rows))
        self.assertTrue(all(set(row) == {"index", "payload"} for row in table_preview["data"]))

        vector_output = manifest["outputs"][1]
        vector_preview = store.retrieve(
            next(
                item["handle"]
                for item in vector_output["representations"]
                if item["role"] == "preview"
            )
        )
        preview_features = vector_preview["data"]["features"]
        self.assertLess(len(preview_features), len(features))
        self.assertGreater(len(preview_features), 0)
        self.assertTrue(
            all(feature in features for feature in preview_features),
            "The preview must retain whole features instead of slicing JSON.",
        )
        _assert_manifest_schema(self, manifest)

    def test_oversized_individual_rows_do_not_create_a_false_ready_table(self) -> None:
        registry = build_registry()
        pipeline, store = _pipeline(registry)
        rows = [
            {"id": 1, "payload": "x" * (MAX_PREVIEW_BYTES + 1_000)},
            {"id": 2, "payload": "y" * (MAX_PREVIEW_BYTES + 1_000)},
        ]
        manifest = pipeline.build(
            _response(
                {
                    "outputs": {
                        "oversized-rows": {
                            "value": rows,
                            "mediaType": "application/json",
                        }
                    }
                }
            ),
            server=registry.get(service="processes"),
            operation="jobs.get_results",
        )
        output = manifest["outputs"][0]
        preview = next(
            item for item in output["representations"] if item["role"] == "preview"
        )
        self.assertEqual(store.retrieve(preview["handle"])["data"], [])
        table = next(
            item for item in output["presentations"] if item["kind"] == "table"
        )
        self.assertEqual(table["state"], "unavailable")
        self.assertNotIn("artifactRef", table)
        self.assertEqual(output["status"], "partial")
        _assert_manifest_schema(self, manifest)

    def test_max_outputs_is_schema_compatible_and_truncates_at_one_hundred(self) -> None:
        registry = build_registry(output_resolution={"max_outputs": 100})
        pipeline, _ = _pipeline(registry)
        manifest = pipeline.build(
            _response(
                {
                    "outputs": {
                        f"output-{index}": {"value": index}
                        for index in range(101)
                    }
                }
            ),
            server=registry.get(service="processes"),
            operation="jobs.get_results",
        )
        self.assertEqual(len(manifest["outputs"]), 100)
        _assert_manifest_schema(self, manifest)

    def test_long_output_ids_and_units_are_bounded_and_schema_valid(self) -> None:
        registry = build_registry()
        pipeline, _ = _pipeline(registry)
        shared_prefix = "output-" + ("x" * 500)
        manifest = pipeline.build(
            _response(
                {
                    "outputs": {
                        f"{shared_prefix}-one": {
                            "value": 1,
                            "units": [f"unit-{index}-" + ("u" * 300) for index in range(101)],
                        },
                        f"{shared_prefix}-two": {"value": 2},
                    }
                }
            ),
            server=registry.get(service="processes"),
            operation="jobs.get_results",
        )
        self.assertEqual(len(manifest["outputs"]), 2)
        self.assertEqual(
            len({output["id"] for output in manifest["outputs"]}),
            2,
        )
        for output in manifest["outputs"]:
            self.assertLessEqual(len(output["id"]), 280)
            self.assertTrue(
                all(
                    len(item["id"]) <= 300
                    for item in [
                        *output["representations"],
                        *output["presentations"],
                    ]
                )
            )
        units = manifest["outputs"][0]["interpretation"]["units"]
        self.assertEqual(len(units), 100)
        self.assertTrue(all(len(unit["value"]) <= 200 for unit in units))
        _assert_manifest_schema(self, manifest)


class OutputReferenceSecurityTests(unittest.TestCase):
    def test_job_result_redirect_resolves_same_origin_json_then_nested_gml(self) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            if request.url.path == "/jobs/42/results":
                return httpx.Response(
                    302,
                    headers={"Location": "https://ogc.example.test/temp/result.json"},
                    text="<html>Moved</html>",
                )
            if request.url.path == "/temp/result.json":
                return httpx.Response(
                    200,
                    json={
                        "Result": {
                            "value": COMPACT_GML,
                            "format": {"mediaType": "text/xml"},
                        }
                    },
                )
            return httpx.Response(404)

        registry = build_registry()
        service = ProcessesService(
            registry,
            OgcHttpClient(transport=httpx.MockTransport(handler)),
        )
        result = service.get_job_results("42")

        self.assertTrue(result["ok"])
        self.assertEqual(result["response"]["status_code"], 302)
        self.assertEqual(result["data"], "<html>Moved</html>")
        output = result["output_manifest"]["outputs"][0]
        self.assertEqual(output["status"], "ready")
        self.assertEqual(output["retrieval"]["source"], "reference")
        self.assertEqual(output["retrieval"]["redirectCount"], 1)
        self.assertEqual(len(calls), 2)

    def test_cross_origin_reference_is_blocked_without_allowlist(self) -> None:
        registry = build_registry()
        pipeline, _ = _pipeline(registry)
        manifest = pipeline.build(
            _response(
                "<html>Moved</html>",
                content_type="text/html",
                status=302,
                location="https://outputs.example/result.json",
            ),
            server=registry.get(service="processes"),
            operation="jobs.get_results",
        )
        output = manifest["outputs"][0]
        self.assertEqual(output["retrieval"]["state"], "blocked")
        self.assertEqual(output["status"], "blocked")
        self.assertEqual(manifest["overallState"], "unavailable")

    def test_allowlisted_cross_origin_does_not_receive_server_credentials(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.host, "outputs.example")
            self.assertNotIn("authorization", request.headers)
            return httpx.Response(200, json={"Result": {"value": 7}})

        registry = build_registry(
            auth={"type": "bearer_env", "token_env": "TEST_OUTPUT_TOKEN"},
            output_resolution={"allowed_hosts": ["outputs.example"]},
        )
        pipeline, _ = _pipeline(registry, handler)
        with patch.dict(os.environ, {"TEST_OUTPUT_TOKEN": "secret"}):
            manifest = pipeline.build(
                _response(
                    "<html>Moved</html>",
                    content_type="text/html",
                    status=302,
                    location="https://outputs.example/result.json",
                ),
                server=registry.get(service="processes"),
                operation="jobs.get_results",
            )
        self.assertEqual(manifest["outputs"][0]["status"], "ready")

    def test_redirect_to_private_literal_and_metadata_hostname_are_blocked(self) -> None:
        for destination in (
            "http://127.0.0.1/result",
            "http://169.254.169.254/latest/meta-data",
            "http://metadata.google.internal/computeMetadata/v1",
        ):
            with self.subTest(destination):
                def handler(request: httpx.Request) -> httpx.Response:
                    if request.url.host == "ogc.example.test":
                        return httpx.Response(302, headers={"Location": destination})
                    self.fail("Blocked destination must not be requested")

                registry = build_registry()
                pipeline, _ = _pipeline(registry, handler)
                manifest = pipeline.build(
                    _response(
                        "<html>Moved</html>",
                        content_type="text/html",
                        status=302,
                        location="/temp/result",
                    ),
                    server=registry.get(service="processes"),
                    operation="jobs.get_results",
                )
                self.assertEqual(manifest["outputs"][0]["retrieval"]["state"], "blocked")

    def test_https_to_http_downgrade_is_blocked_even_for_allowlisted_host(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                302,
                headers={"Location": "http://outputs.example/result.json"},
            )

        registry = build_registry(
            output_resolution={"allowed_hosts": ["outputs.example"]},
        )
        pipeline, _ = _pipeline(registry, handler)
        manifest = pipeline.build(
            _response(
                "<html>Moved</html>",
                content_type="text/html",
                status=302,
                location="/temp/result",
            ),
            server=registry.get(service="processes"),
            operation="jobs.get_results",
        )
        self.assertEqual(manifest["outputs"][0]["retrieval"]["state"], "blocked")
        self.assertIn(
            "HTTPS-to-HTTP",
            manifest["outputs"][0]["retrieval"]["error"]["message"],
        )

    def test_output_size_and_unsupported_redirect_status_fail_closed(self) -> None:
        for response in (
            httpx.Response(200, content=b"0123456789"),
            httpx.Response(304, content=b""),
        ):
            with self.subTest(status=response.status_code):
                registry = build_registry(
                    output_resolution={"max_response_bytes": 5},
                )
                pipeline, _ = _pipeline(registry, lambda _: response)
                manifest = pipeline.build(
                    _response(
                        "<html>Moved</html>",
                        content_type="text/html",
                        status=302,
                        location="/temp/result",
                    ),
                    server=registry.get(service="processes"),
                    operation="jobs.get_results",
                )
                self.assertEqual(manifest["outputs"][0]["retrieval"]["state"], "failed")

    def test_reference_budget_is_shared_across_outputs_and_redirect_bodies(self) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            if request.url.path == "/first":
                return httpx.Response(
                    302,
                    headers={"Location": "/first-result"},
                    content=b"12345",
                )
            if request.url.path == "/first-result":
                return httpx.Response(
                    200,
                    content=b"7",
                    headers={"Content-Type": "application/json"},
                )
            if request.url.path == "/second":
                return httpx.Response(
                    200,
                    content=b"0123456789",
                    headers={"Content-Type": "text/plain"},
                )
            return httpx.Response(404)

        registry = build_registry(
            output_resolution={
                "max_response_bytes": 12,
                "max_outputs": 2,
                "max_redirects": 1,
            }
        )
        pipeline, _ = _pipeline(registry, handler)
        manifest = pipeline.build(
            _response(
                {
                    "outputs": {
                        "first": {"href": "/first"},
                        "second": {"href": "/second"},
                    }
                }
            ),
            server=registry.get(service="processes"),
            operation="jobs.get_results",
        )

        by_id = {output["id"]: output for output in manifest["outputs"]}
        self.assertEqual(by_id["first"]["retrieval"]["state"], "retrieved")
        self.assertEqual(by_id["second"]["retrieval"]["state"], "failed")
        self.assertIn(
            "aggregate size limit",
            by_id["second"]["retrieval"]["error"]["message"],
        )
        self.assertEqual(calls, ["/first", "/first-result", "/second"])
        _assert_manifest_schema(self, manifest)

    def test_resolution_budget_enforces_aggregate_time_and_fetch_count(self) -> None:
        now = [10.0]
        budget = OutputResolutionBudget(
            max_seconds=1.0,
            max_bytes=100,
            max_fetches=1,
            clock=lambda: now[0],
        )
        budget.claim_fetch(server_id="test")
        with self.assertRaisesRegex(TransportError, "aggregate fetch limit"):
            budget.claim_fetch(server_id="test")

        now[0] = 11.1
        with self.assertRaisesRegex(TransportError, "aggregate time limit"):
            budget.remaining_seconds(server_id="test")


if __name__ == "__main__":
    unittest.main()
