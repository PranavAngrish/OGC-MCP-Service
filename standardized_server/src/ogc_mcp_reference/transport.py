"""Bounded, authenticated HTTP transport for registered OGC APIs."""

from __future__ import annotations

import base64
import json
import os
from typing import Any

import httpx

from .errors import ConfigurationError, TransportError, UpstreamResponseError
from .models import AuthProfile, OgcResponse, ServerProfile
from .security import validate_relative_path


class OgcHttpClient:
    """Perform bounded requests against operator-approved OGC servers."""

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport

    def _required_env(self, name: str, *, server_id: str) -> str:
        if not name:
            raise ConfigurationError(f"Authentication environment variable name is missing for '{server_id}'.")
        value = os.environ.get(name)
        if not value:
            raise ConfigurationError(
                f"Required authentication environment variable '{name}' is not set.",
                server_id=server_id,
            )
        return value

    def _auth_headers(self, server: ServerProfile) -> dict[str, str]:
        auth: AuthProfile = server.auth
        if auth.type == "none":
            return {}
        if auth.type == "bearer_env":
            return {"Authorization": f"Bearer {self._required_env(auth.token_env, server_id=server.id)}"}
        if auth.type == "api_key_env":
            return {
                auth.api_key_header: self._required_env(auth.api_key_env, server_id=server.id)
            }
        if auth.type == "basic_env":
            username = self._required_env(auth.username_env, server_id=server.id)
            password = self._required_env(auth.password_env, server_id=server.id)
            token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
            return {"Authorization": f"Basic {token}"}
        raise ConfigurationError(f"Unsupported authentication type '{auth.type}'.")

    def request(
        self,
        server: ServerProfile,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        json_body: Any = None,
        accept: str = "application/json",
        prefer: str = "",
    ) -> OgcResponse:
        """Send one request without following redirects."""
        validate_relative_path(path)
        headers = {"Accept": accept, **self._auth_headers(server)}
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        if prefer:
            headers["Prefer"] = prefer

        url = f"{server.base_url}{path}"
        try:
            with httpx.Client(
                transport=self._transport,
                timeout=server.limits.timeout_seconds,
                follow_redirects=False,
            ) as client:
                with client.stream(
                    method.upper(),
                    url,
                    headers=headers,
                    params=query,
                    json=json_body,
                ) as response:
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > server.limits.max_response_bytes:
                            raise TransportError(
                                "Upstream response exceeded the configured size limit.",
                                server_id=server.id,
                                max_response_bytes=server.limits.max_response_bytes,
                            )
                    content_type = response.headers.get("content-type", "")
                    data = self._decode(bytes(body), content_type)
                    result = OgcResponse(
                        server_id=server.id,
                        method=method.upper(),
                        path=path,
                        status_code=response.status_code,
                        headers={key.lower(): value for key, value in response.headers.items()},
                        content_type=content_type,
                        data=data,
                    )
        except TransportError:
            raise
        except httpx.HTTPError as exc:
            raise TransportError(
                "Unable to reach the configured OGC API server.",
                server_id=server.id,
                method=method.upper(),
                path=path,
                reason=str(exc),
            ) from exc

        if result.status_code >= 400:
            raise UpstreamResponseError(
                "The upstream OGC API returned an error response.",
                status_code=result.status_code,
                server_id=server.id,
                method=result.method,
                path=result.path,
                response=result.data,
            )
        return result

    @staticmethod
    def _decode(body: bytes, content_type: str) -> Any:
        if not body:
            return None
        text = body.decode("utf-8", errors="replace")
        if "json" in content_type.lower() or text.lstrip().startswith(("{", "[")):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
        return text
