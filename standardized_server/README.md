# OGC API MCP Reference Server

This folder contains a specification-oriented MCP reference server for OGC APIs.
It is designed for review, experimentation, and interoperability work across AI
clients and OGC API implementations.

The implementation is intentionally separate from the earlier single-file
prototype. It is not an adopted OGC Standard. The versioned contract under
`spec/` is an experimental project artifact that can evolve through review,
implementation experience, and conformance testing.

## Goals

- Provide stable MCP tool names for common OGC API workflows.
- Work with any AI client that supports MCP.
- Connect to any operator-registered OGC API deployment.
- Keep credentials outside model-visible tool arguments.
- Support OGC API discovery before execution.
- Preserve process-specific input/output structures exactly as advertised.
- Restrict outbound requests and referenced inputs by default.
- Gate process execution behind explicit human confirmation by default.
- Return predictable structured JSON envelopes.
- Scale state (plans, proxy memory) across multiple workers/replicas when deployed over HTTP.
- Make additional OGC API modules easy to add.

## Supported Modules

| Module | MCP Operations |
| --- | --- |
| Registry | List approved OGC API deployments |
| Proxy Runtime | Capability cache, deterministic fallbacks, memory-backed summaries, schema-validated execution plans |
| OGC API - Common | Landing page, conformance, safe read-only relative resource access |
| OGC API - Features | List collections, describe collection, get items, get item |
| OGC API - Records | List catalogues, search records, get record |
| OGC API - Processes | List processes, describe, execute, list/status/results/dismiss jobs |

The read-only `ogc_common_get_resource` tool is a controlled extension point for
registered OGC APIs that do not yet have dedicated MCP tools, such as EDR,
Coverages, Tiles, Maps, or Styles.

## Architecture

```text
AI client
   |
   | MCP: stdio or Streamable HTTP
   v
FastMCP app
   |
   +-- stable ogc_* tool contract (direct execution tool opt-in only)
   +-- structured result envelopes
   +-- proxy planning/memory/capability services
   |
   v
OGC service modules
   |
   +-- Common
   +-- Features
   +-- Records
   +-- Processes
   |
   v
Registry -> security policy -> bounded HTTP transport -> registered OGC APIs

Plan / proxy-memory state -> pluggable store (in-process, or Redis for multi-worker HTTP)
```

See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for design rationale.

## Quick Start

From the `gsoc-mcp` repository:

```bash
source venv/bin/activate
pip install -e standardized_server

python -m ogc_mcp_reference \
  --config standardized_server/config.example.json
```

The default transport is `stdio`, suitable for desktop AI clients.

For a deployed MCP endpoint:

```bash
python -m ogc_mcp_reference \
  --config standardized_server/config.example.json \
  --transport streamable-http
```

The official MCP Python SDK recommends stateless Streamable HTTP with JSON
responses for scalable deployments. This reference server enables those options.
If you run more than one worker process or replica behind a load balancer,
also configure the Redis store backend -- see
[Storage Backend (Plans and Proxy Memory)](#storage-backend-plans-and-proxy-memory)
below; the default in-process store is only correct for a single worker.

## Desktop Client Configuration

Use [claude-desktop-config.json](examples/claude-desktop-config.json) as a
template. Any MCP-compatible client can launch the same `stdio` entrypoint.

## GeoLabs Delaunay Test

Start the MCP server with `config.example.json`, then ask the MCP client to
run the human-confirmed proxy workflow, which is the recommended path for any
user-facing client:

1. Call `ogc_processes_list` with `server_id="geolabs"`.
2. Call `ogc_processes_describe` with `process_id="Delaunay"`.
3. Call `ogc_proxy_create_plan` with:

   ```json
   {
     "plan_request_json": "{\"operation\":\"process_execute\",\"server_id\":\"geolabs\",\"process_id\":\"Delaunay\",\"execute_request\":{\"inputs\":{\"InputPoints\":{\"type\":\"text/xml\",\"href\":\"https://demo.pygeoapi.io/master/collections/dutch_windmills/items?f=json\"}},\"outputs\":{\"Result\":{\"format\":{\"mediaType\":\"application/json\"},\"transmissionMode\":\"value\"}}}}"
   }
   ```

   The proxy validates `process_id` against `ogc_processes_list` and checks
   `execute_request.inputs` against `Delaunay`'s declared input schema before
   returning a plan with status `ready_for_confirmation` (or
   `needs_resolution`, with the specific problem listed, if something is
   missing or mistyped).

4. Show the returned `confirmation_prompt` to the user.
5. Call `ogc_proxy_confirm_plan` with the returned `plan_id` and
   `approved=true` only after the user has actually approved it.
6. Call `ogc_proxy_execute_plan` with the same `plan_id`. The result is
   summarized by default (`response_mode="summary"`); pass
   `response_mode="raw"` to get the full upstream payload inline instead of a
   proxy memory handle.

The unescaped `execute_request` body is available in
[geolabs-delaunay-execute.json](examples/geolabs-delaunay-execute.json).

### Direct execution (opt-in, low-level testing only)

`ogc_processes_execute` sends `execute_request_json` straight to the upstream
server with no plan, no schema validation, and no human-confirmation gate. It
is **not registered** unless the operator sets
`"policy": {"expose_direct_execution_tools": true}` in the server
configuration -- see
[Tool Exposure Policy](#tool-exposure-policy-direct-execution-tools) below.
When enabled, it accepts the same `execute_request_json` shown above plus
`server_id="geolabs"` and `process_id="Delaunay"`.

## Operator Configuration

Copy `config.example.json` and register the deployments your organization
approves. Tool callers select a `server_id`, not an arbitrary base URL.

Authentication configuration references environment-variable names only:

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
{
  "store": {
    "backend": "memory",
    "plan_ttl_seconds": 3600,
    "memory_ttl_seconds": 1800
  }
}
```

- `backend="memory"` (default): process-local, no setup required. Correct for
  `stdio` and for a single-worker Streamable HTTP deployment. **Not** safe for
  more than one worker process or replica: a plan created on one process is
  invisible to a confirm/execute call routed to another.
- `backend="redis"`: required for a multi-worker or multi-replica Streamable
  HTTP deployment. Install the optional extra and set a connection URL via an
  environment variable (the variable name, not the URL itself, goes in the
  config file -- the same pattern used for OGC API credentials):

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
