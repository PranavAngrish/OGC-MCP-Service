# GSoC 2026 Timeline

High-level phase breakdown of the project. For narrative detail, see the
[final blog post](PranavAngrishGsoCFinalBlog.md); for a deliverable-by-deliverable
index, see [Deliverables](DELIVERABLES.md).

## Community Bonding

- Studied the OGC API family (Common, Features, Records, Processes) and the
  Model Context Protocol specification.
- Surveyed existing OGC API server implementations (pygeoapi, ldproxy) and
  public deployments suitable for integration testing.
- Scoped the core risk the project needed to design around: an AI agent that
  can silently invent geospatial inputs or trigger process execution without
  human review.
- Drafted the initial OGC API → MCP mapping approach with mentors
  Benjamin Proß and Benedikt Gräler.

## Phase 1 — Mapping Specification and Server Skeleton

- Wrote the first version of the OGC API → MCP mapping specification
  (`spec/ogc-mcp-mapping.json`), designed to be modular per OGC API so
  Features and Records translations are independently reusable.
- Stood up the FastMCP server skeleton, operator-owned server registry, and
  configuration schema.
- Implemented the OGC API - Common and Features module services and their
  corresponding `ogc_*` tools.
- Established the bounded HTTP transport and initial SSRF-resistant URL
  validation.

## Phase 2 — Records, Processes, and the Human-in-the-Loop Workflow

- Added OGC API - Records module services and tools.
- Added OGC API - Processes and Jobs module services, including sync/async
  execution handling and capability-aware fallback selection.
- Designed and implemented the confirmation-gated process-execution plan
  lifecycle (`create_plan → update_plan → confirm_plan → execute_plan`),
  documented in [ADR 0001](../adr/0001-human-in-the-loop-process-execution.md).
- Implemented proxy memory (summary-mode responses with opaque `mem_*`
  handles) to keep large/geometry-heavy payloads out of the model's context
  window by default — [ADR 0002](../adr/0002-proxy-memory-summary-mode.md).
- Added the direct-execution policy gate so unmediated execution/dismiss
  tools are hidden from the model unless an operator explicitly opts in —
  [ADR 0003](../adr/0003-direct-execution-policy-gate.md).
- Began the deterministic `unittest` suite, run without network access using
  mocked transports.

## Midterm Milestone

- End-to-end flow working: discovery → plan creation → clarification →
  human confirmation → execution → result, against demo OGC API servers.
- Core security boundary in place: SSRF validation, manual redirect
  revalidation, and response sanitization against prompt injection.
- Pluggable `KeyValueStore` abstraction (in-memory implementation) backing
  plans and proxy memory.

## Phase 3 — Output Artifacts, Real-World Validation, and Scale-Out

- Designed and implemented the process-output artifact pipeline
  (`artifacts/`): extraction of advertised outputs, budgeted reference
  resolution, media-type detection, format-adapter parsing (GeoJSON, GML,
  WKT, generic tabular), and explicit execution/retrieval/interpretation/
  presentation state tracking via a versioned `output_manifest`.
- Added the validated declarative feature-query tool (`ogc_features_query`):
  structured-filter-to-CQL2 translation, automatic pagination, a
  coordinate-free facts table, and the `evidence.safeToAnswer` completeness
  gate.
- Validated the server against a real, production national deployment —
  Spain's IDEE/IGN OGC API (elevation, buffer, and statistics processes) —
  fixing real interoperability issues surfaced only by a live server. See
  [REAL_OGC_TEST_SERVERS.md](../REAL_OGC_TEST_SERVERS.md).
- Added the Redis-backed `KeyValueStore` implementation and Streamable HTTP
  transport support for multi-worker deployment.
- Expanded the test suite to cover the artifact pipeline, the feature-query
  evidence gate, and the tool contract's own JSON Schema validity.

## Phase 4 — Terra Console Reference Client

- Built the Node/Express gateway connecting a Gemini-powered agent to the MCP
  server over stdio, with the gateway (not the browser) owning both the LLM
  API key and the MCP client connection.
- Implemented the model-visible tool policy that withholds
  `ogc_proxy_confirm_plan` and `ogc_proxy_artifact_retrieve` from the LLM's
  callable tools, so approval can only happen through a real, server-validated
  browser action.
- Added a second, independent context-filtering layer in Node that strips
  coordinates and secrets from tool results before they reach Gemini.
- Built the React chat interface, streamed activity feed, approval cards,
  and CRS-aware MapLibre GL result rendering.
- Added Server-Sent Events–based background-job tracking for long-running
  async OGC processes.
- Added the Node test suite for the gateway.

## Final Phase — Documentation, Polish, and Reporting

- Wrote the full documentation set: architecture, codebase tour, tool
  contract, proxy workflow, output artifacts, configuration, security model,
  development/testing/deployment guides, and Architecture Decision Records.
- Produced UML diagrams (system architecture, internal classes, process
  execution sequence) and the project overview slide deck.
- Finalized the deterministic test suites (Python and Node) and the example
  configurations (Claude Desktop, Streamable HTTP + Redis, real IDEE/IGN
  deployment).
- Wrote the [final report](FINAL_REPORT.md), [deliverables index](DELIVERABLES.md),
  and [final blog post](PranavAngrishGsoCFinalBlog.md).

See also: [Final Report](FINAL_REPORT.md) · [Deliverables](DELIVERABLES.md)
