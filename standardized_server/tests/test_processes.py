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
            return httpx.Response(200, json={"processes": [{"id": "Delaunay"}]})

        service = ProcessesService(build_registry(), OgcHttpClient(transport=httpx.MockTransport(handler)))
        result = service.list_processes()
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["processes"][0]["id"], "Delaunay")

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
