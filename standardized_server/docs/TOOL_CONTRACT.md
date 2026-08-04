# Tool Contract

The MCP tool contract is the stable interface exposed to clients. Tool names are
implementation-neutral and use OGC concepts rather than deployment-specific
brands.

The machine-readable contract lives in
[`../spec/ogc-mcp-tool-contract.json`](../spec/ogc-mcp-tool-contract.json).

## Result Envelope

Most successful OGC operations return:

```json
{
  "ok": true,
  "operation": "processes.describe",
  "server": {
    "id": "geolabs-tb17",
    "title": "GeoLabs tb17 Processes",
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

Process execution and job-result operations additionally return
`output_manifest`, conforming to
[`../../spec/ogc-output-manifest.schema.json`](../../spec/ogc-output-manifest.schema.json).
The manifest is additive: `data` remains for compatible clients, while new
clients use the manifest to distinguish execution, retrieval, interpretation,
and presentation states.

Expected failures return:

```json
{
  "ok": false,
  "operation": "processes.execute",
  "error": {
    "code": "security_policy_error",
    "message": "Process input references are disabled until the operator configures allowed_reference_hosts."
  }
}
```

## JSON String Arguments

Several MCP tools accept JSON objects encoded as strings because MCP tool
arguments are simple typed parameters. These include:

- `plan_request_json`;
- `execute_request_json`;
- `query_json`;
- `summary_fields_json`.

The server parses these strings with `parse_json_object` and returns a
structured `invalid_json_argument` error when parsing fails.

## Response Modes

Large or unbounded tools default to:

```text
response_mode = "summary"
```

Summary mode stores the full payload in proxy memory and returns a compact
sanitized summary plus a memory handle. Use:

```text
ogc_proxy_memory_retrieve(handle, offset, limit)
```

to page through the stored full payload.

`response_mode="raw"` returns the original upstream payload and should be used
only for low-level interoperability testing or intentionally small responses.

## Registry Tools

### `ogc_servers_list`

Lists configured, enabled OGC API deployments. The response includes server IDs,
titles, descriptions, base URLs, supported services, and default-service
metadata. Credentials are never included.

## Proxy Tools

### `ogc_proxy_get_capabilities`

Loads or reads cached conformance-derived capability flags for a server and
reports active fallback rules.

### `ogc_proxy_memory_list`

Lists model-safe metadata for stored full payloads. It does not return the full
payloads.

### `ogc_proxy_memory_retrieve`

Retrieves full payload data for a memory handle. FeatureCollections and flat
lists are sliced by `offset` and `limit`; scalar or object payloads are returned
as-is.

Callers should pass non-negative offsets and positive limits.

### `ogc_proxy_artifact_retrieve`

Retrieves one opaque `art_*` representation referenced by an
`output_manifest`. This is a trusted renderer/download capability rather than a
general model tool. Terra hydrates it in the gateway, keeps coordinate arrays
out of model messages, and exposes a download only after the handle is
registered for that browser session.

Artifact handles are expiring bearer capabilities. Shared deployments must add
principal scoping and authorization at the MCP boundary.

### `ogc_proxy_create_plan`

Creates a stored process execution plan. The request must use:

```json
{
  "operation": "process_execute",
  "server_id": "process-server-id",
  "process_id": "ExactProcessId",
  "execute_request": {},
  "sources": []
}
```

The planner validates the process description, declared sources, and simple
execute-input problems before execution is possible.

Optional `input_context` is keyed by the exact process input ID and records the
origin, unit, CRS, note, and human-confirmation state of material values. It
lets the planner distinguish user input from assumptions.

### `ogc_proxy_update_plan`

Updates the `execute_request` for a plan that is in `needs_resolution` or
`ready_for_confirmation`. `input_context_json` may update the corresponding
assumption, unit, and CRS facts. This preserves the `plan_id` and revalidates
the plan.

### `ogc_proxy_get_plan`

Retrieves one stored plan and its current lifecycle state.

### `ogc_proxy_list_plans`

Lists compact metadata for non-expired stored plans. Full execute requests are
available through `ogc_proxy_get_plan`.

### `ogc_proxy_confirm_plan`

Records explicit human approval or rejection. Approval is accepted only for
`ready_for_confirmation` plans. Rejection is accepted for `needs_resolution` and
`ready_for_confirmation` plans.

### `ogc_proxy_execute_plan`

Executes a stored plan only after confirmation. It accepts a `plan_id`, not an
arbitrary process body.

## OGC API - Common Tools

### `ogc_common_get_landing_page`

Retrieves the OGC API landing page.

### `ogc_common_get_conformance`

Retrieves conformance declarations.

### `ogc_common_get_resource`

Reads a relative path from a registered server. This is a read-only escape hatch
for OGC API modules without dedicated tools. Absolute URLs are rejected.

## OGC API - Features Tools

### `ogc_features_list_collections`

Lists feature collections.

### `ogc_features_describe_collection`

Retrieves metadata for one feature collection.

### `ogc_features_get_items`

Retrieves feature items from a collection. Summary mode is the default and
returns `guidance.reference_href` plus `guidance.source` so a process can use
the collection by reference.

### `ogc_features_get_item`

Retrieves one complete feature by ID.

## OGC API - Records Tools

### `ogc_records_list_collections`

Lists metadata collections.

### `ogc_records_search`

Searches a records collection by text, bbox, limit, and optional query
parameters.

### `ogc_records_get_record`

Retrieves one full record by ID.

## OGC API - Processes And Jobs Tools

### `ogc_processes_list`

Lists advertised processes. The optional `search_text` argument filters process
IDs, titles, descriptions, and summaries before response summarization.

### `ogc_processes_describe`

Retrieves the full description of one process. Clients must preserve exact input
and output identifiers from this response.

### `ogc_processes_execute`

Direct, unmediated process execution. This tool is registered only when:

```json
{
  "policy": {
    "expose_direct_execution_tools": true
  }
}
```

It is intended for low-level interoperability testing. User-facing workflows
should use the proxy plan tools.

### `ogc_jobs_list`

Lists jobs advertised by a Processes deployment.

### `ogc_jobs_get_status`

Retrieves one job status.

### `ogc_jobs_get_results`

Retrieves job results. Summary mode is the default. Completed responses include
`output_manifest`; referenced results are resolved only through the
operator-owned output-resolution policy.

### `ogc_jobs_dismiss`

Cancels or deletes a job where supported by the upstream server. Like direct
execution, this state-changing interoperability tool is registered only when
`policy.expose_direct_execution_tools=true`. A user-facing client must still
require an explicit request naming the job to cancel.
