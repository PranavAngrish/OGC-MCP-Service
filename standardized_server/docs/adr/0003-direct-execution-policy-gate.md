# ADR 0003: Direct Execution Policy Gate

## Status

Accepted.

## Context

Direct process execution is useful for low-level interoperability testing, but
it bypasses the proxy plan and human confirmation workflow. If it is always
registered, an MCP client can discover and call it without using the safer path.

The project needed a way to support direct execution for testing without making
it the default public surface.

## Decision

`ogc_processes_execute` is registered only when the operator sets:

```json
{
  "policy": {
    "expose_direct_execution_tools": true
  }
}
```

When the flag is false, the FastMCP tool registration is skipped entirely.

## Consequences

Positive:

- disabled direct execution cannot be discovered by the model;
- user-facing deployments default to the confirmation-gated workflow;
- interoperability testing remains possible for operators who opt in.

Tradeoffs:

- tests and docs must cover both tool surfaces;
- operators need to understand the risk before enabling the flag.

## Related Files

- `src/ogc_mcp_reference/app.py`
- `src/ogc_mcp_reference/models.py`
- `src/ogc_mcp_reference/config.py`
- `tests/test_app.py`
