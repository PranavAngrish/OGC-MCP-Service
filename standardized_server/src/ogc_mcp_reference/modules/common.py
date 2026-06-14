"""OGC API - Common discovery and safe read-only access."""

from __future__ import annotations

from typing import Any

from ..registry import ServerRegistry
from ..result import success
from ..transport import OgcHttpClient


class CommonService:
    """Read discovery resources from registered OGC API deployments."""

    def __init__(self, registry: ServerRegistry, client: OgcHttpClient) -> None:
        self._registry = registry
        self._client = client

    def landing_page(self, server_id: str = "") -> dict[str, Any]:
        server = self._registry.get(server_id, service="common")
        path = server.path("landing_page", "/")
        response = self._client.request(server, "GET", path, query={"f": "json"})
        return success(
            "common.landing_page",
            server,
            response,
            guidance={"next_tools": ["ogc_common_get_conformance", "ogc_processes_list"]},
        )

    def conformance(self, server_id: str = "") -> dict[str, Any]:
        server = self._registry.get(server_id, service="common")
        path = server.path("conformance", "/conformance")
        response = self._client.request(server, "GET", path, query={"f": "json"})
        return success(
            "common.conformance",
            server,
            response,
            guidance={
                "interpretation": "Use conformsTo URIs to decide which OGC API modules and extensions are available."
            },
        )

    def get_resource(
        self,
        server_id: str,
        path: str,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Read a relative path for an OGC module not yet mapped to a dedicated tool."""
        server = self._registry.get(server_id)
        response = self._client.request(server, "GET", path, query=query)
        return success(
            "common.get_resource",
            server,
            response,
            guidance={
                "scope": "Read-only escape hatch for registered servers and relative paths only."
            },
        )
