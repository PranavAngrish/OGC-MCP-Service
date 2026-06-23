"""Token lifecycle management for authenticated OGC API profiles."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from ..errors import ConfigurationError, TransportError
from ..models import ServerProfile
from ..security import validate_relative_path


@dataclass
class CachedToken:
    """One cached bearer token and its refresh metadata."""

    access_token: str
    refresh_token: str = ""
    expires_at: float = 0.0

    def needs_refresh(self, now: float, refresh_window_seconds: int) -> bool:
        return self.expires_at <= 0 or self.expires_at - now <= refresh_window_seconds


class TokenManager:
    """Authenticate JWT-backed profiles without exposing credentials to MCP callers."""

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._transport = transport
        self._now = now or time.time
        self._tokens: dict[str, CachedToken] = {}

    def bearer_header(self, server: ServerProfile) -> dict[str, str]:
        """Return Authorization headers for a jwt_bearer profile."""
        if server.auth.type != "jwt_bearer":
            return {}
        token = self.get_token(server)
        return {"Authorization": f"Bearer {token.access_token}"}

    def get_token(self, server: ServerProfile) -> CachedToken:
        """Return a valid token, logging in or refreshing when required."""
        cached = self._tokens.get(server.id)
        if not cached:
            cached = self.login(server)
        elif cached.needs_refresh(self._now(), server.auth.refresh_window_seconds):
            cached = self.refresh(server, cached)
        return cached

    def invalidate(self, server_id: str) -> None:
        """Forget a token after a 401 so the next call performs a fresh login."""
        self._tokens.pop(server_id, None)

    def login(self, server: ServerProfile) -> CachedToken:
        """Login with operator-owned credentials referenced by environment variables."""
        username = self._required_env(server.auth.username_env, server_id=server.id)
        password = self._required_env(server.auth.password_env, server_id=server.id)
        token = self._request_token(
            server,
            server.auth.login_path,
            {"username": username, "password": password},
            label="login",
        )
        self._tokens[server.id] = token
        return token

    def refresh(self, server: ServerProfile, cached: CachedToken) -> CachedToken:
        """Refresh a token when possible; fall back to login if no refresh token exists."""
        if not cached.refresh_token:
            return self.login(server)
        try:
            token = self._request_token(
                server,
                server.auth.refresh_path,
                {"refresh_token": cached.refresh_token},
                label="refresh",
            )
        except TransportError:
            token = self.login(server)
        self._tokens[server.id] = token
        return token

    def retry_after_unauthorized(self, server: ServerProfile) -> dict[str, str]:
        """Force a fresh login and return replacement headers for a single retry."""
        self.invalidate(server.id)
        return self.bearer_header(server)

    def _request_token(
        self,
        server: ServerProfile,
        path: str,
        payload: dict[str, str],
        *,
        label: str,
    ) -> CachedToken:
        validate_relative_path(path)
        url = f"{server.base_url}{path}"
        try:
            with httpx.Client(
                transport=self._transport,
                timeout=server.limits.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = client.post(
                    url,
                    json=payload,
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                )
        except httpx.HTTPError as exc:
            raise TransportError(
                f"Unable to reach the configured OGC API {label} endpoint.",
                server_id=server.id,
                path=path,
                reason=str(exc),
            ) from exc
        if response.status_code >= 400:
            raise TransportError(
                f"The configured OGC API {label} endpoint rejected authentication.",
                server_id=server.id,
                path=path,
                status_code=response.status_code,
            )
        data = self._decode_json(response.content, server_id=server.id, path=path)
        access_token = str(self._json_path(data, server.auth.token_json_path, default=""))
        if not access_token:
            raise ConfigurationError(
                "Authentication response did not contain an access token.",
                server_id=server.id,
                token_json_path=server.auth.token_json_path,
            )
        refresh_token = str(self._json_path(data, server.auth.refresh_token_json_path, default=""))
        expires_in = self._expires_in(data, server)
        return CachedToken(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=self._now() + expires_in,
        )

    def _expires_in(self, data: Any, server: ServerProfile) -> int:
        raw = self._json_path(data, server.auth.expires_in_json_path, default=3600)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = 3600
        return max(value, 1)

    @staticmethod
    def _required_env(name: str, *, server_id: str) -> str:
        if not name:
            raise ConfigurationError(
                f"Authentication environment variable name is missing for '{server_id}'."
            )
        value = os.environ.get(name)
        if not value:
            raise ConfigurationError(
                f"Required authentication environment variable '{name}' is not set.",
                server_id=server_id,
            )
        return value

    @staticmethod
    def _decode_json(body: bytes, *, server_id: str, path: str) -> Any:
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise TransportError(
                "Authentication response was not valid JSON.",
                server_id=server_id,
                path=path,
            ) from exc

    @staticmethod
    def _json_path(data: Any, path: str, *, default: Any = None) -> Any:
        current = data
        for segment in path.split("."):
            if not segment:
                continue
            if not isinstance(current, dict) or segment not in current:
                return default
            current = current[segment]
        return current
