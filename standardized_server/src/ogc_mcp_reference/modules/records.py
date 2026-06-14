"""OGC API - Records operations."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ..errors import OgcMcpError
from ..registry import ServerRegistry
from ..result import success
from ..transport import OgcHttpClient


def _segment(value: str) -> str:
    return quote(value, safe="")


class RecordsService:
    """Discover metadata records through OGC API - Records."""

    def __init__(self, registry: ServerRegistry, client: OgcHttpClient) -> None:
        self._registry = registry
        self._client = client

    def list_collections(self, server_id: str = "") -> dict[str, Any]:
        server = self._registry.get(server_id, service="records")
        path = server.path("collections", "/collections")
        response = self._client.request(server, "GET", path, query={"f": "json"})
        return success(
            "records.list_collections",
            server,
            response,
            guidance={"next_tools": ["ogc_records_search"]},
        )

    def search(
        self,
        *,
        server_id: str = "",
        collection_id: str = "",
        query_text: str = "",
        bbox: str = "",
        limit: int = 10,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        server = self._registry.get(server_id, service="records")
        selected_collection = collection_id or str(server.defaults.get("records_collection", ""))
        if not selected_collection:
            raise OgcMcpError(
                "invalid_argument",
                "collection_id is required when the server has no defaults.records_collection.",
            )
        path = (
            f"{server.path('collections', '/collections')}/"
            f"{_segment(selected_collection)}/items"
        )
        params: dict[str, Any] = {"f": "json", "limit": limit, **(query or {})}
        if query_text:
            params["q"] = query_text
        if bbox:
            params["bbox"] = bbox
        response = self._client.request(server, "GET", path, query=params)
        return success(
            "records.search",
            server,
            response,
            guidance={"next_tools": ["ogc_records_get_record"]},
        )

    def get_record(
        self,
        record_id: str,
        *,
        server_id: str = "",
        collection_id: str = "",
    ) -> dict[str, Any]:
        server = self._registry.get(server_id, service="records")
        selected_collection = collection_id or str(server.defaults.get("records_collection", ""))
        if not selected_collection:
            raise OgcMcpError(
                "invalid_argument",
                "collection_id is required when the server has no defaults.records_collection.",
            )
        path = (
            f"{server.path('collections', '/collections')}/"
            f"{_segment(selected_collection)}/items/{_segment(record_id)}"
        )
        response = self._client.request(server, "GET", path, query={"f": "json"})
        return success(
            "records.get_record",
            server,
            response,
            guidance={
                "usage": "Inspect links for data/service URLs suitable as referenced process inputs."
            },
        )
