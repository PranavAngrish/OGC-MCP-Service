# Troubleshooting

## The Server Says No Config Was Supplied

Error:

```text
Set OGC_MCP_CONFIG to a JSON configuration file path or pass config_path explicitly.
```

Fix:

```bash
export OGC_MCP_CONFIG="$PWD/standardized_server/config.example.json"
```

or pass:

```bash
ogc-mcp-server --config path/to/config.json
```

## A Default Server Cannot Be Resolved

Check:

- the `default_servers` value points to an enabled server ID;
- the server exists in `servers`;
- the server lists the requested service in `services`.

## Private Or Localhost Server Is Rejected

Private and loopback targets are blocked by default.

For trusted local testing only:

```json
{
  "security": {
    "allow_private_networks": true
  }
}
```

Use infrastructure egress controls in production.

## Process References Are Rejected

If an execute request contains `http://` or `https://` references, configure:

```json
{
  "security": {
    "allowed_reference_hosts": ["demo.pygeoapi.io"]
  }
}
```

or explicitly set:

```json
{
  "security": {
    "allow_unlisted_reference_hosts": true
  }
}
```

The allowlist is safer.

## Direct Process Execution Tool Is Missing

This is expected by default. `ogc_processes_execute` is registered only when:

```json
{
  "policy": {
    "expose_direct_execution_tools": true
  }
}
```

Use the proxy workflow for user-facing process execution.

## A Plan Cannot Be Approved

Only `ready_for_confirmation` plans can be approved.

If the plan is `needs_resolution`, inspect:

```text
resolution_prompt.per_field_questions
```

Then call `ogc_proxy_update_plan` with a corrected `execute_request`.

If the problem is `process_id` or `sources`, create a new plan after discovering
the correct metadata.

## A Plan Cannot Execute

`ogc_proxy_execute_plan` requires a `confirmed` plan.

Check:

```text
ogc_proxy_get_plan(plan_id)
```

Then confirm if appropriate:

```text
ogc_proxy_confirm_plan(plan_id, approved=true)
```

Only after showing the exact `execute_request` to the user.

## A Memory Handle Cannot Be Retrieved

Possible causes:

- the handle is wrong;
- the record expired;
- the server restarted while using the in-memory backend;
- a different worker received the retrieve call without shared Redis state.

For multi-worker deployments, use Redis.

## Redis Backend Fails To Start

Check:

- the `redis` extra is installed;
- `store.redis_url_env` names an environment variable;
- that environment variable is set;
- the Redis server is reachable from the deployment.

Install:

```bash
python -m pip install -e 'standardized_server[redis]'
```

## Upstream Response Exceeds Size Limit

Increase `limits.max_response_bytes` for the server profile only if the upstream
payload is expected and safe.

Prefer summary mode and referenced inputs for large geospatial data.

## Authentication Environment Variable Is Missing

The config names an env var such as `OGC_API_TOKEN`, but the variable is not set
in the server process environment.

Set it before starting the server:

```bash
export OGC_API_TOKEN="..."
```

Do not put the secret value in the JSON config.

## Tests Skip Redis Cases

Redis tests that use `fakeredis` are skipped when `fakeredis` is not installed.
This is normal for a minimal development environment.

The main suite should still pass.
