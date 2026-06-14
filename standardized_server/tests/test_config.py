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


if __name__ == "__main__":
    unittest.main()
