from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import httpx

from ogc_mcp_reference.errors import TransportError, UpstreamResponseError
from ogc_mcp_reference.transport import OgcHttpClient
from helpers import build_registry


class TransportTests(unittest.TestCase):
    def test_injects_api_key_from_environment(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.headers["X-Test-Key"], "secret")
            return httpx.Response(200, json={"ok": True})

        registry = build_registry(
            auth={
                "type": "api_key_env",
                "api_key_env": "TEST_OGC_API_KEY",
                "api_key_header": "X-Test-Key",
            }
        )
        client = OgcHttpClient(transport=httpx.MockTransport(handler))
        with patch.dict(os.environ, {"TEST_OGC_API_KEY": "secret"}):
            response = client.request(registry.get(service="common"), "GET", "/")
        self.assertEqual(response.data, {"ok": True})

    def test_enforces_response_size_limit(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"0123456789")

        registry = build_registry(limits={"max_response_bytes": 5})
        client = OgcHttpClient(transport=httpx.MockTransport(handler))
        with self.assertRaises(TransportError):
            client.request(registry.get(service="common"), "GET", "/")

    def test_raises_structured_upstream_error(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "missing"})

        registry = build_registry()
        client = OgcHttpClient(transport=httpx.MockTransport(handler))
        with self.assertRaises(UpstreamResponseError) as context:
            client.request(registry.get(service="common"), "GET", "/missing")
        self.assertEqual(context.exception.details["status_code"], 404)


if __name__ == "__main__":
    unittest.main()
