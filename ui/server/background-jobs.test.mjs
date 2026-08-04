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
  assert.deepEqual(extractBackgroundJob("ogc_processes_execute", structured({
    ok: true,
    server: { id: "process-server" },
    response: { status_code: 200 },
    data: { jobID: "job-pending", status: "pending" },
  })), { jobId: "job-pending", serverId: "process-server" });
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
  const manifestEvent = events.find((event) => event.event === "output_manifest");
  assert.ok(manifestEvent);
  assert.equal(manifestEvent.data.targetMessageId, "assistant-1");
  assert.equal(manifestEvent.data.manifest.schemaVersion, "ogc-output-manifest/1");
  assert.equal(manifestEvent.data.manifest.manifestId, "job-process-server-job-42");
  assert.equal(manifestEvent.data.manifest.execution.state, "succeeded");
  assert.equal(manifestEvent.data.manifest.outputs[0].retrieval.state, "retrieved");
  assert.equal(manifestEvent.data.manifest.outputs[0].interpretation.state, "recognized");
  assert.ok(events.some(
    (event) => event.event === "artifact_status"
      && event.data.stage === "presentation"
      && event.data.status === "complete",
  ));
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

test("monitorBackgroundJob does not report a redirect page as a retrieved output", async () => {
  const events = [];
  const callTool = async (name) => {
    if (name === "ogc_jobs_get_status") {
      return structured({ ok: true, data: { status: "successful" } });
    }
    if (name === "ogc_jobs_get_results") {
      return structured({
        ok: true,
        server: { id: "redirect-server" },
        response: {
          status_code: 302,
          content_type: "text/html",
          location: "http://outputs.example/temp/result.json",
        },
        data: { summary: "<html>Moved</html>" },
      });
    }
    throw new Error(`Unexpected tool ${name}`);
  };

  await monitorBackgroundJob({
    jobId: "redirect-job",
    serverId: "redirect-server",
    targetMessageId: "assistant-redirect",
  }, {
    callTool,
    publish: (event, data) => events.push({ event, data }),
    initialDelayMs: 0,
    pollIntervalMs: 0,
    timeoutMs: 2_000,
    resultRetryIntervalMs: 0,
    resultAvailabilityTimeoutMs: 2_000,
    maxResultAttempts: 3,
  });

  assert.equal(events.filter(
    (event) => event.event === "job_status"
      && event.data.stage === "retrieving_outputs"
      && event.data.result?.retryable === true,
  ).length, 2);
  const manifestEvent = events.find((event) => event.event === "output_manifest");
  assert.equal(manifestEvent.data.manifest.manifestId, "job-redirect-server-redirect-job");
  assert.equal(manifestEvent.data.manifest.overallState, "unavailable");
  assert.equal(manifestEvent.data.manifest.outputs[0].status, "failed");
  assert.equal(manifestEvent.data.manifest.outputs[0].retrieval.state, "failed");
  assert.equal(
    manifestEvent.data.manifest.outputs[0].retrieval.error.code,
    "result_retrieval_exhausted",
  );
  assert.equal(manifestEvent.data.manifest.outputs[0].interpretation.state, "failed");
  assert.equal(manifestEvent.data.manifest.outputs[0].presentations[0].state, "unavailable");
  assert.equal(events.some((event) => event.event === "map_data"), false);
  assert.equal(events.at(-1).event, "job_status");
  assert.equal(events.at(-1).data.status, "error");
  assert.equal(events.at(-1).data.stage, "output_retrieval_incomplete");
  assert.equal(events.at(-1).data.result.retrievalState, "failed");
  assert.equal(events.at(-1).data.result.interpretationState, "failed");
  assert.equal(events.at(-1).data.result.presentationState, "unavailable");
  assert.equal(events.at(-1).data.result.retrievalAttempts, 3);
  assert.equal(events.at(-1).data.result.retryable, true);
});

test("monitorBackgroundJob retries transient result errors after process success", async () => {
  const events = [];
  let resultAttempts = 0;
  const callTool = async (name, _args, options) => {
    assert.ok("signal" in options);
    if (name === "ogc_jobs_get_status") {
      return structured({ ok: true, data: { status: "successful" } });
    }
    if (name === "ogc_jobs_get_results") {
      resultAttempts += 1;
      if (resultAttempts < 3) {
        return structured({
          ok: false,
          error: "Result is not published yet.",
          response: { status_code: resultAttempts === 1 ? 404 : 429 },
        });
      }
      return structured({
        ok: true,
        data: {
          type: "Feature",
          properties: { name: "Recovered output" },
          geometry: { type: "Point", coordinates: [72, 19] },
        },
      });
    }
    throw new Error(`Unexpected tool ${name}`);
  };

  await monitorBackgroundJob({
    jobId: "eventual-result",
    serverId: "process-server",
    targetMessageId: "assistant-eventual",
  }, {
    callTool,
    publish: (event, data) => events.push({ event, data }),
    initialDelayMs: 0,
    pollIntervalMs: 0,
    timeoutMs: 2_000,
    resultRetryIntervalMs: 0,
    resultAvailabilityTimeoutMs: 2_000,
    maxResultAttempts: 4,
  });

  assert.equal(resultAttempts, 3);
  assert.equal(events.at(-1).data.status, "complete");
  assert.equal(events.at(-1).data.result.retrievalAttempts, 3);
  assert.ok(events.some((event) => event.event === "map_data"));
});

test("monitorBackgroundJob retries a successful envelope with retryable artifact failure", async () => {
  const events = [];
  let resultAttempts = 0;
  const callTool = async (name) => {
    if (name === "ogc_jobs_get_status") {
      return structured({ ok: true, data: { status: "successful" } });
    }
    if (name === "ogc_jobs_get_results") {
      resultAttempts += 1;
      if (resultAttempts < 3) {
        return structured({
          ok: true,
          server: { id: "process-server" },
          output_manifest: {
            schemaVersion: "ogc-output-manifest/1",
            manifestId: "upstream-result",
            execution: {
              state: "succeeded",
              serverId: "process-server",
              jobId: "artifact-race",
            },
            overallState: "unavailable",
            outputs: [{
              id: "result",
              title: "Delayed result",
              status: "failed",
              retrieval: {
                state: "failed",
                source: "reference",
                error: {
                  code: "result_not_published",
                  message: "The result reference is not published yet.",
                  retryable: true,
                },
              },
              interpretation: {
                state: "pending",
                semanticType: "unknown",
                crs: { status: "missing" },
              },
              presentations: [{
                id: "result-map",
                kind: "map",
                state: "preparing",
              }],
              provenance: { serverId: "process-server" },
            }],
          },
        });
      }
      return structured({
        ok: true,
        server: { id: "process-server" },
        data: {
          type: "Feature",
          properties: { name: "Eventually published" },
          geometry: { type: "Point", coordinates: [72, 19] },
        },
      });
    }
    throw new Error(`Unexpected tool ${name}`);
  };

  await monitorBackgroundJob({
    jobId: "artifact-race",
    serverId: "process-server",
    targetMessageId: "assistant-artifact-race",
  }, {
    callTool,
    publish: (event, data) => events.push({ event, data }),
    initialDelayMs: 0,
    pollIntervalMs: 0,
    timeoutMs: 2_000,
    resultRetryIntervalMs: 0,
    resultAvailabilityTimeoutMs: 2_000,
    maxResultAttempts: 4,
  });

  assert.equal(resultAttempts, 3);
  assert.ok(events.some((event) => event.event === "map_data"));
  assert.equal(events.at(-1).data.status, "complete");
  assert.equal(events.at(-1).data.result.retrievalAttempts, 3);
});

test("monitorBackgroundJob publishes a terminal manifest when the process fails", async () => {
  const events = [];
  await monitorBackgroundJob({
    jobId: "failed-job",
    serverId: "process-server",
    targetMessageId: "assistant-failed",
  }, {
    callTool: async (name) => {
      assert.equal(name, "ogc_jobs_get_status");
      return structured({ ok: true, data: { status: "failed" } });
    },
    publish: (event, data) => events.push({ event, data }),
    initialDelayMs: 0,
    pollIntervalMs: 0,
    timeoutMs: 2_000,
  });

  assert.equal(events.length, 2);
  assert.equal(events[0].event, "output_manifest");
  assert.equal(events[0].data.manifest.manifestId, "job-process-server-failed-job");
  assert.equal(events[0].data.manifest.execution.state, "failed");
  assert.equal(events[0].data.manifest.execution.reportedStatus, "failed");
  assert.equal(events[0].data.manifest.overallState, "unavailable");
  assert.deepEqual(events[0].data.manifest.outputs, []);
  assert.equal(events[1].event, "job_status");
  assert.equal(events[1].data.status, "error");
  assert.equal(events[1].data.stage, "process_failed");
});

test("monitorBackgroundJob resolves repeated status errors to a terminal monitoring state", async () => {
  const events = [];
  let attempts = 0;
  await monitorBackgroundJob({
    jobId: "status-error-job",
    serverId: "process-server",
    targetMessageId: "assistant-status-error",
  }, {
    callTool: async (name) => {
      assert.equal(name, "ogc_jobs_get_status");
      attempts += 1;
      return structured({ ok: false, error: "Temporary status failure" });
    },
    publish: (event, data) => events.push({ event, data }),
    initialDelayMs: 0,
    pollIntervalMs: 0,
    timeoutMs: 2_000,
  });

  assert.equal(attempts, 3);
  const manifestEvent = events.find((event) => event.event === "output_manifest");
  assert.equal(manifestEvent.data.manifest.manifestId, "job-process-server-status-error-job");
  assert.equal(manifestEvent.data.manifest.execution.state, "running");
  assert.equal(manifestEvent.data.manifest.execution.reportedStatus, "monitoring_failed");
  assert.equal(manifestEvent.data.manifest.overallState, "unavailable");
  assert.equal(events.at(-1).event, "job_status");
  assert.equal(events.at(-1).data.stage, "monitoring_failed");
});

test("monitorBackgroundJob publishes a failed output when results cannot be retrieved", async () => {
  const events = [];
  let resultAttempts = 0;
  await monitorBackgroundJob({
    jobId: "missing-result-job",
    serverId: "process-server",
    targetMessageId: "assistant-missing",
  }, {
    callTool: async (name) => {
      if (name === "ogc_jobs_get_status") {
        return structured({ ok: true, data: { status: "successful" } });
      }
      if (name === "ogc_jobs_get_results") {
        resultAttempts += 1;
        throw new Error("Result endpoint unavailable");
      }
      throw new Error(`Unexpected tool ${name}`);
    },
    publish: (event, data) => events.push({ event, data }),
    initialDelayMs: 0,
    pollIntervalMs: 0,
    timeoutMs: 2_000,
    resultRetryIntervalMs: 0,
    resultAvailabilityTimeoutMs: 2_000,
    maxResultAttempts: 2,
  });

  assert.equal(resultAttempts, 2);
  const manifestEvent = events.find((event) => event.event === "output_manifest");
  assert.equal(manifestEvent.data.manifest.manifestId, "job-process-server-missing-result-job");
  assert.equal(manifestEvent.data.manifest.execution.state, "succeeded");
  assert.equal(manifestEvent.data.manifest.overallState, "unavailable");
  assert.equal(manifestEvent.data.manifest.outputs[0].status, "failed");
  assert.equal(
    manifestEvent.data.manifest.outputs[0].retrieval.error.code,
    "output_retrieval_failed",
  );
  assert.equal(events.at(-1).data.stage, "output_retrieval_failed");
  assert.equal(events.at(-1).data.result.retrievalAttempts, 2);
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
