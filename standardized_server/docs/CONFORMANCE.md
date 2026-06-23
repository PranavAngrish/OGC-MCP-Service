# Experimental Conformance Checklist

This checklist describes the behavior expected from implementations of the
experimental OGC API MCP tool contract in `spec/ogc-mcp-tool-contract.json`.
It is not an OGC conformance class.

## Registry

- [ ] The implementation exposes stable server IDs.
- [ ] MCP callers cannot send arbitrary upstream base URLs.
- [ ] Server metadata responses omit credentials and secret values.
- [ ] Module defaults are explicit and operator-configured.

## Security

- [ ] Upstream requests are limited to registered deployments.
- [ ] Generic paths are relative and reject absolute URLs.
- [ ] Credentials are injected outside model-visible arguments.
- [ ] Process execution references are validated recursively.
- [ ] Private network access is disabled by default.
- [ ] Redirects are not followed without validation.
- [ ] Response sizes and request durations are bounded.
- [ ] Infrastructure-level egress restrictions are recommended for production.
- [ ] Unmediated direct process execution (no human-confirmation gate) is not
      registered as a tool at all unless the operator explicitly opts in via
      `policy.expose_direct_execution_tools`; the model cannot discover or
      call a tool that was never registered.
- [ ] Job cancellation/dismissal remains available without the confirmation
      gate, since it is lower-risk and more reversible than starting a new
      execution.

## Results

- [ ] Every success contains `ok`, `operation`, `server`, `request`, `response`,
      and `data`.
- [ ] Every expected failure contains `ok=false`, `operation`, and `error`.
- [ ] Error responses use stable machine-readable codes.
- [ ] Upstream payloads are preserved unless a documented transformation exists.

## Proxy Runtime

- [ ] Server conformance can be cached and normalized into capability flags.
- [ ] Missing capabilities map to deterministic fallback rules.
- [ ] Full upstream payloads can be stored behind opaque proxy memory handles.
- [ ] Model-facing summaries extract allowlisted fields only.
- [ ] Instruction-like values in upstream data are sanitized before model use.
- [ ] Tools that can return large or unbounded upstream payloads (feature
      items, job results, plan execution, and direct execution when enabled)
      default to `response_mode="summary"`; `response_mode="raw"` is opt-in.
- [ ] Execution plans validate process and collection IDs before execution.
- [ ] Execution plans perform a best-effort, conservative check of
      `execute_request` inputs against the process's declared input schema
      (required-but-missing inputs and simple literal type mismatches), and
      append any issue found to the plan's unresolved list rather than
      silently accepting a malformed request.
- [ ] Input-schema validation fails open (skips the extra check rather than
      blocking plan creation) when the process description cannot be
      fetched, and intentionally skips reference-form inputs,
      multi-occurrence inputs, and union (`oneOf`/`anyOf`/`allOf`/`$ref`)
      schemas to avoid false positives.
- [ ] Plan creation returns a user-confirmable workflow state.
- [ ] Plan execution accepts stored `plan_id` values, not arbitrary destinations.
- [ ] Plan execution is blocked until explicit human approval is recorded.
- [ ] Rejected or unresolved plans cannot execute.
- [ ] Workflow orchestration can run through LangGraph or an equivalent
      deterministic state-machine backend.
- [ ] Plan and proxy-memory state is stored through a pluggable backend so
      a multi-worker or multi-replica deployment can share consistent state
      (for example, a confirm call routed to a different worker than the one
      that created the plan still resolves correctly).
- [ ] The default storage backend is documented as process-local and
      single-worker-only; deployments running more than one worker process
      or replica must configure an external backend.
- [ ] Stored plans and proxy-memory records expire after a configurable TTL
      (zero disables expiry).

## OGC API - Common

- [ ] Landing page retrieval is supported.
- [ ] Conformance declaration retrieval is supported.
- [ ] Safe read-only relative resource access is supported.

## OGC API - Features

- [ ] Collection listing is supported.
- [ ] Collection metadata retrieval is supported.
- [ ] Feature item listing is supported.
- [ ] Single feature retrieval is supported.

## OGC API - Records

- [ ] Catalogue collection listing is supported.
- [ ] Record search is supported.
- [ ] Single record retrieval is supported.

## OGC API - Processes

- [ ] Process listing is supported.
- [ ] Process description retrieval is supported.
- [ ] Execute requests preserve advertised input/output names.
- [ ] Inline and referenced process inputs are supported.
- [ ] `Prefer: respond-async` can be requested.
- [ ] Job listing, status, results, and dismissal are supported.
