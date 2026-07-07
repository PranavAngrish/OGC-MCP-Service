# ADR 0001: Human-In-The-Loop Process Execution

## Status

Accepted.

## Context

OGC API - Processes can start expensive, long-running, or state-changing
operations. An AI client may build a plausible process request without fully
understanding the consequences or exact input values.

The project needed a way to let AI clients prepare process executions while
keeping the human in control of the final request.

## Decision

Process execution should go through a stored proxy plan by default:

```text
create plan -> resolve inputs -> show execute_request -> confirm -> execute
```

The server stores the exact `execute_request`, validates high-confidence issues,
returns resolution prompts when inputs are incomplete, and blocks execution until
`ogc_proxy_confirm_plan` records explicit approval.

## Consequences

Positive:

- users can inspect the exact request before execution;
- execution becomes auditable through `plan_id`;
- missing inputs can be corrected without restarting the workflow;
- state-changing work is structurally gated.

Tradeoffs:

- the workflow is more verbose than a direct execute call;
- clients must follow plan state transitions correctly;
- plans need a state store and expiry policy.

## Related Files

- `src/ogc_mcp_reference/services/planner.py`
- `src/ogc_mcp_reference/workflows/planning.py`
- `src/ogc_mcp_reference/app.py`
- `tests/test_proxy_services.py`
