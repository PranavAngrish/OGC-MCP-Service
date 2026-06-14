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
  -> ogc_processes_execute
```

Process identifiers and schemas are server-owned. The MCP layer must not invent
or silently normalize them.

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
MCP tool schemas, tool responses, or model prompts.

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
├── app.py          FastMCP tools and resources
├── config.py       JSON configuration loading
├── models.py       Typed immutable configuration models
├── registry.py     Registered server resolution
├── security.py     URL and reference validation
├── transport.py    Auth injection and bounded HTTP
├── result.py       Stable success/error envelopes
└── modules/
    ├── common.py
    ├── features.py
    ├── records.py
    └── processes.py
```

OGC module classes do not know about MCP. They can be tested independently and
reused by another MCP SDK or language implementation.

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

Use `stdio` for local desktop clients. Use Streamable HTTP for deployed MCP
services. Production deployments should also add:

- TLS termination;
- MCP-layer authorization;
- network egress restrictions;
- observability and audit logging;
- secret management;
- rate limiting;
- deployment-specific data governance.
