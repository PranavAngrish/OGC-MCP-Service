# Architecture

## Status

This project is an experimental MCP reference implementation for OGC APIs. It is
intended to support design review and interoperability testing. It is not an
adopted OGC Standard and should not be represented as one.

## Design Principles

### Stable MCP Contract

The public surface is a small set of stable `ogc_*` tools. Tool names describe
OGC concepts rather than implementation brands. AI clients can use the same tool
workflow against GeoLabs, CubeWerx, pygeoapi, pycsw, or another registered
deployment.

### OGC Discovery First

Clients should discover capabilities before acting:

```text
ogc_servers_list
  -> ogc_common_get_landing_page
  -> ogc_common_get_conformance
  -> ogc_processes_list
  -> ogc_processes_describe
  -> ogc_proxy_create_plan
  -> human reviews confirmation_prompt
  -> ogc_proxy_confirm_plan
  -> ogc_proxy_execute_plan
```

Process identifiers and schemas are server-owned. The MCP layer must not invent
or silently normalize them.

### Stateful Proxy Runtime

The `ogc_proxy_*` tools are the recommended production-style workflow. They keep
full payloads in proxy memory, return compact sanitized summaries to the model,
validate advertised process and collection identifiers (and, on a best-effort
basis, the declared input schema) before execution, and choose deterministic
fallbacks from cached conformance facts.

`ogc_processes_execute` -- the unmediated, no-confirmation-gate execution tool
-- is not part of the default tool surface at all. It is only registered when
the operator sets `policy.expose_direct_execution_tools=true` in the server
configuration. This is enforced structurally: the `@mcp.tool()` registration
itself is skipped, so a disabled tool cannot be discovered or called by the
model, not merely refused at call time. `ogc_jobs_dismiss` (cancelling a job)
is intentionally left ungated in both configurations, since cancelling
in-flight work is lower-risk and more reversible than starting a new
execution, and a multi-step confirmation flow would be poor UX for an
emergency-stop action.

The proxy workflow layer is LangGraph-ready. When LangGraph is installed, the
planning workflow is compiled as a state graph; when it is not installed, the
same deterministic node methods run locally. In both cases, execution is blocked
until a plan reaches the explicit `confirmed` lifecycle state.

### Plan and Proxy-Memory Persistence

`ProxyPlanner` and `ProxyMemoryStore` persist their state through a pluggable
`KeyValueStore` (see `services/store.py`) rather than an in-process dict:

- `backend="memory"` (default): process-local, zero configuration, correct for
  a single-worker `stdio` deployment. State is invisible to any other worker,
  replica, or process restart -- a plan created on one process cannot be
  confirmed or executed from another.
- `backend="redis"`: required once a `streamable-http` deployment runs more
  than one worker process or replica behind a load balancer, so a
  `ogc_proxy_confirm_plan` call routed to a different worker than the one that
  ran `ogc_proxy_create_plan` still resolves the same plan. Requires the
  optional `redis` extra and an environment variable (named by
  `store.redis_url_env`) holding the connection URL; the URL itself is never a
  tool argument or model-visible value, consistent with how upstream OGC API
  credentials are handled.

Plans and proxy-memory records expire after a configurable TTL (defaults:
`plan_ttl_seconds=3600`, `memory_ttl_seconds=1800`; `0` disables expiry) so
abandoned, never-confirmed plans and unused memory handles do not accumulate
forever in a long-running process or shared store.

### Execute-Input Schema Validation

`ogc_proxy_create_plan` fetches the target process's description and runs
`execute_request` through `services/input_schema.py` before the plan is
considered `ready_for_confirmation`. This is intentionally conservative rather
than a full JSON Schema validator: OGC process input schemas frequently
express a literal-value-or-href-reference union, or accept multiple
occurrences of an input, shapes that are easy to mis-validate. The checker
only flags two high-confidence problems -- a required input missing entirely,
or a literal value whose JSON type plainly conflicts with a simple declared
schema type -- and otherwise skips rather than risks blocking a legitimate
call with a false positive. Any flagged issue is appended to the plan's
`unresolved` list using the same mechanism as the existing process/collection
ID checks, which naturally keeps the plan at `needs_resolution` until the
caller supplies a corrected `execute_request`.

### Operator-Owned Registry

The model chooses from registered `server_id` values. It cannot provide an
arbitrary destination URL for MCP-originated HTTP requests. This boundary:

- reduces SSRF exposure;
- keeps server onboarding auditable;
- supports deployment-specific auth;
- makes defaults explicit;
- allows profile-specific timeouts and response limits.

### Credentials Stay Outside Model Context

Profiles refer to environment-variable names. The transport layer injects
credentials immediately before sending a request. Credentials never appear in
MCP tool schemas, tool responses, or model prompts. The Redis connection URL
used by the plan/memory store backend follows the same pattern.

### Structured Envelopes

Every OGC operation returns:

```json
{
  "ok": true,
  "operation": "processes.describe",
  "server": {
    "id": "geolabs",
    "title": "GeoLabs OGC API - Processes",
    "base_url": "http://tb17.geolabs.fr:8119/ogc-api"
  },
  "request": {
    "method": "GET",
    "path": "/processes/Delaunay"
  },
  "response": {
    "status_code": 200,
    "content_type": "application/json"
  },
  "data": {}
}
```

Failures return:

```json
{
  "ok": false,
  "operation": "processes.execute",
  "error": {
    "code": "security_policy_error",
    "message": "Process input reference host is not operator-approved.",
    "details": {}
  }
}
```

Tools that can return a large or unbounded upstream payload
(`ogc_features_get_items`, `ogc_jobs_get_results`, `ogc_proxy_execute_plan`,
and `ogc_processes_execute` when enabled) default to `response_mode="summary"`:
`data` becomes a sanitized summary and a `memory` field carries an opaque
handle resolving the full payload via `ogc_proxy_memory_list` /
`ProxyMemoryStore`. `response_mode="raw"` returns the original upstream
payload unchanged.

### Bounded Network Access

The transport layer:

- rejects absolute URLs in generic path tools;
- blocks private/loopback base URLs unless explicitly allowed;
- validates process-input references;
- blocks referenced inputs until the operator configures allowed hosts or
  explicitly permits unlisted public hosts;
- does not automatically follow redirects;
- limits response bytes;
- enforces timeouts;
- catches upstream errors as structured MCP output.

These checks complement infrastructure-level egress restrictions.

## Package Boundaries

```text
src/ogc_mcp_reference/
├── app.py          FastMCP tools, resources, and response-mode wiring
├── config.py       JSON configuration loading
├── models.py       Typed immutable configuration models
├── runtime.py      Service composition root
├── registry.py     Registered server resolution
├── security.py     URL and reference validation
├── transport.py    Auth injection and bounded HTTP
├── result.py       Stable success/error envelopes
├── services/       Stateful proxy services
│   ├── auth.py
│   ├── capabilities.py
│   ├── fallback.py
│   ├── input_schema.py   Conservative execute-input schema checks
│   ├── memory.py
│   ├── planner.py
│   ├── sanitization.py
│   └── store.py           Pluggable KeyValueStore (memory / redis)
├── workflows/      LangGraph-ready workflow orchestration
│   ├── planning.py
│   └── state.py
└── modules/
    ├── common.py
    ├── features.py
    ├── records.py
    └── processes.py
```

OGC module classes do not know about MCP. They can be tested independently and
reused by another MCP SDK or language implementation.

Proxy services sit between the MCP tool surface and OGC modules. They are where
deterministic production behavior belongs: token refresh, conformance-derived
capabilities, fallback selection, full-response memory handles, sanitized
summaries, plan validation (including input-schema checks) before execution,
and pluggable persistence for plan/memory state.

`response_mode`/memory-handle wrapping is intentionally implemented only in
`app.py`'s tool callbacks (via the shared `_apply_response_mode` helper), not
inside `services/planner.py` or `workflows/planning.py`. Those lower layers
keep returning the full, unwrapped result so they stay simple to test and
reusable outside an MCP-specific context; summarization is a model-context
concern that belongs at the MCP tool boundary, the same way
`ogc_features_get_items` has always wrapped `FeaturesService.get_items()`.

## UML Diagrams

PlantUML source files under [`docs/uml/`](uml/README.md) document the system
boundary, internal class relationships, and process-execution sequence.

## Extension Strategy

Add a dedicated module when a read-only generic path is no longer sufficient:

1. Define stable operations in `spec/ogc-mcp-tool-contract.json`.
2. Add service methods under `modules/`.
3. Register detailed MCP tools in `app.py`.
4. Add configuration paths/defaults only where necessary.
5. Add deterministic tests.
6. Document conformance expectations.

Candidate modules:

- OGC API - EDR
- OGC API - Coverages
- OGC API - Tiles
- OGC API - Maps
- OGC API - Styles

## Deployment

Use `stdio` for local desktop clients; the default `store.backend="memory"`
is correct here since there is exactly one worker process per user. Use
Streamable HTTP for deployed MCP services:

- A single-worker Streamable HTTP deployment can still use the default
  in-process store.
- A multi-worker or multi-replica Streamable HTTP deployment (anything behind
  a load balancer that may route a confirm/execute call to a different
  process than the one that created the plan) must set `store.backend="redis"`
  and provide a connection URL via the environment variable named in
  `store.redis_url_env`.

Production deployments should also add:

- TLS termination;
- MCP-layer authorization;
- network egress restrictions;
- observability and audit logging;
- secret management;
- rate limiting;
- deployment-specific data governance.

Multi-tenant request isolation (for example, scoping `ogc_proxy_memory_list`
and plan visibility per session/user rather than per deployment) is a known
gap tracked for future work and is not yet implemented.
