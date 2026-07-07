# Extending The Server

This document explains how to extend the reference server with new tools or OGC
API modules.

## When To Add A Dedicated Tool

Use `ogc_common_get_resource` for occasional read-only exploration of modules
that are not yet mapped.

Add a dedicated tool when:

- the workflow is common enough to need stable arguments;
- the response needs summary or memory-handle behavior;
- the operation has security implications;
- the operation participates in a multi-step workflow;
- engineers or clients need a documented contract.

## Candidate Modules

Likely future modules include:

- OGC API - EDR;
- OGC API - Coverages;
- OGC API - Tiles;
- OGC API - Maps;
- OGC API - Styles;
- OGC API - 3D GeoVolumes.

## Extension Checklist

1. Define the user workflow.
2. Decide the stable MCP tool names.
3. Update the JSON tool contract.
4. Add module service methods under `modules/`.
5. Wire the service into `runtime.py`.
6. Register MCP tools in `app.py`.
7. Add response summary mode if the payload can be large.
8. Add security validation before outbound requests.
9. Add deterministic tests.
10. Update docs and conformance checklist.

## Naming Rules

Use the existing convention:

```text
ogc_<module>_<operation>
```

Examples:

- `ogc_features_get_items`;
- `ogc_records_search`;
- `ogc_processes_describe`;
- `ogc_jobs_get_results`.

Prefer OGC concepts over implementation-specific names.

## Module Service Pattern

Module services should:

- accept stable Python arguments;
- resolve the server through `ServerRegistry`;
- build relative OGC API paths;
- call `OgcHttpClient`;
- return `success(...)` envelopes;
- avoid MCP-specific response-mode logic.

MCP-specific wrapping belongs in `app.py`.

## Security Pattern

Before adding a tool, ask:

- Can the caller choose an arbitrary URL?
- Can the caller smuggle credentials?
- Can the call start expensive or state-changing work?
- Can the response be too large?
- Does the response contain untrusted text?
- Does the operation need human confirmation?

When in doubt, prefer a stored plan or operator-owned configuration over direct
model-supplied execution.

## Response Mode Pattern

Use summary mode by default for:

- collection item lists;
- search results;
- process outputs;
- job results;
- coverages;
- tiles metadata with large lists;
- any potentially unbounded payload.

The common pattern in `app.py` is:

```python
result = service.method(...)
return _apply_response_mode(
    result,
    response_mode=response_mode,
    summary_fields_json=summary_fields_json,
    operation="module.operation",
    runtime=runtime,
)
```

## Process-Related Extensions

Do not add local geospatial computation as a fallback. If a requested operation
requires spatial analysis, route it through an advertised OGC API - Processes
operation and the proxy confirmation workflow.

## Updating Documentation

For every public extension, update:

- `TOOL_CONTRACT.md`;
- `CONFIGURATION.md`, if config changed;
- `SECURITY.md`, if boundaries changed;
- `TESTING.md`, if tests changed;
- `CONFORMANCE.md`;
- `spec/ogc-mcp-tool-contract.json`.
