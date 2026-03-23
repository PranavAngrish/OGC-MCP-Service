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
  "id": "features_get_items",
  "module": "features",
  "description": "Fetches features from a collection...",
  "natural_language_triggers": [
    "get features from X",
    "show me X in this area",
    "find X near Y"
  ],
  "prerequisites": ["features_list_collections"],
  "http_mapping": {
    "method": "GET",
    "path_template": "/collections/{collection_id}/items",
    "path_params": ["collection_id"],
    "query_params": ["bbox", "limit"],
    "default_params": { "f": "json" }
  },
  "input_schema": { "parameters": [...] },
  "output_schema": {
    "description": "GeoJSON FeatureCollection...",
    "summary_fields": ["id", "geometry.type", "properties"],
    "followup_tools": ["features_get_feature_by_id", "processes_execute_sync"]
  },
  "error_handling": { "errors": [...] }
}
```

**Current modules:**

| Module | OGC API Type | Tools | Status |
|--------|-------------|-------|--------|
| `processes` | OGC API – Processes | 8 tools | ✅ Implemented |
| `features` | OGC API – Features | 4 tools | ✅ Implemented |
| `records` | OGC API – Records | 3 tools | ✅ Implemented |
| `edr` | OGC API – EDR | — | 🔨 Planned |

**Cross-cutting concerns** documented in the spec:
- Server capability negotiation (`/conformance` check before each operation)
- Pagination (transparent multi-page result handling)
- CRS handling (always EPSG:4326, automatic reprojection)
- Response summarisation (prevents LLM context window overflow)
- Authentication (JWT, API key, or none — injected by proxy, never seen by LLM)
- Error translation (all HTTP errors → plain English + suggested LLM action)

**Extensibility:** New OGC API types are added by adding a new module entry to the
JSON. Existing modules are unaffected.

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
User:   "Create a 1km buffer around MG Road Bangalore"

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
git clone https://github.com/PranavAngrish/gsoc-mcp
cd gsoc-mcp

python3.11 -m venv venv
source venv/bin/activate
pip install mcp requests
```

### Start the MCP server

```bash
# Make sure your OGC API Docker stack is running first
cd path/to/OGC-API---Processes
make restart

# Then start the MCP server
cd path/to/gsoc-mcp
source venv/bin/activate
python3.11 ogc_mcp_server_v2.py
```

### Connect to Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ogc-api": {
      "command": "/path/to/gsoc-mcp/venv/bin/python3.11",
      "args": ["/path/to/gsoc-mcp/ogc_mcp_server_v2.py"]
    }
  }
}
```

Restart Claude Desktop. You should see the hammer icon 🔨 in the chat input.

### Try it

```
What geospatial processes are available on my OGC API server?
Create a 500m buffer around the Eiffel Tower
Get me 5 lakes from the features server
Search the catalogue for flood risk datasets
```

---

## Architecture

```
User (plain English)
        │
        ▼
LLM (Claude / GPT-4 / any MCP-compatible client)
        │ reads spec, decides which tool to call
        ▼
MCP Mapping Specification (ogc-mcp-mapping.json)
        │ implemented by
        ▼
FastMCP Server (ogc_mcp_server_v2.py)
        │ HTTP calls to three independent servers
        ├── OGC API – Processes  →  localhost (pygeoapi)
        ├── OGC API – Features   →  demo.pygeoapi.io
        └── OGC API – Records    →  demo.pycsw.org
```

**Key design principles:**

**Spec-first:** The JSON mapping spec is the primary deliverable. The Python server
is one implementation of it. Anyone can implement the spec in any language.

**LLM-agnostic:** Any MCP-compatible LLM client works — Claude, GPT-4, Llama, or
any future model. No vendor lock-in.

**Module independence:** Each OGC API type is a self-contained module. A developer
building only a Processes integration imports only the Processes module.

**Proxy pattern:** The MCP server acts as a proxy — translating LLM tool calls into
OGC API HTTP requests, handling auth, CRS, pagination, and response summarisation
transparently. The LLM never sees raw GeoJSON or HTTP errors.

---

## Relationship to the GSoC Project

This repository is the pre-GSoC prototype. The full GSoC project (May–August 2026)
will extend this into:

1. **Complete MCP mapping spec** — EDR module added, full CQL2 filter support,
   formal validation tooling
2. **Production proxy service** — configurable server registry, server capability
   negotiation, robust error handling, >85% test coverage
3. **Standalone showcase** — web-based chat + Leaflet map interface, no Claude
   Desktop required, end-user focused (cool spot analysis demo)
4. **pygeoapi integration path** — design aligned with pygeoapi plugin architecture
   (following pygeoapi-odc-provider pattern) for eventual native integration

---

## Questions for 52°North Mentors

The `spec/ogc-mcp-mapping.json` is a draft for mentor review. Specific questions:

1. Does the spec structure (one module per API type, cross_cutting_concerns section)
   align with the intended design?
2. Are `natural_language_triggers` the right mechanism for intent-to-tool mapping?
3. Should `summary_fields` live in the spec or purely in the proxy implementation?
4. Any conflicts with 52°North's ongoing internal MCP work to be aware of?
5. Is there a 52°North EDR server available for EDR module development?

---

## References

- [MCP Specification](https://modelcontextprotocol.io/docs)
- [OGC API – Processes](https://ogcapi.ogc.org/processes/)
- [OGC API – Features](https://ogcapi.ogc.org/features/)
- [OGC API – Records](https://ogcapi.ogc.org/records/)
- [OGC API – EDR](https://ogcapi.ogc.org/edr/)
- [pygeoapi](https://pygeoapi.io/)
- [FastMCP](https://github.com/jlowin/fastmcp)
- [Coding Challenge Repository](https://github.com/PranavAngrish/OGC-API---Processes)
- [52°North GSoC 2026 Project Idea](https://52north.org/gsoc-2026-mcp-for-ogc-apis)

---

## License

Apache 2.0 — consistent with 52°North's licensing model.