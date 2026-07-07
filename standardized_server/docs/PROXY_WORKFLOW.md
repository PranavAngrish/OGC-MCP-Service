# Proxy Workflow

The proxy workflow is the safest way to execute OGC API - Processes operations.
It turns a model-built process request into an auditable plan that cannot run
until a human approves the exact payload.

## Why The Workflow Exists

Process execution can be state-changing, expensive, long-running, or capable of
producing large geospatial outputs. The workflow protects users and operators by
requiring:

- discovery before execution;
- exact process identifiers from the upstream server;
- best-effort input validation;
- explicit human confirmation;
- stored execution state;
- response summarization for large outputs.

## Required Sequence

```text
ogc_servers_list
  -> ogc_processes_list
  -> ogc_processes_describe
  -> ogc_proxy_create_plan
  -> ogc_proxy_update_plan, if resolution_required is true
  -> show confirmation_prompt.execute_request verbatim
  -> ogc_proxy_confirm_plan
  -> ogc_proxy_execute_plan
```

For asynchronous responses:

```text
ogc_jobs_get_status
  -> ogc_jobs_get_results
```

## Plan Request Shape

Minimal shape:

```json
{
  "operation": "process_execute",
  "server_id": "geolabs-tb17",
  "process_id": "Delaunay",
  "execute_request": {
    "inputs": {}
  }
}
```

Preferred shape when a Features response is used as process input:

```json
{
  "operation": "process_execute",
  "server_id": "geolabs-tb17",
  "process_id": "Delaunay",
  "sources": [
    {
      "server_id": "pygeoapi-demo",
      "collection_id": "dutch_windmills",
      "href": "https://demo.pygeoapi.io/master/collections/dutch_windmills/items?f=json",
      "input_id": "InputPoints"
    }
  ],
  "execute_request": {
    "inputs": {
      "InputPoints": {
        "href": "https://demo.pygeoapi.io/master/collections/dutch_windmills/items?f=json"
      }
    }
  }
}
```

## Plan States

| State | Meaning |
| --- | --- |
| `needs_resolution` | The plan has missing, invalid, or ambiguous details. It cannot execute. |
| `ready_for_confirmation` | The plan validated and must be shown to the user. |
| `confirmed` | A human approved the exact execute request. |
| `rejected` | A human rejected or abandoned the plan. |
| `running` | Execution has started. |
| `completed` | Execution completed successfully. |
| `failed` | Execution failed after starting or while attempting to start. |

## Resolution Loop

When `ogc_proxy_create_plan` returns:

```json
{
  "resolution_required": true
}
```

the response includes `resolution_prompt.per_field_questions`.

The client should:

1. Ask one question at a time.
2. Wait for a concrete answer.
3. Build a corrected `execute_request`.
4. Call `ogc_proxy_update_plan`.
5. Repeat until `resolution_required` is `false`.

Do not create a new plan for ordinary input corrections once a valid `plan_id`
exists.

## Metadata That Requires A New Plan

`ogc_proxy_update_plan` can update only `execute_request`. If the problem is the
`process_id` or declared `sources`, create a new plan after rediscovering the
correct metadata.

The workflow returns `resolution_prompt.next_tool` to make this explicit.

## Confirmation Gate

When the plan is ready, the response includes:

```json
{
  "confirmation_required": true,
  "confirmation_prompt": {
    "execute_request": {}
  }
}
```

The client must show `confirmation_prompt.execute_request` verbatim to the user.
Only call:

```text
ogc_proxy_confirm_plan(plan_id, approved=true)
```

after the user explicitly approves.

If the user wants to change a value, call `ogc_proxy_update_plan`. If the user
cancels the operation, call `ogc_proxy_confirm_plan` with `approved=false`.

## Execution

`ogc_proxy_execute_plan` accepts only:

- `plan_id`;
- execution mode preference;
- wait preference;
- response mode arguments.

It does not accept arbitrary process input. The stored and confirmed
`execute_request` is the body sent upstream.

## Input Validation

The planner validates high-confidence issues:

- missing required process inputs;
- simple JSON type mismatches for literal inputs;
- declared source href missing from `execute_request`;
- source href not matching the declared collection;
- source href outside the declared Features server base URL;
- collection not advertised by the declared Features server.

It intentionally skips complex JSON Schema validation, reference-form type
checking, union schemas, and multi-occurrence inputs to avoid false positives.

## Referenced Feature Inputs

For large feature datasets, prefer:

```json
{
  "href": "<reference_href from ogc_features_get_items>"
}
```

over inline coordinates. Include the matching `guidance.source` entry in the
plan request `sources` array so the proxy can validate the relationship between
the Features server, collection, and href.

## Direct Execution

`ogc_processes_execute` bypasses the proxy workflow. It is disabled by default
and is registered only when the operator sets:

```json
{
  "policy": {
    "expose_direct_execution_tools": true
  }
}
```

Use it only for interoperability testing.
