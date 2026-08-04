from __future__ import annotations

import json
import unittest
from pathlib import Path

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

    def test_output_resolution_has_model_safe_defaults(self) -> None:
        settings = parse_settings(
            {
                "servers": [
                    {
                        "id": "example",
                        "base_url": "https://example.org",
                        "services": ["processes"],
                    }
                ]
            }
        )
        policy = settings.servers[0].output_resolution
        self.assertTrue(policy.enabled)
        self.assertTrue(policy.allow_same_origin)
        self.assertEqual(policy.allowed_hosts, ())
        self.assertFalse(policy.allow_private_networks)
        self.assertFalse(policy.allow_insecure_redirects)
        self.assertEqual(policy.inline_preview_bytes, 0)
        self.assertEqual(settings.store.artifact_ttl_seconds, 1800)

    def test_parses_explicit_output_resolution_policy(self) -> None:
        settings = parse_settings(
            {
                "store": {"artifact_ttl_seconds": 600},
                "servers": [
                    {
                        "id": "example",
                        "base_url": "https://example.org",
                        "services": ["processes"],
                        "output_resolution": {
                            "allowed_hosts": ["outputs.example.org"],
                            "max_redirects": 2,
                            "max_resolution_seconds": 12.5,
                            "max_response_bytes": 12345,
                            "max_outputs": 5,
                            "inline_preview_bytes": 0,
                        },
                    }
                ],
            }
        )
        policy = settings.servers[0].output_resolution
        self.assertEqual(policy.allowed_hosts, ("outputs.example.org",))
        self.assertEqual(policy.max_redirects, 2)
        self.assertEqual(policy.max_resolution_seconds, 12.5)
        self.assertEqual(policy.max_response_bytes, 12345)
        self.assertEqual(policy.max_outputs, 5)
        self.assertEqual(settings.store.artifact_ttl_seconds, 600)

    def test_rejects_max_outputs_above_manifest_contract(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "must be at most 100"):
            parse_settings(
                {
                    "servers": [
                        {
                            "id": "example",
                            "base_url": "https://example.org",
                            "services": ["processes"],
                            "output_resolution": {"max_outputs": 101},
                        }
                    ]
                }
            )

    def test_server_config_schema_enforces_max_outputs_contract(self) -> None:
        try:
            import jsonschema
        except ImportError:
            return
        schema_path = (
            Path(__file__).resolve().parents[1]
            / "schemas"
            / "server-config.schema.json"
        )
        validator = jsonschema.Draft202012Validator(
            json.loads(schema_path.read_text(encoding="utf-8"))
        )
        config = {
            "servers": [
                {
                    "id": "example",
                    "base_url": "https://example.org",
                    "services": ["processes"],
                    "output_resolution": {"max_outputs": 100},
                }
            ]
        }
        validator.validate(config)
        config["servers"][0]["output_resolution"]["max_outputs"] = 101
        with self.assertRaises(jsonschema.ValidationError):
            validator.validate(config)


if __name__ == "__main__":
    unittest.main()
