import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  createWorkflowEventEmitter,
  MAX_INLINE_WORKFLOW_MANIFEST_BYTES,
  WORKFLOW_EVENT_TYPES,
  workflowManifestPayload,
} from "./workflow-events.mjs";

const workflowSchema = JSON.parse(readFileSync(
  new URL("../../spec/ogc-workflow-event.schema.json", import.meta.url),
  "utf8",
));

test("activity/2 producer types stay synchronized with the shared schema", () => {
  assert.deepEqual(
    [...WORKFLOW_EVENT_TYPES].sort(),
    [...workflowSchema.properties.type.enum].sort(),
  );
});

test("activity/2 producer emits complete envelopes with monotonic per-run sequence", () => {
  const emitted = [];
  const emitWorkflowEvent = createWorkflowEventEmitter({
    emit: (event, data) => emitted.push({ event, data }),
    sessionId: "session-1",
    turnId: "turn-1",
    targetMessageId: "assistant-1",
    runId: "agent-turn-1",
    now: () => 1_700_000_000_000,
  });

  const first = emitWorkflowEvent("intent_recognized", {
    activityId: "understand",
    payload: { title: "Request understood", status: "complete" },
  });
  const second = emitWorkflowEvent("output_manifest_upserted", {
    activityId: "manifest-1",
    payload: { manifest: { schemaVersion: "ogc-output-manifest/1" } },
    atMs: 1_700_000_000_100,
  });

  assert.equal(emitted.length, 2);
  assert.equal(emitted[0].event, "workflow_event");
  assert.equal(emitted[0].data.targetMessageId, "assistant-1");
  assert.deepEqual(first, emitted[0].data.event);
  assert.equal(first.schemaVersion, "activity/2");
  assert.equal(first.sequence, 0);
  assert.equal(second.sequence, 1);
  assert.notEqual(first.eventId, second.eventId);
  assert.match(first.eventId, /^evt_[0-9a-f-]{36}$/);
  assert.equal(first.sessionId, "session-1");
  assert.equal(first.turnId, "turn-1");
  assert.equal(first.targetMessageId, "assistant-1");
  assert.equal(first.runId, "agent-turn-1");
  assert.equal(first.timestamp, "2023-11-14T22:13:20.000Z");
  assert.equal(second.timestamp, "2023-11-14T22:13:20.100Z");
  for (const required of workflowSchema.required) {
    assert.equal(Object.hasOwn(first, required), true, `missing schema field ${required}`);
  }
  assert.equal(first.schemaVersion, workflowSchema.properties.schemaVersion.const);
  assert.ok(workflowSchema.properties.type.enum.includes(first.type));
});

test("activity/2 producer rejects incomplete or unsupported events", () => {
  assert.throws(
    () => createWorkflowEventEmitter({
      emit: () => undefined,
      sessionId: "",
      turnId: "turn-1",
      targetMessageId: "assistant-1",
    }),
    /sessionId is required/,
  );
  const emitWorkflowEvent = createWorkflowEventEmitter({
    emit: () => undefined,
    sessionId: "session-1",
    turnId: "turn-1",
    targetMessageId: "assistant-1",
  });
  assert.throws(
    () => emitWorkflowEvent("unknown", { activityId: "activity-1" }),
    /Unsupported activity\/2 event type/,
  );
  assert.throws(
    () => emitWorkflowEvent("step_started", { activityId: "" }),
    /activityId is required/,
  );
});

test("small workflow manifests remain inline for compatible consumers", () => {
  const manifest = {
    schemaVersion: "ogc-output-manifest/1",
    manifestId: "manifest-small",
    execution: { state: "succeeded", serverId: "demo" },
    overallState: "ready",
    outputs: [],
  };
  const payload = workflowManifestPayload(manifest);
  assert.equal(payload.manifest, manifest);
  assert.equal(payload.omittedInlineManifest, undefined);
});

test("large workflow manifests use a bounded coordinate-free summary", () => {
  const manifest = {
    schemaVersion: "ogc-output-manifest/1",
    manifestId: "manifest-large",
    execution: { state: "succeeded", serverId: "demo", processId: "buffer" },
    overallState: "ready",
    outputs: [{
      id: "result",
      title: "Result",
      status: "ready",
      retrieval: { state: "retrieved", source: "memory", bytes: 500_000 },
      interpretation: { state: "recognized", kind: "geojson" },
      representations: [{
        mediaType: "application/geo+json",
        data: {
          type: "FeatureCollection",
          features: [{
            type: "Feature",
            geometry: { type: "Polygon", coordinates: [[Array(40_000).fill(1)]] },
            properties: { name: "large geometry" },
          }],
        },
      }],
      presentations: [{ id: "map", kind: "map", state: "ready", title: "Map" }],
      provenance: {},
    }],
  };

  const payload = workflowManifestPayload(manifest);
  const serialized = JSON.stringify(payload);
  assert.equal(payload.manifest, undefined);
  assert.equal(payload.omittedInlineManifest, true);
  assert.equal(payload.manifestSummary.outputs[0].representations, undefined);
  assert.equal(serialized.includes("coordinates"), false);
  assert.ok(Buffer.byteLength(serialized, "utf8") < MAX_INLINE_WORKFLOW_MANIFEST_BYTES);
  assert.ok(payload.originalBytes > MAX_INLINE_WORKFLOW_MANIFEST_BYTES);
});
