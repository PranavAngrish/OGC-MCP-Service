# Codebase Tour

This guide helps engineers navigate the reference implementation.

## Top-Level Layout

```text
standardized_server/
|-- config.example.json
|-- docs/
|-- examples/
|-- pyproject.toml
|-- schemas/
|-- spec/
|-- src/ogc_mcp_reference/
`-- tests/
```

## Entry Points

### `src/ogc_mcp_reference/__main__.py`

Defines the CLI:

```bash
python -m ogc_mcp_reference --config path/to/config.json --transport stdio
```

It parses `--config` and `--transport`, creates the FastMCP server, and calls
`mcp.run()`.

### `src/ogc_mcp_reference/app.py`

Registers the FastMCP server, resources, tools, and server instructions.

Important responsibilities:

- creates the runtime with `create_runtime`;
- publishes `ogc-mcp://guide/workflow`;
- publishes `ogc-mcp://registry/servers`;
- registers all `ogc_*` tools;
- conditionally registers `ogc_processes_execute`;
- applies response summary/raw mode through `_apply_response_mode`;
- parses JSON string arguments used by MCP tools.

If you add or remove an MCP tool, this is where the tool is registered.

## Runtime And Configuration

### `runtime.py`

The composition root. It creates the registry, transport client, OGC module
services, proxy services, stores, and workflow facade.

### `config.py`

Parses operator JSON configuration into typed dataclasses. It validates server
IDs, service names, auth types, security policy shape, store settings, and
policy toggles.

### `models.py`

Defines immutable dataclasses for:

- auth profiles;
- security policy;
- request limits;
- server profiles;
- store settings;
- tool-surface policy;
- registry settings;
- upstream response envelopes.

### `registry.py`

Resolves server IDs and defaults. It also verifies that a selected server
supports the requested OGC service.

## HTTP, Security, And Result Envelopes

### `transport.py`

Owns HTTP calls to upstream OGC APIs.

It injects auth headers, enforces response-size limits, sets timeouts, avoids
redirect following, retries JWT bearer requests once after a `401`, decodes JSON
responses, and raises structured transport/upstream errors.

### `security.py`

Validates:

- configured base URLs;
- private/loopback URL policy;
- relative upstream paths;
- execute-request HTTP(S) references;
- reference host allowlists.

### `result.py`

Builds stable success and failure envelopes. Expected server errors become
model-friendly structured results instead of uncaught exceptions.

### `errors.py`

Defines error classes with stable machine-readable codes.

## OGC Module Services

The `modules/` package contains service classes that know OGC API HTTP shapes
but not MCP.

### `modules/common.py`

Implements:

- landing page retrieval;
- conformance retrieval;
- safe generic read-only relative resource access.

### `modules/features.py`

Implements:

- collection listing;
- collection description;
- a bounded query-surface discovery call (`describe_query_surface`) that merges
  collection metadata, conformance, queryables, and one sample so callers know
  which fields are filterable/returnable/observed;
- a validated, auto-paginated declarative query (`query`, backing
  `ogc_features_query`) that translates structured filters to CQL2, follows
  same-origin `rel=next` links, and returns a coordinate-free facts table plus
  an explicit `evidence.safeToAnswer` completeness gate;
- feature item listing;
- single feature retrieval.

`get_items` and `query` both return `guidance.reference_href` and
`guidance.source`, which are used by the process planning workflow for
referenced feature inputs.

### `modules/records.py`

Implements:

- catalogue collection listing;
- record search;
- single record retrieval.

### `modules/processes.py`

Implements:

- process listing (with bounded, paginated `search_text` filtering for large
  catalogues);
- process description;
- process execution;
- job listing;
- job status retrieval;
- job result retrieval;
- job dismissal.

Execution validates referenced inputs before the network call leaves the server.
Successful execution and job-result responses are also passed through
`runtime.output_artifacts` (see `artifacts/` below) to build the versioned
`output_manifest`.

## Proxy Services

The `services/` package contains cross-cutting behavior that makes the bridge
safe and useful for AI clients.

### `services/auth.py`

Manages JWT bearer login, token caching, refresh, invalidation, and retry.

### `services/capabilities.py`

Loads `/conformance`, caches results, and normalizes selected capability flags.

### `services/fallback.py`

Maps missing capability flags to fallback rules. The workflow currently uses
this for async-to-sync execution selection.

### `services/input_schema.py`

Performs conservative execute-input validation. It flags missing required inputs
and simple literal JSON type mismatches, while intentionally skipping complex
schemas, references, unions, and multi-occurrence shapes.

### `services/memory.py`

Stores full upstream payloads behind opaque memory handles. It returns compact
metadata for list views and paginated slices for retrieval.

### `services/planner.py`

Creates, validates, updates, confirms, rejects, executes, and lists proxy plans.
This is the core state machine for human-confirmed process execution.

### `services/process_descriptions.py`

Short-lived cache for process description responses. This avoids repeated
upstream calls when the same process has already been described.

### `services/sanitization.py`

Builds model-facing summaries and removes instruction-like text from upstream
data before it enters the model-visible response.

### `services/store.py`

Defines the `KeyValueStore` protocol and implements:

- `InMemoryStore`;
- `RedisStore`;
- `build_store`.

## Workflow Layer

### `workflows/planning.py`

Wraps `ProxyPlanner` in a LangGraph-ready workflow facade. If LangGraph is
installed, it compiles a graph. Otherwise, it runs the same deterministic nodes
locally.

### `workflows/state.py`

Defines the typed workflow state used by LangGraph and the local fallback.

## Process Output Artifacts

The `artifacts/` package turns a raw upstream process response into a
versioned, presentation-aware `output_manifest`. It is used by
`modules/processes.py` (via `runtime.output_artifacts`) for both synchronous
execution and `ogc_jobs_get_results`.

### `artifacts/pipeline.py`

`OutputArtifactPipeline.build(...)` is the orchestrator. It extracts advertised
outputs, resolves inline values or references (budgeted through
`transport.OutputResolutionBudget`), detects media type, parses with a
registered adapter, stores original/canonical/preview representations, and
decides which presentations (map/table/chart/metric/image/text/download) are
actually ready.

### `artifacts/extractors.py`

Recognizes advertised output identifiers and common OGC output wrapper shapes
(`value`, `data`, `href`, nested `format.mediaType`). Does not follow arbitrary
links found inside feature properties or record metadata.

### `artifacts/detection.py`

Detects and normalizes media types, combining the advertised process output,
the requested output format, wrapper metadata, HTTP content type, and bounded
content inspection.

### `artifacts/parsers/`

Format adapters: `geojson.py`, `gml.py`, `wkt.py`, and `generic.py` (tabular
/ JSON / text fallback). Each adapter probes a bounded sample, decodes with
explicit resource limits, and produces canonical and/or bounded preview data.

### `artifacts/models.py`

Dataclasses shared across the pipeline: `OutputCandidate`, `ParsedArtifact`,
and the manifest schema version/state helpers (`retrieval_state`,
`interpretation_state`).

### `artifacts/previews.py`

Builds bounded, renderer-safe previews (`bounded_geojson_preview`,
`bounded_json_preview`) that retain complete features/rows rather than cutting
JSON or geometry mid-structure.

### `artifacts/registry.py`

`ParserRegistry` selects the adapter for a detected media type.

### `artifacts/store.py`

`ArtifactStore` persists original/canonical/preview representations behind
opaque `art_*` handles with a configurable TTL, retrievable via
`ogc_proxy_artifact_retrieve`.

## Tests

The `tests/` package uses Python `unittest` and `httpx.MockTransport`.

Important files:

- `test_app.py`: FastMCP tool registration and response-mode behavior.
- `test_artifacts.py`: output-artifact pipeline -- extraction, resolution,
  media-type detection, parser adapters, and presentation-state decisions.
- `test_config.py`: config parsing and registry validation.
- `test_feature_query.py`: `ogc_features_query` -- CQL2 translation,
  pagination, the facts table, and the `evidence.safeToAnswer` gate.
- `test_transport.py`: auth injection, limits, and upstream errors.
- `test_security.py`: URL/path/reference validation.
- `test_processes.py`: process service behavior.
- `test_input_schema.py`: conservative input-schema validation.
- `test_proxy_services.py`: planner, workflow, memory, capabilities, JWT retry.
- `test_store.py`: in-memory and Redis store behavior.
- `test_tool_contract_schema.py`: validates `spec/ogc-mcp-tool-contract.json`
  itself against its embedded Draft 2020-12 JSON Schema.

Run all tests from the repository root:

```bash
PYTHONPATH=standardized_server/src \
  python -m unittest discover -s standardized_server/tests -v
```
