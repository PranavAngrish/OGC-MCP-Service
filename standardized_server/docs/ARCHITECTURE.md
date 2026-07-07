# Architecture

## Status

The reference server is an experimental MCP implementation for OGC APIs. It is
intended for design review, research, and interoperability testing. It should not
be represented as an adopted OGC Standard.

## System Boundary

The server sits between MCP clients and operator-approved OGC API deployments.

```text
MCP client
  -> FastMCP tool call
  -> OGC MCP reference server
  -> registered OGC API deployment
```

The MCP client never supplies arbitrary upstream base URLs or credentials.
Operators define servers, services, auth profiles, security policy, and limits
in a JSON configuration file.

## Runtime Composition

[`src/ogc_mcp_reference/runtime.py`](../src/ogc_mcp_reference/runtime.py) builds
one `ProxyRuntime` object that wires together:

- `ServerRegistry` for registered server lookup;
- `OgcHttpClient` for bounded HTTP requests and auth injection;
- OGC module services for Common, Features, Records, and Processes;
- capability and fallback services;
- proxy memory storage and response sanitization;
- process description cache;
- proxy planner;
- LangGraph-ready planning workflow;
- operator policy settings.

`app.py` then registers FastMCP resources and tools using that runtime.

## Package Boundaries

```text
src/ogc_mcp_reference/
|-- app.py              FastMCP resources, tools, instructions, response modes
|-- __main__.py         CLI entry point
|-- config.py           JSON configuration parsing
|-- models.py           typed dataclass models
|-- registry.py         server resolution and service checks
|-- security.py         URL, path, and execute-reference validation
|-- transport.py        bounded HTTP client and auth headers
|-- result.py           success/error envelopes
|-- errors.py           stable error types
|-- modules/            OGC API module operations
|-- services/           proxy services and stateful support
`-- workflows/          plan workflow orchestration
```

The `modules/` layer does not know about MCP. It builds OGC HTTP requests and
returns structured envelopes. The MCP-specific behavior, including response
summary mode, lives at the tool boundary in `app.py`.

## Tool Surface

The public MCP surface uses stable names with the `ogc_` prefix:

- registry tools: `ogc_servers_list`;
- proxy tools: `ogc_proxy_*`;
- Common tools: `ogc_common_*`;
- Features tools: `ogc_features_*`;
- Records tools: `ogc_records_*`;
- Processes and Jobs tools: `ogc_processes_*`, `ogc_jobs_*`.

The contract is documented in [Tool Contract](TOOL_CONTRACT.md) and represented
as JSON in [`../spec/ogc-mcp-tool-contract.json`](../spec/ogc-mcp-tool-contract.json).

## Human-Confirmed Process Execution

The default process workflow is intentionally stateful:

```text
discover process
  -> describe exact process schema
  -> create proxy plan
  -> resolve missing or invalid inputs
  -> show execute_request verbatim to user
  -> record approval
  -> execute stored plan
```

`ogc_processes_execute`, the unmediated direct execution tool, is not registered
unless `policy.expose_direct_execution_tools` is set to `true`. This is a
structural gate: when disabled, the model cannot discover or call the tool.

## Response Summary Mode

Tools that can return large payloads default to `response_mode="summary"`.

In summary mode:

1. the full upstream payload is stored in proxy memory;
2. a compact sanitized summary replaces `data`;
3. the response includes a memory handle;
4. callers can page through the full payload with `ogc_proxy_memory_retrieve`.

Raw mode is available for low-level testing and intentionally small payloads,
but it should not be used as a way to load feature coordinates into model
context for model-side spatial analysis.

## State Storage

Plans and memory records use the pluggable `KeyValueStore` interface in
`services/store.py`.

- `memory`: process-local, zero setup, suitable for single-worker stdio.
- `redis`: external state store, required for multi-worker or multi-replica
  Streamable HTTP deployments where calls may be routed to different workers.

Plans and memory records have configurable TTLs. A TTL of `0` disables expiry.

## Capability Discovery And Fallbacks

`CapabilityCache` loads `/conformance` and normalizes selected flags such as
async support, CQL2, CRS negotiation, temporal filtering, and property
selection.

`FallbackEngine` reports deterministic fallback rules for missing capabilities.
The workflow currently applies the async fallback by selecting `auto` when an
async request targets a server without async/job capability. Other advertised
fallback rules describe policy intent and must not be treated as implemented
geospatial computation unless support is added explicitly.

## Security Boundaries

The server enforces:

- registered upstream deployments only;
- relative paths for generic reads;
- no embedded credentials in configured URLs;
- environment-based credential injection;
- private and loopback base URL blocking by default;
- execute-reference host allowlists;
- no automatic redirect following;
- response byte limits;
- request timeouts;
- structured error envelopes.

Application checks should be combined with infrastructure egress controls in
production.

## Known Gaps

- Plan and memory visibility is deployment-wide, not scoped per user/session.
- DNS names that resolve to private addresses require infrastructure-level
  egress controls or future DNS-aware validation.
- The conservative input-schema checker is intentionally not a full JSON Schema
  validator.
- Capability fallback rules beyond async selection are documented but not fully
  implemented as processing behavior.
