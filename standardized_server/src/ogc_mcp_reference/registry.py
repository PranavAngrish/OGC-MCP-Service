"""Resolve configured OGC API deployments by stable operator-owned IDs."""

from __future__ import annotations

from .errors import ConfigurationError, ServerNotFoundError, ServiceNotSupportedError
from .models import SUPPORTED_SERVICES, RegistrySettings, ServerProfile
from .security import validate_http_url


class ServerRegistry:
    """Read-only registry of approved upstream OGC API servers."""

    def __init__(self, settings: RegistrySettings) -> None:
        self._settings = settings
        self._servers = {server.id: server for server in settings.servers if server.enabled}
        if not self._servers:
            raise ConfigurationError("At least one enabled OGC server is required.")
        for server in self._servers.values():
            validate_http_url(
                server.base_url,
                allow_private_networks=server.security.allow_private_networks,
                label=f"Base URL for server '{server.id}'",
            )
        for service, server_id in settings.default_servers.items():
            if service not in SUPPORTED_SERVICES:
                raise ConfigurationError(
                    f"default_servers contains unsupported service '{service}'."
                )
            if server_id not in self._servers:
                raise ConfigurationError(
                    f"default_servers.{service} points to unknown or disabled server '{server_id}'."
                )
            if service not in self._servers[server_id].services:
                raise ConfigurationError(
                    f"default_servers.{service} points to server '{server_id}', "
                    f"but that profile does not enable service '{service}'."
                )

    def get(self, server_id: str = "", *, service: str = "") -> ServerProfile:
        selected_id = server_id or self._settings.default_servers.get(service, "")
        if not selected_id:
            raise ConfigurationError(
                f"No server_id was supplied and no default server is configured for '{service}'."
            )
        server = self._servers.get(selected_id)
        if not server:
            raise ServerNotFoundError(selected_id)
        if service and service not in server.services:
            raise ServiceNotSupportedError(server.id, service)
        return server

    def list(self) -> list[dict[str, object]]:
        """Return non-secret server metadata for MCP callers."""
        return [
            {
                "id": server.id,
                "title": server.title,
                "description": server.description,
                "base_url": server.base_url,
                "services": sorted(server.services),
                "default_for": sorted(
                    service
                    for service, server_id in self._settings.default_servers.items()
                    if server_id == server.id
                ),
            }
            for server in sorted(self._servers.values(), key=lambda item: item.id)
        ]

    def enabled_servers(self) -> tuple[ServerProfile, ...]:
        """Return enabled server profiles for internal runtime services."""
        return tuple(sorted(self._servers.values(), key=lambda item: item.id))
