"""Outbound URL and process-reference validation."""

from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlparse

from .errors import SecurityPolicyError
from .models import SecurityPolicy


def _is_private_hostname(hostname: str) -> bool:
    lowered = hostname.lower().rstrip(".")
    if lowered == "localhost" or lowered.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        return False
    return not address.is_global


def host_matches(hostname: str, pattern: str) -> bool:
    """Match exact hosts or explicit wildcard subdomains such as *.example.org."""
    hostname = hostname.lower().rstrip(".")
    pattern = pattern.lower().rstrip(".")
    if pattern.startswith("*."):
        suffix = pattern[1:]
        return hostname.endswith(suffix) and hostname != suffix[1:]
    return hostname == pattern


def validate_http_url(
    url: str,
    *,
    allow_private_networks: bool,
    allowed_hosts: tuple[str, ...] = (),
    label: str = "URL",
) -> str:
    """Validate scheme, host, credentials, private-network access, and allowlist."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise SecurityPolicyError(f"{label} must use http or https.", url=url)
    if not parsed.hostname:
        raise SecurityPolicyError(f"{label} must include a hostname.", url=url)
    if parsed.username or parsed.password:
        raise SecurityPolicyError(f"{label} must not embed credentials.", url=url)
    if not allow_private_networks and _is_private_hostname(parsed.hostname):
        raise SecurityPolicyError(f"{label} targets a private or loopback address.", url=url)
    if allowed_hosts and not any(host_matches(parsed.hostname, host) for host in allowed_hosts):
        raise SecurityPolicyError(
            f"{label} host '{parsed.hostname}' is not operator-approved.",
            url=url,
            allowed_hosts=list(allowed_hosts),
        )
    return url


def validate_relative_path(path: str) -> str:
    """Allow only relative upstream paths, never caller-controlled absolute URLs."""
    if not path.startswith("/") or path.startswith("//"):
        raise SecurityPolicyError("Upstream path must start with one '/'.", path=path)
    if "://" in path:
        raise SecurityPolicyError("Upstream path must not contain an absolute URL.", path=path)
    return path


def _walk_urls(value: Any, *, depth: int = 0) -> list[str]:
    if depth > 40:
        raise SecurityPolicyError("Execute payload nesting is too deep.")
    if isinstance(value, dict):
        urls: list[str] = []
        for item in value.values():
            urls.extend(_walk_urls(item, depth=depth + 1))
        return urls
    if isinstance(value, list):
        urls = []
        for item in value:
            urls.extend(_walk_urls(item, depth=depth + 1))
        return urls
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return [value]
    return []


def validate_execute_references(payload: Any, policy: SecurityPolicy) -> None:
    """Validate every HTTP(S) reference found in a process execution body."""
    if not policy.validate_execute_references:
        return
    urls = _walk_urls(payload)
    if urls and not policy.allowed_reference_hosts and not policy.allow_unlisted_reference_hosts:
        raise SecurityPolicyError(
            "Process input references are disabled until the operator configures allowed_reference_hosts."
        )
    for url in urls:
        validate_http_url(
            url,
            allow_private_networks=policy.allow_private_networks,
            allowed_hosts=() if policy.allow_unlisted_reference_hosts else policy.allowed_reference_hosts,
            label="Process input reference",
        )
