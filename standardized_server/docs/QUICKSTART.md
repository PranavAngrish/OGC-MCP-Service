# Quickstart

This guide gets the reference server running locally for development or desktop
MCP clients.

## Prerequisites

- Python 3.11 or newer.
- A JSON configuration file that registers at least one OGC API deployment.
- Optional: Redis, only if testing the Redis state backend.

The deterministic unit tests use mocked HTTP transports and do not require
public network access.

## Install

From the repository root:

```bash
python -m pip install -e standardized_server
```

For Redis-backed plan and memory state:

```bash
python -m pip install -e 'standardized_server[redis]'
```

## Configure

Use the example configuration as a starting point:

```bash
export OGC_MCP_CONFIG="$PWD/standardized_server/config.example.json"
```

The example registers:

- `pygeoapi-demo` for Common, Features, and Records;
- `geolabs-tb17` for Processes;
- in-memory plan and proxy-memory storage;
- direct process execution disabled by default.

For field-level details, see [Configuration](CONFIGURATION.md).

## Run With stdio

`stdio` is the normal local transport for desktop MCP clients:

```bash
python -m ogc_mcp_reference --config "$OGC_MCP_CONFIG" --transport stdio
```

The installed console script is equivalent:

```bash
ogc-mcp-server --config "$OGC_MCP_CONFIG" --transport stdio
```

## Run With Streamable HTTP

For HTTP-based testing:

```bash
OGC_MCP_HOST=127.0.0.1 OGC_MCP_PORT=8000 \
  ogc-mcp-server --config "$OGC_MCP_CONFIG" --transport streamable-http
```

If you run more than one worker process or replica, use Redis for plan and
proxy-memory state. See [Deployment](DEPLOYMENT.md).

## Claude Desktop Example

Use [`../examples/claude-desktop-config.json`](../examples/claude-desktop-config.json)
as a template:

```json
{
  "mcpServers": {
    "ogc-api-reference": {
      "command": "/absolute/path/to/python",
      "args": [
        "-m",
        "ogc_mcp_reference",
        "--config",
        "/absolute/path/to/standardized_server/config.example.json"
      ]
    }
  }
}
```

Make sure the Python environment used by the desktop client has the package
installed.

## Run Tests

From the repository root:

```bash
PYTHONPATH=standardized_server/src \
  python -m unittest discover -s standardized_server/tests -v
```

The suite covers configuration parsing, transport behavior, security checks,
input-schema validation, proxy planning, response summary mode, state storage,
and FastMCP tool registration.

## First Tool Calls

In an MCP client, a safe first exploration sequence is:

```text
ogc_servers_list
ogc_common_get_landing_page
ogc_proxy_get_capabilities
ogc_processes_list
```

For process execution, do not call direct execution unless the operator has
explicitly enabled it for interoperability testing. Use the proxy workflow in
[Proxy Workflow](PROXY_WORKFLOW.md).
