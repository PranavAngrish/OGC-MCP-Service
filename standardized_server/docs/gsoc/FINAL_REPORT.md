# GSoC Final Report

## Project

**Title:** MCP for OGC APIs: Developing Model Context Protocols for the Suite of
OGC APIs

**Organization:** 52North

**Repository:** `gsoc-mcp`

**Primary implementation:** `standardized_server/`

## Summary

This project explored how the Model Context Protocol can expose OGC API
capabilities to AI clients through a stable, auditable, and security-conscious
tool contract.

The final implementation is a Python FastMCP reference server that connects MCP
clients to operator-approved OGC API deployments. It supports OGC API - Common,
Features, Records, and Processes operations, with a human-confirmed proxy
workflow for process execution.

## Motivation

OGC APIs provide standard HTTP interfaces for geospatial data, metadata, and
processing. However, non-specialist users and general-purpose AI clients need
help with discovery, exact process identifiers, input schemas, job lifecycle,
large payloads, and safe execution.

The project goal was to design and implement a bridge that gives AI clients a
structured way to interact with OGC APIs without handing the model unrestricted
network access, credentials, or process execution authority.

## Delivered Work

The project delivered:

- an early OGC API to MCP mapping specification;
- an experimental MCP tool contract for the reference server;
- a FastMCP Python reference implementation;
- operator-owned server registry and configuration schema;
- bounded HTTP transport with auth injection;
- OGC API Common, Features, Records, Processes, and Jobs tools;
- human-confirmed proxy plan workflow for process execution;
- conservative execute-input validation;
- source href validation for Features-to-Processes workflows;
- proxy memory handles and sanitized summary mode;
- in-memory and Redis-backed plan/memory stores;
- policy-gated direct execution tool registration;
- deterministic unit tests using mocked HTTP transports;
- architecture, configuration, security, development, testing, deployment, and
  extension documentation.

See [Deliverables](DELIVERABLES.md) for file-level details.

## Key Design Decisions

### Stable Tool Names

The public interface uses stable `ogc_*` tool names based on OGC concepts. Tool
names do not depend on a specific backend implementation.

### Operator-Owned Registry

MCP clients choose from configured `server_id` values. They cannot supply
arbitrary upstream base URLs.

### Human-In-The-Loop Process Execution

Process execution is routed through a stored plan:

```text
create plan -> resolve inputs -> confirm -> execute
```

Execution cannot proceed until a human approves the exact `execute_request`.

### Proxy Memory Summary Mode

Large responses are stored inside the proxy and summarized for model context.
This keeps feature collections, process outputs, and job results from being
blindly copied into the model.

### Direct Execution Is Opt-In

The low-level `ogc_processes_execute` tool is not registered unless the operator
sets `policy.expose_direct_execution_tools=true`.

## Implementation Highlights

The implementation is organized around clear boundaries:

- `app.py` owns the MCP surface.
- `runtime.py` composes long-lived services.
- `modules/` owns OGC HTTP operations.
- `services/` owns auth, planning, capabilities, memory, sanitization, and
  storage.
- `workflows/` wraps planning in a LangGraph-ready workflow facade.
- `tests/` verifies behavior without public network dependencies.

## Testing

The deterministic test suite covers:

- FastMCP tool registration;
- policy-gated direct execution;
- summary/raw response modes;
- proxy memory handles;
- config parsing;
- transport limits and auth;
- JWT retry behavior;
- security validation;
- process execution body preservation;
- input-schema validation;
- plan lifecycle and confirmation gate;
- source href validation;
- in-memory and Redis store behavior.

Run:

```bash
PYTHONPATH=standardized_server/src \
  python -m unittest discover -s standardized_server/tests -v
```

## Current Limitations

- The project is experimental and not an adopted standard.
- The input-schema validator is intentionally conservative, not a full JSON
  Schema validator.
- Plan and memory state is deployment-wide, not user/session scoped.
- DNS-aware private address blocking is not implemented in the application
  layer.
- Capability fallback rules beyond async-to-sync are documented but not fully
  implemented as processing behavior.

## Future Work

Potential next steps:

- add user/session scoping for plan and memory visibility;
- strengthen DNS-aware network validation;
- add richer JSON Schema validation where safe;
- add dedicated tools for EDR, Coverages, Tiles, Maps, and Styles;
- improve observability and audit logging;
- define an independent interoperability test suite;
- align the experimental contract with broader OGC community review.

## Documentation Map

- [Product Overview](../PRODUCT.md)
- [Architecture](../ARCHITECTURE.md)
- [Codebase Tour](../CODEBASE_TOUR.md)
- [Tool Contract](../TOOL_CONTRACT.md)
- [Proxy Workflow](../PROXY_WORKFLOW.md)
- [Security Model](../SECURITY.md)
- [Testing Guide](../TESTING.md)
- [Conformance Checklist](../CONFORMANCE.md)
