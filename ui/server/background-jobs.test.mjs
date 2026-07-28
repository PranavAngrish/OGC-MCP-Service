import assert from "node:assert/strict";
import test from "node:test";
import {
  clearBackgroundJobs,
  classifyJobStatus,
  extractBackgroundJob,
  monitorBackgroundJob,
  subscribeSessionEvents,
  trackBackgroundJob,
} from "./background-jobs.mjs";

const structured = (payload) => ({ structuredContent: payload });

test("extractBackgroundJob recognizes confirmed asynchronous plan executions", () => {
  const job = extractBackgroundJob("ogc_proxy_execute_plan", structured({
    ok: true,
    server: { id: "process-server" },
    response: { status_code: 202, location: "/jobs/job-42" },
    data: { boundary: "tool_result_data_only", summary: { jobID: "job-42", status: "accepted" } },
  }));
  assert.deepEqual(job, { jobId: "job-42", serverId: "process-server" });
  assert.equal(extractBackgroundJob("ogc_jobs_get_status", structured({ ok: true })), null);
  assert.equal(extractBackgroundJob("ogc_proxy_execute_plan", structured({
    ok: true,
    response: { status_code: 200 },
    data: { result: "synchronous" },
  })), null);
});

test("classifyJobStatus handles OGC terminal and in-progress states", () => {
  assert.deepEqual(classifyJobStatus(structured({ ok: true, data: { status: "successful" } })), {
    state: "success", raw: "successful",
  });
  assert.deepEqual(classifyJobStatus(structured({ ok: true, data: { state: "failed" } })), {
    state: "error", raw: "failed",
  });
  assert.deepEqual(classifyJobStatus(structured({ ok: true, data: { status: "running" } })), {
    state: "running", raw: "running",
  });
});

test("monitorBackgroundJob retrieves and publishes a map after completion", async () => {
  const calls = [];
  const events = [];
  let checks = 0;
  const pointResult = {
    ok: true,
    server: { id: "process-server", base_url: "https://process.example" },
    data: {
      outputs: {
        result: {
          type: "FeatureCollection",
          features: [{
            type: "Feature",
            properties: { name: "Result" },
            geometry: { type: "Point", coordinates: [77.59, 12.97] },
          }],
        },
      },
    },
  };
  const callTool = async (name, args) => {
    calls.push({ name, args });
    if (name === "ogc_jobs_get_status") {
      checks += 1;
      return structured({ ok: true, data: { status: checks === 1 ? "running" : "successful" } });
    }
    if (name === "ogc_jobs_get_results") return structured(pointResult);
    throw new Error(`Unexpected tool ${name}`);
  };

  await monitorBackgroundJob({
    jobId: "job-42",
    serverId: "process-server",
    targetMessageId: "assistant-1",
  }, {
    callTool,
    publish: (event, data) => events.push({ event, data }),
    initialDelayMs: 0,
    pollIntervalMs: 0,
    timeoutMs: 2_000,
  });

  assert.equal(calls.filter((call) => call.name === "ogc_jobs_get_status").length, 2);
  assert.equal(calls.filter((call) => call.name === "ogc_jobs_get_results").length, 1);
  const mapEvent = events.find((event) => event.event === "map_data");
  assert.ok(mapEvent);
  assert.equal(mapEvent.data.targetMessageId, "assistant-1");
  assert.equal(mapEvent.data.visualization.id, "job-process-server-job-42-map");
  assert.equal(mapEvent.data.visualization.stats.featureCount, 1);
  assert.match(mapEvent.data.timestamp, /^\d{4}-\d{2}-\d{2}T/);
  assert.ok(mapEvent.data.durationMs >= 0);
  assert.equal(mapEvent.data.elapsedMs, mapEvent.data.durationMs);
  const retrievingEvent = events.find(
    (event) => event.event === "job_status" && event.data.stage === "retrieving_outputs",
  );
  assert.ok(retrievingEvent);
  assert.equal(retrievingEvent.data.input.jobId, "job-42");
  assert.equal(retrievingEvent.data.input.serverId, "process-server");
  assert.match(retrievingEvent.data.purpose, /Monitor background job/);
  assert.equal(retrievingEvent.data.result.processStatus, "successful");
  assert.equal(retrievingEvent.data.pollCount, 2);
  assert.equal(events.at(-1).data.status, "complete");
  assert.equal(events.at(-1).data.stage, "outputs_ready");
  assert.equal(events.at(-1).data.result.spatialOutput, true);
  assert.equal(events.at(-1).data.result.map.featureCount, 1);
  assert.equal(events.at(-1).data.result.map.layerCount, 1);
  assert.ok(events.at(-1).data.durationMs >= 0);
  assert.equal(events.at(-1).data.elapsedMs, events.at(-1).data.durationMs);
});

test("tracked jobs deliver session-scoped status and map events", async () => {
  const sessionId = "session-event-test";
  const events = [];
  let resolveComplete;
  const completed = new Promise((resolve) => { resolveComplete = resolve; });
  const unsubscribe = subscribeSessionEvents(sessionId, (event, data) => {
    events.push({ event, data });
    if (event === "job_status" && data.status === "complete") resolveComplete();
  });
  const callTool = async (name) => {
    if (name === "ogc_jobs_get_status") return structured({ ok: true, data: { status: "successful" } });
    if (name === "ogc_jobs_get_results") {
      return structured({
        ok: true,
        data: featureResult([72, 19]),
      });
    }
    throw new Error(`Unexpected tool ${name}`);
  };
  const featureResult = (coordinates) => ({
    type: "Feature",
    properties: {},
    geometry: { type: "Point", coordinates },
  });

  assert.equal(trackBackgroundJob({
    sessionId,
    targetMessageId: "assistant-event-test",
    job: { jobId: "event-job", serverId: "process-server" },
  }, {
    callTool,
    initialDelayMs: 0,
    pollIntervalMs: 0,
    timeoutMs: 2_000,
  }), true);

  let timeout;
  await Promise.race([
    completed,
    new Promise((_, reject) => {
      timeout = setTimeout(() => reject(new Error("background event timeout")), 1_000);
    }),
  ]);
  clearTimeout(timeout);
  assert.equal(events[0].data.status, "running");
  assert.equal(events[0].data.stage, "submitted");
  assert.equal(events[0].data.pollCount, 0);
  assert.equal(events[0].data.input.jobId, "event-job");
  assert.match(events[0].data.startedAt, /^\d{4}-\d{2}-\d{2}T/);
  assert.ok(events.some((item) => item.event === "map_data" && item.data.targetMessageId === "assistant-event-test"));
  unsubscribe();
  clearBackgroundJobs(sessionId);
});
