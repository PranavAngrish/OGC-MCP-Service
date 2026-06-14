# OGC API MCP Reference Server

This folder contains a specification-oriented MCP reference server for OGC APIs.
It is designed for review, experimentation, and interoperability work across AI
clients and OGC API implementations.

The implementation is intentionally separate from the earlier single-file
prototype. It is not an adopted OGC Standard. The versioned contract under
`spec/` is an experimental project artifact that can evolve through review,
implementation experience, and conformance testing.

## Goals

- Provide stable MCP tool names for common OGC API workflows.
- Work with any AI client that supports MCP.
- Connect to any operator-registered OGC API deployment.
- Keep credentials outside model-visible tool arguments.
- Support OGC API discovery before execution.
- Preserve process-specific input/output structures exactly as advertised.
- Restrict outbound requests and referenced inputs by default.
- Return predictable structured JSON envelopes.
- Make additional OGC API modules easy to add.

## Supported Modules

| Module | MCP Operations |
| --- | --- |
| Registry | List approved OGC API deployments |
| OGC API - Common | Landing page, conformance, safe read-only relative resource access |
| OGC API - Features | List collections, describe collection, get items, get item |
| OGC API - Records | List catalogues, search records, get record |
| OGC API - Processes | List processes, describe, execute, list/status/results/dismiss jobs |

The read-only `ogc_common_get_resource` tool is a controlled extension point for
registered OGC APIs that do not yet have dedicated MCP tools, such as EDR,
Coverages, Tiles, Maps, or Styles.

## Architecture

```text
AI client
   |
   | MCP: stdio or Streamable HTTP
   v
FastMCP app
   |
   +-- stable ogc_* tool contract
   +-- structured result envelopes
   |
   v
OGC service modules
   |
   +-- Common
   +-- Features
   +-- Records
   +-- Processes
   |
   v
Registry -> security policy -> bounded HTTP transport -> registered OGC APIs
```

See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for design rationale.

## Quick Start

From the `gsoc-mcp` repository:

```bash
source venv/bin/activate
pip install -e standardized_server

python -m ogc_mcp_reference \
  --config standardized_server/config.example.json
```

The default transport is `stdio`, suitable for desktop AI clients.

For a deployed MCP endpoint:

```bash
python -m ogc_mcp_reference \
  --config standardized_server/config.example.json \
  --transport streamable-http
```

The official MCP Python SDK recommends stateless Streamable HTTP with JSON
responses for scalable deployments. This reference server enables those options.

## Desktop Client Configuration

Use [claude-desktop-config.json](examples/claude-desktop-config.json) as a
template. Any MCP-compatible client can launch the same `stdio` entrypoint.

## GeoLabs Delaunay Test

Start the MCP server with `config.example.json`, then ask the MCP client to:

1. Call `ogc_processes_list` with `server_id="geolabs"`.
2. Call `ogc_processes_describe` with `process_id="Delaunay"`.
3. Call `ogc_processes_execute` with:

```json
{
  "server_id": "geolabs",
  "process_id": "Delaunay",
  "execute_request_json": "{\"inputs\":{\"InputPoints\":{\"type\":\"text/xml\",\"href\":\"https://demo.pygeoapi.io/master/collections/dutch_windmills/items?f=json\"}},\"outputs\":{\"Result\":{\"format\":{\"mediaType\":\"application/json\"},\"transmissionMode\":\"value\"}}}"
}
```

The unescaped body is available in
[geolabs-delaunay-execute.json](examples/geolabs-delaunay-execute.json).

## Operator Configuration

Copy `config.example.json` and register the deployments your organization
approves. Tool callers select a `server_id`, not an arbitrary base URL.

Authentication configuration references environment-variable names only:

```json
{
  "auth": {
    "type": "bearer_env",
    "token_env": "MY_OGC_API_TOKEN"
  }
}
```

Supported auth modes:

- `none`
- `bearer_env`
- `api_key_env`
- `basic_env`

The model never receives secret values.

## Security Model

- Only registered upstream deployments are callable.
- Generic reads accept relative paths only.
- Private and loopback networks are blocked unless the operator explicitly
  enables them for a profile.
- Process execution payloads are scanned recursively for HTTP(S) references.
- Referenced input URLs are blocked until the operator configures an allowlist
  or explicitly enables unlisted public reference hosts.
- Redirects are returned to the caller but not followed automatically.
- Upstream response size and request timeout are bounded per profile.

Application-level checks should be combined with network egress controls in
production.

## Tests

```bash
PYTHONPATH=standardized_server/src \
  python -m unittest discover -s standardized_server/tests -v
```

The test suite does not depend on public network availability.

## Versioned Artifacts

- `spec/ogc-mcp-tool-contract.json`: experimental MCP tool contract
- `schemas/server-config.schema.json`: operator configuration schema
- `docs/CONFORMANCE.md`: checklist for future independent implementations
