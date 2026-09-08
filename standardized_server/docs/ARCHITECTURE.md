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
- `ArtifactStore` and `OutputArtifactPipeline` for process-output resolution,
  parsing, and presentation state (see [Process Output Artifacts](OUTPUT_ARTIFACTS.md));
- operator policy settings.

`app.py` then registers FastMCP resources and tools using that runtime.
`ProcessesService` also receives `output_artifacts` so `processes.execute`,
`jobs.get_results`, and the proxy plan execution path all build an
`output_manifest` from the same pipeline.

## Package Boundaries

```text
src/ogc_mcp_reference/
|-- app.py              FastMCP resources, tools, instructions, response modes
|-- __main__.py         CLI entry point
|-- config.py           JSON configuration parsing
|-- models.py           typed dataclass models
|-- registry.py         server resolution and service checks
|-- security.py         URL, path, and execute-reference validation
|-- transport.py        bounded HTTP client, auth headers, OutputResolutionBudget
|-- result.py           success/error envelopes
|-- errors.py           stable error types
|-- modules/            OGC API module operations
|-- services/           proxy services and stateful support
|-- workflows/          plan workflow orchestration
`-- artifacts/          process-output resolution, parsing, and artifact storage
```

The `modules/` layer does not know about MCP. It builds OGC HTTP requests and
returns structured envelopes. The MCP-specific behavior, including response
summary mode, lives at the tool boundary in `app.py`.

## Process Output Artifact Pipeline

Synchronous process results and `ogc_jobs_get_results` responses both pass
through `OutputArtifactPipeline` ([`artifacts/pipeline.py`](../src/ogc_mcp_reference/artifacts/pipeline.py))
before they reach the MCP result envelope:

```text
upstream response
  -> extract advertised named outputs (artifacts/extractors.py)
  -> resolve inline values or follow references (transport.py, budgeted)
  -> detect media type (artifacts/detection.py)
  -> parse with a registered adapter (artifacts/parsers/: geojson, gml, wkt, generic)
  -> store original/canonical/preview representations behind art_* handles
  -> classify presentation readiness (map/table/chart/metric/image/text/download)
  -> return a versioned output_manifest
```

The manifest tracks four independent states per output -- `execution`,
`retrieval`, `interpretation`, and per-presentation `state` -- so an `ok: true`
tool envelope never implies that a map or download actually exists. See
[Process Output Artifacts](OUTPUT_ARTIFACTS.md) for the full contract.

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

- Plan, proxy-memory, and artifact (`art_*`) visibility is deployment-wide at
  the Python MCP layer, not scoped per user/session. The bundled `ui/` gateway
  adds session-scoped artifact registration at its own boundary, but that does
  not remove the Python-layer limitation for other MCP clients.
- DNS names that resolve to private addresses require infrastructure-level
  egress controls or future DNS-aware validation.
- The conservative input-schema checker is intentionally not a full JSON Schema
  validator.
- Capability fallback rules beyond async selection are documented but not fully
  implemented as processing behavior.
- Format adapters exist for GeoJSON, GML, WKT, and generic tabular data; raster,
  coverage, and tile outputs are detected and stored but have no compatible
  preview/tiler adapter yet, so they remain safe reference/download artifacts
  rather than rendered previews.
