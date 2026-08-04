"""Bounded, authenticated HTTP transport for registered OGC APIs."""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit

import httpx

from .errors import (
    ConfigurationError,
    SecurityPolicyError,
    TransportError,
    UpstreamResponseError,
)
from .models import AuthProfile, OgcResponse, OutputResolutionPolicy, ServerProfile
from .security import validate_http_url, validate_relative_path
from .services.auth import TokenManager


@dataclass
class OutputResolutionBudget:
    """Shared resource budget for every reference resolved by one manifest.

    ``max_fetches`` counts every outbound HTTP request, including redirect
    hops. A pipeline creates one instance and passes it through all top-level
    and nested output references so each configured limit is genuinely
    aggregate rather than being reset for every output.
    """

    max_seconds: float
    max_bytes: int
    max_fetches: int
    clock: Callable[[], float] = field(
        default=time.monotonic,
        repr=False,
        compare=False,
    )
    started_at: float = field(init=False)
    consumed_bytes: int = 0
    fetches: int = 0

    def __post_init__(self) -> None:
        self.started_at = self.clock()

    @classmethod
    def from_policy(
        cls,
        policy: OutputResolutionPolicy,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> "OutputResolutionBudget":
        # max_outputs bounds independently advertised references, while
        # max_redirects bounds each chain. Their product gives the manifest a
        # deterministic HTTP-request ceiling without another operator setting.
        max_fetches = max(1, policy.max_outputs * (policy.max_redirects + 1))
        return cls(
            max_seconds=policy.max_resolution_seconds,
            max_bytes=policy.max_response_bytes,
            max_fetches=max_fetches,
            clock=clock,
        )

    def remaining_seconds(self, *, server_id: str) -> float:
        remaining = self.max_seconds - (self.clock() - self.started_at)
        if remaining <= 0:
            raise TransportError(
                "Process output resolution exceeded the configured aggregate time limit.",
                server_id=server_id,
                max_resolution_seconds=self.max_seconds,
            )
        return remaining

    def claim_fetch(self, *, server_id: str) -> float:
        """Reserve one HTTP request and return the remaining wall-clock time."""
        remaining = self.remaining_seconds(server_id=server_id)
        if self.fetches >= self.max_fetches:
            raise TransportError(
                "Process output resolution exceeded the configured aggregate fetch limit.",
                server_id=server_id,
                max_fetches=self.max_fetches,
            )
        self.fetches += 1
        return remaining

    def consume_bytes(self, amount: int, *, server_id: str) -> None:
        self.consumed_bytes += amount
        if self.consumed_bytes > self.max_bytes:
            raise TransportError(
                "Process output resolution exceeded the configured aggregate size limit.",
                server_id=server_id,
                max_response_bytes=self.max_bytes,
            )


class OgcHttpClient:
    """Perform bounded requests against operator-approved OGC servers."""

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        token_manager: TokenManager | None = None,
    ) -> None:
        self._transport = transport
        self._token_manager = token_manager or TokenManager(transport=transport)

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
        if auth.type == "jwt_bearer":
            return self._token_manager.bearer_header(server)
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
        result = self._request_once(
            server,
            method,
            path,
            query=query,
            json_body=json_body,
            accept=accept,
            prefer=prefer,
        )
        if result.status_code == 401 and server.auth.type == "jwt_bearer":
            self._token_manager.invalidate(server.id)
            result = self._request_once(
                server,
                method,
                path,
                query=query,
                json_body=json_body,
                accept=accept,
                prefer=prefer,
            )

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

    def _request_once(
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
        """Send one bounded HTTP request and return the upstream status unchanged."""
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
                        body=bytes(body),
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

        return result

    @staticmethod
    def _origin(url: str) -> tuple[str, str, int | None]:
        parsed = urlsplit(url)
        port = parsed.port
        if port is None:
            port = 443 if parsed.scheme.lower() == "https" else 80
        return parsed.scheme.lower(), (parsed.hostname or "").lower().rstrip("."), port

    def fetch_output_reference(
        self,
        server: ServerProfile,
        href: str,
        policy: OutputResolutionPolicy,
        *,
        budget: OutputResolutionBudget | None = None,
    ) -> OgcResponse:
        """Resolve one bounded process-output reference.

        Redirects are followed manually so every hop is revalidated. Same
        origin requests may receive the registered server's credentials;
        credentials are never forwarded to a different scheme/host/port.
        """
        if not policy.enabled:
            raise TransportError(
                "Process output reference resolution is disabled by operator policy.",
                server_id=server.id,
            )
        current_url = urljoin(f"{server.base_url}/", href)
        server_origin = self._origin(server.base_url)
        redirect_count = 0
        previous_url = ""
        resolution_budget = budget or OutputResolutionBudget.from_policy(policy)

        while True:
            current_origin = self._origin(current_url)
            same_origin = current_origin == server_origin
            if same_origin:
                if not policy.allow_same_origin:
                    raise TransportError(
                        "Same-origin process output references are disabled by operator policy.",
                        server_id=server.id,
                    )
                # The operator already approved the registered base URL. Still
                # reject embedded credentials and non-HTTP schemes.
                validate_http_url(
                    current_url,
                    allow_private_networks=server.security.allow_private_networks,
                    label="Process output reference",
                )
            else:
                if not policy.allowed_hosts:
                    raise SecurityPolicyError(
                        "Cross-origin process output reference is not operator-approved.",
                        server_id=server.id,
                        host=current_origin[1],
                    )
                validate_http_url(
                    current_url,
                    allow_private_networks=(
                        policy.allow_private_networks
                        and server.security.allow_private_networks
                    ),
                    allowed_hosts=policy.allowed_hosts,
                    label="Process output reference",
                )
            if (
                previous_url
                and urlsplit(previous_url).scheme.lower() == "https"
                and urlsplit(current_url).scheme.lower() == "http"
                and not policy.allow_insecure_redirects
            ):
                raise SecurityPolicyError(
                    "HTTPS-to-HTTP process output redirects are disabled.",
                    server_id=server.id,
                )

            headers = {"Accept": "*/*"}
            if same_origin:
                headers.update(self._auth_headers(server))
            try:
                remaining_seconds = resolution_budget.claim_fetch(server_id=server.id)
                with httpx.Client(
                    transport=self._transport,
                    timeout=min(server.limits.timeout_seconds, remaining_seconds),
                    follow_redirects=False,
                ) as client:
                    with client.stream("GET", current_url, headers=headers) as response:
                        body = bytearray()
                        for chunk in response.iter_bytes():
                            resolution_budget.remaining_seconds(server_id=server.id)
                            body.extend(chunk)
                            resolution_budget.consume_bytes(
                                len(chunk),
                                server_id=server.id,
                            )
                        status_code = response.status_code
                        response_headers = {
                            key.lower(): value for key, value in response.headers.items()
                        }
                        content_type = response.headers.get("content-type", "")
            except TransportError:
                raise
            except httpx.HTTPError as exc:
                raise TransportError(
                    "Unable to retrieve the referenced process output.",
                    server_id=server.id,
                    reason=str(exc),
                ) from exc

            if status_code in {301, 302, 303, 307, 308}:
                location = response_headers.get("location", "")
                if not location:
                    raise TransportError(
                        "Process output redirect did not include a Location header.",
                        server_id=server.id,
                        status_code=status_code,
                    )
                redirect_count += 1
                if redirect_count > policy.max_redirects:
                    raise TransportError(
                        "Process output exceeded the configured redirect limit.",
                        server_id=server.id,
                        max_redirects=policy.max_redirects,
                    )
                previous_url = current_url
                current_url = urljoin(current_url, location)
                continue
            if 300 <= status_code < 400:
                raise TransportError(
                    "Referenced process output returned an unsupported redirect response.",
                    server_id=server.id,
                    status_code=status_code,
                )
            if status_code >= 400:
                data = self._decode(bytes(body), content_type)
                raise UpstreamResponseError(
                    "The referenced process output returned an error response.",
                    status_code=status_code,
                    server_id=server.id,
                    method="GET",
                    path=urlsplit(current_url).path,
                    response=data,
                )

            return OgcResponse(
                server_id=server.id,
                method="GET",
                path=urlsplit(current_url).path or "/",
                status_code=status_code,
                headers=response_headers,
                content_type=content_type,
                data=self._decode(bytes(body), content_type),
                body=bytes(body),
                redirect_count=redirect_count,
            )

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
