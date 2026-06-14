from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ogc_mcp_reference.app import create_mcp_server


class AppTests(unittest.TestCase):
    def test_creates_fastmcp_server_from_config(self) -> None:
        config = {
            "default_servers": {"common": "example"},
            "servers": [
                {
                    "id": "example",
                    "base_url": "https://example.org",
                    "services": ["common"],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            server = create_mcp_server(path)
        self.assertEqual(server.name, "OGC API MCP Reference Server")


if __name__ == "__main__":
    unittest.main()
