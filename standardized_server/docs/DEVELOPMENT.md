# Development Guide

This guide is for engineers changing the reference server.

## Setup

From the repository root:

```bash
python -m pip install -e standardized_server
```

With Redis support:

```bash
python -m pip install -e 'standardized_server[redis]'
```

Run tests:

```bash
PYTHONPATH=standardized_server/src \
  python -m unittest discover -s standardized_server/tests -v
```

## Development Principles

- Keep MCP tool names stable.
- Preserve exact upstream process input and output identifiers.
- Prefer operator-owned configuration over model-supplied values.
- Keep OGC module services independent from MCP when possible.
- Put model-context behavior at the MCP boundary in `app.py`.
- Add tests for every security, state, or workflow behavior change.
- Do not implement geospatial analysis as a local fallback.

## Adding A Tool

1. Decide whether the tool belongs to an existing OGC module or a new module.
2. Add the HTTP behavior to `modules/`.
3. Return a standard envelope with `success()`.
4. Register the MCP tool in `app.py`.
5. Decide whether the tool needs `response_mode`.
6. Add or update the JSON tool contract.
7. Add tests through the FastMCP tool surface when possible.
8. Update docs.

## Adding A New OGC Module

Use a dedicated module when a generic `ogc_common_get_resource` call is no
longer enough.

Suggested sequence:

1. Define stable operation names in the tool contract.
2. Add a new service under `modules/`.
3. Register the service in `runtime.py`.
4. Add tools in `app.py`.
5. Extend configuration defaults only if needed.
6. Add security and response-mode behavior.
7. Add deterministic tests.
8. Update `EXTENDING.md`, `TOOL_CONTRACT.md`, and conformance docs.

## Working With Plans

Plan lifecycle behavior is owned by `services/planner.py` and wrapped by
`workflows/planning.py`.

Be careful when changing:

- which plan states can be updated;
- which states can be approved or rejected;
- source href validation;
- execute-input validation;
- persisted plan shape;
- Redis compatibility.

Tests in `test_proxy_services.py` are the main safety net.

## Working With Response Modes

Response summary behavior is intentionally implemented in `app.py`, not inside
the module services. This keeps lower layers reusable and easier to test.

When adding summary mode to a tool:

1. return a normal result envelope from the service;
2. call `_apply_response_mode` in the MCP tool callback;
3. add tests for default summary mode, raw mode, and memory retrieval.

## Working With Security

Security-sensitive changes should include tests before and after the change.

Relevant files:

- `security.py`;
- `transport.py`;
- `services/planner.py`;
- `services/sanitization.py`;
- `app.py` for tool registration policy.

## Style Notes

- Keep code comments short and useful.
- Keep docs close to behavior that exists.
- Avoid adding broad abstractions before there is repeated behavior.
- Use `httpx.MockTransport` for deterministic tests.

## Before Opening A Pull Request

Run:

```bash
PYTHONPATH=standardized_server/src \
  python -m unittest discover -s standardized_server/tests -v
```

Check:

- config examples still parse;
- docs links still point to real files;
- tool contract and docs match the code;
- new tools have tests and security notes;
- direct process execution remains disabled by default.
