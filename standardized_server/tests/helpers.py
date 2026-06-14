"""Shared deterministic test helpers."""

from __future__ import annotations

from typing import Any

from ogc_mcp_reference.config import parse_settings
from ogc_mcp_reference.registry import ServerRegistry


def build_registry(
    *,
    base_url: str = "https://ogc.example.test",
    services: list[str] | None = None,
    security: dict[str, Any] | None = None,
    limits: dict[str, Any] | None = None,
    auth: dict[str, Any] | None = None,
) -> ServerRegistry:
    return ServerRegistry(
        parse_settings(
            {
                "default_servers": {
                    "common": "test",
                    "features": "test",
                    "records": "test",
                    "processes": "test",
                },
                "servers": [
                    {
                        "id": "test",
                        "title": "Test OGC API",
                        "base_url": base_url,
                        "services": services or ["common", "features", "records", "processes"],
                        "defaults": {"records_collection": "metadata"},
                        "security": security or {},
                        "limits": limits or {},
                        "auth": auth or {},
                    }
                ],
            }
        )
    )
