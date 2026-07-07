# GSoC Deliverables

This page maps project deliverables to repository artifacts.

## Deliverable 1: OGC API To MCP Mapping Specification

**Artifact:** [`../../../spec/ogc-mcp-mapping.json`](../../../spec/ogc-mcp-mapping.json)

Purpose:

- describe how OGC API capabilities can be represented as MCP tools;
- define modules, operations, input/output shapes, and error-handling ideas;
- provide a language-agnostic starting point for future implementations.

Status:

- draft experimental artifact;
- useful as a conceptual mapping;
- complemented by the newer reference-server tool contract.

## Deliverable 2: MCP Tool Contract

**Artifact:** [`../../spec/ogc-mcp-tool-contract.json`](../../spec/ogc-mcp-tool-contract.json)

Purpose:

- document the implemented `ogc_*` tools;
- describe side effects and response modes;
- capture process workflow lifecycle requirements;
- document state persistence expectations.

Status:

- experimental reference contract;
- aligned with the Python implementation;
- not an adopted OGC Standard.

## Deliverable 3: Python Reference Server

**Artifact:** [`../../src/ogc_mcp_reference/`](../../src/ogc_mcp_reference/)

Implemented capabilities:

- FastMCP server creation;
- `stdio`, `streamable-http`, and `sse` transport selection through the CLI;
- OGC API Common tools;
- OGC API Features tools;
- OGC API Records tools;
- OGC API Processes and Jobs tools;
- proxy planning workflow;
- response summary mode and memory handles;
- auth injection and JWT token lifecycle;
- in-memory and Redis-backed state stores;
- configuration parsing and validation;
- bounded HTTP transport;
- security validation.

## Deliverable 4: Configuration Schema And Examples

Artifacts:

- [`../../schemas/server-config.schema.json`](../../schemas/server-config.schema.json)
- [`../../config.example.json`](../../config.example.json)
- [`../../examples/streamable-http-redis-config.json`](../../examples/streamable-http-redis-config.json)
- [`../../examples/claude-desktop-config.json`](../../examples/claude-desktop-config.json)
- [`../../examples/geolabs-delaunay-execute.json`](../../examples/geolabs-delaunay-execute.json)

Purpose:

- show how operators register OGC API deployments;
- describe auth profiles, security settings, limits, store backends, and policy;
- provide realistic local and deployment-oriented examples.

## Deliverable 5: Human-Confirmed Proxy Workflow

Artifacts:

- [`../../src/ogc_mcp_reference/services/planner.py`](../../src/ogc_mcp_reference/services/planner.py)
- [`../../src/ogc_mcp_reference/workflows/planning.py`](../../src/ogc_mcp_reference/workflows/planning.py)
- [Proxy Workflow](../PROXY_WORKFLOW.md)

Implemented states:

- `needs_resolution`;
- `ready_for_confirmation`;
- `confirmed`;
- `rejected`;
- `running`;
- `completed`;
- `failed`.

## Deliverable 6: Test Suite

Artifact: [`../../tests/`](../../tests/)

Coverage includes:

- FastMCP tool behavior;
- policy-gated direct execution;
- response modes and memory handles;
- configuration and registry validation;
- transport behavior;
- security checks;
- process service behavior;
- input-schema validation;
- planning and workflow behavior;
- storage backends.

## Deliverable 7: Documentation

Artifacts:

- [`../INDEX.md`](../INDEX.md)
- [`../PRODUCT.md`](../PRODUCT.md)
- [`../ARCHITECTURE.md`](../ARCHITECTURE.md)
- [`../CODEBASE_TOUR.md`](../CODEBASE_TOUR.md)
- [`../TOOL_CONTRACT.md`](../TOOL_CONTRACT.md)
- [`../PROXY_WORKFLOW.md`](../PROXY_WORKFLOW.md)
- [`../CONFIGURATION.md`](../CONFIGURATION.md)
- [`../SECURITY.md`](../SECURITY.md)
- [`../DEVELOPMENT.md`](../DEVELOPMENT.md)
- [`../TESTING.md`](../TESTING.md)
- [`../DEPLOYMENT.md`](../DEPLOYMENT.md)
- [`../EXTENDING.md`](../EXTENDING.md)
- [`../CONFORMANCE.md`](../CONFORMANCE.md)

Purpose:

- help engineers understand the product;
- explain how to navigate the codebase;
- document operational and security boundaries;
- support future maintainers and reviewers.
