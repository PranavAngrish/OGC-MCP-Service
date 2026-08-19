from __future__ import annotations

import unittest

import httpx

from ogc_mcp_reference.errors import OgcMcpError
from ogc_mcp_reference.modules import FeaturesService
from ogc_mcp_reference.transport import OgcHttpClient
from helpers import build_registry


def _feature(identifier: str, name: str, area: float, start: str) -> dict:
    return {
        "type": "Feature",
        "id": identifier,
        "geometry": {"type": "Point", "coordinates": [7.0, 52.0]},
        "properties": {
            "name": name,
            "area_km2": area,
            "gwsdate": start,
        },
    }


class FeatureQuerySurfaceTests(unittest.TestCase):
    def test_surface_merges_queryables_schema_and_observed_sample_fields(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/collections/history":
                return httpx.Response(200, json={"id": "history", "title": "History"})
            if request.url.path == "/conformance":
                return httpx.Response(200, json={
                    "conformsTo": [
                        "http://www.opengis.net/spec/cql2/1.0/conf/cql2-text",
                        "http://www.opengis.net/spec/ogcapi-features-6/0.0/conf/properties",
                        "http://www.opengis.net/spec/ogcapi-features-n/0.0/conf/versioned-features-core",
                    ]
                })
            if request.url.path == "/collections/history/queryables":
                return httpx.Response(200, json={
                    "type": "object",
                    "properties": {"name": {"type": "string", "title": "Name"}},
                })
            if request.url.path == "/collections/history/sortables":
                return httpx.Response(200, json={
                    "properties": {"gwsdate": {"type": "string", "format": "date"}},
                })
            if request.url.path == "/collections/history/schema":
                return httpx.Response(200, json={
                    "type": "object",
                    "properties": {
                        "properties": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "gwsdate": {"type": "string", "format": "date"},
                            },
                        }
                    },
                })
            if request.url.path == "/collections/history/items":
                return httpx.Response(200, json={
                    "type": "FeatureCollection",
                    "features": [_feature("1", "Example", 123.5, "1900-01-01")],
                })
            return httpx.Response(404, json={})

        service = FeaturesService(
            build_registry(),
            OgcHttpClient(transport=httpx.MockTransport(handler)),
        )
        result = service.describe_query_surface("history")
        fields = {field["name"]: field for field in result["fields"]}

        self.assertTrue(result["capabilities"]["cql2_text"])
        self.assertTrue(result["capabilities"]["property_selection"])
        self.assertTrue(result["capabilities"]["versioned_features"])
        self.assertTrue(fields["name"]["filterable"])
        self.assertTrue(fields["gwsdate"]["returnable"])
        self.assertTrue(fields["gwsdate"]["sortable"])
        self.assertTrue(fields["area_km2"]["observed"])
        self.assertFalse(fields["area_km2"]["filterable"])
        self.assertTrue(service.describe_query_surface("history")["cache"]["hit"])


class ValidatedFeatureQueryTests(unittest.TestCase):
    def _service(
        self,
        *,
        second_page: bool = True,
        versioned: bool = False,
        empty_result: bool = False,
    ) -> tuple[FeaturesService, list[httpx.Request]]:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/collections/history":
                return httpx.Response(200, json={"id": "history", "title": "History"})
            if request.url.path == "/conformance":
                return httpx.Response(200, json={
                    "conformsTo": [
                        "http://www.opengis.net/spec/cql2/1.0/conf/cql2-text",
                        "http://www.opengis.net/spec/ogcapi-features-6/0.0/conf/properties",
                        *(["http://www.opengis.net/spec/ogcapi-features-n/0.0/conf/versioned-features-core"] if versioned else []),
                    ],
                })
            if request.url.path == "/collections/history/queryables":
                return httpx.Response(200, json={
                    "properties": {
                        "name": {"type": "string"},
                        "gwsdate": {"type": "string", "format": "date"},
                    }
                })
            if request.url.path == "/collections/history/sortables":
                return httpx.Response(200, json={
                    "properties": {"gwsdate": {"type": "string", "format": "date"}},
                })
            if request.url.path == "/collections/history/schema":
                return httpx.Response(404, json={})
            if request.url.path == "/collections/history/items" and request.url.params.get("limit") == "1":
                return httpx.Response(200, json={
                    "type": "FeatureCollection",
                    "features": [_feature("sample", "Sample", 1.0, "1900-01-01")],
                })
            if request.url.path == "/collections/history/items" and empty_result:
                return httpx.Response(200, json={
                    "type": "FeatureCollection",
                    "numberMatched": 0,
                    "numberReturned": 0,
                    "features": [],
                    "links": [],
                })
            if request.url.path == "/collections/history/items" and request.url.params.get("offset") == "2":
                return httpx.Response(200, json={
                    "type": "FeatureCollection",
                    "numberMatched": 3,
                    "numberReturned": 1,
                    "features": [_feature("3", "German C", 300.0, "1990-01-01")],
                    "links": [],
                })
            if request.url.path == "/collections/history/items":
                links = [{
                    "rel": "next",
                    "href": "https://ogc.example.test/collections/history/items?limit=2&offset=2&f=json",
                }] if second_page else []
                return httpx.Response(200, json={
                    "type": "FeatureCollection",
                    "numberMatched": 3,
                    "numberReturned": 2,
                    "features": [
                        _feature("1", "German A", 100.0, "1900-01-01"),
                        _feature("2", "German B", 200.0, "1950-01-01"),
                    ],
                    "links": links,
                })
            return httpx.Response(404, json={})

        return FeaturesService(
            build_registry(),
            OgcHttpClient(transport=httpx.MockTransport(handler)),
        ), requests

    def test_query_validates_cql_and_follows_upstream_next_links(self) -> None:
        service, requests = self._service()
        result = service.query({
            "collection_id": "history",
            "filters": [{"property": "name", "operator": "contains_ci", "value": "german"}],
            "datetime": {"start": "1900-01-01", "end": "2000-12-31"},
            "properties": ["name", "area_km2", "gwsdate"],
            "page_size": 2,
            "max_pages": 3,
            "max_items": 10,
        })

        self.assertEqual(result["data"]["pagination"], {
            "matched": 3,
            "retrieved": 3,
            "pages": 2,
            "complete": True,
            "stoppedReason": None,
        })
        self.assertTrue(result["data"]["evidence"]["safeToAnswer"])
        self.assertEqual(
            [row["area_km2"] for row in result["data"]["facts"]["rows"]],
            [100.0, 200.0, 300.0],
        )
        self.assertEqual(len(result["_feature_collection"]["features"]), 3)
        query_requests = [
            request for request in requests
            if request.url.path == "/collections/history/items"
            and request.url.params.get("limit") != "1"
        ]
        self.assertEqual(len(query_requests), 2)
        self.assertEqual(query_requests[1].url.params["offset"], "2")
        self.assertIn("CASEI(name) LIKE CASEI('%german%')", query_requests[0].url.params["filter"])
        self.assertEqual(query_requests[0].url.params["properties"], "name,area_km2,gwsdate")

    def test_incomplete_upstream_result_fails_evidence_gate(self) -> None:
        service, _ = self._service(second_page=False)
        result = service.query({
            "collection_id": "history",
            "properties": ["name", "area_km2"],
            "page_size": 2,
            "max_pages": 1,
            "max_items": 10,
        })

        self.assertFalse(result["data"]["pagination"]["complete"])
        self.assertFalse(result["data"]["evidence"]["safeToAnswer"])
        self.assertIn("incomplete", result["data"]["evidence"]["reasons"][0].lower())

    def test_bbox_results_disclose_intersection_scope(self) -> None:
        service, _ = self._service()
        result = service.query({
            "collection_id": "history",
            "bbox": [-25, 34, 45, 72],
            "properties": ["name"],
            "page_size": 2,
            "max_pages": 3,
            "max_items": 10,
        })

        self.assertTrue(result["data"]["evidence"]["safeToAnswer"])
        self.assertIn(
            "not semantic membership",
            result["data"]["evidence"]["qualifications"][0],
        )

    def test_versioned_collection_requires_explicit_datetime(self) -> None:
        service, requests = self._service(versioned=True)
        with self.assertRaises(OgcMcpError) as context:
            service.query({"collection_id": "history", "properties": ["name"]})

        self.assertEqual(context.exception.code, "invalid_argument")
        self.assertIn("explicit query_plan.datetime", context.exception.message)
        analytical_requests = [
            request for request in requests
            if request.url.path == "/collections/history/items"
            and request.url.params.get("limit") != "1"
        ]
        self.assertEqual(analytical_requests, [])

    def test_empty_exact_historical_name_requires_candidate_discovery(self) -> None:
        service, _ = self._service(versioned=True, empty_result=True)
        result = service.query({
            "collection_id": "history",
            "datetime": "1900-01-01/2000-12-31",
            "filters": [{"property": "name", "operator": "eq", "value": "Germany"}],
            "properties": ["name"],
        })

        evidence = result["data"]["evidence"]
        self.assertFalse(evidence["safeToAnswer"])
        self.assertEqual(evidence["suggestedFilters"], [{
            "property": "name",
            "operator": "candidate_ci",
            "value": "German",
        }])

    def test_candidate_name_query_cannot_be_used_as_final_evidence(self) -> None:
        service, _ = self._service()
        result = service.query({
            "collection_id": "history",
            "filters": [{"property": "name", "operator": "candidate_ci", "value": "German"}],
            "properties": ["name"],
            "page_size": 2,
            "max_pages": 3,
            "max_items": 10,
        })

        evidence = result["data"]["evidence"]
        self.assertFalse(evidence["safeToAnswer"])
        self.assertIn("candidate discovery only", evidence["reasons"][0])

    def test_default_facts_select_all_non_spatial_scalars_and_normalize_sort(self) -> None:
        service, requests = self._service()
        result = service.query({
            "collection_id": "history",
            "sortby": {"property": "gwsdate", "order": "descending"},
            "page_size": 2,
            "max_pages": 3,
            "max_items": 10,
        })

        self.assertIn("area_km2", result["data"]["facts"]["columns"])
        self.assertNotIn("geometry.type", result["data"]["facts"]["columns"])
        query_request = next(
            request for request in requests
            if request.url.path == "/collections/history/items"
            and request.url.params.get("limit") != "1"
        )
        self.assertIn("area_km2", query_request.url.params["properties"])
        self.assertNotIn("geometry", query_request.url.params["properties"].split(","))
        self.assertEqual(query_request.url.params["sortby"], "-gwsdate")

    def test_unadvertised_filter_property_is_rejected_before_query_execution(self) -> None:
        service, requests = self._service()
        with self.assertRaises(OgcMcpError) as context:
            service.query({
                "collection_id": "history",
                "filters": [{"property": "area_km2", "operator": "gt", "value": 10}],
            })

        self.assertEqual(context.exception.code, "invalid_argument")
        analytical_requests = [
            request for request in requests
            if request.url.path == "/collections/history/items"
            and request.url.params.get("limit") != "1"
        ]
        self.assertEqual(analytical_requests, [])

    def test_cross_origin_next_link_is_rejected(self) -> None:
        service, _ = self._service()

        original_client = service._client  # noqa: SLF001 - deliberate security-path test

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/collections/history/items" and request.url.params.get("limit") != "1":
                return httpx.Response(200, json={
                    "type": "FeatureCollection",
                    "numberMatched": 2,
                    "features": [_feature("1", "A", 1.0, "1900-01-01")],
                    "links": [{"rel": "next", "href": "https://evil.example/items?offset=1"}],
                })
            return original_client._transport.handle_request(request)  # type: ignore[union-attr]

        service._client = OgcHttpClient(transport=httpx.MockTransport(handler))  # noqa: SLF001
        with self.assertRaises(OgcMcpError) as context:
            service.query({"collection_id": "history", "properties": ["name"]})
        self.assertEqual(context.exception.code, "security_policy_error")
