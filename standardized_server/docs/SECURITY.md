# Security Model

The reference server is designed to put hard boundaries between MCP clients,
credentials, upstream targets, and process execution.

It should still be deployed with infrastructure-level egress control,
authorization, observability, and secret management in production.

## Threat Model

The server assumes an AI client may:

- misunderstand user intent;
- try to call tools in an unsafe order;
- include malicious text copied from upstream data;
- attempt to send requests to unapproved hosts;
- build process inputs that contain arbitrary HTTP references;
- load too much geospatial data into model context;
- execute state-changing processes before the user has approved them.

The design makes these cases explicit and bounded.

## Registered Servers Only

MCP callers choose from operator-owned `server_id` values. They do not provide
arbitrary upstream base URLs.

The registry validates:

- unique server IDs;
- enabled servers;
- supported services;
- defaults that point to real servers;
- private-network policy for configured base URLs.

## Credentials Stay Outside Model Context

Auth profiles name environment variables. Secret values are read by the server
when an upstream request is sent.

Tool schemas and tool responses do not expose:

- bearer tokens;
- API keys;
- usernames;
- passwords;
- Redis URLs.

## Relative Generic Paths

`ogc_common_get_resource` can read arbitrary relative paths on a registered
server, but it cannot be used to target another host. Paths must start with one
slash and must not contain an absolute URL.

## Private Network Policy

Configured base URLs and process-input references are blocked when they use
literal private or loopback hosts unless `allow_private_networks` is true for
that server profile.

Production note: application-level validation cannot replace network egress
controls. Hostnames that resolve to private addresses should be blocked by
infrastructure policy or future DNS-aware validation.

## Process Reference Validation

Before process execution, the server recursively scans the execute payload for
HTTP(S) strings.

If references exist, the policy must either:

- list approved `allowed_reference_hosts`; or
- explicitly allow unlisted public reference hosts.

References with embedded credentials are rejected.

## Human Confirmation Gate

The default execution path is:

```text
create plan -> resolve inputs -> show execute_request -> confirm -> execute
```

`ogc_proxy_execute_plan` refuses to run a plan that is not confirmed.

Terra Console also removes the confirmation tool from the conversational
model's callable tools. A session-scoped approval card displays and fingerprints
the exact request; the gateway re-fetches the current plan before recording the
human's one-time decision outside model context.

The direct execution and job-dismissal tools, `ogc_processes_execute` and
`ogc_jobs_dismiss`, are not registered at all unless
`policy.expose_direct_execution_tools=true`.

## Response Size Limits

The HTTP transport streams upstream responses and stops when the configured
`max_response_bytes` limit is exceeded.

This prevents a single upstream response from unboundedly filling process memory
or model context.

## Request Timeouts

Each server profile has a request timeout. Slow or unreachable upstream servers
return structured transport errors.

## Redirect Handling

The HTTP client does not automatically follow redirects. Redirect metadata is
available in response headers where relevant, but the server does not silently
send credentials or payloads to a redirected destination.

Process-output references are the narrow exception: the artifact pipeline may
follow them under `output_resolution`, with every hop revalidated against
same-origin or explicit host policy. A complete manifest build shares one
deadline, byte budget, fetch limit, and output limit. Registered-server
credentials are never forwarded cross-origin.

## Prompt-Injection Mitigation In Upstream Data

Summary mode passes upstream values through `ResponseSanitizer`. Instruction-like
strings such as "ignore previous instructions" are replaced with `[removed]` in
model-facing summaries.

This is not a complete prompt-injection solution. It is a focused mitigation for
common dangerous phrases in summarized upstream data.

## Large Payload Boundary

Large and unbounded responses default to summary mode. The full payload is
stored behind an opaque memory handle, and the model sees a compact data-only
summary.

This reduces accidental coordinate dumping and avoids using model context as a
geospatial processing environment.

Process outputs use a second opaque namespace, `art_*`. Original, canonical,
and bounded-preview representations are stored with a TTL. The trusted UI
gateway privately hydrates preview handles and exposes a download only after
the handle has been registered for that browser session. Raw coordinate arrays
are not added to the language-model conversation.
The registry pre-reserves the schema maximum of 2,000 representation handles
for the current manifest so a newly returned link is not already evicted.

## Multi-Tenant Caveat

Plan, proxy-memory, and artifact visibility is currently deployment-wide at the
Python MCP layer. `ogc_proxy_list_plans` and `ogc_proxy_memory_list` return
non-expired state visible to the server instance or shared store, and an
`art_*` handle acts as an expiring bearer capability.

A multi-tenant deployment should add session or user scoping before exposing the
service broadly.

## Production Controls To Add

Recommended production controls:

- TLS termination;
- MCP-layer authentication and authorization;
- network egress allowlists;
- DNS-aware private address blocking;
- secret management;
- audit logging;
- rate limiting;
- request tracing;
- per-user or per-session plan and memory isolation;
- monitoring for upstream failures and store errors.
