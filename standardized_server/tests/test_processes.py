from __future__ import annotations

import json
import unittest

import httpx

from ogc_mcp_reference.errors import SecurityPolicyError
from ogc_mcp_reference.modules.processes import ProcessesService
from ogc_mcp_reference.transport import OgcHttpClient
from helpers import build_registry


class ProcessesServiceTests(unittest.TestCase):
    def test_lists_processes(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/processes")
            self.assertEqual(request.url.params["limit"], "100")
            return httpx.Response(200, json={"processes": [{"id": "Delaunay"}]})

        service = ProcessesService(build_registry(), OgcHttpClient(transport=httpx.MockTransport(handler)))
        result = service.list_processes()
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["processes"][0]["id"], "Delaunay")

    def test_searches_bounded_process_pages(self) -> None:
        requests: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(str(request.url))
            if request.url.path == "/processes/delaunay":
                return httpx.Response(404, json={"code": "NotFound"})
            if request.url.params.get("skip") == "100":
                return httpx.Response(200, json={
                    "processes": [
                        {"id": "Delaunay", "title": "Delaunay triangulation"},
                        {"id": "Buffer", "title": "Buffer"},
                    ],
                    "links": [{
                        "rel": "next",
                        "href": "https://ogc.example.test/processes?limit=100&skip=200",
                    }],
                })
            return httpx.Response(200, json={
                "processes": [{"id": "Raster", "title": "Raster processing"}],
                "links": [{
                    "rel": "next",
                    "href": "https://ogc.example.test/processes?limit=100&skip=100",
                }],
            })

        service = ProcessesService(build_registry(), OgcHttpClient(transport=httpx.MockTransport(handler)))
        result = service.list_processes(search_text="delaunay")
        self.assertEqual(len(requests), 3)
        self.assertEqual(result["guidance"]["pages_scanned"], 2)
        self.assertEqual(result["data"]["numberReturned"], 1)
        self.assertEqual(result["data"]["processes"][0]["id"], "Delaunay")

    def test_search_uses_exact_process_id_before_scanning_pages(self) -> None:
        requests: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(str(request.url))
            self.assertEqual(request.url.path, "/processes/buffer")
            self.assertEqual(request.url.params["f"], "json")
            return httpx.Response(
                200,
                json={
                    "id": "Buffer",
                    "title": "Create a buffer around a polygon",
                    "description": "Returns a buffered feature collection.",
                    "version": "2.0.0",
                },
            )

        service = ProcessesService(build_registry(), OgcHttpClient(transport=httpx.MockTransport(handler)))
        result = service.list_processes(search_text=" buffer ")

        self.assertEqual(len(requests), 1)
        self.assertEqual(result["request"]["path"], "/processes/buffer")
        self.assertEqual(result["guidance"]["lookup_strategy"], "exact_process_id")
        self.assertEqual(result["guidance"]["matched_process_id"], "Buffer")
        self.assertEqual(result["guidance"]["pages_scanned"], 0)
        self.assertEqual(result["data"]["numberReturned"], 1)
        self.assertEqual(result["data"]["processes"][0]["id"], "Buffer")

    def test_executes_process_without_rewriting_body(self) -> None:
        execute_body = {
            "inputs": {
                "InputPoints": {
                    "href": "https://demo.pygeoapi.io/master/collections/dutch_windmills/items?f=json",
                    "type": "text/xml",
                }
            }
        }

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/processes/Delaunay/execution")
            self.assertEqual(request.headers["Prefer"], "respond-async")
            self.assertEqual(json.loads(request.content), execute_body)
            return httpx.Response(
                201,
                headers={"Location": "/jobs/42"},
                json={"jobID": "42", "status": "accepted"},
            )

        registry = build_registry(
            security={"allowed_reference_hosts": ["demo.pygeoapi.io"]}
        )
        service = ProcessesService(registry, OgcHttpClient(transport=httpx.MockTransport(handler)))
        result = service.execute("Delaunay", execute_body, execution_mode="async")
        self.assertEqual(result["response"]["status_code"], 201)
        self.assertEqual(result["guidance"]["location"], "/jobs/42")

    def test_rejects_unapproved_reference_before_network_call(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            self.fail("Network transport should not be called for rejected references.")

        service = ProcessesService(
            build_registry(security={"allowed_reference_hosts": ["approved.example"]}),
            OgcHttpClient(transport=httpx.MockTransport(handler)),
        )
        with self.assertRaises(SecurityPolicyError):
            service.execute(
                "Example",
                {"inputs": {"data": {"href": "https://evil.example/data"}}},
            )


if __name__ == "__main__":
    unittest.main()
