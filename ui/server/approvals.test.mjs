import assert from "node:assert/strict";
import test from "node:test";
import {
  clearApprovalSession,
  decideApproval,
  registerApprovalRequest,
} from "./approvals.mjs";

const structured = (payload) => ({ structuredContent: payload });

function readyPayload(distance = 500) {
  return {
    ok: true,
    confirmation_required: true,
    plan: {
      plan_id: "plan-42",
      server_id: "process-server",
      status: "ready_for_confirmation",
      execute_request: { inputs: { distance } },
      input_context: { distance: { origin: "user", unit: "metres", confirmed: true } },
      steps: [{ kind: "process_execute", process_id: "Buffer" }],
    },
  };
}

test("approval is bound to the exact reviewed plan and recorded outside model tools", async () => {
  const sessionId = "approval-session";
  const request = registerApprovalRequest({
    sessionId,
    targetMessageId: "assistant-1",
    payload: readyPayload(),
    now: 1_000,
  });
  assert.ok(request);
  assert.equal(request.planId, "plan-42");
  assert.deepEqual(request.executeRequest, { inputs: { distance: 500 } });

  const calls = [];
  const result = await decideApproval({
    sessionId,
    challengeId: request.challengeId,
    approved: true,
    now: 2_000,
    callTool: async (name, args) => {
      calls.push({ name, args });
      if (name === "ogc_proxy_get_plan") return structured(readyPayload());
      if (name === "ogc_proxy_confirm_plan") {
        return structured({ ok: true, plan: { status: "confirmed" } });
      }
      throw new Error(`Unexpected tool ${name}`);
    },
  });

  assert.equal(result.ok, true);
  assert.equal(result.decision, "approved");
  assert.deepEqual(calls.map((call) => call.name), [
    "ogc_proxy_get_plan",
    "ogc_proxy_confirm_plan",
  ]);
  assert.equal(calls[1].args.plan_id, "plan-42");
  assert.equal(calls[1].args.approved, true);
  assert.match(calls[1].args.comment, new RegExp(request.digest));
  clearApprovalSession(sessionId);
});

test("approval is refused when the plan changed after being displayed", async () => {
  const sessionId = "changed-session";
  const request = registerApprovalRequest({
    sessionId,
    targetMessageId: "assistant-2",
    payload: readyPayload(),
    now: 1_000,
  });
  let confirmationCalled = false;
  const result = await decideApproval({
    sessionId,
    challengeId: request.challengeId,
    approved: true,
    now: 2_000,
    callTool: async (name) => {
      if (name === "ogc_proxy_get_plan") return structured(readyPayload(1_000));
      confirmationCalled = true;
      return structured({ ok: true });
    },
  });
  assert.equal(result.ok, false);
  assert.equal(result.status, 409);
  assert.match(result.error, /changed/);
  assert.equal(confirmationCalled, false);
  clearApprovalSession(sessionId);
});

test("only ready plans produce bounded user approval requests", () => {
  assert.equal(registerApprovalRequest({
    sessionId: "not-ready",
    payload: { plan: { ...readyPayload().plan, status: "needs_resolution" } },
  }), null);
  const oversized = readyPayload();
  oversized.plan.execute_request = { inputs: { payload: "x".repeat(140_000) } };
  assert.equal(registerApprovalRequest({
    sessionId: "oversized",
    payload: oversized,
  }), null);
  clearApprovalSession("not-ready");
  clearApprovalSession("oversized");
});
