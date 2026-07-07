# ADR 0002: Proxy Memory Summary Mode

## Status

Accepted.

## Context

OGC APIs can return large FeatureCollections, records, process outputs, and job
results. Passing full payloads directly into model context is expensive,
unreliable, and can encourage model-side geospatial analysis.

The server needed to preserve full upstream data while returning compact,
model-safe responses.

## Decision

Tools that can return large or unbounded payloads default to summary mode:

1. store the full payload in proxy memory;
2. return a sanitized summary in `data`;
3. include an opaque memory handle;
4. allow later paginated retrieval by handle.

Raw mode remains available for small responses and interoperability testing.

## Consequences

Positive:

- large payloads stay outside model context by default;
- full data is still available when needed;
- summaries can remove instruction-like upstream text;
- referenced feature workflows are easier to encourage.

Tradeoffs:

- memory handles require state storage;
- handles can expire;
- clients must retrieve pages explicitly when they need full data.

## Related Files

- `src/ogc_mcp_reference/app.py`
- `src/ogc_mcp_reference/services/memory.py`
- `src/ogc_mcp_reference/services/sanitization.py`
- `src/ogc_mcp_reference/services/store.py`
- `tests/test_app.py`
- `tests/test_proxy_services.py`
