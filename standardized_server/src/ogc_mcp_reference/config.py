"""Load and validate operator-owned JSON configuration."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .errors import ConfigurationError
from .models import (
    SUPPORTED_AUTH_TYPES,
    SUPPORTED_SERVICES,
    AuthProfile,
    RegistrySettings,
    RequestLimits,
    SecurityPolicy,
    ServerProfile,
)


DEFAULT_CONFIG_ENV = "OGC_MCP_CONFIG"


def _as_object(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigurationError(f"{label} must be a JSON object.")
    return value


def _as_string_tuple(value: Any, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigurationError(f"{label} must be a JSON array of strings.")
    return tuple(value)


def _load_auth(value: Any, server_id: str) -> AuthProfile:
    raw = _as_object(value, f"servers.{server_id}.auth")
    auth_type = str(raw.get("type", "none"))
    if auth_type not in SUPPORTED_AUTH_TYPES:
        raise ConfigurationError(
            f"servers.{server_id}.auth.type must be one of {sorted(SUPPORTED_AUTH_TYPES)}."
        )
    return AuthProfile(
        type=auth_type,
        token_env=str(raw.get("token_env", "")),
        api_key_env=str(raw.get("api_key_env", "")),
        api_key_header=str(raw.get("api_key_header", "X-API-Key")),
        username_env=str(raw.get("username_env", "")),
        password_env=str(raw.get("password_env", "")),
    )


def _load_security(value: Any, server_id: str) -> SecurityPolicy:
    raw = _as_object(value, f"servers.{server_id}.security")
    return SecurityPolicy(
        allow_private_networks=bool(raw.get("allow_private_networks", False)),
        allowed_reference_hosts=_as_string_tuple(
            raw.get("allowed_reference_hosts", []),
            f"servers.{server_id}.security.allowed_reference_hosts",
        ),
        allow_unlisted_reference_hosts=bool(raw.get("allow_unlisted_reference_hosts", False)),
        validate_execute_references=bool(raw.get("validate_execute_references", True)),
    )


def _load_limits(value: Any, server_id: str) -> RequestLimits:
    raw = _as_object(value, f"servers.{server_id}.limits")
    timeout_seconds = float(raw.get("timeout_seconds", 30))
    max_response_bytes = int(raw.get("max_response_bytes", 1_000_000))
    if timeout_seconds <= 0:
        raise ConfigurationError(f"servers.{server_id}.limits.timeout_seconds must be positive.")
    if max_response_bytes <= 0:
        raise ConfigurationError(f"servers.{server_id}.limits.max_response_bytes must be positive.")
    return RequestLimits(
        timeout_seconds=timeout_seconds,
        max_response_bytes=max_response_bytes,
    )


def _load_server(raw: Any, index: int) -> ServerProfile:
    if not isinstance(raw, dict):
        raise ConfigurationError(f"servers[{index}] must be a JSON object.")

    server_id = str(raw.get("id", "")).strip()
    base_url = str(raw.get("base_url", "")).strip().rstrip("/")
    if not server_id:
        raise ConfigurationError(f"servers[{index}].id is required.")
    if not base_url:
        raise ConfigurationError(f"servers.{server_id}.base_url is required.")

    services = _as_string_tuple(raw.get("services"), f"servers.{server_id}.services")
    if not services:
        raise ConfigurationError(f"servers.{server_id}.services must not be empty.")
    unknown_services = sorted(set(services) - SUPPORTED_SERVICES)
    if unknown_services:
        raise ConfigurationError(
            f"servers.{server_id}.services contains unsupported values.",
            unsupported_services=unknown_services,
        )

    paths = _as_object(raw.get("paths"), f"servers.{server_id}.paths")
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in paths.items()):
        raise ConfigurationError(f"servers.{server_id}.paths must map strings to strings.")

    defaults = _as_object(raw.get("defaults"), f"servers.{server_id}.defaults")
    return ServerProfile(
        id=server_id,
        title=str(raw.get("title", server_id)),
        base_url=base_url,
        services=frozenset(services),
        description=str(raw.get("description", "")),
        enabled=bool(raw.get("enabled", True)),
        paths=dict(paths),
        defaults=dict(defaults),
        auth=_load_auth(raw.get("auth"), server_id),
        security=_load_security(raw.get("security"), server_id),
        limits=_load_limits(raw.get("limits"), server_id),
    )


def parse_settings(raw: Any) -> RegistrySettings:
    """Parse already-decoded JSON settings."""
    root = _as_object(raw, "configuration")
    raw_servers = root.get("servers")
    if not isinstance(raw_servers, list) or not raw_servers:
        raise ConfigurationError("configuration.servers must be a non-empty JSON array.")

    servers = tuple(_load_server(server, index) for index, server in enumerate(raw_servers))
    ids = [server.id for server in servers]
    if len(ids) != len(set(ids)):
        raise ConfigurationError("Each servers[].id value must be unique.")

    default_servers = _as_object(root.get("default_servers"), "default_servers")
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in default_servers.items()):
        raise ConfigurationError("default_servers must map service names to server IDs.")

    return RegistrySettings(servers=servers, default_servers=dict(default_servers))


def load_settings(path: str | Path | None = None) -> RegistrySettings:
    """Load settings from a JSON file path or OGC_MCP_CONFIG."""
    configured_path = path or os.environ.get(DEFAULT_CONFIG_ENV)
    if not configured_path:
        raise ConfigurationError(
            f"Set {DEFAULT_CONFIG_ENV} to a JSON configuration file path or pass config_path explicitly."
        )

    config_path = Path(configured_path).expanduser()
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Configuration file not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"Configuration file is not valid JSON: {exc}") from exc

    return parse_settings(raw)
