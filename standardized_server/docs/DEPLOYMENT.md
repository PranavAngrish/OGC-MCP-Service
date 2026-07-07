# Deployment Guide

The reference server can run over stdio for local desktop clients or over
Streamable HTTP for service-style deployments.

## Local Desktop Deployment

Use stdio for desktop clients:

```bash
ogc-mcp-server --config config.example.json --transport stdio
```

The default in-memory store is appropriate here because one process handles one
client session.

## Streamable HTTP Deployment

Run:

```bash
OGC_MCP_HOST=127.0.0.1 OGC_MCP_PORT=8000 \
  ogc-mcp-server --config config.example.json --transport streamable-http
```

For a single worker, the default memory store works for basic testing. For more
than one worker or replica, configure Redis.

## Redis State Backend

Multi-worker deployments need shared plan and proxy-memory state. Otherwise, a
plan created on one worker may not be visible to a confirmation or execution
call routed to another worker.

Example:

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

Then:

```bash
export OGC_MCP_REDIS_URL="redis://localhost:6379/0"
```

## Capability Bootstrap

Set:

```bash
export OGC_MCP_BOOTSTRAP_CAPABILITIES=1
```

to load conformance profiles for enabled servers during startup. Without this,
capabilities are loaded lazily.

## Production Security Controls

Add controls outside the Python process:

- TLS termination;
- MCP-layer authentication and authorization;
- network egress restrictions;
- DNS-aware private network blocking;
- secret management;
- Redis authentication and network isolation;
- audit logging;
- request tracing;
- rate limiting;
- deployment monitoring.

## Secrets

Do not put secret values in the JSON config. Put environment variable names in
the config and inject actual values through the deployment environment.

Examples:

- `OGC_API_TOKEN`;
- `OGC_API_KEY`;
- `OGC_USERNAME`;
- `OGC_PASSWORD`;
- `OGC_MCP_REDIS_URL`.

## Scaling Notes

For a shared HTTP deployment:

- use Redis for state;
- keep TTLs enabled unless there is a clear reason not to;
- avoid exposing deployment-wide plan and memory list tools to untrusted tenants
  without adding user/session scoping;
- keep `policy.expose_direct_execution_tools=false` for user-facing use.

## Operational Checks

Before deployment:

- run the unit tests;
- validate config against `schemas/server-config.schema.json`;
- verify registered server base URLs;
- verify auth env vars exist;
- verify reference host allowlists;
- verify response limits are appropriate;
- test plan create, confirm, and execute through the intended MCP client.
