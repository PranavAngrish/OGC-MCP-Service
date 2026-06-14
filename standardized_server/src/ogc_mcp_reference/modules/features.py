"""OGC API - Features operations."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

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
        return success(
            "features.get_items",
            server,
            response,
            guidance={
                "reference_href": f"{server.base_url}{path}",
                "next_tools": ["ogc_features_get_item", "ogc_processes_execute"],
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
