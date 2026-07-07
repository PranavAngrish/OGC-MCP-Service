# Testing Guide

The test suite uses Python `unittest` and deterministic `httpx.MockTransport`
handlers. It does not depend on public network availability.

Run all tests from the repository root:

```bash
PYTHONPATH=standardized_server/src \
  python -m unittest discover -s standardized_server/tests -v
```

## Test Areas

### FastMCP Tool Surface

`tests/test_app.py` checks:

- server creation;
- direct execution tool gating;
- default summary mode;
- raw response mode;
- memory handles;
- proxy execution summary mode;
- input validation through actual MCP tool calls.

These tests call FastMCP tools through `mcp.call_tool(...)` rather than only
calling service classes.

### Configuration

`tests/test_config.py` checks:

- minimal config parsing;
- duplicate server rejection;
- unknown service rejection;
- invalid defaults;
- boolean validation;
- JWT bearer profile parsing.

### Transport

`tests/test_transport.py` checks:

- environment-based API key injection;
- response size limits;
- structured upstream errors.

### Security

`tests/test_security.py` checks:

- private base URL rejection by default;
- explicit private URL allowance;
- absolute generic path rejection;
- recursive reference allowlists;
- disabled references before operator approval;
- wildcard host matching;
- embedded credential rejection.

### Processes

`tests/test_processes.py` checks:

- process listing;
- execution body preservation;
- `Prefer: respond-async`;
- rejection of unapproved references before network calls.

### Input Schema

`tests/test_input_schema.py` checks the conservative validator:

- missing required inputs;
- optional inputs;
- reference-form inputs;
- union schemas;
- valid literals;
- qualified value forms;
- multi-occurrence inputs;
- missing declared schema.

### Proxy Services And Workflow

`tests/test_proxy_services.py` checks:

- JWT login and retry after `401`;
- capability cache and fallback mapping;
- sanitizer behavior;
- unadvertised process IDs;
- plan confirmation gate;
- cached process descriptions;
- source href validation;
- cross-server Features to Processes references;
- plan updates;
- plan persistence across shared stores;
- process-local state limitations;
- TTL expiry;
- workflow confirmation and execution.

### Store Backends

`tests/test_store.py` checks:

- in-memory store put/get/list/expiry;
- Redis store behavior when `fakeredis` is installed;
- store construction rules.

Redis tests are skipped automatically when `fakeredis` is unavailable.

## Adding Tests

When adding behavior:

- use `httpx.MockTransport` instead of public network calls;
- test both success and failure paths;
- prefer testing through the MCP tool surface for public behavior;
- test service classes directly for lower-level validation logic;
- include security regressions for any validation boundary.

## Suggested Manual Smoke Test

With a valid config:

```text
ogc_servers_list
ogc_proxy_get_capabilities
ogc_processes_list
ogc_processes_describe
```

For process execution, stop at `ogc_proxy_create_plan` unless you are prepared to
review and explicitly approve the exact `execute_request`.
