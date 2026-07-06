"""OGC API - Features operations."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode

from ..registry import ServerRegistry
from ..result import success
from ..transport import OgcHttpClient


def _segment(value: str) -> str:
    return quote(value, safe="")


class FeaturesService:
    """Discover and retrieve vector features from OGC API - Features."""

    def __init__(self, registry: ServerRegistry, client: OgcHttpClient) -> None:
        self._registry = registry
        self._client = client

    def list_collections(self, server_id: str = "") -> dict[str, Any]:
        server = self._registry.get(server_id, service="features")
        path = server.path("collections", "/collections")
        response = self._client.request(server, "GET", path, query={"f": "json"})
        return success(
            "features.list_collections",
            server,
            response,
            guidance={"next_tools": ["ogc_features_describe_collection", "ogc_features_get_items"]},
        )

    def describe_collection(self, collection_id: str, server_id: str = "") -> dict[str, Any]:
        server = self._registry.get(server_id, service="features")
        path = f"{server.path('collections', '/collections')}/{_segment(collection_id)}"
        response = self._client.request(server, "GET", path, query={"f": "json"})
        return success(
            "features.describe_collection",
            server,
            response,
            guidance={"next_tools": ["ogc_features_get_items"]},
        )

    def get_items(
        self,
        collection_id: str,
        *,
        server_id: str = "",
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        server = self._registry.get(server_id, service="features")
        path = f"{server.path('collections', '/collections')}/{_segment(collection_id)}/items"
        params = {"f": "json", **(query or {})}
        response = self._client.request(server, "GET", path, query=params)
        query_string = urlencode(params, doseq=True)
        reference_href = f"{server.base_url}{path}"
        if query_string:
            reference_href = f"{reference_href}?{query_string}"
        return success(
            "features.get_items",
            server,
            response,
            guidance={
                "reference_href": reference_href,
                "source": {
                    "server_id": server.id,
                    "collection_id": collection_id,
                    "href": reference_href,
                },
                "next_tools": ["ogc_features_get_item", "ogc_processes_list", "ogc_proxy_create_plan"],
                "workflow_hint": (
                    "To run a geospatial process on this data, follow the proxy plan workflow: "
                    "ogc_processes_list \u2192 ogc_processes_describe \u2192 ogc_proxy_create_plan. "
                    "Pass reference_href as a referenced input "
                    '({\"href\": \"<reference_href value>\"}) rather than copying feature '
                    "coordinates into model context, and include guidance.source in "
                    "the create-plan sources array. "
                    "NEVER perform spatial analysis yourself in any form \u2014 Python, bash, "
                    "JavaScript, visualization artifacts, or any other mechanism. "
                    "All geospatial computation MUST go through an OGC process (RULE 0)."
                ),
            },
        )

    def get_item(
        self,
        collection_id: str,
        item_id: str,
        *,
        server_id: str = "",
    ) -> dict[str, Any]:
        server = self._registry.get(server_id, service="features")
        path = (
            f"{server.path('collections', '/collections')}/"
            f"{_segment(collection_id)}/items/{_segment(item_id)}"
        )
        response = self._client.request(server, "GET", path, query={"f": "json"})
        return success(
            "features.get_item",
            server,
            response,
            guidance={"usage": "Use the returned GeoJSON inline only when a process expects one feature."},
        )
