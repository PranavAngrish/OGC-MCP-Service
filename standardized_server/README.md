# OGC API MCP Bridge

An experimental reference bridge between natural-language MCP clients and OGC
API deployments. It was developed as part of a GSoC 2026 project with 52North:
MCP for OGC APIs.

The project has two main artifacts:

- `spec/ogc-mcp-mapping.json`: an early mapping specification for representing
  OGC API operations as MCP tools.
- `standardized_server/`: a Python FastMCP reference server with a stable
  `ogc_*` tool surface, operator-owned server registry, human-confirmed process
  execution workflow, proxy memory handles, and deterministic tests.

This repository is experimental research and implementation work. It is not an
adopted OGC Standard.

## Why This Exists

OGC APIs expose powerful geospatial data and processing capabilities, but using
them correctly requires knowledge of endpoints, process identifiers, input
schemas, coordinate handling, job lifecycles, and security boundaries.

This bridge gives MCP clients a structured way to:

- discover registered OGC API servers;
- inspect Features, Records, Common, and Processes resources;
- create auditable process execution plans;
- require explicit human approval before execution;
- keep large upstream responses outside model context behind memory handles;
- prevent the model from choosing arbitrary outbound URLs or handling secrets.

## Documentation

Start here if you are new to the project:

- [Documentation Index](./docs/INDEX.md)
- [Product Overview](./docs/PRODUCT.md)
- [Quickstart](./docs/QUICKSTART.md)
- [Architecture](./docs/ARCHITECTURE.md)
- [Codebase Tour](./docs/CODEBASE_TOUR.md)

For implementation and operations:

- [Tool Contract](./docs/TOOL_CONTRACT.md)
- [Proxy Workflow](./docs/PROXY_WORKFLOW.md)
- [Configuration](./docs/CONFIGURATION.md)
- [Security Model](./docs/SECURITY.md)
- [Development Guide](./docs/DEVELOPMENT.md)
- [Testing Guide](./docs/TESTING.md)
- [Deployment Guide](./docs/DEPLOYMENT.md)
- [Extending the Server](./docs/EXTENDING.md)
- [Troubleshooting](./docs/TROUBLESHOOTING.md)
- [Experimental Conformance Checklist](./docs/CONFORMANCE.md)

For GSoC review:

- [GSoC Final Report](./docs/gsoc/FINAL_REPORT.md)
- [GSoC Deliverables](./docs/gsoc/DELIVERABLES.md)
- [GSoC Timeline](./docs/gsoc/TIMELINE.md)

## Quick Start

From the repository root:

```bash
python -m pip install -e standardized_server
export OGC_MCP_CONFIG="$PWD/standardized_server/config.example.json"
python -m ogc_mcp_reference --transport stdio
```

Run the deterministic test suite:

```bash
PYTHONPATH=standardized_server/src \
  python -m unittest discover -s standardized_server/tests -v
```

The tests use mocked HTTP transports and do not require public network access.

## Repository Layout

```text
gsoc-mcp/
|-- spec/
|   `-- ogc-mcp-mapping.json
|-- standardized_server/
|   |-- config.example.json
|   |-- docs/
|   |-- examples/
|   |-- schemas/
|   |-- spec/
|   |-- src/ogc_mcp_reference/
|   `-- tests/
`-- README.md
```

## Current Status

The reference server implements:

- OGC API - Common discovery tools;
- OGC API - Features collection and item tools;
- OGC API - Records search and record tools;
- OGC API - Processes discovery, jobs, and confirmation-gated execution;
- optional direct process execution, disabled by default;
- response summary mode and proxy memory handles;
- in-memory and Redis-backed plan/memory stores;
- JWT bearer, bearer token, API key, basic auth, and no-auth profiles;
- structured error envelopes and a deterministic unittest suite.

Known production considerations are documented in
[Security Model](standardized_server/docs/SECURITY.md) and
[Deployment Guide](standardized_server/docs/DEPLOYMENT.md).
