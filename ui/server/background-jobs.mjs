import { callMcpTool } from "./mcp-client.mjs";
import { structuredToolPayload } from "./map-artifacts.mjs";
import {
  artifactStatusEvents,
  prepareResultArtifacts,
} from "./result-artifacts.mjs";

const subscribers = new Map();
const queuedEvents = new Map();
const trackedJobs = new Map();

const DEFAULT_POLL_INTERVAL_MS = 3_000;
const DEFAULT_TIMEOUT_MS = 30 * 60 * 1_000;
const DEFAULT_RESULT_RETRY_INTERVAL_MS = 1_500;
const DEFAULT_RESULT_AVAILABILITY_TIMEOUT_MS = 60_000;
const DEFAULT_MAX_RESULT_ATTEMPTS = 8;
const MAX_QUEUED_EVENTS = 50;

function boundedMilliseconds(value, fallback, minimum, maximum) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.min(maximum, Math.max(minimum, parsed)) : fallback;
}

function cleanIdentifier(value, maximum = 200) {
  if (typeof value !== "string" && typeof value !== "number") return "";
  const text = String(value).trim();
  return /^[a-zA-Z0-9_.~-]+$/.test(text) ? text.slice(0, maximum) : "";
}

function eventFor(sessionId, event, data) {
  const listeners = subscribers.get(sessionId);
  if (listeners?.size) {
    for (const listener of listeners) {
      try {
        listener(event, data);
      } catch {
        listeners.delete(listener);
      }
    }
    return;
  }
  const queue = queuedEvents.get(sessionId) || [];
  queue.push({ event, data });
  queuedEvents.set(sessionId, queue.slice(-MAX_QUEUED_EVENTS));
}

export function subscribeSessionEvents(sessionId, listener) {
  const listeners = subscribers.get(sessionId) || new Set();
  listeners.add(listener);
  subscribers.set(sessionId, listeners);
  const queue = queuedEvents.get(sessionId) || [];
  queuedEvents.delete(sessionId);
  for (const item of queue) listener(item.event, item.data);
  return () => {
    listeners.delete(listener);
    if (!listeners.size) subscribers.delete(sessionId);
  };
}

function findNamedValue(value, names, depth = 0) {
  if (!value || depth > 4) return undefined;
  if (Array.isArray(value)) {
    for (const item of value.slice(0, 30)) {
      const found = findNamedValue(item, names, depth + 1);
      if (found !== undefined) return found;
    }
    return undefined;
  }
  if (typeof value !== "object") return undefined;
  for (const [key, item] of Object.entries(value).slice(0, 60)) {
    if (names.has(key.toLowerCase())) return item;
  }
  for (const item of Object.values(value).slice(0, 60)) {
    const found = findNamedValue(item, names, depth + 1);
    if (found !== undefined) return found;
  }
  return undefined;
}

function jobIdFromLocation(location) {
  if (typeof location !== "string" || !location.trim()) return "";
  try {
    const path = new URL(location, "https://ogc.invalid").pathname;
    const segments = path.split("/").filter(Boolean);
    const jobsIndex = segments.findIndex((segment) => segment.toLowerCase() === "jobs");
    const encoded = jobsIndex >= 0 ? segments[jobsIndex + 1] : segments.at(-1);
    if (!encoded) return "";
    return cleanIdentifier(decodeURIComponent(encoded));
  } catch {
    return "";
  }
}

export function extractBackgroundJob(toolName, result) {
  if (!["ogc_proxy_execute_plan", "ogc_processes_execute"].includes(toolName) || result?.isError) return null;
  const payload = structuredToolPayload(result);
  if (!payload || payload.ok === false) return null;
  const statusCode = Number(payload.response?.status_code);
  const location = payload.guidance?.location || payload.response?.location || "";
  const status = String(findNamedValue(payload.data, new Set(["status", "state"])) || "").toLowerCase();
  if (
    ![201, 202].includes(statusCode)
    && !["accepted", "running", "queued", "pending", "submitted"].includes(status)
  ) return null;
  const nestedId = findNamedValue(payload.data, new Set(["jobid", "job_id"]));
  const jobId = cleanIdentifier(nestedId) || jobIdFromLocation(location);
  if (!jobId) return null;
  return {
    jobId,
    serverId: cleanIdentifier(payload.server?.id, 120),
  };
}

export function classifyJobStatus(result) {
  if (result?.isError) return { state: "error", raw: "error" };
  const payload = structuredToolPayload(result);
  if (!payload || payload.ok === false) return { state: "error", raw: "error" };
  const raw = String(findNamedValue(payload.data, new Set(["status", "state"])) || "unknown").toLowerCase().slice(0, 80);
  if (["successful", "succeeded", "success", "finished", "complete", "completed"].includes(raw)) {
    return { state: "success", raw };
  }
  if (["failed", "dismissed", "cancelled", "canceled", "error"].includes(raw)) {
    return { state: "error", raw };
  }
  return { state: "running", raw };
}

function wait(milliseconds, signal) {
  if (milliseconds <= 0) return Promise.resolve();
  return new Promise((resolve) => {
    const timeout = setTimeout(resolve, milliseconds);
    signal?.addEventListener("abort", () => {
      clearTimeout(timeout);
      resolve();
    }, { once: true });
  });
}

function statusEvent(job, status, detail, {
  stage = status,
  now = Date.now(),
  result,
  pollCount,
} = {}) {
  const startedAtMs = Number.isFinite(job.startedAtMs) ? job.startedAtMs : now;
  return {
    targetMessageId: job.targetMessageId,
    jobId: job.jobId,
    serverId: job.serverId,
    status,
    stage,
    title: `Background job ${job.jobId}`,
    detail,
    purpose: `Monitor background job “${job.jobId}” until its outputs are ready.`,
    input: {
      jobId: job.jobId,
      ...(job.serverId ? { serverId: job.serverId } : {}),
    },
    summary: detail,
    ...(result ? { result } : {}),
    ...(Number.isFinite(pollCount) ? { pollCount } : {}),
    startedAt: new Date(startedAtMs).toISOString(),
    timestamp: new Date(now).toISOString(),
    durationMs: Math.max(0, now - startedAtMs),
    elapsedMs: Math.max(0, now - startedAtMs),
  };
}

function jobManifestId(job) {
  const serverId = cleanIdentifier(job.serverId, 120) || "default";
  return `job-${serverId}-${cleanIdentifier(job.jobId)}`;
}

function terminalManifest(job, {
  executionState,
  overallState,
  reportedStatus,
  warning,
  outputs = [],
}) {
  return {
    schemaVersion: "ogc-output-manifest/1",
    manifestId: jobManifestId(job),
    execution: {
      state: executionState,
      serverId: cleanIdentifier(job.serverId, 120) || "default",
      jobId: cleanIdentifier(job.jobId),
      ...(reportedStatus ? { reportedStatus: String(reportedStatus).slice(0, 200) } : {}),
    },
    overallState,
    outputs,
    ...(warning ? { warnings: [String(warning).slice(0, 2_000)] } : {}),
  };
}

function exhaustedResultManifest(manifest, job, detail) {
  const message = String(detail || "The result was not published within the bounded retry window.").slice(0, 2_000);
  const outputs = (manifest?.outputs || []).map((output) => {
    const retrievalPending = ["pending", "resolving"].includes(output?.retrieval?.state);
    const interpretationPending = output?.interpretation?.state === "pending";
    const presentationPending = (output?.presentations || []).some((presentation) =>
      ["pending", "preparing", "resolving", "running"].includes(presentation?.state)
    );
    if (!retrievalPending && !interpretationPending && !presentationPending) return output;
    return {
      ...output,
      status: "failed",
      retrieval: retrievalPending
        ? {
          ...output.retrieval,
          state: "failed",
          error: {
            code: "result_retrieval_exhausted",
            message,
            phase: "retrieval",
            retryable: true,
          },
        }
        : output.retrieval,
      interpretation: interpretationPending
        ? {
          ...output.interpretation,
          state: "failed",
          error: {
            code: "result_interpretation_incomplete",
            message,
            phase: "interpretation",
            retryable: true,
          },
        }
        : output.interpretation,
      presentations: (output.presentations || []).map((presentation) => (
        ["pending", "preparing", "resolving", "running"].includes(presentation?.state)
          ? {
            ...presentation,
            state: "unavailable",
            reason: presentation.reason || message,
          }
          : presentation
      )),
    };
  });
  const hasUsableOutput = outputs.some((output) =>
    ["ready", "partial", "empty"].includes(output.status)
  );
  return {
    ...manifest,
    manifestId: jobManifestId(job),
    execution: {
      ...(manifest?.execution || {}),
      state: "succeeded",
      serverId: cleanIdentifier(job.serverId, 120)
        || manifest?.execution?.serverId
        || "default",
      jobId: cleanIdentifier(job.jobId),
    },
    overallState: hasUsableOutput ? "partial" : "unavailable",
    outputs,
    warnings: [...new Set([...(manifest?.warnings || []), message])].slice(0, 100),
  };
}

function firstOutputPhase(manifest) {
  const output = manifest?.outputs?.[0];
  return {
    retrievalState: output?.retrieval?.state || "failed",
    interpretationState: output?.interpretation?.state || "failed",
    presentationState: output?.presentations?.find((item) => item.kind === "map")?.state
      || output?.presentations?.[0]?.state
      || "unavailable",
  };
}

function retryableManifestIssue(manifest) {
  for (const output of manifest?.outputs || []) {
    for (const error of [output?.retrieval?.error, output?.interpretation?.error]) {
      if (error?.retryable === true) {
        return String(error.message || "The process output is not available yet.").slice(0, 500);
      }
    }
  }
  return "";
}

function publishManifest(publish, job, manifest, startedAt, activityId = "") {
  const now = Date.now();
  publish("output_manifest", {
    targetMessageId: job.targetMessageId,
    activityId: activityId || `background-${job.jobId}`,
    manifest,
    timestamp: new Date(now).toISOString(),
    durationMs: Math.max(0, now - startedAt),
    elapsedMs: Math.max(0, now - startedAt),
  });
}

/** Poll one OGC job until it reaches a terminal status, then retrieve and map it. */
export async function monitorBackgroundJob(job, {
  callTool = callMcpTool,
  publish = () => undefined,
  signal,
  initialDelayMs = DEFAULT_POLL_INTERVAL_MS,
  pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
  timeoutMs = DEFAULT_TIMEOUT_MS,
  resultRetryIntervalMs = DEFAULT_RESULT_RETRY_INTERVAL_MS,
  resultAvailabilityTimeoutMs = DEFAULT_RESULT_AVAILABILITY_TIMEOUT_MS,
  maxResultAttempts = DEFAULT_MAX_RESULT_ATTEMPTS,
} = {}) {
  const startedAt = Number.isFinite(job.startedAtMs) ? job.startedAtMs : Date.now();
  const monitoredJob = Number.isFinite(job.startedAtMs) ? job : { ...job, startedAtMs: startedAt };
  let consecutiveErrors = 0;
  let pollCount = 0;
  await wait(initialDelayMs, signal);

  while (!signal?.aborted && Date.now() - startedAt <= timeoutMs) {
    let statusResult;
    try {
      pollCount += 1;
      statusResult = await callTool("ogc_jobs_get_status", {
        job_id: job.jobId,
        ...(job.serverId ? { server_id: job.serverId } : {}),
      }, { signal });
    } catch {
      consecutiveErrors += 1;
      if (consecutiveErrors >= 3) {
        publishManifest(
          publish,
          monitoredJob,
          terminalManifest(monitoredJob, {
            executionState: "running",
            overallState: "unavailable",
            reportedStatus: "monitoring_failed",
            warning: "Automatic job monitoring stopped after repeated status errors; the process may still be running.",
          }),
          startedAt,
        );
        publish("job_status", statusEvent(
          monitoredJob,
          "error",
          "Job monitoring stopped after repeated status errors.",
          { stage: "monitoring_failed", pollCount },
        ));
        return;
      }
      await wait(pollIntervalMs, signal);
      continue;
    }

    if (signal?.aborted) return;
    const statusPayload = structuredToolPayload(statusResult);
    if (statusResult?.isError || !statusPayload || statusPayload.ok === false) {
      consecutiveErrors += 1;
      if (consecutiveErrors >= 3) {
        publishManifest(
          publish,
          monitoredJob,
          terminalManifest(monitoredJob, {
            executionState: "running",
            overallState: "unavailable",
            reportedStatus: "monitoring_failed",
            warning: "Automatic job monitoring stopped after repeated status errors; the process may still be running.",
          }),
          startedAt,
        );
        publish("job_status", statusEvent(
          monitoredJob,
          "error",
          "Job monitoring stopped after repeated status errors.",
          { stage: "monitoring_failed", pollCount },
        ));
        return;
      }
      await wait(pollIntervalMs, signal);
      continue;
    }
    const status = classifyJobStatus(statusResult);
    if (status.state === "error") {
      publishManifest(
        publish,
        monitoredJob,
        terminalManifest(monitoredJob, {
          executionState: status.raw.includes("cancel") || status.raw === "dismissed"
            ? "cancelled"
            : "failed",
          overallState: "unavailable",
          reportedStatus: status.raw,
          warning: `The upstream process ended with status ${status.raw}.`,
        }),
        startedAt,
      );
      publish("job_status", statusEvent(
        monitoredJob,
        "error",
        `The process ended with status ${status.raw}.`,
        {
          stage: "process_failed",
          pollCount,
          result: { processStatus: status.raw },
        },
      ));
      return;
    }
    if (status.state === "success") {
      let retrievalAttempts = 0;
      let retrievalIssue = "";
      publish("job_status", statusEvent(
        monitoredJob,
        "running",
        "Process complete; retrieving geospatial outputs.",
        {
          stage: "retrieving_outputs",
          pollCount,
          result: { processStatus: status.raw },
        },
      ));
      try {
        const args = {
          job_id: job.jobId,
          ...(job.serverId ? { server_id: job.serverId } : {}),
        };
        const resultDeadline = Date.now() + Math.max(0, resultAvailabilityTimeoutMs);
        const boundedAttempts = Math.max(1, Math.min(50, Math.round(maxResultAttempts)));
        let result;
        let artifacts;
        let retrievalComplete = false;

        while (
          !signal?.aborted
          && retrievalAttempts < boundedAttempts
          && Date.now() <= resultDeadline
        ) {
          retrievalAttempts += 1;
          try {
            result = await callTool("ogc_jobs_get_results", args, { signal });
            if (signal?.aborted) return;
            const resultPayload = structuredToolPayload(result);
            if (result?.isError || !resultPayload || resultPayload.ok === false) {
              const responseStatus = Number(resultPayload?.response?.status_code);
              retrievalIssue = Number.isFinite(responseStatus)
                ? `The result endpoint returned HTTP ${responseStatus}.`
                : String(resultPayload?.error || "The result endpoint did not return a usable response.").slice(0, 500);
            } else {
              artifacts = await prepareResultArtifacts({
                toolName: "ogc_jobs_get_results",
                args,
                activityId: `background-${job.jobId}`,
                result,
                callTool: (name, toolArgs, toolOptions = {}) => callTool(name, toolArgs, {
                  ...toolOptions,
                  signal: toolOptions.signal || signal,
                }),
                sessionId: job.sessionId || "",
              });
              const retryableIssue = retryableManifestIssue(artifacts?.manifest);
              if (artifacts?.manifest?.overallState === "pending" || retryableIssue) {
                retrievalIssue = retryableIssue
                  || "The result endpoint is reachable, but the output is still being prepared.";
              } else {
                retrievalComplete = true;
                break;
              }
            }
          } catch (error) {
            retrievalIssue = error instanceof Error
              ? error.message.slice(0, 500)
              : String(error).slice(0, 500);
          }

          if (
            signal?.aborted
            || retrievalAttempts >= boundedAttempts
            || Date.now() >= resultDeadline
          ) break;
          publish("job_status", statusEvent(
            monitoredJob,
            "running",
            `${retrievalIssue || "The output is not ready yet"} Retrying safely.`,
            {
              stage: "retrieving_outputs",
              pollCount,
              result: {
                processStatus: status.raw,
                retrievalAttempts,
                retryable: true,
              },
            },
          ));
          await wait(resultRetryIntervalMs, signal);
        }

        if (signal?.aborted) return;
        if (!retrievalComplete && !artifacts?.manifest) {
          throw new Error(retrievalIssue || "Job result retrieval failed.");
        }
        if (!retrievalComplete && artifacts?.manifest) {
          const manifest = exhaustedResultManifest(
            artifacts.manifest,
            monitoredJob,
            retrievalIssue,
          );
          artifacts = {
            ...artifacts,
            manifest,
            visualization: null,
            artifactEvents: artifactStatusEvents(manifest),
          };
        }
        if (artifacts?.manifest) {
          publishManifest(
            publish,
            monitoredJob,
            artifacts.manifest,
            startedAt,
          );
          for (const artifactEvent of artifacts.artifactEvents || []) {
            publish("artifact_status", {
              targetMessageId: job.targetMessageId,
              activityId: `background-${job.jobId}`,
              ...artifactEvent,
              manifestId: artifacts.manifest.manifestId,
              timestamp: new Date().toISOString(),
            });
          }
        }
        if (artifacts?.visualization) {
          const mapReadyAt = Date.now();
          publish("map_data", {
            targetMessageId: job.targetMessageId,
            jobId: job.jobId,
            serverId: job.serverId,
            visualization: artifacts.visualization,
            timestamp: new Date(mapReadyAt).toISOString(),
            durationMs: Math.max(0, mapReadyAt - startedAt),
            elapsedMs: Math.max(0, mapReadyAt - startedAt),
          });
          publish("job_status", statusEvent(
            monitoredJob,
            "complete",
            "Process complete; map result ready.",
            {
              stage: "outputs_ready",
              pollCount,
              result: {
                processStatus: status.raw,
                spatialOutput: true,
                map: {
                  id: artifacts.visualization.id,
                  title: artifacts.visualization.title,
                  layerCount: artifacts.visualization.layers.length,
                  featureCount: artifacts.visualization.stats?.featureCount,
                  truncated: artifacts.visualization.stats?.truncated === true,
                  warnings: artifacts.visualization.warnings || [],
                },
                outputManifestId: artifacts.manifest?.manifestId,
                retrievalState: artifacts.manifest?.outputs?.[0]?.retrieval?.state,
                interpretationState: artifacts.manifest?.outputs?.[0]?.interpretation?.state,
                presentationState: "ready",
                retrievalAttempts,
              },
            },
          ));
        } else if (!retrievalComplete) {
          const phases = firstOutputPhase(artifacts.manifest);
          publish("job_status", statusEvent(
            monitoredJob,
            "error",
            "The process completed, but its output could not be prepared within the retry window.",
            {
              stage: "output_retrieval_incomplete",
              pollCount,
              result: {
                processStatus: status.raw,
                spatialOutput: false,
                outputManifestId: artifacts.manifest.manifestId,
                ...phases,
                retrievalAttempts,
                retryable: true,
                detail: retrievalIssue || "The output was not ready before the bounded retry window ended.",
              },
            },
          ));
        } else {
          publish("job_status", statusEvent(
            monitoredJob,
            "complete",
            artifacts?.manifest
              ? "Process complete; outputs were retrieved but no map-ready layer was produced."
              : "Process complete; no declared output was returned.",
            {
              stage: "outputs_ready",
              pollCount,
              result: {
                processStatus: status.raw,
                spatialOutput: false,
                ...(artifacts?.manifest ? {
                  outputManifestId: artifacts.manifest.manifestId,
                  retrievalState: artifacts.manifest.outputs?.[0]?.retrieval?.state,
                  interpretationState: artifacts.manifest.outputs?.[0]?.interpretation?.state,
                  presentationState: artifacts.manifest.outputs?.[0]?.presentations?.find((item) => item.kind === "map")?.state
                    || "unavailable",
                } : {}),
                retrievalAttempts,
              },
            },
          ));
        }
      } catch (error) {
        const detail = error instanceof Error ? error.message.slice(0, 500) : String(error).slice(0, 500);
        publishManifest(
          publish,
          monitoredJob,
          terminalManifest(monitoredJob, {
            executionState: "succeeded",
            overallState: "unavailable",
            reportedStatus: status.raw,
            warning: detail || "The process completed, but its outputs could not be retrieved.",
            outputs: [{
              id: "result",
              title: "Process output",
              status: "failed",
              retrieval: {
                state: "failed",
                source: "reference",
                error: {
                  code: "output_retrieval_failed",
                  message: detail || "The process output could not be retrieved.",
                  phase: "retrieval",
                  retryable: true,
                },
              },
              interpretation: {
                state: "pending",
                semanticType: "unknown",
                crs: { status: "missing" },
              },
              presentations: [{
                id: "result-download",
                kind: "download",
                state: "unavailable",
                reason: "Output retrieval must succeed before a presentation is available.",
              }],
              provenance: {
                serverId: cleanIdentifier(monitoredJob.serverId, 120) || "default",
              },
            }],
          }),
          startedAt,
        );
        publish("job_status", statusEvent(
          monitoredJob,
          "error",
          "The process completed, but its outputs could not be retrieved.",
          {
            stage: "output_retrieval_failed",
            pollCount,
            result: {
              processStatus: status.raw,
              retrievalAttempts,
              retryable: true,
              detail,
            },
          },
        ));
      }
      return;
    }

    consecutiveErrors = 0;
    publish("job_status", statusEvent(
      monitoredJob,
      "running",
      `Process status: ${status.raw}.`,
      {
        stage: "monitoring",
        pollCount,
        result: { processStatus: status.raw },
      },
    ));
    await wait(pollIntervalMs, signal);
  }

  if (!signal?.aborted) {
    publishManifest(
      publish,
      monitoredJob,
      terminalManifest(monitoredJob, {
        executionState: "running",
        overallState: "unavailable",
        reportedStatus: "monitoring_timed_out",
        warning: "Automatic job monitoring timed out; the process may still be running.",
      }),
      startedAt,
    );
    publish("job_status", statusEvent(
      monitoredJob,
      "error",
      "Job monitoring timed out; ask Terra to check the job again.",
      { stage: "monitoring_timed_out", pollCount },
    ));
  }
}

function trackedKey(sessionId, serverId, jobId) {
  return JSON.stringify([sessionId, serverId || "default", jobId]);
}

export function trackBackgroundJob({ sessionId, targetMessageId, job }, overrides = {}) {
  if (!sessionId || !targetMessageId || !job?.jobId) return false;
  const key = trackedKey(sessionId, job.serverId, job.jobId);
  if (trackedJobs.has(key)) return false;
  const controller = new AbortController();
  const tracked = {
    controller,
    sessionId,
    job: {
      ...job,
      targetMessageId,
      sessionId,
      startedAtMs: Date.now(),
    },
  };
  trackedJobs.set(key, tracked);
  eventFor(sessionId, "job_status", statusEvent(
    tracked.job,
    "running",
    "Background process submitted; waiting for completion.",
    { stage: "submitted", pollCount: 0 },
  ));
  const pollIntervalMs = boundedMilliseconds(
    process.env.OGC_JOB_POLL_INTERVAL_MS,
    DEFAULT_POLL_INTERVAL_MS,
    1_000,
    60_000,
  );
  const timeoutMs = boundedMilliseconds(
    process.env.OGC_JOB_MONITOR_TIMEOUT_MS,
    DEFAULT_TIMEOUT_MS,
    30_000,
    24 * 60 * 60 * 1_000,
  );
  const resultRetryIntervalMs = boundedMilliseconds(
    process.env.OGC_JOB_RESULT_RETRY_INTERVAL_MS,
    DEFAULT_RESULT_RETRY_INTERVAL_MS,
    250,
    60_000,
  );
  const resultAvailabilityTimeoutMs = boundedMilliseconds(
    process.env.OGC_JOB_RESULT_TIMEOUT_MS,
    DEFAULT_RESULT_AVAILABILITY_TIMEOUT_MS,
    1_000,
    10 * 60 * 1_000,
  );
  tracked.promise = monitorBackgroundJob(tracked.job, {
    callTool: overrides.callTool || callMcpTool,
    publish: (event, data) => eventFor(sessionId, event, data),
    signal: controller.signal,
    initialDelayMs: overrides.initialDelayMs ?? pollIntervalMs,
    pollIntervalMs: overrides.pollIntervalMs ?? pollIntervalMs,
    timeoutMs: overrides.timeoutMs ?? timeoutMs,
    resultRetryIntervalMs: overrides.resultRetryIntervalMs ?? resultRetryIntervalMs,
    resultAvailabilityTimeoutMs:
      overrides.resultAvailabilityTimeoutMs ?? resultAvailabilityTimeoutMs,
    maxResultAttempts: overrides.maxResultAttempts ?? DEFAULT_MAX_RESULT_ATTEMPTS,
  }).finally(() => {
    if (trackedJobs.get(key) === tracked) trackedJobs.delete(key);
  });
  return true;
}

export function stopTrackedJob(sessionId, jobId, serverId = "") {
  const cleanJobId = cleanIdentifier(jobId);
  if (!cleanJobId) return;
  const matches = [...trackedJobs.entries()].filter(([, tracked]) => (
    tracked.sessionId === sessionId
    && tracked.job.jobId === cleanJobId
    && (!serverId || tracked.job.serverId === serverId)
  ));
  if (!serverId && matches.length !== 1) return;
  for (const [key, tracked] of matches) {
    tracked.controller.abort();
    trackedJobs.delete(key);
    eventFor(sessionId, "job_status", statusEvent(
      tracked.job,
      "complete",
      "Process complete; result retrieved in the conversation.",
    ));
  }
}

export function clearBackgroundJobs(sessionId) {
  for (const [key, tracked] of trackedJobs) {
    if (tracked.sessionId === sessionId) {
      tracked.controller.abort();
      trackedJobs.delete(key);
    }
  }
  queuedEvents.delete(sessionId);
}

export function backgroundJobCount() {
  return trackedJobs.size;
}
