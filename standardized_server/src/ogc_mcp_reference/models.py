"""Typed configuration and response models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SUPPORTED_SERVICES = frozenset({"common", "features", "records", "processes"})
SUPPORTED_AUTH_TYPES = frozenset({"none", "bearer_env", "api_key_env", "basic_env"})


@dataclass(frozen=True)
class AuthProfile:
    """Authentication injected by the MCP server, never supplied by an LLM."""

    type: str = "none"
    token_env: str = ""
    api_key_env: str = ""
    api_key_header: str = "X-API-Key"
    username_env: str = ""
    password_env: str = ""


@dataclass(frozen=True)
class SecurityPolicy:
    """Outbound request restrictions for one registered server."""

    allow_private_networks: bool = False
    allowed_reference_hosts: tuple[str, ...] = ()
    allow_unlisted_reference_hosts: bool = False
    validate_execute_references: bool = True


@dataclass(frozen=True)
class RequestLimits:
    """Resource limits applied to upstream requests."""

    timeout_seconds: float = 30.0
    max_response_bytes: int = 1_000_000


@dataclass(frozen=True)
class ServerProfile:
    """Operator-approved OGC API deployment."""

    id: str
    title: str
    base_url: str
    services: frozenset[str]
    description: str = ""
    enabled: bool = True
    paths: dict[str, str] = field(default_factory=dict)
    defaults: dict[str, Any] = field(default_factory=dict)
    auth: AuthProfile = field(default_factory=AuthProfile)
    security: SecurityPolicy = field(default_factory=SecurityPolicy)
    limits: RequestLimits = field(default_factory=RequestLimits)

    def path(self, name: str, fallback: str) -> str:
        return self.paths.get(name, fallback)


@dataclass(frozen=True)
class RegistrySettings:
    """Top-level configuration loaded from JSON."""

    servers: tuple[ServerProfile, ...]
    default_servers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class OgcResponse:
    """Sanitized upstream response passed to the service layer."""

    server_id: str
    method: str
    path: str
    status_code: int
    headers: dict[str, str]
    content_type: str
    data: Any

    @property
    def location(self) -> str:
        return self.headers.get("location", "")

    def metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "status_code": self.status_code,
            "content_type": self.content_type,
        }
        for key in ("location", "preference-applied", "link"):
            if key in self.headers:
                metadata[key.replace("-", "_")] = self.headers[key]
        return metadata
