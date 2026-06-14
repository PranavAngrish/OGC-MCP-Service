"""Structured errors returned by the OGC MCP reference server."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OgcMcpError(Exception):
    """Base error with a stable machine-readable code."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.details:
            payload["details"] = self.details
        return payload


class ConfigurationError(OgcMcpError):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__("configuration_error", message, details)


class ServerNotFoundError(OgcMcpError):
    def __init__(self, server_id: str) -> None:
        super().__init__(
            "server_not_found",
            f"OGC server profile '{server_id}' is not registered.",
            {"server_id": server_id},
        )


class ServiceNotSupportedError(OgcMcpError):
    def __init__(self, server_id: str, service: str) -> None:
        super().__init__(
            "service_not_supported",
            f"Server '{server_id}' is not configured for OGC API - {service.title()}.",
            {"server_id": server_id, "service": service},
        )


class SecurityPolicyError(OgcMcpError):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__("security_policy_error", message, details)


class TransportError(OgcMcpError):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__("transport_error", message, details)


class UpstreamResponseError(OgcMcpError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        server_id: str,
        method: str,
        path: str,
        response: Any,
    ) -> None:
        super().__init__(
            "upstream_response_error",
            message,
            {
                "status_code": status_code,
                "server_id": server_id,
                "method": method,
                "path": path,
                "response": response,
            },
        )
