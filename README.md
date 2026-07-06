# OGC API – MCP Bridge

A working prototype that bridges natural language to OGC API operations through the
[Model Context Protocol (MCP)](https://modelcontextprotocol.io/docs). Part of a
GSoC 2026 project with [52°North](https://52north.org) —
**MCP for OGC APIs: Developing Multi Context Protocols for the Suite of OGC APIs**.

---

## What This Is

The Open Geospatial Consortium (OGC) has built a suite of REST APIs — Features,
Records, EDR, and Processes — that are widely adopted across the geospatial domain.
These APIs are powerful. But using them requires expertise: knowing the right
endpoints, input formats, coordinate systems, and how to chain multiple operations
together.

This project builds the bridge. MCP provides a structured mechanism for LLMs to
interact with external tools through a well-defined interface. By formally describing
OGC API operations as MCP tools, any LLM can translate a non-expert's plain English
request into the precise API calls required to fulfil it.

**Before this bridge:** A GIS expert manually constructs API calls, handles CRS
transformations, paginates results, chains operations, and interprets outputs.

**After this bridge:** A user types *"Create a 1km buffer around MG Road Bangalore"*
and gets a GeoJSON polygon on a map.

---

## Repository Structure

```
gsoc-mcp/
├── spec/
│   └── ogc-mcp-mapping.json     ← Formal MCP mapping specification (Deliverable 1)
├── ogc_mcp_server.py         ← FastMCP reference implementation (Deliverable 2)
├── spec_driven_server.py        ← Spec-driven prototype (architecture demo)
└── README.md
```

---

## The Two Deliverables

### Deliverable 1 — MCP Mapping Specification

**File:** `spec/ogc-mcp-mapping.json`

A formal, machine-readable JSON schema that translates core OGC API operations into
MCP tool concepts. This is the primary deliverable — language-agnostic, modular, and
extensible. Anyone can read this spec and implement it in Python, JavaScript, Java,
or any other language.

**What the spec defines for each tool:**

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
- `jwt_bearer`

The model never receives secret values.

`jwt_bearer` profiles log in with username/password environment variables,
cache access tokens, refresh before expiry when a refresh token is available,
and retry once with a fresh login after a 401 response.

### Storage Backend (Plans and Proxy Memory)

Proxy plans and proxy-memory records (full payloads behind summary handles)
are persisted through a pluggable backend, configured at the top level of the
config file:

```json
"extensibility": {
  "planned_modules": ["edr", "coverages", "tiles", "styles", "3d-geovolumes"]
}
```

---

### Deliverable 2 — Reference Implementation

**File:** `ogc_mcp_server.py`

A working Python MCP server using [FastMCP](https://github.com/jlowin/fastmcp) that
implements the mapping specification. Exposes 15 tools across three OGC API modules,
connected to three independent OGC API servers simultaneously.

**Server connections:**

```
OGC API – Processes → http://localhost          (pygeoapi, locally deployed)
OGC API – Features  → demo.pygeoapi.io          (public pygeoapi instance)
OGC API – Records   → demo.pycsw.org            (public pycsw instance)
```

**Tool list:**

```
Processes module (8 tools):
  processes_list            → GET /processes
  processes_describe        → GET /processes/{id}
  processes_execute_sync    → POST /processes/{id}/execution
  processes_execute_async   → POST /processes/{id}/execution + Prefer: respond-async
  jobs_list                 → GET /jobs
  jobs_get_status           → GET /jobs/{id}
  jobs_get_results          → GET /jobs/{id}/results
  jobs_delete               → DELETE /jobs/{id}

Features module (4 tools):
  features_list_collections     → GET /collections
  features_get_collection_info  → GET /collections/{id}
  features_get_items            → GET /collections/{id}/items
  features_get_feature_by_id    → GET /collections/{id}/items/{fid}

Records module (3 tools):
  records_list_collections  → GET /collections
  records_search            → GET /collections/{id}/items?q={keyword}
  records_get_record        → GET /collections/{id}/items/{record_id}
```

---

## Demos — What Works Right Now

All demos verified working in Claude Desktop connected to this MCP server.

### Demo 1 — Plain English to Geospatial Operation

```
User:   "Create a 1km buffer around 52°North Spatial Information Research GmbH"

System: Resolves "52°North Spatial Information Research GmbH" → 51.9691°N, 7.5957°E
        Calls execute_buffer(latitude=51.9691, longitude=7.5957, distance=1000)
        Gets 65-point GeoJSON polygon from local pygeoapi
        Displays on map
        Explains: "extends roughly from longitude 7.5867° to 7.6047° (east–west) and latitude 51.9636° to 51.9746° (north–south)"
```

### Demo 2 — Multi-Step Workflow Chaining

```
User:   "Run zonal stats on that buffer area with these elevation values:
         14.2, 15.8, 12.1, 18.3, 16.7, 13.4"

System: Uses buffer polygon from previous message as zone — no re-input needed
        Calls execute_zonal_stats(zone=<previous buffer>, values=[...])
        Returns: mean=15.08, std_dev=2.08, range=6.2
        Interprets: "The terrain within the 1km buffer around 52°North's office is quite flat, which is consistent with Münster's generally low-lying geography. The average elevation is around 15 metres, with only a 6.2m spread between the lowest (12.1m) and highest (18.3m) points. Sonnet 4.6"
```

### Demo 3 — Cross-API Chaining (Features → Processes)

```
User:   "Get the geometry of Lake Ontario and run zonal stats
         with these temperature readings: 15.2, 18.4, 16.7, 19.1, 17.3"

System: Calls features_get_feature_by_id("lakes", "ontario") → demo.pygeoapi.io
        Extracts Lake Ontario's polygon geometry
        Passes geometry directly into execute_zonal_stats → local pygeoapi
        Returns statistics with domain interpretation

Two different OGC API servers. Zero manual coordination. One sentence.
```

### Demo 4 — Records Catalogue Discovery

```
User:   "Search the geospatial catalogue for datasets about temperature"

System: Calls records_search(keyword="temperature") → demo.pycsw.org
        No results → automatically broadens to "climate"
        Returns 30 MACC atmospheric datasets
        Cross-references: "Also, demo.pygeoapi.io has gdps-temperature and icoads-sst"
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- OGC API stack running (see
  [OGC-API-Processes](https://github.com/PranavAngrish/OGC-API---Processes)
  for the coding challenge backend)
- Claude Desktop (for demo)

### Setup

  ```bash
  pip install 'ogc-mcp-reference-server[redis]'
  export OGC_MCP_REDIS_URL="redis://localhost:6379/0"
  ```

  ```json
  {
    "store": {
      "backend": "redis",
      "redis_url_env": "OGC_MCP_REDIS_URL",
      "key_prefix": "ogc_mcp_prod",
      "plan_ttl_seconds": 3600,
      "memory_ttl_seconds": 1800
    }
  }
  ```

  See [streamable-http-redis-config.json](examples/streamable-http-redis-config.json)
  for a complete example.

`plan_ttl_seconds` and `memory_ttl_seconds` control how long abandoned plans
and unused memory handles survive before expiring; `0` disables expiry.

### Tool Exposure Policy (Direct Execution Tools)

```json
{
  "policy": {
    "expose_direct_execution_tools": false
  }
}
```

`expose_direct_execution_tools` defaults to `false`. When `false`,
`ogc_processes_execute` is not registered as an MCP tool at all -- the model
cannot discover or call it, so it cannot run an arbitrary process execution
that bypasses `ogc_proxy_create_plan` / `ogc_proxy_confirm_plan`. Set it to
`true` only when you specifically need unmediated low-level access, for
example interoperability testing against a new OGC API server.

`ogc_jobs_dismiss` (cancel/delete a job) is always registered regardless of
this flag: cancelling in-flight work is lower-risk and more reversible than
starting new execution, so it is intentionally not behind the confirmation
gate.

## Proxy Runtime Tools

The standard OGC tool names remain the canonical public surface. Tools that
can return a large or unbounded upstream payload --
`ogc_features_get_items`, `ogc_jobs_get_results`, `ogc_proxy_execute_plan`,
and `ogc_processes_execute` when enabled -- default to a proxy-safe summary
mode: the full payload is stored in proxy memory and the model receives
sanitized summary fields plus a memory handle. Use `response_mode="raw"` only
for low-level interoperability testing or intentionally small responses.

The `ogc_proxy_*` tools are reserved for cross-cutting proxy workflows and state:

- `ogc_proxy_get_capabilities`: loads `/conformance`, normalizes capability
  flags, and reports active fallback rules.
- `ogc_proxy_memory_list`: lists model-safe metadata for stored payloads.
- `ogc_proxy_create_plan`: validates process and collection identifiers, and
  on a best-effort basis the `execute_request` inputs against the process's
  declared input schema (required fields, simple type mismatches), before
  execution; returns a user-confirmable workflow state.
- `ogc_proxy_get_plan`: retrieves the stored plan lifecycle state.
- `ogc_proxy_confirm_plan`: records explicit human approval or rejection.
- `ogc_proxy_execute_plan`: executes only a stored, confirmed plan by `plan_id`.

This keeps high-volume data, credentials, and fallback decisions inside the
proxy while giving the model compact, deterministic handles and summaries.

The proxy workflow layer is designed to use LangGraph for orchestration when it
is installed. In constrained development environments it falls back to the same
deterministic local workflow nodes. Either backend enforces the same plan
lifecycle: `needs_resolution` or `ready_for_confirmation`, then `confirmed`,
then `running` and `completed` or `failed`.

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
- Unmediated direct process execution is opt-in and, when disabled (the
  default), is not registered as a tool at all -- the gate is structural, not
  a runtime check the model could be persuaded around.

Application-level checks should be combined with network egress controls in
production.

## Tests

```bash
PYTHONPATH=standardized_server/src \
  python -m unittest discover -s standardized_server/tests -v
```

The test suite does not depend on public network availability. It includes
integration-style tests that call the actual registered FastMCP tools (not
just the underlying service classes) via `mcp.call_tool(...)`, including
coverage for the policy-gated direct execution tool and `response_mode`
behavior.

## Versioned Artifacts

- `spec/ogc-mcp-tool-contract.json`: experimental MCP tool contract
- `schemas/server-config.schema.json`: operator configuration schema
- `docs/CONFORMANCE.md`: checklist for future independent implementations
