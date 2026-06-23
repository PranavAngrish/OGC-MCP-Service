from __future__ import annotations

import unittest

from ogc_mcp_reference.config import parse_settings
from ogc_mcp_reference.errors import ConfigurationError
from ogc_mcp_reference.registry import ServerRegistry


class ConfigurationTests(unittest.TestCase):
    def test_parses_minimal_server(self) -> None:
        settings = parse_settings(
            {
                "default_servers": {"common": "example"},
                "servers": [
                    {
                        "id": "example",
                        "base_url": "https://example.org",
                        "services": ["common"],
                    }
                ],
            }
        )
        registry = ServerRegistry(settings)
        self.assertEqual(registry.get(service="common").id, "example")

    def test_rejects_duplicate_server_ids(self) -> None:
        with self.assertRaises(ConfigurationError):
            parse_settings(
                {
                    "servers": [
                        {"id": "same", "base_url": "https://one.example", "services": ["common"]},
                        {"id": "same", "base_url": "https://two.example", "services": ["common"]},
                    ]
                }
            )

    def test_rejects_unknown_service(self) -> None:
        with self.assertRaises(ConfigurationError):
            parse_settings(
                {
                    "servers": [
                        {
                            "id": "example",
                            "base_url": "https://example.org",
                            "services": ["imaginary"],
                        }
                    ]
                }
            )

    def test_rejects_default_for_service_not_enabled_by_server(self) -> None:
        settings = parse_settings(
            {
                "default_servers": {"processes": "example"},
                "servers": [
                    {
                        "id": "example",
                        "base_url": "https://example.org",
                        "services": ["common"],
                    }
                ],
            }
        )
        with self.assertRaises(ConfigurationError):
            ServerRegistry(settings)

    def test_rejects_string_boolean_values(self) -> None:
        with self.assertRaises(ConfigurationError):
            parse_settings(
                {
                    "servers": [
                        {
                            "id": "example",
                            "base_url": "https://example.org",
                            "services": ["common"],
                            "security": {"allow_private_networks": "false"},
                        }
                    ]
                }
            )

    def test_parses_jwt_bearer_auth_profile(self) -> None:
        settings = parse_settings(
            {
                "servers": [
                    {
                        "id": "example",
                        "base_url": "https://example.org",
                        "services": ["common"],
                        "auth": {
                            "type": "jwt_bearer",
                            "username_env": "OGC_USER",
                            "password_env": "OGC_PASS",
                            "login_path": "/auth/login",
                        },
                    }
                ]
            }
        )
        self.assertEqual(settings.servers[0].auth.type, "jwt_bearer")
        self.assertEqual(settings.servers[0].auth.login_path, "/auth/login")


if __name__ == "__main__":
    unittest.main()
