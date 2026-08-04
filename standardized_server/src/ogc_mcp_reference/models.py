"""Typed configuration and response models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SUPPORTED_SERVICES = frozenset({"common", "features", "records", "processes"})
SUPPORTED_AUTH_TYPES = frozenset(
    {"none", "bearer_env", "api_key_env", "basic_env", "jwt_bearer"}
)
SUPPORTED_STORE_BACKENDS = frozenset({"memory", "redis"})


@dataclass(frozen=True)
class AuthProfile:
    """Authentication injected by the MCP server, never supplied by an LLM."""

    type: str = "none"
    token_env: str = ""
    api_key_env: str = ""
    api_key_header: str = "X-API-Key"
    username_env: str = ""
    password_env: str = ""
    login_path: str = "/auth/login"
    refresh_path: str = "/auth/refresh"
    token_json_path: str = "access_token"
    refresh_token_json_path: str = "refresh_token"
    expires_in_json_path: str = "expires_in"
    refresh_window_seconds: int = 300


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
class OutputResolutionPolicy:
    """Security and resource policy for resolving process output references.

    Same-origin references are enabled because the server base URL is already
    operator controlled. Cross-origin references remain disabled until their
    hosts are explicitly allowlisted. Authentication is never forwarded to a
    different origin.
    """

    enabled: bool = True
    allow_same_origin: bool = True
    allowed_hosts: tuple[str, ...] = ()
    allow_private_networks: bool = False
    allow_insecure_redirects: bool = False
    max_redirects: int = 3
    max_resolution_seconds: float = 60.0
    max_response_bytes: int = 5_000_000
    max_outputs: int = 20
    inline_preview_bytes: int = 0


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
    output_resolution: OutputResolutionPolicy = field(default_factory=OutputResolutionPolicy)

    def path(self, name: str, fallback: str) -> str:
        return self.paths.get(name, fallback)


@dataclass(frozen=True)
class StoreSettings:
    """Configuration for the pluggable plan/proxy-memory storage backend.

    backend="memory" (default) keeps all plan and proxy-memory state inside
    this process. It requires no setup and is correct for a single-worker
    stdio deployment, but a plan created on one process is invisible to any
    other worker, replica, or process restart.

    backend="redis" persists plan and proxy-memory state externally so a
    streamable-http deployment can run more than one worker or replica behind
    a load balancer. Requires the optional 'redis' extra and an environment
    variable (named by redis_url_env) holding the connection URL.
    """

    backend: str = "memory"
    redis_url_env: str = ""
    key_prefix: str = "ogc_mcp"
    plan_ttl_seconds: int = 3600
    memory_ttl_seconds: int = 1800
    artifact_ttl_seconds: int = 1800


@dataclass(frozen=True)
class ServerPolicy:
    """Operator-controlled toggles for the MCP tool surface itself.

    expose_direct_execution_tools defaults to False: ogc_processes_execute and
    ogc_jobs_dismiss are state-changing tools that, if registered, an LLM can
    call without ever going through the ogc_proxy_create_plan /
    ogc_proxy_confirm_plan human-confirmation gate. Leave this disabled unless
    you specifically need unmediated low-level access for interoperability
    testing.
    """

    expose_direct_execution_tools: bool = False


@dataclass(frozen=True)
class RegistrySettings:
    """Top-level configuration loaded from JSON."""

    servers: tuple[ServerProfile, ...]
    default_servers: dict[str, str] = field(default_factory=dict)
    store: StoreSettings = field(default_factory=StoreSettings)
    policy: ServerPolicy = field(default_factory=ServerPolicy)


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
    body: bytes = b""
    redirect_count: int = 0

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
