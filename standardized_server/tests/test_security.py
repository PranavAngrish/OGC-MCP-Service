from __future__ import annotations

import unittest

from ogc_mcp_reference.errors import SecurityPolicyError
from ogc_mcp_reference.models import SecurityPolicy
from ogc_mcp_reference.registry import ServerRegistry
from ogc_mcp_reference.security import (
    host_matches,
    validate_execute_references,
    validate_http_url,
    validate_relative_path,
)
from helpers import build_registry


class SecurityTests(unittest.TestCase):
    def test_rejects_private_base_url_by_default(self) -> None:
        with self.assertRaises(SecurityPolicyError):
            build_registry(base_url="http://127.0.0.1")

    def test_allows_private_base_url_when_explicit(self) -> None:
        registry: ServerRegistry = build_registry(
            base_url="http://127.0.0.1",
            security={"allow_private_networks": True},
        )
        self.assertEqual(registry.get(service="common").base_url, "http://127.0.0.1")

    def test_rejects_absolute_generic_path(self) -> None:
        with self.assertRaises(SecurityPolicyError):
            validate_relative_path("https://evil.example/path")

    def test_reference_allowlist_is_enforced_recursively(self) -> None:
        policy = SecurityPolicy(allowed_reference_hosts=("demo.pygeoapi.io",))
        validate_execute_references(
            {"inputs": {"points": {"href": "https://demo.pygeoapi.io/master/items"}}},
            policy,
        )
        with self.assertRaises(SecurityPolicyError):
            validate_execute_references(
                {"inputs": {"points": {"href": "https://evil.example/items"}}},
                policy,
            )

    def test_reference_urls_are_disabled_until_operator_configures_policy(self) -> None:
        with self.assertRaises(SecurityPolicyError):
            validate_execute_references(
                {"inputs": {"points": {"href": "https://public.example/items"}}},
                SecurityPolicy(),
            )

    def test_wildcard_hosts_match_subdomains_only(self) -> None:
        self.assertTrue(host_matches("api.example.org", "*.example.org"))
        self.assertFalse(host_matches("example.org", "*.example.org"))

    def test_embedded_credentials_are_rejected(self) -> None:
        with self.assertRaises(SecurityPolicyError):
            validate_http_url(
                "https://user:password@example.org/path",
                allow_private_networks=False,
            )


if __name__ == "__main__":
    unittest.main()
