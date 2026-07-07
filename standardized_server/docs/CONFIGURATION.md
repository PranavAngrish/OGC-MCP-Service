# Configuration

The server is configured with an operator-owned JSON file. The path is supplied
through either:

```bash
ogc-mcp-server --config path/to/config.json
```

or:

```bash
export OGC_MCP_CONFIG=path/to/config.json
```

The configuration schema is
[`../schemas/server-config.schema.json`](../schemas/server-config.schema.json).
An example is [`../config.example.json`](../config.example.json).

## Top-Level Shape

```json
{
  "default_servers": {
    "common": "pygeoapi-demo",
    "features": "pygeoapi-demo",
    "records": "pygeoapi-demo",
    "processes": "geolabs-tb17"
  },
  "store": {},
  "policy": {},
  "servers": []
}
```

Only `servers` is required, but defaults are strongly recommended.

## `default_servers`

Maps service names to server IDs:

```json
{
  "default_servers": {
    "common": "example",
    "features": "example",
    "records": "example",
    "processes": "process-server"
  }
}
```

Supported service names:

- `common`;
- `features`;
- `records`;
- `processes`.

If a tool omits `server_id`, the registry uses the matching default. The default
server must exist, be enabled, and support the requested service.

## `servers`

Each server profile registers one approved upstream deployment.

```json
{
  "id": "pygeoapi-demo",
  "title": "pygeoapi Demo",
  "description": "Public demo deployment",
  "base_url": "https://demo.pygeoapi.io/master",
  "enabled": true,
  "services": ["common", "features", "records"],
  "paths": {},
  "defaults": {},
  "auth": {},
  "security": {},
  "limits": {}
}
```

### `id`

Stable operator-owned identifier used in MCP tool calls. It must be unique.

### `base_url`

The upstream OGC API base URL. The server blocks private and loopback targets by
default unless the profile explicitly allows private networks.

Do not embed credentials in the URL.

### `enabled`

Defaults to `true`. Disabled servers are ignored.

### `services`

Non-empty list of supported services:

```json
["common", "features", "records", "processes"]
```

### `paths`

Optional endpoint overrides. When omitted, defaults are used:

| Name | Default |
| --- | --- |
| `landing_page` | `/` |
| `conformance` | `/conformance` |
| `collections` | `/collections` |
| `processes` | `/processes` |
| `jobs` | `/jobs` |

Example:

```json
{
  "paths": {
    "collections": "/api/collections"
  }
}
```

### `defaults`

Module-specific defaults. Currently the Records service uses:

```json
{
  "defaults": {
    "records_collection": "metadata"
  }
}
```

## Auth Profiles

Auth values are injected by the server immediately before an upstream request.
Secrets are read from environment variables and are never accepted as MCP tool
arguments.

### No Auth

```json
{
  "auth": {
    "type": "none"
  }
}
```

### Bearer Token From Environment

```json
{
  "auth": {
    "type": "bearer_env",
    "token_env": "OGC_API_TOKEN"
  }
}
```

### API Key From Environment

```json
{
  "auth": {
    "type": "api_key_env",
    "api_key_env": "OGC_API_KEY",
    "api_key_header": "X-API-Key"
  }
}
```

### Basic Auth From Environment

```json
{
  "auth": {
    "type": "basic_env",
    "username_env": "OGC_USERNAME",
    "password_env": "OGC_PASSWORD"
  }
}
```

### JWT Bearer Login

```json
{
  "auth": {
    "type": "jwt_bearer",
    "username_env": "OGC_USERNAME",
    "password_env": "OGC_PASSWORD",
    "login_path": "/auth/login",
    "refresh_path": "/auth/refresh",
    "token_json_path": "access_token",
    "refresh_token_json_path": "refresh_token",
    "expires_in_json_path": "expires_in",
    "refresh_window_seconds": 300
  }
}
```

The token manager logs in, caches the access token, refreshes before expiry when
possible, and retries once after a `401`.

## Security Policy

```json
{
  "security": {
    "allow_private_networks": false,
    "allowed_reference_hosts": ["demo.pygeoapi.io"],
    "allow_unlisted_reference_hosts": false,
    "validate_execute_references": true
  }
}
```

### `allow_private_networks`

Defaults to `false`. Set to `true` only for explicitly trusted local or private
deployments.

### `allowed_reference_hosts`

Allowed hostnames for HTTP(S) references inside process execution payloads.
Supports exact hostnames and explicit wildcard subdomains such as
`*.example.org`.

### `allow_unlisted_reference_hosts`

Defaults to `false`. If true, public HTTP(S) references do not need to match the
allowlist.

### `validate_execute_references`

Defaults to `true`. When true, execution payloads are recursively scanned for
HTTP(S) references before the upstream request is sent.

## Request Limits

```json
{
  "limits": {
    "timeout_seconds": 30,
    "max_response_bytes": 5000000
  }
}
```

`timeout_seconds` must be positive. `max_response_bytes` must be positive.

## Store Settings

```json
{
  "store": {
    "backend": "memory",
    "redis_url_env": "OGC_MCP_REDIS_URL",
    "key_prefix": "ogc_mcp",
    "plan_ttl_seconds": 3600,
    "memory_ttl_seconds": 1800
  }
}
```

### `backend`

Supported values:

- `memory`: process-local state;
- `redis`: shared external state.

Use Redis for multi-worker or multi-replica Streamable HTTP deployments.

### `redis_url_env`

Name of the environment variable containing the Redis connection URL. Required
when `backend` is `redis`.

### `key_prefix`

Prefix used for Redis keys.

### TTLs

- `plan_ttl_seconds`: expiration for stored plans.
- `memory_ttl_seconds`: expiration for proxy memory records.

Use `0` to disable expiry.

## Policy Settings

```json
{
  "policy": {
    "expose_direct_execution_tools": false
  }
}
```

When `false`, `ogc_processes_execute` is not registered as an MCP tool. This is
the default and recommended setting for user-facing workflows.

Set it to `true` only when you need direct, unmediated process execution for
low-level interoperability testing.

## Environment Variables

| Variable | Purpose |
| --- | --- |
| `OGC_MCP_CONFIG` | Default config path. |
| `OGC_MCP_TRANSPORT` | Default CLI transport. |
| `OGC_MCP_HOST` | Streamable HTTP bind host. |
| `OGC_MCP_PORT` | Streamable HTTP bind port. |
| `OGC_MCP_BOOTSTRAP_CAPABILITIES` | Set to `1` to load conformance on startup. |
| Auth-specific env vars | Token, API key, username, password, or Redis URL names configured by the operator. |
