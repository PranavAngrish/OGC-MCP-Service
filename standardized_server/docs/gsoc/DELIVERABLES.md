# GSoC 2026 Deliverables

Concrete artifacts produced during the project, and where each one lives in
the repository.

## 1. Specification

| Deliverable | Location |
| --- | --- |
| OGC API → MCP mapping specification | [`spec/ogc-mcp-mapping.json`](../../../spec/ogc-mcp-mapping.json) |
| Server-implemented tool contract (Draft 2020-12 JSON Schema, modular Features/Records translations) | [`standardized_server/spec/ogc-mcp-tool-contract.json`](../../spec/ogc-mcp-tool-contract.json) |
| Output-manifest contract | [`spec/ogc-output-manifest.schema.json`](../../../spec/ogc-output-manifest.schema.json) |
| Workflow-event contract | [`spec/ogc-workflow-event.schema.json`](../../../spec/ogc-workflow-event.schema.json) |
| Clarification-request contract | [`spec/ogc-clarification-request.schema.json`](../../../spec/ogc-clarification-request.schema.json) |
| Operator configuration schema | [`standardized_server/schemas/server-config.schema.json`](../../schemas/server-config.schema.json) |

## 2. Python Reference Server (`standardized_server/`)

| Deliverable | Location |
| --- | --- |
| FastMCP tool registration and server instructions | [`src/ogc_mcp_reference/app.py`](../../src/ogc_mcp_reference/app.py) |
| Runtime composition root | [`src/ogc_mcp_reference/runtime.py`](../../src/ogc_mcp_reference/runtime.py) |
| Operator configuration parsing and models | [`config.py`](../../src/ogc_mcp_reference/config.py), [`models.py`](../../src/ogc_mcp_reference/models.py) |
| Server registry | [`registry.py`](../../src/ogc_mcp_reference/registry.py) |
| SSRF-resistant URL/path/reference validation | [`security.py`](../../src/ogc_mcp_reference/security.py) |
| Bounded, budgeted HTTP transport | [`transport.py`](../../src/ogc_mcp_reference/transport.py) |
| Result envelopes and stable error codes | [`result.py`](../../src/ogc_mcp_reference/result.py), [`errors.py`](../../src/ogc_mcp_reference/errors.py) |
| OGC API - Common, Features, Records, Processes module services | [`modules/`](../../src/ogc_mcp_reference/modules/) |
| Auth (none/bearer/API key/basic/JWT with refresh) | [`services/auth.py`](../../src/ogc_mcp_reference/services/auth.py) |
| Capability discovery and fallback rules | [`services/capabilities.py`](../../src/ogc_mcp_reference/services/capabilities.py), [`services/fallback.py`](../../src/ogc_mcp_reference/services/fallback.py) |
| Conservative execute-input validation | [`services/input_schema.py`](../../src/ogc_mcp_reference/services/input_schema.py) |
| Proxy memory (summary mode + handles) | [`services/memory.py`](../../src/ogc_mcp_reference/services/memory.py) |
| Response sanitization / prompt-injection mitigation | [`services/sanitization.py`](../../src/ogc_mcp_reference/services/sanitization.py) |
| Process description cache | [`services/process_descriptions.py`](../../src/ogc_mcp_reference/services/process_descriptions.py) |
| Human-confirmed process-execution planner | [`services/planner.py`](../../src/ogc_mcp_reference/services/planner.py) |
| Pluggable key-value store (in-memory + Redis) | [`services/store.py`](../../src/ogc_mcp_reference/services/store.py) |
| LangGraph-ready plan workflow | [`workflows/planning.py`](../../src/ogc_mcp_reference/workflows/planning.py), [`workflows/state.py`](../../src/ogc_mcp_reference/workflows/state.py) |
| Process-output artifact pipeline (extraction, resolution, detection, parsing, storage, presentation state) | [`artifacts/`](../../src/ogc_mcp_reference/artifacts/) |
| Format adapters (GeoJSON, GML, WKT, generic tabular) | [`artifacts/parsers/`](../../src/ogc_mcp_reference/artifacts/parsers/) |
| Deterministic, network-free `unittest` suite (11 test modules) | [`tests/`](../../tests/) |
| Example configs (Claude Desktop, Streamable HTTP + Redis, real IDEE/IGN deployment) | [`config.example.json`](../../config.example.json), [`examples/`](../../examples/) |

## 3. Terra Console — Conversational Reference Client (`ui/`)

| Deliverable | Location |
| --- | --- |
| Express gateway: sessions, SSE streaming, Gemini tool loop | [`server/index.mjs`](../../../ui/server/index.mjs), [`server/agent.mjs`](../../../ui/server/agent.mjs) |
| MCP stdio client wrapper | [`server/mcp-client.mjs`](../../../ui/server/mcp-client.mjs) |
| Model-visible tool policy (withholds confirm/artifact-retrieve from the LLM) | [`server/tool-policy.mjs`](../../../ui/server/tool-policy.mjs) |
| Model-context filtering / coordinate stripping | [`server/model-output.mjs`](../../../ui/server/model-output.mjs) |
| Manifest hydration and render verification | [`server/result-artifacts.mjs`](../../../ui/server/result-artifacts.mjs) |
| Browser-safe geospatial normalization | [`server/geospatial.mjs`](../../../ui/server/geospatial.mjs) |
| Background async-job polling | [`server/background-jobs.mjs`](../../../ui/server/background-jobs.mjs) |
| React chat, activity feed, approval card, output panel, map renderer | [`src/components/`](../../../ui/src/components/) |
| Node test suite | [`server/*.test.mjs`](../../../ui/server) |

## 4. Documentation

| Deliverable | Location |
| --- | --- |
| Root project README (what/why/how, architecture, install) | [`README.md`](../../../README.md) |
| Documentation index | [`INDEX.md`](../INDEX.md) |
| Product overview | [`PRODUCT.md`](../PRODUCT.md) |
| Quickstart | [`QUICKSTART.md`](../QUICKSTART.md) |
| Architecture | [`ARCHITECTURE.md`](../ARCHITECTURE.md) |
| Full-stack system flow and rendering architecture | [`SYSTEM_FLOW_REPORT.md`](../SYSTEM_FLOW_REPORT.md) |
| Codebase tour | [`CODEBASE_TOUR.md`](../CODEBASE_TOUR.md) |
| Tool contract reference | [`TOOL_CONTRACT.md`](../TOOL_CONTRACT.md) |
| Proxy (human-in-the-loop) workflow | [`PROXY_WORKFLOW.md`](../PROXY_WORKFLOW.md) |
| Process output artifacts | [`OUTPUT_ARTIFACTS.md`](../OUTPUT_ARTIFACTS.md) |
| Configuration reference | [`CONFIGURATION.md`](../CONFIGURATION.md) |
| Security model | [`SECURITY.md`](../SECURITY.md) |
| Development guide | [`DEVELOPMENT.md`](../DEVELOPMENT.md) |
| Testing guide | [`TESTING.md`](../TESTING.md) |
| Deployment guide | [`DEPLOYMENT.md`](../DEPLOYMENT.md) |
| Extending the server | [`EXTENDING.md`](../EXTENDING.md) |
| Troubleshooting | [`TROUBLESHOOTING.md`](../TROUBLESHOOTING.md) |
| Experimental conformance checklist | [`CONFORMANCE.md`](../CONFORMANCE.md) |
| React UI overview | [`UI.md`](../UI.md) |
| Real OGC test deployment notes | [`REAL_OGC_TEST_SERVERS.md`](../REAL_OGC_TEST_SERVERS.md) |
| Architecture Decision Records (0001–0003) | [`adr/`](../adr/) |
| UML diagrams (system architecture, internal classes, process-execution sequence) | [`uml/`](../uml/) |
| Final blog post (Markdown + Word) | [`PranavAngrishGsoCFinalBlog.md`](PranavAngrishGsoCFinalBlog.md) / [`.docx`](PranavAngrishGsoCFinalBlog.docx) |
| Project overview slide deck | [`OGC_to_MCP_Bridging_Pranav_Angrish.pptx`](../../../OGC_to_MCP_Bridging_Pranav_Angrish.pptx) (source: [`scripts/generate_ogc_mcp_deck.py`](../../../scripts/generate_ogc_mcp_deck.py)) |

## 5. Test Coverage Summary

The Python suite (`PYTHONPATH=src python -m unittest discover -s tests -v`)
covers, deterministically and without network access:

- FastMCP tool registration and response-mode behavior (`test_app.py`)
- the output-artifact pipeline end to end (`test_artifacts.py`)
- configuration parsing and registry validation (`test_config.py`)
- `ogc_features_query` CQL2 translation and the evidence gate (`test_feature_query.py`)
- conservative execute-input validation (`test_input_schema.py`)
- process/job service behavior (`test_processes.py`)
- the human-confirmed plan lifecycle, capabilities, JWT auth, sanitization (`test_proxy_services.py`)
- SSRF/reference/path validation (`test_security.py`)
- in-memory and Redis store behavior (`test_store.py`)
- the tool contract's own JSON Schema validity (`test_tool_contract_schema.py`)
- HTTP transport, auth injection, and structured error handling (`test_transport.py`)

The UI gateway has its own `node --test` suite under `ui/server/*.test.mjs`.

See also: [Final Report](FINAL_REPORT.md) · [Timeline](TIMELINE.md)
