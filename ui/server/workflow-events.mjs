import { randomUUID } from "node:crypto";

export const MAX_INLINE_WORKFLOW_MANIFEST_BYTES = 64 * 1024;

export const WORKFLOW_EVENT_TYPES = new Set([
  "intent_recognized",
  "decision_recorded",
  "step_started",
  "step_completed",
  "clarification_required",
  "approval_required",
  "job_progress",
  "output_manifest_upserted",
  "presentation_status",
  "workflow_completed",
  "workflow_failed",
]);

function requiredIdentifier(value, label) {
  const identifier = typeof value === "string" ? value.trim() : "";
  if (!identifier) throw new TypeError(`${label} is required for activity/2 events.`);
  return identifier.slice(0, 200);
}

function optionalIdentifier(value) {
  const identifier = typeof value === "string" ? value.trim() : "";
  return identifier ? identifier.slice(0, 200) : "";
}

function boundedText(value, maxLength = 500) {
  return typeof value === "string" ? value.slice(0, maxLength) : value;
}

function compactManifestOutput(output = {}) {
  return {
    id: boundedText(output.id, 300),
    title: boundedText(output.title, 500),
    status: output.status,
    retrieval: output.retrieval && typeof output.retrieval === "object"
      ? {
        state: output.retrieval.state,
        source: output.retrieval.source,
        declaredMediaType: boundedText(output.retrieval.declaredMediaType, 300),
        detectedMediaType: boundedText(output.retrieval.detectedMediaType, 300),
        bytes: output.retrieval.bytes,
      }
      : undefined,
    interpretation: output.interpretation && typeof output.interpretation === "object"
      ? {
        state: output.interpretation.state,
        kind: output.interpretation.kind,
        mediaType: boundedText(output.interpretation.mediaType, 300),
      }
      : undefined,
    presentations: Array.isArray(output.presentations)
      ? output.presentations.slice(0, 20).map((presentation) => ({
        id: boundedText(presentation?.id, 300),
        kind: presentation?.kind,
        state: presentation?.state,
        title: boundedText(presentation?.title, 500),
      }))
      : [],
    warnings: Array.isArray(output.warnings)
      ? output.warnings.slice(0, 10).map((warning) => boundedText(warning, 500))
      : undefined,
  };
}

/**
 * Keep activity/2 manifest updates useful for audit/status UIs without copying
 * large inline representations or coordinate arrays into the event stream.
 * The legacy output_manifest event remains the authoritative full envelope
 * during migration; consumers can also use representation/artifact handles.
 */
export function workflowManifestPayload(manifest, {
  title = "Output manifest updated",
} = {}) {
  const base = {
    title,
    status: manifest?.overallState,
  };
  if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) {
    return base;
  }

  let serializedBytes = Number.POSITIVE_INFINITY;
  try {
    serializedBytes = Buffer.byteLength(JSON.stringify(manifest), "utf8");
  } catch {
    // A non-serializable manifest is represented by the safe summary below.
  }
  if (serializedBytes <= MAX_INLINE_WORKFLOW_MANIFEST_BYTES) {
    return { ...base, manifest };
  }

  return {
    ...base,
    manifestId: boundedText(manifest.manifestId, 200),
    manifestSummary: {
      schemaVersion: manifest.schemaVersion,
      manifestId: boundedText(manifest.manifestId, 200),
      execution: manifest.execution && typeof manifest.execution === "object"
        ? {
          state: manifest.execution.state,
          serverId: boundedText(manifest.execution.serverId, 200),
          processId: boundedText(manifest.execution.processId, 300),
          planId: boundedText(manifest.execution.planId, 300),
          jobId: boundedText(manifest.execution.jobId, 300),
          reportedStatus: boundedText(manifest.execution.reportedStatus, 200),
          trackingState: manifest.execution.trackingState,
        }
        : undefined,
      overallState: manifest.overallState,
      outputs: Array.isArray(manifest.outputs)
        ? manifest.outputs.slice(0, 100).map(compactManifestOutput)
        : [],
      warnings: Array.isArray(manifest.warnings)
        ? manifest.warnings.slice(0, 20).map((warning) => boundedText(warning, 500))
        : undefined,
    },
    omittedInlineManifest: true,
    originalBytes: Number.isFinite(serializedBytes) ? serializedBytes : undefined,
  };
}

/**
 * Create an activity/2 producer for one ordered workflow run.
 *
 * Sequence numbers are scoped to the run represented by this producer. The
 * outer targetMessageId is intentionally repeated so the existing SSE router
 * can associate the event without understanding the versioned envelope.
 */
export function createWorkflowEventEmitter({
  emit,
  sessionId,
  turnId,
  targetMessageId,
  runId = "",
  now = () => Date.now(),
} = {}) {
  if (typeof emit !== "function") throw new TypeError("emit must be a function.");
  const context = {
    sessionId: requiredIdentifier(sessionId, "sessionId"),
    turnId: requiredIdentifier(turnId, "turnId"),
    targetMessageId: requiredIdentifier(targetMessageId, "targetMessageId"),
  };
  const boundedRunId = optionalIdentifier(runId);
  let sequence = 0;

  return function emitWorkflowEvent(type, { activityId, payload = {}, atMs } = {}) {
    if (!WORKFLOW_EVENT_TYPES.has(type)) {
      throw new TypeError(`Unsupported activity/2 event type: ${String(type)}`);
    }
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      throw new TypeError("activity/2 payload must be an object.");
    }
    const candidateTimestampMs = Number.isFinite(atMs) ? atMs : now();
    const timestampMs = Number.isFinite(candidateTimestampMs) ? candidateTimestampMs : Date.now();
    const event = {
      schemaVersion: "activity/2",
      eventId: `evt_${randomUUID()}`,
      sequence,
      ...context,
      ...(boundedRunId ? { runId: boundedRunId } : {}),
      activityId: requiredIdentifier(activityId, "activityId"),
      timestamp: new Date(timestampMs).toISOString(),
      type,
      payload,
    };
    sequence += 1;
    emit("workflow_event", {
      targetMessageId: context.targetMessageId,
      event,
    });
    return event;
  };
}
