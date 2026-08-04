import { createHash, randomUUID } from "node:crypto";
import { structuredToolPayload } from "./map-artifacts.mjs";

const approvals = new Map();
const DEFAULT_TTL_MS = 15 * 60 * 1_000;
const MAX_REVIEW_BYTES = 128 * 1_024;

function stableValue(value) {
  if (Array.isArray(value)) return value.map(stableValue);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.keys(value)
      .sort()
      .map((key) => [key, stableValue(value[key])]),
  );
}

function reviewSnapshot(plan) {
  return {
    planId: String(plan?.plan_id || "").trim().slice(0, 300),
    serverId: String(plan?.server_id || "").trim().slice(0, 200),
    executeRequest: plan?.execute_request,
    inputContext: plan?.input_context || {},
    steps: Array.isArray(plan?.steps) ? plan.steps.slice(0, 100) : [],
  };
}

function encodedSnapshot(snapshot) {
  try {
    return JSON.stringify(stableValue(snapshot));
  } catch {
    return "";
  }
}

function snapshotDigest(snapshot) {
  return createHash("sha256").update(encodedSnapshot(snapshot)).digest("hex");
}

function keyFor(sessionId, challengeId) {
  return JSON.stringify([sessionId, challengeId]);
}

function publicRequest(record) {
  return {
    challengeId: record.challengeId,
    planId: record.snapshot.planId,
    serverId: record.snapshot.serverId,
    executeRequest: record.snapshot.executeRequest,
    inputContext: record.snapshot.inputContext,
    steps: record.snapshot.steps,
    digest: record.digest,
    expiresAt: new Date(record.expiresAt).toISOString(),
    status: record.status,
  };
}

function prune(now = Date.now()) {
  for (const [key, record] of approvals) {
    if (record.expiresAt <= now || ["approved", "rejected"].includes(record.status)) {
      approvals.delete(key);
    }
  }
}

/**
 * Register an exact plan review received from the trusted MCP server.
 * The challenge stays gateway-side and is never included in model context.
 */
export function registerApprovalRequest({
  sessionId,
  targetMessageId,
  payload,
  now = Date.now(),
  ttlMs = DEFAULT_TTL_MS,
}) {
  prune(now);
  const plan = payload?.plan;
  if (
    !sessionId
    || !plan
    || typeof plan !== "object"
    || plan.status !== "ready_for_confirmation"
  ) return null;
  const snapshot = reviewSnapshot(plan);
  const encoded = encodedSnapshot(snapshot);
  if (
    !snapshot.planId
    || snapshot.executeRequest === undefined
    || !encoded
    || Buffer.byteLength(encoded) > MAX_REVIEW_BYTES
  ) return null;
  const digest = snapshotDigest(snapshot);
  const existing = [...approvals.values()].find((record) => (
    record.sessionId === sessionId
    && record.digest === digest
    && record.status === "pending"
    && record.expiresAt > now
  ));
  if (existing) {
    existing.targetMessageId = targetMessageId || existing.targetMessageId;
    return publicRequest(existing);
  }
  const record = {
    challengeId: randomUUID(),
    sessionId,
    targetMessageId: String(targetMessageId || "").slice(0, 200),
    snapshot,
    digest,
    createdAt: now,
    expiresAt: now + Math.max(60_000, Math.min(60 * 60 * 1_000, Number(ttlMs) || DEFAULT_TTL_MS)),
    status: "pending",
  };
  approvals.set(keyFor(sessionId, record.challengeId), record);
  return publicRequest(record);
}

export async function decideApproval({
  sessionId,
  challengeId,
  approved,
  callTool,
  now = Date.now(),
}) {
  prune(now);
  const key = keyFor(sessionId, challengeId);
  const record = approvals.get(key);
  if (!record || record.status !== "pending") {
    return {
      ok: false,
      status: 404,
      error: "This approval request is missing, expired, or has already been used.",
    };
  }
  record.status = "deciding";
  try {
    const currentResult = await callTool("ogc_proxy_get_plan", {
      plan_id: record.snapshot.planId,
    });
    const currentPayload = structuredToolPayload(currentResult);
    const currentPlan = currentPayload?.plan;
    const currentSnapshot = reviewSnapshot(currentPlan);
    if (
      currentResult?.isError
      || currentPayload?.ok === false
      || currentPlan?.status !== "ready_for_confirmation"
    ) {
      record.status = "pending";
      return {
        ok: false,
        status: 409,
        error: "The plan is no longer awaiting approval. Refresh its current state.",
      };
    }
    if (snapshotDigest(currentSnapshot) !== record.digest) {
      approvals.delete(key);
      return {
        ok: false,
        status: 409,
        error: "The plan changed after it was displayed. Review the updated inputs before deciding.",
      };
    }

    const confirmationResult = await callTool("ogc_proxy_confirm_plan", {
      plan_id: record.snapshot.planId,
      approved: approved === true,
      actor: "terra-ui-user",
      comment: approved === true
        ? `Approved exact request sha256:${record.digest}`
        : `Rejected exact request sha256:${record.digest}`,
    });
    const confirmationPayload = structuredToolPayload(confirmationResult);
    if (confirmationResult?.isError || !confirmationPayload || confirmationPayload.ok === false) {
      record.status = "pending";
      return {
        ok: false,
        status: 502,
        error: String(confirmationPayload?.error || "The MCP server did not record the decision.").slice(0, 500),
      };
    }
    record.status = approved === true ? "approved" : "rejected";
    approvals.delete(key);
    return {
      ok: true,
      status: 200,
      planId: record.snapshot.planId,
      decision: approved === true ? "approved" : "rejected",
      digest: record.digest,
      planStatus: String(confirmationPayload?.plan?.status || ""),
    };
  } catch (error) {
    record.status = "pending";
    return {
      ok: false,
      status: 502,
      error: error instanceof Error ? error.message.slice(0, 500) : String(error).slice(0, 500),
    };
  }
}

export function clearApprovalSession(sessionId) {
  for (const [key, record] of approvals) {
    if (record.sessionId === sessionId) approvals.delete(key);
  }
}

export function approvalRequestCount() {
  prune();
  return approvals.size;
}
