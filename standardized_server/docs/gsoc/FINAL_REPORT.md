# GSoC 2026 Final Report

**Project:** MCP for OGC APIs — Developing Model Context Protocols for the Suite of OGC APIs
**Organization:** [52°North](https://52north.org/)
**Contributor:** Pranav Angrish ([LinkedIn](https://www.linkedin.com/in/pranav-angrish) · [GitHub](https://github.com/PranavAngrish/OGC-MCP-Service))
**Mentors:** Benjamin Proß, Benedikt Gräler

## Status

This is an experimental reference implementation, not an adopted OGC Standard.
It is a working demonstration of how the Model Context Protocol (MCP) can
expose OGC API capabilities to AI clients through a stable, auditable tool
contract, with a full-stack reference implementation to validate the design.

## Problem Statement

OGC APIs (Common, Features, Records, Processes) are powerful but require
specialist knowledge: exact endpoint shapes, process identifiers and input
schemas, coordinate reference systems and axis order, sync/async execution
semantics, and careful handling of credentials and untrusted upstream data.
A naive "let an LLM call the API" integration is unsafe — the model can
invent inputs, hallucinate coordinates, follow a malicious redirect, or
trigger a real-world process execution with no human ever reviewing it.

The project's goal was to design and build a bridge that gives an AI client
just enough structure to discover, inspect, and safely act on OGC API
deployments — with every consequential action validated against the server's
actual schema and explicitly approved by a human before it runs.

## What Was Built

### 1. Mapping Specification (`spec/`)

An early, extensible mapping from OGC API concepts to MCP tool calls,
expressed as Draft 2020-12 JSON Schema. The mapping is modular per OGC API
(Features and Records are independently reusable) so future modules
(Coverages, EDR, Tiles, Maps, Styles) can be added without breaking existing
contracts. Companion schemas define the output-manifest, workflow-event, and
clarification-request contracts used throughout the server.

### 2. Python Reference Server (`standardized_server/`)

A production-quality FastMCP server exposing ~25 `ogc_*` tools across
Common, Features, Records, Processes, and Jobs, built around:

- **An operator-owned server registry** — the model can never choose an
  arbitrary upstream base URL or supply credentials as a tool argument.
- **A validated, human-confirmed process-execution plan lifecycle**
  (`ogc_proxy_create_plan → update_plan → confirm_plan → execute_plan`),
  where a plan literally cannot reach `confirmed` state while any input is
  unresolved or invalid, and cannot execute without an explicit, recorded
  human approval. See [ADR 0001](../adr/0001-human-in-the-loop-process-execution.md).
- **Proxy memory** — large or unbounded responses default to a sanitized,
  coordinate-free summary plus an opaque `mem_*` handle, keeping raw
  geospatial payloads out of the model's context window by default. See
  [ADR 0002](../adr/0002-proxy-memory-summary-mode.md).
- **A canonical output-artifact pipeline** (`artifacts/`) that turns any
  process result into a versioned `output_manifest`, separately tracking
  whether execution succeeded, whether each output was retrieved, whether its
  format was understood, and which presentations (map/table/chart/metric/
  image/text/download) are genuinely ready — so a successful process response
  never silently implies a usable result.
- **A validated declarative feature-query tool** (`ogc_features_query`) that
  translates structured filters to CQL2, auto-paginates, and returns a
  coordinate-free facts table gated by an explicit `evidence.safeToAnswer`
  completeness flag, preventing the model from answering factual questions
  from incomplete data.
- **Defense-in-depth security**: SSRF-resistant URL validation, manual
  redirect handling with per-hop revalidation, a shared resolution budget
  bounding time/bytes/fetch-count across an entire output manifest,
  prompt-injection sanitization of upstream text, and a policy gate
  (`policy.expose_direct_execution_tools`) that structurally prevents the
  model from even discovering the unmediated execution tool unless an
  operator opts in. See [ADR 0003](../adr/0003-direct-execution-policy-gate.md).
- **Pluggable, horizontally scalable state** — plans, proxy memory, and
  artifacts all sit behind a `KeyValueStore` protocol with in-memory and
  Redis-backed implementations.
- **A deterministic, network-free `unittest` suite** covering the tool
  surface, configuration, transport, security boundaries, the plan lifecycle,
  the artifact pipeline, and the tool-contract schema itself.

### 3. Terra Console — A Full Conversational Reference Client (`ui/`)

A React + Node/Express application connecting a Gemini-powered agent to the
MCP server over stdio, built to prove the server's safety model end-to-end
rather than just in isolation:

- The Node gateway owns the LLM API key and the MCP client; the browser never
  talks to either directly.
- `ogc_proxy_confirm_plan` and `ogc_proxy_artifact_retrieve` are deliberately
  withheld from the model's callable tools — approval is a real browser
  action, fingerprinted and re-validated server-side against the exact plan
  before it is recorded.
- A second, independent model-safety boundary in Node strips coordinates,
  geometries, and secrets from every tool result before it reaches Gemini,
  on top of the Python server's own sanitization.
- Interactive MapLibre GL result rendering, CRS-aware and fail-closed:
  unknown coordinate systems or ambiguous columns are never guessed onto a
  map.
- Live background-job tracking over Server-Sent Events so long-running async
  OGC processes update the original chat message on completion.
- Its own Node test suite (`ui/server/*.test.mjs`).

Full technical detail of this stack lives in
[SYSTEM_FLOW_REPORT.md](../SYSTEM_FLOW_REPORT.md).

## Real-World Validation

Beyond demo servers, the project validated against Spain's national IDEE/IGN
OGC API deployment (`api-features.idee.es`, `api-processes.idee.es`) —
production elevation, buffer, and statistics processes over a real national
feature catalogue. This surfaced and fixed real interoperability issues (for
example, an upstream endpoint returning a misleading `Location: /jobs/...`
header alongside an already-complete inline result). See
[REAL_OGC_TEST_SERVERS.md](../REAL_OGC_TEST_SERVERS.md).

## Design Values

- Discovery before execution; exact upstream identifiers, never invented ones.
- Operator-owned registry, not model-owned URLs.
- Human confirmation before any state-changing or costly action.
- Compact, sanitized, model-facing summaries — never unbounded raw payloads.
- Credentials and secrets stay outside model context and tool schemas.
- Honesty about system state: a successful HTTP call, a successful process
  execution, a retrieved output, and a rendered presentation are four
  different facts, never conflated into one.
- Deterministic tests for every behavior that matters.

## Known Limitations

- Plan, proxy-memory, and artifact visibility is deployment-wide at the
  Python MCP layer, not scoped per user/session; the bundled UI gateway adds
  its own session scoping for artifact downloads, but a multi-tenant Python
  deployment needs this addressed directly.
- The bundled UI is intentionally scoped for local/single-user use; production
  use needs authentication, per-user session isolation, durable storage, and
  rate limiting.
- Raster, coverage, and tile outputs are safely stored and referenced but have
  no compatible preview/tiler adapter yet, so they remain downloadable rather
  than rendered.
- The input-schema validator is intentionally conservative (high-confidence
  checks only), not a full JSON Schema validator.
- This is a reference implementation of an evolving specification, not an
  adopted OGC Standard.

## Future Work

- Authentication and per-user/session isolation for plans, memory, artifacts,
  and gateway sessions.
- Durable storage and event delivery for multi-instance deployments.
- DNS-aware egress controls, stronger audit logging, and rate limiting.
- Additional OGC API module coverage: Coverages, EDR, Tiles, Maps, Styles.
- Additional format adapters and preview support, especially for raster and
  coverage outputs.
- Broader interoperability testing against more public OGC API deployments,
  and feedback from the OGC and MCP communities.

## Acknowledgements

Thank you to 52°North, mentors Benjamin Proß and Benedikt Gräler, and the
Google Summer of Code program for the opportunity to work on this project.

See also: [Deliverables](DELIVERABLES.md) · [Timeline](TIMELINE.md) ·
[Final Blog Post](PranavAngrishGsoCFinalBlog.md)
