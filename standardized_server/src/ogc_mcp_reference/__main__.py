"""Command-line entrypoint for stdio and Streamable HTTP transports."""

from __future__ import annotations

import argparse
import os

from .app import create_mcp_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the OGC API MCP reference server.")
    parser.add_argument(
        "--config",
        default=os.environ.get("OGC_MCP_CONFIG", ""),
        help="Path to the operator-owned JSON configuration file.",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http", "sse"),
        default=os.environ.get("OGC_MCP_TRANSPORT", "stdio"),
        help="MCP transport. Use stdio for desktop clients and streamable-http for deployment.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    mcp = create_mcp_server(args.config or None)
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
