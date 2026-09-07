# OGC API MCP Bridge

**A production-grade reference bridge between natural-language AI agents (MCP clients) and OGC API geospatial servers — with human-in-the-loop safety, auditable execution plans, and a full-stack reference implementation.**

Built as a [Google Summer of Code 2026](https://summerofcode.withgoogle.com/) project with **[52°North](https://52north.org/)**, under the proposal *"MCP for OGC APIs."*

> This repository is experimental research and implementation work. It is **not** an adopted OGC Standard — it is a concrete, working demonstration of what standardizing this interface could look like, backed by a real server, a real UI, and a deterministic test suite.

---

## Table of Contents

- [What This Project Solves](#what-this-project-solves)
- [What's In This Repository](#whats-in-this-repository)
- [Architecture at a Glance](#architecture-at-a-glance)
- [Core Design Decisions](#core-design-decisions)
- [The `ogc_*` Tool Surface](#the-ogc_-tool-surface)
- [The Human-in-the-Loop Execution Workflow](#the-human-in-the-loop-execution-workflow)
- [Security Model](#security-model)
- [The Conversational UI (Terra Console)](#the-conversational-ui-terra-console)
- [Installation & Running It Yourself](#installation--running-it-yourself)
- [Configuration](#configuration)
- [Testing](#testing)
- [Repository Layout](#repository-layout)
- [Current Status & Known Limitations](#current-status--known-limitations)
- [Documentation Index](#documentation-index)

---

## What This Project Solves

The [OGC API](https://ogcapi.ogc.org/) family of standards (Features, Records, Processes, Common) expose enormous amounts of geospatial data and computation — national mapping agencies, weather services, cadastral registries, and scientific data catalogues all speak this protocol. But using them correctly requires knowing:

- exact endpoint shapes, process identifiers, and input schemas per deployment,
- coordinate reference systems, axis order, and unit conventions,
- synchronous vs. asynchronous job lifecycles,
- and how to avoid leaking credentials or letting an AI model call arbitrary URLs.

**The Model Context Protocol (MCP)** lets AI assistants call external tools, but a naive "point an LLM at an OGC API" integration is dangerous: the model could invent process parameters, silently perform "spatial analysis" using hallucinated coordinates, follow a malicious redirect to exfiltrate data, or execute a real-world process (triggering compute costs, side effects, or irreversible actions) without a human ever approving it.

This project answers: **how do you give a conversational AI agent safe, auditable, standards-compliant access to OGC APIs — where every consequential action is validated against the server's actual schema and explicitly approved by a human before it runs?**

---

## What's In This Repository

| Component | What it is |
|---|---|
| **`spec/`** | The early mapping specification: how OGC API operations translate into MCP tool calls, plus JSON Schemas for workflow events, clarification requests, and output manifests. |
| **`standardized_server/`** | A production-quality **Python FastMCP server** — the reference implementation of the spec. Exposes a stable `ogc_*` tool surface, an operator-owned server registry, a confirmation-gated process-execution workflow, and a deterministic `unittest` suite. |
| **`ui/` ("Terra Console")** | A **React + Node.js conversational client** that connects a Gemini-powered LLM to the MCP server over stdio, renders live tool activity, geospatial result maps, and human-approval cards in the browser. |
| **`OGC_to_MCP_Bridging_Pranav_Angrish.pptx`** | Project overview deck, generated via `scripts/generate_ogc_mcp_deck.py`. |

Together these form an end-to-end demonstration: **user chat message → LLM plans a call → server validates it against a live OGC schema → human approves → server executes → results are safely rendered as maps/tables/downloads.**

---

## Architecture at a Glance

```text
                        ┌────────────────────────────────────────────┐
                        │              Terra Console (ui/)            │
                        │  React SPA  ──SSE/HTTP──▶  Node gateway     │
                        │  (chat, maps, approval cards)  (Express)    │
                        └───────────────────┬──────────────────────────┘
                                             │ Gemini (OpenAI-compatible API)
                                             │ exposes MCP tools as function-calling tools
                                             │
                                             │ MCP client (stdio)
                                             ▼
                        ┌────────────────────────────────────────────┐
                        │      OGC MCP Reference Server (Python)       │
                        │      standardized_server/src/ogc_mcp_reference│
                        │                                              │
                        │  FastMCP tool layer  (app.py)                │
                        │       │                                      │
                        │  ┌────┴─────────────────────────────────┐   │
                        │  │ Modules: Common · Features · Records  │   │
                        │  │          · Processes                  │   │
                        │  ├────────────────────────────────────────┤   │
                        │  │ Services: capabilities · fallback ·   │   │
                        │  │  input_schema · sanitization · auth · │   │
                        │  │  memory · planner · process_desc.     │   │
                        │  ├────────────────────────────────────────┤   │
                        │  │ Workflows: LangGraph-backed plan       │   │
                        │  │            lifecycle (create → resolve │   │
                        │  │            → confirm → execute)        │   │
                        │  ├────────────────────────────────────────┤   │
                        │  │ Artifacts: output-manifest pipeline    │   │
                        │  │            (parse, sanitize, store)    │   │
                        │  ├────────────────────────────────────────┤   │
                        │  │ Security: URL/SSRF validation, host    │   │
                        │  │           allowlisting, private-IP     │   │
                        │  │           blocking                     │   │
                        │  ├────────────────────────────────────────┤   │
                        │  │ Transport: bounded, budgeted HTTP       │   │
                        │  │            client (httpx)               │   │
                        │  ├────────────────────────────────────────┤   │
                        │  │ Store: pluggable KV (in-memory / Redis) │   │
                        │  │        for plans, memory, artifacts     │   │
                        │  └────────────────────────────────────────┘   │
                        └───────────────────┬──────────────────────────┘
                                             │ bounded, validated HTTPS
                                             ▼
                        ┌────────────────────────────────────────────┐
                        │     Registered OGC API Deployments           │
                        │  (pygeoapi, ldproxy, GeoLabs, national SDIs,│
                        │   IDEE/IGN Spain, etc. — operator-approved) │
                        └────────────────────────────────────────────┘
```

The server is **transport-agnostic** at the LLM level: any MCP-compatible client (Claude Desktop, the bundled Terra Console UI, or a custom agent) can drive it over stdio or Streamable HTTP.

---

## Core Design Decisions

These are the decisions that separate this from a toy "LLM calls an API" demo:

### 1. A stable `ogc_*` tool contract, not a raw API pass-through
Instead of exposing every possible OGC endpoint combination, the server exposes ~25 well-documented tools (`ogc_features_query`, `ogc_processes_describe`, `ogc_proxy_create_plan`, …) with rich docstrings that *are* the prompt engineering. See [`spec/ogc-mcp-mapping.json`](./spec/ogc-mcp-mapping.json) and [`standardized_server/spec/ogc-mcp-tool-contract.json`](./standardized_server/spec/ogc-mcp-tool-contract.json).

### 2. Human-in-the-loop process execution (Rules 0–6 baked into the server instructions)
The FastMCP server ships an extensive `SERVER_INSTRUCTIONS` system prompt (see [`app.py`](./standardized_server/src/ogc_mcp_reference/app.py)) that forbids the model from ever performing spatial analysis itself (no Python/JS/shapely fallback), forces one-question-at-a-time clarification of ambiguous inputs, and requires the model to display the *exact* `execute_request` to the user before execution can proceed. This is enforced at two levels — prompt-level instructions **and** server-side state machine gates (see below).

### 3. A validated plan lifecycle, not "just call the API"
Every process execution goes through:
```
ogc_proxy_create_plan → (needs_resolution ⇄ ogc_proxy_update_plan)* → ready_for_confirmation
    → ogc_proxy_confirm_plan(approved) → confirmed → ogc_proxy_execute_plan → completed
```
Plans are validated against a **live, cached process description** fetched from the actual upstream server — the model cannot invent input names, and a plan literally cannot reach `confirmed` state with unresolved/invalid inputs. See [`services/planner.py`](./standardized_server/src/ogc_mcp_reference/services/planner.py) and [`workflows/planning.py`](./standardized_server/src/ogc_mcp_reference/workflows/planning.py) (LangGraph-backed, with a deterministic local fallback when LangGraph isn't installed).

### 4. Proxy memory: large payloads never enter the model's context window
Tools that can return unbounded data (`ogc_features_get_items`, `ogc_records_search`, `ogc_jobs_get_results`, …) default to `response_mode="summary"`: the full payload is stored behind an opaque `mem_*` handle in a pluggable key-value store, and the model only sees a sanitized, field-limited summary. Geometry coordinates are stripped from every summary by design — full geometry is retrievable via the handle or passed by reference (`href`) directly to a downstream process, never copy-pasted through the LLM. See [`services/memory.py`](./standardized_server/src/ogc_mcp_reference/services/memory.py) and [`services/sanitization.py`](./standardized_server/src/ogc_mcp_reference/services/sanitization.py).

### 5. A canonical output-artifact pipeline with explicit truth-tracking
Process outputs (which can be inline JSON, referenced downloads, coverages, images, tables…) go through [`artifacts/pipeline.py`](./standardized_server/src/ogc_mcp_reference/artifacts/pipeline.py), which produces a versioned **output manifest** separating four independent phases:

| Phase | Answers |
|---|---|
| `execution.state` | Did the upstream computation actually run? |
| `retrieval.state` | Was each inline/referenced output actually fetched? |
| `interpretation.state` | Was its format/semantics understood (GeoJSON, GML, WKT, table, coverage…)? |
| `presentations[].state` | Is a map / table / chart / metric / download *actually* ready to show? |

This means the model (and the UI) can never claim "here's your map" unless a map genuinely exists — an `ok: true` envelope does **not** imply a usable result. Format adapters live in [`artifacts/parsers/`](./standardized_server/src/ogc_mcp_reference/artifacts/parsers/) (GeoJSON, GML, WKT, generic tables).

### 6. Defense-in-depth against SSRF and prompt injection
- [`security.py`](./standardized_server/src/ogc_mcp_reference/security.py): every outbound URL is validated — scheme allowlisting, private/loopback/cloud-metadata IP blocking, credential-in-URL rejection, and an explicit reference-host allowlist for any URL the model tries to pass as process input.
- [`transport.py`](./standardized_server/src/ogc_mcp_reference/transport.py): redirects are followed **manually**, re-validated at every hop, with a shared `OutputResolutionBudget` bounding total time, bytes, and fetch count across an entire manifest — so a malicious or misconfigured upstream can't cause unbounded resource consumption.
- [`services/sanitization.py`](./standardized_server/src/ogc_mcp_reference/services/sanitization.py): every string returned to the model is scanned for prompt-injection patterns (`"ignore previous instructions"`, `"system prompt"`, etc.) and redacted.
- Direct, unconfirmed process execution (`ogc_processes_execute`, `ogc_jobs_dismiss`) is **disabled by default** (`policy.expose_direct_execution_tools = false`) and must be explicitly opted into by the operator.

### 7. Capability-aware fallbacks, not hard failures
[`services/capabilities.py`](./standardized_server/src/ogc_mcp_reference/services/capabilities.py) and [`services/fallback.py`](./standardized_server/src/ogc_mcp_reference/services/fallback.py) probe `/conformance` and choose deterministic fallback behavior (e.g. sync execution when async isn't supported) instead of letting the model guess.

### 8. Pluggable, horizontally-scalable state
Plans, proxy-memory records, and artifacts all sit behind a `KeyValueStore` protocol ([`services/store.py`](./standardized_server/src/ogc_mcp_reference/services/store.py)) with an in-memory implementation for single-worker/stdio use and a Redis-backed implementation for multi-worker Streamable HTTP deployments — selected purely by config, with TTL-based expiry throughout.

---

## The `ogc_*` Tool Surface

| Category | Tools |
|---|---|
| **Discovery** | `ogc_servers_list`, `ogc_common_get_landing_page`, `ogc_common_get_conformance`, `ogc_common_get_resource` |
| **Features** | `ogc_features_list_collections`, `ogc_features_describe_collection`, `ogc_features_describe_query_surface`, `ogc_features_query` (validated, auto-paginated, evidence-gated factual queries), `ogc_features_get_items`, `ogc_features_get_item` |
| **Records** | `ogc_records_list_collections`, `ogc_records_search`, `ogc_records_get_record` |
| **Processes** | `ogc_processes_list` (with `search_text` for bounded catalogue search), `ogc_processes_describe`, `ogc_processes_execute` *(opt-in only)* |
| **Jobs** | `ogc_jobs_list`, `ogc_jobs_get_status`, `ogc_jobs_get_results`, `ogc_jobs_dismiss` *(opt-in only)* |
| **Proxy / HITL workflow** | `ogc_proxy_create_plan`, `ogc_proxy_update_plan`, `ogc_proxy_get_plan`, `ogc_proxy_list_plans`, `ogc_proxy_confirm_plan`, `ogc_proxy_execute_plan` |
| **Proxy memory & artifacts** | `ogc_proxy_get_capabilities`, `ogc_proxy_memory_list`, `ogc_proxy_memory_retrieve`, `ogc_proxy_artifact_retrieve` |

Every tool returns a **stable envelope**: `{"ok": bool, "operation": str, "server": {...}, "data": ..., "error"?: {...}}` — see [`result.py`](./standardized_server/src/ogc_mcp_reference/result.py).

---

## The Human-in-the-Loop Execution Workflow

```
 1. ogc_servers_list
 2. ogc_processes_list  (search_text=... for large catalogues)
 3. ogc_processes_describe          ← read exact input schema, never invented
 4. ogc_proxy_create_plan           ← validates inputs against the live schema
       │
       ├── needs_resolution ──▶ ask the user ONE question at a time
       │        │                        (per_field_questions)
       │        └── ogc_proxy_update_plan ──▶ re-validates in place
       │
       └── ready_for_confirmation ──▶ show execute_request VERBATIM to the user
                │
                └── ogc_proxy_confirm_plan(approved=true/false)
                         │
                         └── ogc_proxy_execute_plan   ← only runs if confirmed
                                  │
                                  ├── sync  → output_manifest returned immediately
                                  └── async → ogc_jobs_get_status → ogc_jobs_get_results
```

A plan **cannot** transition to `confirmed` while any input is unresolved, and **cannot** execute without an explicit, recorded `approved=true`. Rejection is always available. This whole lifecycle is persisted (survivable across conversation turns) and fully inspectable via `ogc_proxy_get_plan` / `ogc_proxy_list_plans`.

For details on why this exists and how it's implemented, see [Proxy Workflow docs](./standardized_server/docs/PROXY_WORKFLOW.md).

---

## Security Model

| Threat | Mitigation |
|---|---|
| Model calls an arbitrary/internal URL (SSRF) | `security.py` validates every URL: scheme, hostname, no embedded credentials, private/loopback/cloud-metadata IP blocking, operator-defined host allowlists |
| Model redirects a request off-allowlist | Redirects are followed manually in `transport.py`, re-validated at every hop, with HTTPS→HTTP downgrade blocked by default |
| Unbounded upstream response (DoS) | Every fetch is size- and time-bounded; a shared `OutputResolutionBudget` caps aggregate bytes/seconds/fetches across an entire output manifest |
| Model invents process inputs or executes untested calls | Plans are validated against a live-fetched process description; execution requires explicit human confirmation |
| Prompt injection via upstream data (e.g. a malicious dataset description) | `ResponseSanitizer` strips instruction-like patterns from all model-visible text |
| Large geometry payload silently entering model context / costing tokens | Proxy-memory summary mode strips coordinates by default; raw mode is opt-in and explicitly discouraged for analysis |
| Credential leakage | Auth headers (JWT bearer, static bearer, API key, basic) are injected server-side per registered server and never exposed to the model or client; env-var-based secrets only |
| Unconfirmed state-changing actions | Direct execution/dismiss tools are disabled unless the operator explicitly opts in via config |

Full detail: [Security Model docs](./standardized_server/docs/SECURITY.md).

---

## The Conversational UI (Terra Console)

`ui/` is a full React + Express application, **not** a demo stub:

- **Server-side Gemini gateway** (`ui/server/agent.mjs`, `index.mjs`) — the browser never sees the LLM API key and never spawns the MCP process itself; the Node gateway owns both.
- **MCP tools exposed to Gemini as OpenAI-style function-calling tools**, via the official `@modelcontextprotocol/sdk` client connected to the Python server over stdio.
- **`ogc_proxy_confirm_plan` is deliberately withheld from the LLM's tool list** — approval can only happen through an explicit browser UI action, re-validated server-side against the exact plan fingerprint. The model cannot self-approve.
- **Streamed activity feed**: safe planning summaries, tool calls/arguments, bounded result previews — explicitly *not* hidden chain-of-thought presented as fact.
- **Live background-job tracking** via Server-Sent Events, so async OGC jobs (e.g. long-running raster processing) update the original chat message when they complete.
- **Interactive MapLibre GL result maps**, generated only from data with a `state="ready"` presentation (see output manifest above) — points/lines/polygons/heatmaps/tiles, CRS-aware (CRS84 default, EPSG:3857 reprojected, unknown CRS left unmapped and flagged for clarification rather than guessed).
- **Full test suite** for the gateway (`ui/server/*.test.mjs`, run via `node --test`).

See [`ui/README.md`](./ui/README.md) for the complete environment-variable reference and production-hardening checklist (this UI is intentionally scoped for local/single-user use today — auth, multi-tenant session isolation, and durable job storage are the explicit next steps documented there).

---

## Installation & Running It Yourself

### Prerequisites

- Python **3.11+**
- Node.js **22+** (for the UI)
- (Optional) Redis, only if you want multi-worker Streamable HTTP deployment

### 1. Clone and install the server

```bash
git clone <this-repo-url> gsoc-mcp
cd gsoc-mcp

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

python -m pip install -e standardized_server
# For Redis-backed multi-worker deployments, instead:
# python -m pip install -e "standardized_server[redis]"
```

### 2. Point it at a configuration file

The bundled example config registers real, public OGC API deployments (a pygeoapi demo, IDEE/IGN Spain, GeoLabs, ldproxy CShapes) so you can try it immediately with no credentials:

```bash
export OGC_MCP_CONFIG="$PWD/standardized_server/config.example.json"
```

### 3. Run the server

**Stdio transport** (what MCP desktop clients and the bundled UI use):

```bash
python -m ogc_mcp_reference --transport stdio
```

**Streamable HTTP transport** (for remote/multi-client deployments):

```bash
python -m ogc_mcp_reference --transport streamable-http
# Configure OGC_MCP_HOST / OGC_MCP_PORT as needed; see examples/streamable-http-redis-config.json
```

### 4. Connect it to an MCP client

To use it from **Claude Desktop** (or any MCP-compatible desktop client), add an entry like [`standardized_server/examples/claude-desktop-config.json`](./standardized_server/examples/claude-desktop-config.json) to your client's MCP server configuration, pointing at the `venv` Python interpreter and this config file.

### 5. (Optional) Run the bundled conversational UI

```bash
cd ui
cp .env.example .env
# Edit .env and set GEMINI_API_KEY

npm install
npm run dev
```

Open `http://localhost:5173`. The dev command runs the Vite frontend and the Node/Express gateway concurrently; the gateway spawns the Python server over stdio automatically (configure `OGC_MCP_PYTHON` / `OGC_MCP_CONFIG` in `.env` if your paths differ from the defaults).

For a production-style local build:

```bash
npm run build
npm start   # serves API + built frontend from one process on :8787
```

---

## Configuration

The server is entirely driven by one JSON config file (`OGC_MCP_CONFIG`), validated against [`schemas/server-config.schema.json`](./standardized_server/schemas/server-config.schema.json). Key sections:

```jsonc
{
  "default_servers": { "features": "idee-features", "processes": "idee-processes", ... },
  "store": { "backend": "memory", "plan_ttl_seconds": 3600, ... },   // or "redis"
  "policy": { "expose_direct_execution_tools": false },              // opt-in escape hatch
  "servers": [
    {
      "id": "idee-processes",
      "base_url": "https://api-processes.idee.es",
      "services": ["common", "processes"],
      "auth": { "type": "none" },                                    // or bearer_env / api_key_env / basic_env / jwt_bearer
      "security": {
        "allow_private_networks": false,
        "allowed_reference_hosts": [],
        "validate_execute_references": true
      },
      "limits": { "timeout_seconds": 120, "max_response_bytes": 15000000 },
      "output_resolution": { "enabled": true, "max_outputs": 20, "max_redirects": 3, ... }
    }
  ]
}
```

Every server is opted-in explicitly by an operator — the model can never talk to a server that isn't in this file. See [Configuration docs](./standardized_server/docs/CONFIGURATION.md) for the full schema reference and [`config.example.json`](./standardized_server/config.example.json) for a working multi-server example.

---

## Testing

```bash
cd standardized_server
PYTHONPATH=src python -m unittest discover -s tests -v
```

The suite (`tests/test_app.py`, `test_artifacts.py`, `test_config.py`, `test_feature_query.py`, `test_input_schema.py`, `test_processes.py`, `test_proxy_services.py`, `test_security.py`, `test_store.py`, `test_tool_contract_schema.py`, `test_transport.py`) uses **mocked HTTP transports** — it requires no network access and is fully deterministic, covering the plan lifecycle, SSRF/security boundaries, output-artifact parsing, and the tool-contract JSON Schema itself.

The UI gateway has its own Node test suite:

```bash
cd ui
npm test   # node --test server/*.test.mjs
```

---

## Repository Layout

```text
gsoc-mcp/
├── README.md                                  ← you are here
├── OGC_to_MCP_Bridging_Pranav_Angrish.pptx     ← project overview deck
├── scripts/
│   └── generate_ogc_mcp_deck.py
├── spec/                                       ← early mapping spec & JSON Schemas
│   ├── ogc-mcp-mapping.json
│   ├── ogc-output-manifest.schema.json
│   ├── ogc-workflow-event.schema.json
│   └── ogc-clarification-request.schema.json
├── standardized_server/                        ← the Python FastMCP reference server
│   ├── config.example.json
│   ├── pyproject.toml
│   ├── schemas/server-config.schema.json
│   ├── spec/ogc-mcp-tool-contract.json
│   ├── examples/                               ← Claude Desktop config, execution examples
│   ├── docs/                                   ← full documentation set (see below)
│   ├── src/ogc_mcp_reference/
│   │   ├── app.py                              ← FastMCP tool definitions + system instructions
│   │   ├── config.py / models.py / registry.py ← operator-owned server config & registry
│   │   ├── runtime.py                          ← wires every service together
│   │   ├── security.py / transport.py          ← SSRF defense, bounded HTTP client
│   │   ├── errors.py / result.py               ← structured error & result envelopes
│   │   ├── modules/                            ← common / features / processes / records
│   │   ├── services/                           ← auth, capabilities, fallback, memory,
│   │   │                                          planner, sanitization, store, input_schema
│   │   ├── workflows/                          ← LangGraph-backed plan lifecycle
│   │   └── artifacts/                          ← output-manifest pipeline + format parsers
│   └── tests/                                  ← deterministic unittest suite
└── ui/                                          ← "Terra Console" React + Node client
    ├── server/                                  ← Express gateway, Gemini + MCP client glue
    └── src/                                      ← React components (chat, maps, approvals)
```

---

## Current Status & Known Limitations

**Implemented:**
- OGC API — Common, Features, Records, Processes discovery and interaction tools
- Confirmation-gated process execution with a persisted, resumable plan lifecycle
- Response summary mode with opaque proxy-memory handles for large payloads
- Canonical process-output manifests with format detection/parsing (GeoJSON, GML, WKT, tables) and explicit presentation-readiness states
- In-memory and Redis-backed storage for plans, memory, and artifacts
- JWT bearer, static bearer, API key, basic auth, and no-auth server profiles
- Structured, machine-readable error envelopes throughout
- A deterministic, network-free `unittest` suite

**Known limitations** (see linked docs for full detail):
- The bundled UI gateway is designed for **local, single-user use**; production/multi-tenant deployment needs authentication, per-user session isolation, persistent storage, and rate limiting — see [`ui/README.md`](./ui/README.md#production-work-still-required).
- Raster/coverage/tile outputs are surfaced as safe reference/download links rather than rendered directly — a production tile service is needed for full raster rendering.
- This is a reference implementation of an evolving specification, not a finished OGC Standard.

---

## Documentation Index

Deep dives beyond this README:

- [Documentation Index](./standardized_server/docs/INDEX.md)
- [Product Overview](./standardized_server/docs/PRODUCT.md)
- [Quickstart](./standardized_server/docs/QUICKSTART.md)
- [Architecture](./standardized_server/docs/ARCHITECTURE.md)
- [Codebase Tour](./standardized_server/docs/CODEBASE_TOUR.md)
- [Tool Contract](./standardized_server/docs/TOOL_CONTRACT.md)
- [Proxy Workflow](./standardized_server/docs/PROXY_WORKFLOW.md)
- [Process Output Artifacts](./standardized_server/docs/OUTPUT_ARTIFACTS.md)
- [Configuration](./standardized_server/docs/CONFIGURATION.md)
- [Security Model](./standardized_server/docs/SECURITY.md)
- [Development Guide](./standardized_server/docs/DEVELOPMENT.md)
- [Testing Guide](./standardized_server/docs/TESTING.md)
- [Deployment Guide](./standardized_server/docs/DEPLOYMENT.md)
- [Extending the Server](./standardized_server/docs/EXTENDING.md)
- [Troubleshooting](./standardized_server/docs/TROUBLESHOOTING.md)
- [Experimental Conformance Checklist](./standardized_server/docs/CONFORMANCE.md)
- [GSoC Final Report](./standardized_server/docs/gsoc/FINAL_REPORT.md) · [Deliverables](./standardized_server/docs/gsoc/DELIVERABLES.md) · [Timeline](./standardized_server/docs/gsoc/TIMELINE.md)

---

*Developed by Pranav Angrish for Google Summer of Code 2026, mentored by 52°North.*
