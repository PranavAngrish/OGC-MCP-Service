# Experimental Conformance Checklist

This checklist describes behavior expected from implementations of the
experimental OGC API MCP tool contract. It is not an OGC conformance class.

## Registry

- [ ] The implementation exposes stable server IDs.
- [ ] MCP callers cannot send arbitrary upstream base URLs.
- [ ] Server metadata responses omit credentials and secret values.
- [ ] Module defaults are explicit and operator-configured.
- [ ] Disabled servers are not callable.

## Security

- [ ] Upstream requests are limited to registered deployments.
- [ ] Generic paths are relative and reject absolute URLs.
- [ ] Credentials are injected outside model-visible arguments.
- [ ] Process execution references are validated recursively.
- [ ] Private and loopback access is disabled by default.
- [ ] Embedded credentials in URLs are rejected.
- [ ] Redirects are not followed automatically.
- [ ] Response sizes and request durations are bounded.
- [ ] Direct process execution is not registered unless the operator opts in.
- [ ] Job dismissal remains available even when direct execution is disabled.
- [ ] Production deployments document external egress restrictions.

## Result Envelopes

- [ ] Every success contains `ok`, `operation`, `server`, `request`, `response`,
      and `data` where applicable.
- [ ] Every expected failure contains `ok=false`, `operation`, and `error`.
- [ ] Error responses use stable machine-readable codes.
- [ ] Upstream payloads are preserved unless a documented transformation exists.

## Proxy Runtime

- [ ] Server conformance can be cached and normalized into capability flags.
- [ ] Missing capabilities map to deterministic fallback rules.
- [ ] Full upstream payloads can be stored behind opaque proxy memory handles.
- [ ] Model-facing summaries extract allowlisted fields only.
- [ ] Instruction-like upstream values are sanitized before model use.
- [ ] Large or unbounded tools default to `response_mode="summary"`.
- [ ] Raw mode is opt-in.
- [ ] Plan and memory records expire after configurable TTLs.
- [ ] A TTL of `0` disables expiry.
- [ ] Multi-worker deployments can use a shared external store.

## Human-Confirmed Process Execution

- [ ] Process execution plans validate process IDs before execution.
- [ ] Plans validate declared source hrefs against source metadata.
- [ ] Plans perform conservative execute-input validation.
- [ ] Plans with unresolved inputs cannot be approved.
- [ ] Plans cannot execute without explicit human approval.
- [ ] Rejected, unresolved, running, completed, or failed plans cannot be
      approved.
- [ ] `ogc_proxy_update_plan` can correct execute inputs without changing the
      plan ID.
- [ ] `ogc_proxy_execute_plan` accepts a stored `plan_id`, not arbitrary process
      inputs.
- [ ] Confirmation prompts expose the exact `execute_request` for review.

## OGC API - Common

- [ ] Landing page retrieval is supported.
- [ ] Conformance retrieval is supported.
- [ ] Safe read-only relative resource access is supported.

## OGC API - Features

- [ ] Collection listing is supported.
- [ ] Collection metadata retrieval is supported.
- [ ] Feature item listing is supported.
- [ ] Single feature retrieval is supported.
- [ ] Feature item listing provides a reference href suitable for process input.

## OGC API - Records

- [ ] Catalogue collection listing is supported.
- [ ] Record search is supported.
- [ ] Single record retrieval is supported.

## OGC API - Processes

- [ ] Process listing is supported.
- [ ] Process descriptions are supported.
- [ ] Execute requests preserve advertised input and output names.
- [ ] Inline and referenced process inputs are supported.
- [ ] `Prefer: respond-async` can be requested.
- [ ] Job listing, status, results, and dismissal are supported.

## Documentation

- [ ] The implementation documents configuration.
- [ ] The implementation documents security boundaries.
- [ ] The implementation documents the plan lifecycle.
- [ ] The implementation documents development and testing workflows.
