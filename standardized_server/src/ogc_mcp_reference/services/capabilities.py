"""Server conformance discovery and capability caching."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..errors import OgcMcpError
from ..models import ServerProfile
from ..registry import ServerRegistry
from ..transport import OgcHttpClient


@dataclass(frozen=True)
class CapabilityProfile:
    """Normalized capabilities inferred from an OGC API conformance document."""

    server_id: str
    loaded: bool
    conforms_to: tuple[str, ...] = ()
    flags: dict[str, bool] = field(default_factory=dict)
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "server_id": self.server_id,
            "loaded": self.loaded,
            "conforms_to": list(self.conforms_to),
            "flags": dict(self.flags),
        }
        if self.error:
            payload["error"] = self.error
        return payload


class CapabilityCache:
    """Load and cache capability facts per registered server."""

    def __init__(self, registry: ServerRegistry, client: OgcHttpClient) -> None:
        self._registry = registry
        self._client = client
        self._profiles: dict[str, CapabilityProfile] = {}

    def bootstrap(self) -> None:
        """Best-effort startup discovery for every enabled server."""
        for server in self._registry.enabled_servers():
            self.get(server.id, refresh=True)

    def get(self, server_id: str = "", *, refresh: bool = False) -> CapabilityProfile:
        server = self._registry.get(server_id)
        if not refresh and server.id in self._profiles:
            return self._profiles[server.id]
        profile = self._load(server)
        self._profiles[server.id] = profile
        return profile

    def list(self) -> list[dict[str, Any]]:
        """Return all cached profiles, loading any missing profiles lazily."""
        return [
            self.get(server.id).to_dict()
            for server in self._registry.enabled_servers()
        ]

    def _load(self, server: ServerProfile) -> CapabilityProfile:
        path = server.path("conformance", "/conformance")
        try:
            response = self._client.request(server, "GET", path, query={"f": "json"})
        except OgcMcpError as exc:
            return CapabilityProfile(
                server_id=server.id,
                loaded=False,
                flags=_flags_from_conformance(()),
                error=exc.to_dict(),
            )

        conforms_to = _extract_conformance(response.data)
        return CapabilityProfile(
            server_id=server.id,
            loaded=True,
            conforms_to=conforms_to,
            flags=_flags_from_conformance(conforms_to),
        )


def _extract_conformance(data: Any) -> tuple[str, ...]:
    if not isinstance(data, dict):
        return ()
    values = data.get("conformsTo", data.get("conformsto", ()))
    if not isinstance(values, list):
        return ()
    return tuple(str(item) for item in values)


def _flags_from_conformance(conforms_to: tuple[str, ...]) -> dict[str, bool]:
    lowered = " ".join(item.lower() for item in conforms_to)
    return {
        "async": "job-list" in lowered or "async" in lowered,
        "cql2": "cql2" in lowered,
        "crs_negotiation": "crs" in lowered,
        "temporal_filter": "datetime" in lowered or "temporal" in lowered,
        "property_selection": "queryables" in lowered or "properties" in lowered,
    }
