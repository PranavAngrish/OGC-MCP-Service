import { buildMapVisualization } from "./geospatial.mjs";
import { findMemoryHandle, MAP_SOURCE_TOOLS, structuredToolPayload } from "./map-artifacts.mjs";

export const OUTPUT_MANIFEST_SCHEMA_VERSION = "ogc-output-manifest/1";

const HYDRATION_LIMIT = 1_000;
const MAX_INLINE_BYTES = 1_250_000;
export const CANONICAL_ARTIFACT_HYDRATION_LIMITS = Object.freeze({
  maxFetches: 8,
  maxTotalBytes: 2_500_000,
  maxElapsedMs: 5_000,
});
const EXECUTION_STATES = new Set([
  "awaiting_input",
  "awaiting_approval",
  "submitted",
  "running",
  "succeeded",
  "failed",
  "cancelled",
]);
const OUTPUT_STATES = new Set([
  "pending",
  "ready",
  "partial",
  "empty",
  "unresolved",
  "blocked",
  "unsupported",
  "failed",
]);
const RETRIEVAL_STATES = new Set(["pending", "resolving", "retrieved", "partial", "failed", "blocked"]);
const INTERPRETATION_STATES = new Set(["pending", "recognized", "ambiguous", "unsupported", "failed"]);
const SEMANTIC_TYPES = new Set([
  "vector",
  "raster",
  "coverage",
  "tiles",
  "table",
  "timeseries",
  "scalar",
  "image",
  "document",
  "binary",
  "unknown",
]);
const PRESENTATION_STATES = new Set(["preparing", "ready", "partial", "unavailable"]);
const PRESENTATION_KINDS = new Set(["map", "table", "chart", "metric", "image", "text", "download"]);
const TERMINAL_JOB_STATES = new Set(["successful", "succeeded", "success", "finished", "complete", "completed"]);
const FAILED_JOB_STATES = new Set(["failed", "dismissed", "cancelled", "canceled", "error"]);
const sessionArtifacts = new Map();
const MAX_SESSION_ARTIFACTS = 2_000;

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function text(value, maximum = 2_000) {
  if (typeof value !== "string" && typeof value !== "number") return "";
  return String(value).trim().slice(0, maximum);
}

function identifier(value, fallback = "result") {
  return (text(value, 300) || fallback)
    .replace(/[^a-zA-Z0-9_.~-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 300) || fallback;
}

function titleFor(value, fallback = "Process output") {
  const label = text(value, 500)
    .replace(/[_-]+/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2");
  return label ? `${label[0].toUpperCase()}${label.slice(1)}` : fallback;
}

function enumValue(value, allowed, fallback) {
  const normalized = text(value, 100).toLowerCase();
  return allowed.has(normalized) ? normalized : fallback;
}

function uniqueWarnings(...groups) {
  return [...new Set(
    groups
      .flatMap((group) => (Array.isArray(group) ? group : group ? [group] : []))
      .filter((value) => typeof value === "string" && value.trim())
      .map((value) => value.trim().slice(0, 2_000)),
  )].slice(0, 100);
}

function byteLength(value) {
  if (Buffer.isBuffer(value)) return value.length;
  try {
    return Buffer.byteLength(typeof value === "string" ? value : JSON.stringify(value));
  } catch {
    return 0;
  }
}

function firstNamedValue(value, names, depth = 0) {
  if (!value || depth > 5) return undefined;
  if (Array.isArray(value)) {
    for (const item of value.slice(0, 40)) {
      const found = firstNamedValue(item, names, depth + 1);
      if (found !== undefined) return found;
    }
    return undefined;
  }
  if (!isObject(value)) return undefined;
  for (const [key, item] of Object.entries(value).slice(0, 80)) {
    if (names.has(key.toLowerCase())) return item;
  }
  for (const item of Object.values(value).slice(0, 80)) {
    const found = firstNamedValue(item, names, depth + 1);
    if (found !== undefined) return found;
  }
  return undefined;
}

function mediaTypeFrom(value, fallback = "") {
  if (!isObject(value)) return text(fallback, 300);
  const format = isObject(value.format) ? value.format : {};
  return text(
    value.mediaType
      || value.media_type
      || value.contentType
      || value.content_type
      || format.mediaType
      || format.media_type
      || format.contentType
      || format.content_type
      || fallback,
    300,
  ).toLowerCase();
}

function responseStatus(payload) {
  const parsed = Number(payload?.response?.status_code ?? payload?.response?.statusCode);
  return Number.isInteger(parsed) && parsed >= 100 && parsed <= 599 ? parsed : undefined;
}

function executionFrom(payload, toolName, args, isError) {
  const reported = text(
    firstNamedValue(payload?.data, new Set(["status", "state"]))
      || payload?.execution?.reportedStatus
      || payload?.execution?.state,
    200,
  ).toLowerCase();
  const statusCode = responseStatus(payload);
  let state = "succeeded";
  if (isError || payload?.ok === false || (statusCode && statusCode >= 400) || FAILED_JOB_STATES.has(reported)) {
    state = reported.includes("cancel") || reported === "dismissed" ? "cancelled" : "failed";
  } else if (["accepted", "queued", "submitted"].includes(reported) || [201, 202].includes(statusCode)) {
    state = "submitted";
  } else if (["running", "started", "processing"].includes(reported)) {
    state = "running";
  } else if (TERMINAL_JOB_STATES.has(reported)) {
    state = "succeeded";
  }
  const serverId = text(payload?.server?.id || args?.server_id || payload?.execution?.serverId, 200);
  return {
    state,
    serverId,
    ...(text(args?.process_id || payload?.execution?.processId, 300)
      ? { processId: text(args?.process_id || payload?.execution?.processId, 300) }
      : {}),
    ...(text(args?.plan_id || payload?.execution?.planId, 300)
      ? { planId: text(args?.plan_id || payload?.execution?.planId, 300) }
      : {}),
    ...(text(args?.job_id || payload?.execution?.jobId, 300)
      ? { jobId: text(args?.job_id || payload?.execution?.jobId, 300) }
      : {}),
    ...(reported ? { reportedStatus: reported } : {}),
    ...(toolName ? { sourceTool: text(toolName, 200) } : {}),
  };
}

function manifestFrom(payload) {
  const candidates = [
    payload?.output_manifest,
    payload?.outputManifest,
    payload?.data?.output_manifest,
    payload?.data?.outputManifest,
    payload?.data?.manifest,
  ];
  return candidates.find((candidate) => (
    isObject(candidate)
    && (
      candidate.schemaVersion === OUTPUT_MANIFEST_SCHEMA_VERSION
      || (isObject(candidate.execution) && Array.isArray(candidate.outputs))
    )
  )) || null;
}

function crsObject(value) {
  if (isObject(value)) {
    const status = enumValue(value.status, new Set(["declared", "inferred", "missing", "unsupported"]), "missing");
    return {
      status,
      ...(text(value.value, 300) ? { value: text(value.value, 300) } : {}),
      ...(text(value.axisOrder, 100) ? { axisOrder: text(value.axisOrder, 100) } : {}),
      ...(text(value.nativeValue, 300) ? { nativeValue: text(value.nativeValue, 300) } : {}),
    };
  }
  const label = text(value, 300);
  return label ? { status: "declared", value: label } : { status: "missing" };
}

function normalizeError(value, phase) {
  if (!value) return undefined;
  if (typeof value === "string") {
    return { code: "output_error", message: text(value), ...(phase ? { phase } : {}) };
  }
  if (!isObject(value)) return undefined;
  return {
    code: text(value.code, 200) || "output_error",
    message: text(value.message || value.detail, 2_000) || "The output could not be prepared.",
    ...(text(value.phase || phase, 100) ? { phase: text(value.phase || phase, 100) } : {}),
    ...(typeof value.retryable === "boolean" ? { retryable: value.retryable } : {}),
  };
}

function normalizeRepresentation(value, outputId, index) {
  if (!isObject(value)) return null;
  const mediaType = mediaTypeFrom(value);
  if (!mediaType) return null;
  let inlineData;
  if (value.data !== undefined) {
    try {
      const serialized = JSON.stringify(value.data);
      if (serialized !== undefined && Buffer.byteLength(serialized) <= MAX_INLINE_BYTES) {
        inlineData = value.data;
      }
    } catch {
      // Circular or otherwise non-JSON values cannot cross the SSE boundary.
    }
  }
  return {
    id: identifier(value.id, `${outputId}-representation-${index + 1}`),
    role: enumValue(value.role, new Set(["original", "canonical", "preview", "tiles"]), "original"),
    mediaType,
    ...(text(value.handle, 300) ? { handle: text(value.handle, 300) } : {}),
    ...(Number.isInteger(value.sizeBytes) && value.sizeBytes >= 0 ? { sizeBytes: value.sizeBytes } : {}),
    ...(text(value.encoding, 100) ? { encoding: text(value.encoding, 100) } : {}),
    ...(inlineData !== undefined ? { data: inlineData } : {}),
  };
}

function normalizeUnits(value) {
  if (!Array.isArray(value)) return undefined;
  const units = value.slice(0, 100).flatMap((unit) => {
    if (typeof unit === "string" || typeof unit === "number") {
      const label = text(unit, 200);
      return label ? [{ value: label, status: "declared" }] : [];
    }
    if (!isObject(unit)) return [];
    const quantity = text(unit.quantity, 200);
    const unitValue = text(unit.value, 200);
    const status = enumValue(unit.status, new Set(["declared", "missing"]), unitValue ? "declared" : "missing");
    return [{
      ...(quantity ? { quantity } : {}),
      ...(unitValue ? { value: unitValue } : {}),
      status,
    }];
  });
  return units.length ? units : undefined;
}

function normalizePresentation(value, outputId, index) {
  if (!isObject(value)) return null;
  return {
    id: identifier(value.id, `${outputId}-presentation-${index + 1}`),
    kind: enumValue(value.kind, PRESENTATION_KINDS, "text"),
    state: enumValue(value.state, PRESENTATION_STATES, "unavailable"),
    ...(text(value.artifactRef, 300) ? { artifactRef: text(value.artifactRef, 300) } : {}),
    ...(text(value.reason, 2_000) ? { reason: text(value.reason, 2_000) } : {}),
  };
}

function boundedObservedValue(value) {
  try {
    const encoded = JSON.stringify(value);
    if (!encoded || byteLength(encoded) > 4_000) return undefined;
    return JSON.parse(encoded);
  } catch {
    return undefined;
  }
}

function normalizeClarificationRequest(value) {
  if (!isObject(value) || !Array.isArray(value.issues)) return null;
  const scope = enumValue(
    value.scope,
    new Set(["execution", "interpretation", "presentation"]),
    "interpretation",
  );
  const kinds = new Set([
    "unit",
    "crs",
    "axis_order",
    "input",
    "output_format",
    "presentation",
    "remote_fetch",
  ]);
  const issues = value.issues.slice(0, 100).flatMap((candidate, index) => {
    if (!isObject(candidate)) return [];
    const question = text(candidate.question, 2_000);
    const whyItMatters = text(candidate.whyItMatters, 4_000);
    const fieldPath = text(candidate.fieldPath, 500);
    if (!question || !whyItMatters || !fieldPath) return [];
    const observedValue = boundedObservedValue(candidate.observedValue);
    return [{
      id: identifier(candidate.id, `output-issue-${index + 1}`),
      kind: enumValue(candidate.kind, kinds, "presentation"),
      fieldPath,
      question,
      whyItMatters,
      allowFreeText: candidate.allowFreeText !== false,
      ...(observedValue !== undefined ? { observedValue } : {}),
    }];
  });
  if (!issues.length) return null;
  return {
    blocking: value.blocking === true,
    scope,
    issues,
  };
}

function normalizeCanonicalOutput(value, index, serverId) {
  const raw = isObject(value) ? value : {};
  const id = identifier(raw.id, `output-${index + 1}`);
  const retrieval = isObject(raw.retrieval) ? raw.retrieval : {};
  const interpretation = isObject(raw.interpretation) ? raw.interpretation : {};
  const provenance = isObject(raw.provenance) ? raw.provenance : {};
  const normalizedRetrieval = {
    state: enumValue(retrieval.state, RETRIEVAL_STATES, "pending"),
    source: enumValue(retrieval.source, new Set(["inline", "reference", "memory"]), "inline"),
    ...(text(retrieval.declaredMediaType, 300) ? { declaredMediaType: text(retrieval.declaredMediaType, 300) } : {}),
    ...(text(retrieval.detectedMediaType, 300) ? { detectedMediaType: text(retrieval.detectedMediaType, 300) } : {}),
    ...(Number.isInteger(retrieval.bytes) && retrieval.bytes >= 0 ? { bytes: retrieval.bytes } : {}),
    ...(Number.isInteger(retrieval.httpStatus) && retrieval.httpStatus >= 100 && retrieval.httpStatus <= 599
      ? { httpStatus: retrieval.httpStatus }
      : {}),
    ...(Number.isInteger(retrieval.redirectCount) && retrieval.redirectCount >= 0
      ? { redirectCount: retrieval.redirectCount }
      : {}),
    ...(normalizeError(retrieval.error, "retrieval") ? { error: normalizeError(retrieval.error, "retrieval") } : {}),
  };
  const normalizedInterpretation = {
    state: enumValue(interpretation.state, INTERPRETATION_STATES, "pending"),
    semanticType: enumValue(interpretation.semanticType, SEMANTIC_TYPES, "unknown"),
    ...(text(interpretation.format, 300) ? { format: text(interpretation.format, 300) } : {}),
    crs: crsObject(interpretation.crs),
    ...(Array.isArray(interpretation.bbox) && interpretation.bbox.length === 4
      && interpretation.bbox.every(Number.isFinite)
      ? { bbox: interpretation.bbox }
      : {}),
    ...(Number.isInteger(interpretation.featureCount) && interpretation.featureCount >= 0
      ? { featureCount: interpretation.featureCount }
      : {}),
    ...(Number.isInteger(interpretation.rowCount) && interpretation.rowCount >= 0
      ? { rowCount: interpretation.rowCount }
      : {}),
    ...(Array.isArray(interpretation.geometryTypes)
      ? { geometryTypes: [...new Set(interpretation.geometryTypes.map((item) => text(item, 100)).filter(Boolean))] }
      : {}),
    ...(normalizeUnits(interpretation.units) ? { units: normalizeUnits(interpretation.units) } : {}),
    ...(uniqueWarnings(interpretation.warnings).length
      ? { warnings: uniqueWarnings(interpretation.warnings) }
      : {}),
    ...(normalizeError(interpretation.error, "interpretation")
      ? { error: normalizeError(interpretation.error, "interpretation") }
      : {}),
  };
  return {
    id,
    title: text(raw.title, 500) || titleFor(id),
    ...(text(raw.description, 4_000) ? { description: text(raw.description, 4_000) } : {}),
    status: enumValue(raw.status, OUTPUT_STATES, "pending"),
    retrieval: normalizedRetrieval,
    interpretation: normalizedInterpretation,
    ...(Array.isArray(raw.representations)
      ? {
        representations: raw.representations
          .slice(0, 20)
          .map((item, representationIndex) => normalizeRepresentation(item, id, representationIndex))
          .filter(Boolean),
      }
      : {}),
    presentations: Array.isArray(raw.presentations)
      ? raw.presentations
        .slice(0, 20)
        .map((item, presentationIndex) => normalizePresentation(item, id, presentationIndex))
        .filter(Boolean)
      : [],
    ...(normalizeClarificationRequest(raw.clarificationRequest)
      ? { clarificationRequest: normalizeClarificationRequest(raw.clarificationRequest) }
      : {}),
    provenance: {
      serverId: text(provenance.serverId || serverId, 200),
      ...(text(provenance.requestPath, 2_000) ? { requestPath: text(provenance.requestPath, 2_000) } : {}),
      ...(text(provenance.retrievedAt, 100) ? { retrievedAt: text(provenance.retrievedAt, 100) } : {}),
      ...(text(provenance.parser, 200) ? { parser: text(provenance.parser, 200) } : {}),
      ...(Array.isArray(provenance.transformations)
        ? { transformations: provenance.transformations.slice(0, 100).map((item) => text(item, 300)).filter(Boolean) }
        : {}),
      ...(typeof provenance.sha256 === "string" && /^[a-fA-F0-9]{64}$/.test(provenance.sha256)
        ? { sha256: provenance.sha256 }
        : {}),
    },
    ...(uniqueWarnings(raw.warnings).length ? { warnings: uniqueWarnings(raw.warnings) } : {}),
  };
}

function inlineDataFromCanonicalOutput(output) {
  const values = [];
  if (!isObject(output)) return values;
  for (const key of ["preview", "data", "value"]) {
    if (output[key] !== undefined) values.push(output[key]);
  }
  if (Array.isArray(output.representations)) {
    for (const representation of output.representations.slice(0, 20)) {
      if (!isObject(representation)) continue;
      for (const key of ["data", "value", "content", "preview"]) {
        if (representation[key] !== undefined) values.push(representation[key]);
      }
    }
  }
  for (const presentation of Array.isArray(output.presentations) ? output.presentations : []) {
    if (isObject(presentation?.visualization)) values.push(presentation.visualization);
  }
  return values;
}

function canonicalHydrationBudget(overrides = {}) {
  const bounded = (value, fallback, minimum, maximum) => {
    const parsed = Number(value);
    return Number.isFinite(parsed)
      ? Math.min(maximum, Math.max(minimum, Math.floor(parsed)))
      : fallback;
  };
  return {
    maxFetches: bounded(
      overrides.maxFetches,
      CANONICAL_ARTIFACT_HYDRATION_LIMITS.maxFetches,
      1,
      32,
    ),
    maxTotalBytes: bounded(
      overrides.maxTotalBytes,
      CANONICAL_ARTIFACT_HYDRATION_LIMITS.maxTotalBytes,
      1_024,
      10_000_000,
    ),
    maxElapsedMs: bounded(
      overrides.maxElapsedMs,
      CANONICAL_ARTIFACT_HYDRATION_LIMITS.maxElapsedMs,
      10,
      30_000,
    ),
  };
}

async function callArtifactBeforeDeadline(callTool, handle, remainingMs) {
  let timer;
  const timeout = new Promise((resolve) => {
    timer = setTimeout(() => resolve({ timedOut: true }), Math.max(1, remainingMs));
  });
  const call = Promise.resolve()
    .then(() => callTool(
      "ogc_proxy_artifact_retrieve",
      { handle },
      { timeout: Math.max(1, remainingMs) },
    ))
    .then(
      (result) => ({ result }),
      (error) => ({ error }),
    );
  const settled = await Promise.race([call, timeout]);
  clearTimeout(timer);
  return settled;
}

async function hydrateCanonicalRepresentations(rawManifest, callTool, budgetOverrides = {}) {
  const outputs = Array.isArray(rawManifest?.outputs) ? rawManifest.outputs : [];
  const budget = canonicalHydrationBudget(budgetOverrides);
  const startedAt = Date.now();
  const deadline = startedAt + budget.maxElapsedMs;
  let fetchCount = 0;
  let fetchedBytes = 0;
  let aggregateStopReason = "";
  const hydrationWarnings = [];
  const hydratedOutputs = [];
  for (const output of outputs.slice(0, 100)) {
    if (!isObject(output) || !Array.isArray(output.representations)) {
      hydratedOutputs.push(output);
      continue;
    }
    const outputWarnings = [];
    const presentationHandles = new Set(
      (Array.isArray(output.presentations) ? output.presentations : [])
        .filter((presentation) => presentation?.kind !== "download")
        .map((presentation) => text(presentation?.artifactRef, 300))
        .filter(Boolean),
    );
    const representations = [];
    for (const representation of output.representations.slice(0, 20)) {
      if (!isObject(representation) || representation.data !== undefined) {
        representations.push(representation);
        continue;
      }
      const handle = text(representation.handle, 300);
      const role = text(representation.role, 50).toLowerCase();
      const advertisedSize = Number(representation.sizeBytes);
      const neededForPresentation = presentationHandles.has(handle)
        || ["canonical", "preview", "tiles"].includes(role);
      if (
        !neededForPresentation
        || !/^art_[a-f0-9]{32}$/.test(handle)
      ) {
        representations.push(representation);
        continue;
      }
      const outputId = text(output.id, 300) || "result";
      let skipReason = aggregateStopReason;
      if (!skipReason && fetchCount >= budget.maxFetches) {
        skipReason = `the aggregate fetch limit of ${budget.maxFetches} was reached`;
        aggregateStopReason = skipReason;
      }
      if (!skipReason && Date.now() >= deadline) {
        skipReason = `the aggregate ${budget.maxElapsedMs} ms hydration deadline was reached`;
        aggregateStopReason = skipReason;
      }
      if (
        !skipReason
        && Number.isFinite(advertisedSize)
        && advertisedSize > MAX_INLINE_BYTES
      ) {
        skipReason = `its advertised size exceeds the per-representation limit of ${MAX_INLINE_BYTES} bytes`;
      }
      const remainingByteBudget = budget.maxTotalBytes - fetchedBytes;
      if (!skipReason && remainingByteBudget <= 0) {
        skipReason = `the aggregate byte limit of ${budget.maxTotalBytes} was reached`;
        aggregateStopReason = skipReason;
      }
      if (
        !skipReason
        && Number.isFinite(advertisedSize)
        && advertisedSize > remainingByteBudget
      ) {
        skipReason = `its advertised size exceeds the remaining aggregate byte budget of ${Math.max(0, remainingByteBudget)} bytes`;
      }
      if (skipReason) {
        const warning = `Preview data for output ${outputId} was not hydrated because ${skipReason}.`;
        outputWarnings.push(warning);
        hydrationWarnings.push(warning);
        representations.push(representation);
        continue;
      }

      fetchCount += 1;
      const settled = await callArtifactBeforeDeadline(
        callTool,
        handle,
        deadline - Date.now(),
      );
      if (settled.timedOut || Date.now() > deadline) {
        aggregateStopReason = `the aggregate ${budget.maxElapsedMs} ms hydration deadline was reached`;
        const warning = `Preview data for output ${outputId} was not hydrated because ${aggregateStopReason}.`;
        outputWarnings.push(warning);
        hydrationWarnings.push(warning);
        representations.push(representation);
        continue;
      }
      if (settled.error) {
        const warning = `Preview data for output ${outputId} could not be hydrated safely.`;
        outputWarnings.push(warning);
        hydrationWarnings.push(warning);
        representations.push(representation);
        continue;
      }
      const result = settled.result;
      const payload = structuredToolPayload(result);
      const artifact = artifactRecordFromPayload(payload);
      const dataSize = artifact ? byteLength(artifact.data) : 0;
      fetchedBytes += dataSize;
      if (fetchedBytes >= budget.maxTotalBytes) {
        aggregateStopReason = `the aggregate byte limit of ${budget.maxTotalBytes} was reached`;
      }
      if (
        result?.isError
        || !payload
        || payload.ok === false
        || !artifact
        || dataSize > MAX_INLINE_BYTES
        || fetchedBytes > budget.maxTotalBytes
        || text(artifact.encoding, 100).toLowerCase() === "base64"
      ) {
        const reason = fetchedBytes > budget.maxTotalBytes
          ? `it would exceed the aggregate byte limit of ${budget.maxTotalBytes}`
          : "the retrieved representation was invalid, binary, or over its safe inline limit";
        const warning = `Preview data for output ${outputId} was not hydrated because ${reason}.`;
        outputWarnings.push(warning);
        hydrationWarnings.push(warning);
        representations.push(representation);
        continue;
      }
      representations.push({
        ...representation,
        mediaType: mediaTypeFrom(artifact, mediaTypeFrom(representation)),
        sizeBytes: Number.isInteger(artifact.sizeBytes) ? artifact.sizeBytes : dataSize,
        data: artifact.data,
      });
    }
    hydratedOutputs.push({
      ...output,
      representations,
      ...(uniqueWarnings(output.warnings, outputWarnings).length
        ? { warnings: uniqueWarnings(output.warnings, outputWarnings) }
        : {}),
    });
  }
  if (aggregateStopReason) {
    hydrationWarnings.push(
      `Canonical preview hydration stopped after ${fetchCount} fetch${fetchCount === 1 ? "" : "es"} and ${fetchedBytes} byte${fetchedBytes === 1 ? "" : "s"} because ${aggregateStopReason}.`,
    );
  }
  return {
    manifest: {
      ...rawManifest,
      outputs: hydratedOutputs,
      ...(uniqueWarnings(rawManifest?.warnings, hydrationWarnings).length
        ? { warnings: uniqueWarnings(rawManifest?.warnings, hydrationWarnings) }
        : {}),
    },
    warnings: hydrationWarnings,
  };
}

function normalizeCanonicalManifest(raw, fallbackExecution, manifestId) {
  const execution = isObject(raw.execution) ? raw.execution : {};
  const normalizedExecution = {
    state: enumValue(execution.state, EXECUTION_STATES, fallbackExecution.state),
    serverId: text(execution.serverId || fallbackExecution.serverId, 200),
    ...(text(execution.processId || fallbackExecution.processId, 300)
      ? { processId: text(execution.processId || fallbackExecution.processId, 300) }
      : {}),
    ...(text(execution.planId || fallbackExecution.planId, 300)
      ? { planId: text(execution.planId || fallbackExecution.planId, 300) }
      : {}),
    ...(text(execution.jobId || fallbackExecution.jobId, 300)
      ? { jobId: text(execution.jobId || fallbackExecution.jobId, 300) }
      : {}),
    ...(text(execution.reportedStatus || fallbackExecution.reportedStatus, 200)
      ? { reportedStatus: text(execution.reportedStatus || fallbackExecution.reportedStatus, 200) }
      : {}),
  };
  const outputs = (Array.isArray(raw.outputs) ? raw.outputs : [])
    .slice(0, 100)
    .map((output, index) => normalizeCanonicalOutput(output, index, normalizedExecution.serverId));
  const lifecycleManifestId = normalizedExecution.jobId
    ? identifier(
      `job-${normalizedExecution.serverId || "default"}-${normalizedExecution.jobId}`,
      manifestId,
    )
    : identifier(raw.manifestId, manifestId);
  return {
    schemaVersion: OUTPUT_MANIFEST_SCHEMA_VERSION,
    // A job submission and every later results retrieval must upsert the same
    // UI lifecycle instead of leaving a stale "pending" manifest beside the
    // completed one. Synchronous executions retain the server manifest ID.
    manifestId: lifecycleManifestId,
    execution: normalizedExecution,
    overallState: enumValue(raw.overallState, new Set(["pending", "ready", "partial", "unavailable"]), deriveOverallState(outputs, normalizedExecution)),
    outputs,
    ...(uniqueWarnings(raw.warnings).length ? { warnings: uniqueWarnings(raw.warnings) } : {}),
  };
}

function registeredArtifactHref(handle, sessionId) {
  return `/api/artifacts/${encodeURIComponent(handle)}?sessionId=${encodeURIComponent(sessionId)}`;
}

function registerManifestArtifacts(manifest, sessionId) {
  if (!sessionId || !manifest) return manifest;
  const registered = sessionArtifacts.get(sessionId) || new Map();
  const currentHandles = new Set(
    manifest.outputs
      .flatMap((output) => Array.isArray(output.representations) ? output.representations : [])
      .map((representation) => text(representation?.handle, 300))
      .filter((handle) => /^art_[a-f0-9]{32}$/.test(handle))
      .slice(0, MAX_SESSION_ARTIFACTS),
  );
  const missingCurrentHandles = [...currentHandles].filter((handle) => !registered.has(handle)).length;
  for (const existingHandle of registered.keys()) {
    if (registered.size + missingCurrentHandles <= MAX_SESSION_ARTIFACTS) break;
    if (!currentHandles.has(existingHandle)) registered.delete(existingHandle);
  }
  const outputs = manifest.outputs.map((output) => ({
    ...output,
    ...(Array.isArray(output.representations)
      ? {
        representations: output.representations.map((representation) => {
          const handle = text(representation.handle, 300);
          if (!/^art_[a-f0-9]{32}$/.test(handle)) return representation;
          registered.set(handle, {
            mediaType: representation.mediaType,
            sizeBytes: representation.sizeBytes,
            registeredAt: Date.now(),
          });
          return {
            ...representation,
            href: registeredArtifactHref(handle, sessionId),
          };
        }),
      }
      : {}),
  }));
  sessionArtifacts.set(sessionId, registered);
  return { ...manifest, outputs };
}

export function clearResultArtifactSession(sessionId) {
  sessionArtifacts.delete(sessionId);
}

function artifactRecordFromPayload(payload) {
  if (isObject(payload?.artifact) && payload.data !== undefined) {
    return { ...payload.artifact, data: payload.data };
  }
  if (isObject(payload?.data?.artifact) && payload.data.data !== undefined) {
    return { ...payload.data.artifact, data: payload.data.data };
  }
  const candidates = [
    payload?.artifact,
    payload?.data?.artifact,
    payload?.data,
    payload,
  ];
  return candidates.find((candidate) => (
    isObject(candidate)
    && candidate.data !== undefined
    && mediaTypeFrom(candidate)
  )) || null;
}

/**
 * Retrieve only an opaque artifact previously advertised to this chat session.
 * Upstream URLs are never accepted here.
 */
export async function retrieveSessionArtifact({ sessionId, handle, callTool }) {
  const cleanHandle = text(handle, 300);
  const registered = sessionArtifacts.get(sessionId)?.get(cleanHandle);
  if (!registered || !/^art_[a-f0-9]{32}$/.test(cleanHandle)) {
    return { ok: false, status: 404, error: "Artifact is not available in this session." };
  }
  try {
    const result = await callTool("ogc_proxy_artifact_retrieve", { handle: cleanHandle });
    const payload = structuredToolPayload(result);
    const artifact = artifactRecordFromPayload(payload);
    if (result?.isError || !payload || payload.ok === false || !artifact) {
      return { ok: false, status: 502, error: "The protected artifact could not be retrieved." };
    }
    const advertisedMediaType = mediaTypeFrom(artifact, registered.mediaType);
    const mediaType = /^[a-z0-9!#$&^_.+-]+\/[a-z0-9!#$&^_.+-]+(?:\s*;\s*[a-z0-9!#$&^_.+-]+=[a-z0-9!#$&^_.+:'"-]+)*$/i.test(advertisedMediaType)
      ? advertisedMediaType
      : "application/octet-stream";
    const encoding = text(artifact.encoding, 100).toLowerCase();
    let data = artifact.data;
    if (encoding === "base64") {
      if (typeof data !== "string" || data.length > 20_000_000 || !/^[a-zA-Z0-9+/=\s]*$/.test(data)) {
        return { ok: false, status: 502, error: "The protected binary artifact is invalid or too large." };
      }
      data = Buffer.from(data, "base64");
    } else if (typeof data !== "string" && !Buffer.isBuffer(data)) {
      data = JSON.stringify(data);
    }
    if (byteLength(data) > 15_000_000) {
      return { ok: false, status: 413, error: "The artifact exceeds the gateway download limit." };
    }
    return {
      ok: true,
      status: 200,
      mediaType,
      data,
      filename: `${cleanHandle}.${mediaType.includes("json") ? "json" : mediaType.includes("xml") ? "xml" : "bin"}`,
    };
  } catch {
    return { ok: false, status: 502, error: "The protected artifact retrieval service is unavailable." };
  }
}

function xmlDecode(value) {
  return value
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, "\"")
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, "&");
}

function numericPositions(value, tupleSeparator = /\s+/) {
  const tuples = value.trim().split(tupleSeparator).filter(Boolean);
  const positions = [];
  for (const tuple of tuples) {
    const numbers = tuple.includes(",")
      ? tuple.split(",").map(Number)
      : tuple.trim().split(/\s+/).map(Number);
    if (numbers.length < 2 || !numbers.every(Number.isFinite)) return null;
    positions.push(numbers.slice(0, 3));
  }
  return positions.length ? positions : null;
}

function positionsFromGeometry(xml) {
  const coordinates = xml.match(/<(?:[\w.-]+:)?coordinates\b[^>]*>([\s\S]*?)<\/(?:[\w.-]+:)?coordinates\s*>/i);
  if (coordinates) return numericPositions(xmlDecode(coordinates[1]));
  const posList = xml.match(/<(?:[\w.-]+:)?posList\b([^>]*)>([\s\S]*?)<\/(?:[\w.-]+:)?posList\s*>/i);
  if (posList) {
    const numbers = xmlDecode(posList[2]).trim().split(/\s+/).map(Number);
    const dimension = Number(posList[1].match(/srsDimension\s*=\s*["'](\d+)["']/i)?.[1] || 2);
    if (![2, 3].includes(dimension) || numbers.length < dimension || numbers.length % dimension || !numbers.every(Number.isFinite)) {
      return null;
    }
    const positions = [];
    for (let index = 0; index < numbers.length; index += dimension) {
      positions.push(numbers.slice(index, index + dimension));
    }
    return positions;
  }
  const positions = [...xml.matchAll(/<(?:[\w.-]+:)?pos\b[^>]*>([\s\S]*?)<\/(?:[\w.-]+:)?pos\s*>/gi)]
    .map((match) => match[1].trim().split(/\s+/).map(Number));
  return positions.length && positions.every((position) => position.length >= 2 && position.every(Number.isFinite))
    ? positions.map((position) => position.slice(0, 3))
    : null;
}

function geometryXmlBlocks(xml, localName) {
  const expression = new RegExp(
    `<(?:[\\w.-]+:)?${localName}\\b[^>]*>[\\s\\S]*?<\\/(?:[\\w.-]+:)?${localName}\\s*>`,
    "gi",
  );
  return [...xml.matchAll(expression)].map((match) => match[0]);
}

function gmlGeometry(xml) {
  const polygons = geometryXmlBlocks(xml, "Polygon");
  if (polygons.length) {
    const parsedPolygons = polygons.map((polygon) => {
      const outer = polygon.match(/<(?:[\w.-]+:)?(?:outerBoundaryIs|exterior)\b[^>]*>([\s\S]*?)<\/(?:[\w.-]+:)?(?:outerBoundaryIs|exterior)\s*>/i);
      const outerPositions = positionsFromGeometry(outer?.[1] || polygon);
      if (!outerPositions || outerPositions.length < 3) return null;
      const interiors = [...polygon.matchAll(/<(?:[\w.-]+:)?(?:innerBoundaryIs|interior)\b[^>]*>([\s\S]*?)<\/(?:[\w.-]+:)?(?:innerBoundaryIs|interior)\s*>/gi)]
        .map((match) => positionsFromGeometry(match[1]))
        .filter((ring) => ring?.length >= 3);
      return [outerPositions, ...interiors];
    }).filter(Boolean);
    if (!parsedPolygons.length) return null;
    return parsedPolygons.length === 1
      ? { type: "Polygon", coordinates: parsedPolygons[0] }
      : { type: "MultiPolygon", coordinates: parsedPolygons };
  }
  const lines = geometryXmlBlocks(xml, "LineString")
    .map(positionsFromGeometry)
    .filter((positions) => positions?.length >= 2);
  if (lines.length) {
    return lines.length === 1
      ? { type: "LineString", coordinates: lines[0] }
      : { type: "MultiLineString", coordinates: lines };
  }
  const points = geometryXmlBlocks(xml, "Point")
    .map(positionsFromGeometry)
    .filter((positions) => positions?.length)
    .map((positions) => positions[0]);
  if (points.length) {
    return points.length === 1
      ? { type: "Point", coordinates: points[0] }
      : { type: "MultiPoint", coordinates: points };
  }
  return null;
}

function simpleGmlProperties(member) {
  const properties = {};
  for (const match of member.matchAll(/<(?:[\w.-]+:)?([\w.-]+)\b[^>]*>([^<]{1,1000})<\/(?:[\w.-]+:)?\1\s*>/gi)) {
    const key = match[1];
    if (/^(?:coordinates|pos|posList|X|Y)$/i.test(key) || Object.keys(properties).length >= 40) continue;
    properties[key] = xmlDecode(match[2].trim()).slice(0, 1_000);
  }
  return properties;
}

/** Parse the bounded, common GML Simple Features subset used by OGC process outputs. */
export function parseEmbeddedGml(value) {
  if (typeof value !== "string" || !value.trim() || byteLength(value) > MAX_INLINE_BYTES) {
    return { ok: false, error: "GML output is empty or exceeds the browser-preview limit." };
  }
  if (/<!DOCTYPE|<!ENTITY|<\?xml-stylesheet/i.test(value)) {
    return { ok: false, error: "Unsafe XML declarations are not accepted for preview." };
  }
  if (!/<(?:[\w.-]+:)?(?:FeatureCollection|featureMember|Point|LineString|Polygon)\b/i.test(value)) {
    return { ok: false, error: "The XML is not a supported GML feature document." };
  }
  const memberBlocks = geometryXmlBlocks(value, "featureMember");
  const sources = memberBlocks.length ? memberBlocks : [value];
  const features = [];
  for (const source of sources.slice(0, 2_000)) {
    const geometry = gmlGeometry(source);
    if (!geometry) continue;
    const id = source.match(/\b(?:fid|gml:id)\s*=\s*["']([^"']+)["']/i)?.[1];
    features.push({
      type: "Feature",
      ...(id ? { id: id.slice(0, 300) } : {}),
      properties: simpleGmlProperties(source),
      geometry,
    });
  }
  if (!features.length) {
    return { ok: false, error: "No supported GML Point, LineString, or Polygon geometry was found." };
  }
  const crs = value.match(/\bsrsName\s*=\s*["']([^"']+)["']/i)?.[1] || "";
  const warnings = [];
  if (/EPSG(?::|\/0\/)4326/i.test(crs)) {
    warnings.push("GML coordinates were interpreted in the order supplied by the service; the native EPSG:4326 identifier was preserved.");
  }
  if (memberBlocks.length > 2_000) warnings.push("Only the first 2,000 GML feature members were prepared for preview.");
  return {
    ok: true,
    data: { type: "FeatureCollection", features },
    crs,
    warnings,
  };
}

function detectedMediaType(value, declared = "") {
  const normalized = text(declared, 300).toLowerCase().split(";")[0];
  if (isObject(value) && ["Feature", "FeatureCollection"].includes(value.type)) return "application/geo+json";
  if (isObject(value) && typeof value.type === "string" && /^(?:Point|MultiPoint|LineString|MultiLineString|Polygon|MultiPolygon|GeometryCollection)$/.test(value.type)) {
    return "application/geo+json";
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (/^<\?xml|^<(?:[\w.-]+:)?(?:FeatureCollection|featureMember|Point|LineString|Polygon)\b/i.test(trimmed)) {
      return /<(?:[\w.-]+:)?(?:FeatureCollection|featureMember|Point|LineString|Polygon)\b/i.test(trimmed)
        ? "application/gml+xml"
        : "application/xml";
    }
    if (/^<!doctype\s+html|^<html\b/i.test(trimmed)) return "text/html";
    if (/^(?:SRID=\d+;)?(?:POINT|MULTIPOINT|LINESTRING|MULTILINESTRING|POLYGON|MULTIPOLYGON|GEOMETRYCOLLECTION)\s*[\s(]/i.test(trimmed)) {
      return "application/wkt";
    }
    if (["{", "["].includes(trimmed[0])) {
      try {
        JSON.parse(trimmed);
        return normalized.includes("geo+json") ? "application/geo+json" : "application/json";
      } catch {
        // Keep the declared media type for malformed JSON.
      }
    }
    if (normalized.startsWith("text/")) return normalized;
    return normalized || "text/plain";
  }
  if (Array.isArray(value) || isObject(value)) return normalized || "application/json";
  if (typeof value === "number" || typeof value === "boolean") return normalized || "text/plain";
  return normalized || "application/octet-stream";
}

function geometryFacts(visualization) {
  return {
    ...(visualization?.crs ? { crs: { status: "inferred", value: visualization.crs } } : {}),
    ...(Array.isArray(visualization?.bounds) ? { bbox: visualization.bounds } : {}),
    ...(Number.isInteger(visualization?.stats?.featureCount)
      ? { featureCount: visualization.stats.featureCount }
      : {}),
    ...(isObject(visualization?.stats?.geometryTypes)
      ? { geometryTypes: Object.keys(visualization.stats.geometryTypes) }
      : {}),
  };
}

function interpretValue(value, declaredMediaType) {
  const mediaType = detectedMediaType(value, declaredMediaType);
  let previewData = value;
  const warnings = [];
  let parser = "gateway-format-registry";
  let nativeCrs = "";
  if (typeof value === "string" && mediaType === "application/gml+xml") {
    const parsed = parseEmbeddedGml(value);
    if (!parsed.ok) {
      return {
        previewData: null,
        parser: "gateway-gml-simple-features",
        nativeCrs: "",
        interpretation: {
          state: "failed",
          semanticType: "vector",
          format: mediaType,
          crs: { status: "missing" },
          error: { code: "gml_parse_failed", message: parsed.error, phase: "interpretation" },
        },
        warnings,
      };
    }
    previewData = parsed.data;
    parser = "gateway-gml-simple-features";
    nativeCrs = parsed.crs;
    warnings.push(...parsed.warnings);
  } else if (typeof value === "string" && mediaType === "application/json") {
    try {
      previewData = JSON.parse(value);
      parser = "gateway-json";
    } catch {
      return {
        previewData: null,
        parser: "gateway-json",
        interpretation: {
          state: "failed",
          semanticType: "unknown",
          format: mediaType,
          crs: { status: "missing" },
          error: { code: "json_parse_failed", message: "The declared JSON output is malformed.", phase: "interpretation" },
        },
        warnings,
      };
    }
  }
  let semanticType = "unknown";
  let state = "recognized";
  if (mediaType.includes("gml") || mediaType.includes("geo+json") || mediaType.includes("wkt")) semanticType = "vector";
  else if (mediaType.startsWith("image/")) semanticType = "image";
  else if (/geotiff|tiff/.test(mediaType)) semanticType = "raster";
  else if (/coverage/.test(mediaType) || String(previewData?.type).toLowerCase() === "coverage") semanticType = "coverage";
  else if (/tile|mvt/.test(mediaType)) semanticType = "tiles";
  else if (typeof previewData === "number" || typeof previewData === "boolean" || typeof previewData === "string" && mediaType === "text/plain") {
    semanticType = "scalar";
  } else if (Array.isArray(previewData)) {
    semanticType = "table";
  } else if (isObject(previewData)) {
    if (["Feature", "FeatureCollection"].includes(previewData.type)
      || /^(?:Point|MultiPoint|LineString|MultiLineString|Polygon|MultiPolygon|GeometryCollection)$/.test(previewData.type || "")) {
      semanticType = "vector";
    } else {
      semanticType = "table";
    }
  } else if (mediaType.startsWith("text/") || mediaType.includes("xml") || mediaType.includes("html")) {
    semanticType = "document";
  } else if (mediaType === "application/octet-stream") {
    semanticType = "binary";
    state = "unsupported";
  } else {
    state = "unsupported";
  }
  return {
    previewData,
    parser,
    nativeCrs: nativeCrs || "",
    warnings,
    interpretation: {
      state,
      semanticType,
      format: mediaType,
      crs: { status: "missing" },
      ...(semanticType === "table" && Array.isArray(previewData) ? { rowCount: previewData.length } : {}),
    },
  };
}

function unwrapValue(value, inheritedMediaType = "") {
  let current = value;
  let declaredMediaType = mediaTypeFrom(value, inheritedMediaType);
  let encoding = isObject(value) ? text(value.encoding || value.format?.encoding, 100) : "";
  for (let depth = 0; depth < 5 && isObject(current) && Object.prototype.hasOwnProperty.call(current, "value"); depth += 1) {
    declaredMediaType = mediaTypeFrom(current, declaredMediaType);
    encoding = text(current.encoding || current.format?.encoding || encoding, 100);
    current = current.value;
  }
  return { value: current, declaredMediaType, encoding };
}

function outputContainer(payload) {
  const data = payload?.data;
  if (isObject(data?.outputs)) return data.outputs;
  if (isObject(payload?.outputs)) return payload.outputs;
  if (isObject(data) && data.boundary === "tool_result_data_only" && data.summary !== undefined) return data.summary;
  return data;
}

function legacyCandidates(payload) {
  const container = outputContainer(payload);
  if (container === undefined || container === null) return [];
  if (
    typeof container === "string"
    && byteLength(container) <= MAX_INLINE_BYTES
    && ["{", "["].includes(container.trim()[0])
  ) {
    try {
      const parsed = JSON.parse(container);
      return legacyCandidates({ ...payload, data: parsed });
    } catch {
      // Malformed JSON is handled explicitly by the interpretation registry.
    }
  }
  if (isObject(container) && !["Feature", "FeatureCollection"].includes(container.type)) {
    if (text(container.href, 8_192) && !Object.prototype.hasOwnProperty.call(container, "value")) {
      return [{
        id: "result",
        title: "Referenced process output",
        value: undefined,
        declaredMediaType: mediaTypeFrom(container, payload?.response?.content_type),
        referenceOnly: true,
      }];
    }
    const entries = Object.entries(container);
    const wrapped = entries.filter(([, value]) => (
      isObject(value)
      && (
        Object.prototype.hasOwnProperty.call(value, "value")
        || mediaTypeFrom(value)
        || value.href
      )
    ));
    if (wrapped.length) {
      return wrapped.slice(0, 100).map(([key, raw]) => {
        const unwrapped = unwrapValue(raw);
        return {
          id: identifier(key),
          title: titleFor(key),
          ...unwrapped,
          referenceOnly: Boolean(raw.href && !Object.prototype.hasOwnProperty.call(raw, "value")),
        };
      });
    }
  }
  const unwrapped = unwrapValue(container, payload?.response?.content_type);
  return [{ id: "result", title: "Process output", ...unwrapped }];
}

function presentationForSemantic(outputId, semanticType, visualization, interpretationState, artifactRef = "") {
  if (semanticType === "vector" || semanticType === "coverage" || semanticType === "tiles" || semanticType === "raster") {
    const presentations = [{
      id: `${outputId}-map`,
      kind: "map",
      state: visualization ? "ready" : interpretationState === "pending" ? "preparing" : "unavailable",
      ...(visualization ? { ...(artifactRef ? { artifactRef } : {}) } : {
        reason: interpretationState === "failed"
          ? "The spatial output could not be interpreted safely."
          : "No browser-safe drawable layer was produced.",
      }),
    }];
    if (semanticType === "vector" && visualization) {
      presentations.push({
        id: `${outputId}-table`,
        kind: "table",
        state: "ready",
        ...(artifactRef ? { artifactRef } : {}),
      });
    }
    return presentations;
  }
  const kind = semanticType === "table"
    ? "table"
    : semanticType === "timeseries"
      ? "chart"
      : semanticType === "scalar"
        ? "metric"
        : semanticType === "image"
          ? "image"
          : "text";
  return [{
    id: `${outputId}-${kind}`,
    kind,
    state: interpretationState === "recognized" ? "ready" : "unavailable",
    ...(interpretationState === "recognized" && artifactRef ? { artifactRef } : {}),
    ...(interpretationState === "recognized" ? {} : { reason: "This output format is not supported for an inline preview." }),
  }];
}

function outputState(retrieval, interpretation, presentations) {
  if (retrieval.state === "failed" || interpretation.state === "failed") return "failed";
  if (retrieval.state === "blocked") return "blocked";
  if (["pending", "resolving"].includes(retrieval.state) || interpretation.state === "pending") return "pending";
  if (interpretation.state === "ambiguous") return "unresolved";
  if (interpretation.state === "unsupported") return "unsupported";
  if (!presentations.length) return "partial";
  const hasReadyPresentation = presentations.some((item) => ["ready", "partial"].includes(item.state));
  const hasIncompletePresentation = presentations.some((item) => ["partial", "unavailable"].includes(item.state));
  if (
    retrieval.state === "partial"
    || hasIncompletePresentation
    || (presentations.length > 0 && !hasReadyPresentation)
  ) return "partial";
  return "ready";
}

function monotonicOutputState(trustedState, verifiedState) {
  if (["failed", "blocked", "unsupported", "unresolved"].includes(trustedState)) return trustedState;
  if (trustedState === "pending") return "pending";
  if (trustedState === "empty") {
    return ["failed", "blocked", "unsupported", "unresolved", "pending"].includes(verifiedState)
      ? verifiedState
      : "empty";
  }
  if (trustedState === "partial" && ["ready", "empty"].includes(verifiedState)) return "partial";
  return verifiedState;
}

function deriveOverallState(outputs, execution) {
  if (["submitted", "running", "awaiting_input", "awaiting_approval"].includes(execution.state)) return "pending";
  if (execution.state === "failed" || execution.state === "cancelled") return "unavailable";
  if (!outputs.length) return "unavailable";
  if (outputs.every((output) => output.status === "ready" || output.status === "empty")) return "ready";
  if (outputs.some((output) => output.status === "pending")) return "pending";
  if (outputs.some((output) => ["ready", "partial", "unresolved"].includes(output.status))) return "partial";
  if (outputs.some((output) => ["retrieved", "partial"].includes(output.retrieval?.state))) {
    // A safely retrieved representation remains a real partial result even
    // when its semantics or browser presentation are unsupported.
    return "partial";
  }
  return "unavailable";
}

function monotonicOverallState(trustedState, verifiedState) {
  if (trustedState === "unavailable") return "unavailable";
  if (trustedState === "pending") return verifiedState === "unavailable" ? "unavailable" : "pending";
  if (trustedState === "partial" && verifiedState === "ready") return "partial";
  return verifiedState;
}

function validVisualization(value) {
  return isObject(value) && Array.isArray(value.layers) && value.layers.length > 0;
}

function browserSafeVisualization(value) {
  if (!validVisualization(value)) return null;
  const layers = value.layers.filter((layer) => {
    if (!isObject(layer)) return false;
    if (isObject(layer.data)) return true;
    return typeof layer.href === "string"
      && /^data:image\/(?:png|jpeg|webp|gif);base64,[a-z0-9+/=\s]+$/i.test(layer.href);
  });
  if (!layers.length) return null;
  const removed = value.layers.length - layers.length;
  return {
    ...value,
    layers,
    ...(removed ? {
      warnings: uniqueWarnings(
        value.warnings,
        `${removed} external browser-fetch layer${removed === 1 ? " was" : "s were"} withheld; use a controlled artifact representation instead.`,
      ),
    } : {}),
    stats: {
      ...(value.stats || {}),
      layerCount: layers.length,
    },
  };
}

function directVisualization(rawManifest, payload) {
  const candidates = [
    rawManifest?.visualization,
    rawManifest?.map,
    payload?.visualization,
    payload?.map_data?.visualization,
  ];
  for (const output of Array.isArray(rawManifest?.outputs) ? rawManifest.outputs : []) {
    for (const presentation of Array.isArray(output?.presentations) ? output.presentations : []) {
      candidates.push(presentation?.visualization);
    }
  }
  return candidates.find(validVisualization) || null;
}

function directVisualizationForOutput(output) {
  const candidates = [output?.visualization, output?.map];
  for (const presentation of Array.isArray(output?.presentations) ? output.presentations : []) {
    candidates.push(presentation?.visualization);
  }
  return candidates.find(validVisualization) || null;
}

function visualizationFromPreviews(previews, options) {
  if (!previews.length) return null;
  try {
    const visualization = buildMapVisualization(
      { outputs: Object.fromEntries(previews.map((preview) => [preview.id, preview.data])) },
      options,
    );
    return browserSafeVisualization(visualization);
  } catch {
    return null;
  }
}

function representationForPresentation(output, presentation) {
  const representations = Array.isArray(output.representations) ? output.representations : [];
  const artifactRef = text(presentation?.artifactRef, 300);
  if (artifactRef) {
    const exact = representations.find((representation) => (
      representation.id === artifactRef || representation.handle === artifactRef
    ));
    if (exact) return exact;
    return null;
  }
  const preferredRoles = presentation?.kind === "download"
    ? ["original", "canonical", "preview", "tiles"]
    : ["preview", "canonical", "tiles", "original"];
  return preferredRoles
    .flatMap((role) => representations.filter((representation) => representation.role === role))[0]
    || representations[0]
    || null;
}

function hasBoundedNumericSeries(value) {
  if (!Array.isArray(value) || value.length < 2) return false;
  const rows = value.slice(0, 80);
  if (rows.every((item) => typeof item === "number" && Number.isFinite(item))) return true;
  if (!rows.every((item) => isObject(item))) return false;
  const keys = [...new Set(rows.flatMap((row) => Object.keys(row)))].slice(0, 30);
  return keys.some((key) =>
    rows.some((row) => typeof row[key] === "number" && Number.isFinite(row[key]))
  );
}

function nonMapPresentationRenderable(output, presentation) {
  const representation = representationForPresentation(output, presentation);
  const data = representation?.data;
  const hasProtectedHandle = /^art_[a-f0-9]{32}$/.test(text(representation?.handle, 300));
  switch (presentation.kind) {
    case "download":
      return hasProtectedHandle;
    case "table":
      return Array.isArray(data)
        || (isObject(data) && (Array.isArray(data.features) || Array.isArray(data.rows)));
    case "chart":
      return hasBoundedNumericSeries(data);
    case "metric":
      return data !== undefined;
    case "text":
      return data !== undefined;
    case "image":
      return (
        hasProtectedHandle
        && /^image\/(?:png|jpeg|webp|gif|avif)$/i.test(text(representation?.mediaType, 100))
      ) || (
        typeof data === "string"
        && /^data:image\/(?:png|jpeg|webp|gif|avif);base64,[a-z0-9+/=\s]+$/i.test(data)
      );
    default:
      return false;
  }
}

function verifyNonMapPresentations(output) {
  return output.presentations
    .filter((presentation) => presentation.kind !== "map")
    .map((presentation) => {
      const renderable = nonMapPresentationRenderable(output, presentation);
      if (presentation.state === "unavailable") return presentation;
      if (renderable) {
        return {
          ...presentation,
          state: presentation.state === "partial" ? "partial" : "ready",
        };
      }
      if (
        presentation.state === "preparing"
        && (
          output.interpretation.state === "pending"
          || ["pending", "resolving"].includes(output.retrieval.state)
        )
      ) return presentation;
      return {
        ...presentation,
        state: "unavailable",
        reason: presentation.reason || "No bounded browser-safe representation is available for this presentation.",
      };
    });
}

function applyBrowserPresentation(manifest, visualizationsByOutput) {
  return {
    ...manifest,
    outputs: manifest.outputs.map((output) => {
      const spatial = ["vector", "coverage", "tiles", "raster"].includes(output.interpretation.semanticType);
      const verifiedNonMap = verifyNonMapPresentations(output);
      if (!spatial) {
        const verifiedState = outputState(
          output.retrieval,
          output.interpretation,
          verifiedNonMap,
        );
        return {
          ...output,
          presentations: verifiedNonMap,
          status: monotonicOutputState(output.status, verifiedState),
        };
      }
      const verifiedVisualization = visualizationsByOutput.get(output.id) || null;
      const existingMap = output.presentations.find((presentation) => presentation.kind === "map");
      const advertisedArtifactRef = text(existingMap?.artifactRef, 300);
      const advertisedRepresentation = advertisedArtifactRef
        ? output.representations?.find((representation) => (
          representation.id === advertisedArtifactRef
          || representation.handle === advertisedArtifactRef
        ))
        : null;
      const fallbackRepresentation = advertisedArtifactRef
        ? null
        : representationForPresentation(output, { kind: "map" });
      const mapRepresentation = advertisedRepresentation || fallbackRepresentation;
      const realArtifactRef = advertisedArtifactRef
        || text(mapRepresentation?.handle || mapRepresentation?.id, 300);
      const danglingArtifactRef = Boolean(advertisedArtifactRef && !advertisedRepresentation);
      const trustedMapState = existingMap?.state;
      const state = danglingArtifactRef
        ? "unavailable"
        : verifiedVisualization && realArtifactRef
          ? trustedMapState === "unavailable"
            ? "unavailable"
            : trustedMapState === "partial"
              ? "partial"
              : "ready"
          : output.interpretation.state === "pending" || trustedMapState === "preparing"
            ? "preparing"
            : "unavailable";
      const map = {
        id: existingMap?.id || `${output.id}-map`,
        kind: "map",
        state,
        ...(verifiedVisualization && state !== "unavailable" && realArtifactRef && !danglingArtifactRef
          ? {
            artifactRef: realArtifactRef,
            ...(existingMap?.reason ? { reason: existingMap.reason } : {}),
          }
          : {
            reason: danglingArtifactRef
              ? `The advertised artifact reference “${advertisedArtifactRef}” does not match a stored representation.`
              : existingMap?.reason || (
                !realArtifactRef
                  ? "No stored representation is available for this map presentation."
                  : "No validated browser-safe drawable layer is available for this output."
              ),
          }),
      };
      const presentations = [...verifiedNonMap, map];
      const verifiedState = outputState(output.retrieval, output.interpretation, presentations);
      return {
        ...output,
        presentations,
        status: monotonicOutputState(output.status, verifiedState),
      };
    }),
  };
}

function legacyRedirectOutput(payload, execution, manifestId) {
  const location = text(payload?.response?.location || payload?.guidance?.location, 8_192);
  const declaredMediaType = text(payload?.response?.content_type, 300);
  const retrieval = {
    state: "resolving",
    source: "reference",
    ...(declaredMediaType ? { declaredMediaType } : {}),
    ...(responseStatus(payload) ? { httpStatus: responseStatus(payload) } : {}),
    redirectCount: 1,
  };
  const interpretation = {
    state: "pending",
    semanticType: "unknown",
    crs: { status: "missing" },
  };
  const presentations = [{
    id: "result-text",
    kind: "text",
    state: "preparing",
    reason: "The upstream service returned an output reference that has not been resolved by the trusted server.",
  }];
  const output = {
    id: "result",
    title: "Referenced process output",
    description: "The process response points to a separate output representation.",
    status: "pending",
    retrieval,
    interpretation,
    representations: [{
      id: "result-original",
      role: "original",
      mediaType: declaredMediaType || "application/octet-stream",
    }],
    presentations,
    provenance: {
      serverId: execution.serverId,
      ...(text(payload?.request?.path, 2_000) ? { requestPath: text(payload.request.path, 2_000) } : {}),
    },
    warnings: ["Execution may have succeeded, but the referenced output has not yet been retrieved or interpreted."],
  };
  return {
    schemaVersion: OUTPUT_MANIFEST_SCHEMA_VERSION,
    manifestId,
    execution: { ...execution, state: execution.state === "failed" ? "failed" : "succeeded" },
    overallState: "pending",
    outputs: [output],
    warnings: ["An HTTP redirect is an output reference, not a retrieved process result."],
  };
}

async function hydrateProxyMemory(payload, toolName, callTool) {
  const handle = toolName === "ogc_proxy_memory_retrieve" ? "" : findMemoryHandle(payload);
  if (!handle) return { payload, source: "inline", partial: payload?.has_more === true };
  try {
    const result = await callTool("ogc_proxy_memory_retrieve", {
      handle,
      offset: 0,
      limit: HYDRATION_LIMIT,
    });
    const hydrated = structuredToolPayload(result);
    if (result?.isError || !hydrated || hydrated.ok === false) {
      return {
        payload,
        source: "memory",
        failed: true,
        error: "The stored output could not be retrieved from proxy memory.",
      };
    }
    return {
      payload: hydrated,
      source: "memory",
      partial: hydrated.has_more === true,
      handle,
    };
  } catch {
    return {
      payload,
      source: "memory",
      failed: true,
      error: "The stored output could not be retrieved from proxy memory.",
    };
  }
}

function manifestIdFor(activityId, args, payload) {
  return identifier(
    args?.job_id
      ? `job-${payload?.server?.id || args.server_id || "default"}-${args.job_id}`
      : `manifest-${activityId || "result"}`,
    "manifest-result",
  );
}

function mapIdFor(toolName, args, activityId, payload, suffix = "") {
  const base = toolName === "ogc_jobs_get_results" && args?.job_id
    ? `job-${payload?.server?.id || args.server_id || "default"}-${args.job_id}-map`
    : `${activityId || "result"}-map`;
  return identifier(suffix ? `${base}-${suffix}` : base, "result-map");
}

/**
 * Convert canonical or legacy MCP process output into one verified manifest.
 * Reference fetching deliberately remains a standardized-server responsibility:
 * this gateway only hydrates its bounded proxy-memory API.
 */
export async function prepareResultArtifacts({
  toolName,
  args = {},
  activityId,
  result,
  callTool,
  sessionId = "",
  artifactHydrationBudget = undefined,
}) {
  let originalPayload = structuredToolPayload(result);
  if (!originalPayload && MAP_SOURCE_TOOLS.has(toolName)) {
    const fallbackText = Array.isArray(result?.content)
      ? result.content
        .filter((item) => item?.type === "text" && typeof item.text === "string")
        .map((item) => item.text)
        .join("\n")
        .slice(0, MAX_INLINE_BYTES)
      : "";
    originalPayload = {
      ok: !result?.isError,
      operation: toolName,
      data: fallbackText,
      ...(result?.isError ? { error: fallbackText || "The output tool returned an unstructured error." } : {}),
    };
  }
  if (!originalPayload || (!MAP_SOURCE_TOOLS.has(toolName) && !manifestFrom(originalPayload))) return null;
  const manifestId = manifestIdFor(activityId, args, originalPayload);
  const fallbackExecution = executionFrom(originalPayload, toolName, args, Boolean(result?.isError));
  const rawCanonical = manifestFrom(originalPayload);

  if (rawCanonical) {
    const hydratedCanonical = await hydrateCanonicalRepresentations(
      rawCanonical,
      callTool,
      artifactHydrationBudget,
    );
    const browserCanonical = hydratedCanonical.manifest;
    const canonicalOutputs = Array.isArray(browserCanonical.outputs) ? browserCanonical.outputs : [];
    const previews = canonicalOutputs.flatMap((output, index) => (
      inlineDataFromCanonicalOutput(output).map((data) => ({
        id: identifier(output?.id, `output-${index + 1}`),
        data,
      }))
    ));
    const visualizationsByOutput = new Map();
    canonicalOutputs.forEach((output, index) => {
      const outputId = identifier(output?.id, `output-${index + 1}`);
      const outputPreviews = inlineDataFromCanonicalOutput(output).map((data) => ({
        id: outputId,
        data,
      }));
      const direct = browserSafeVisualization(directVisualizationForOutput(output));
      const singleOutputDirect = canonicalOutputs.length === 1
        ? browserSafeVisualization(directVisualization(browserCanonical, originalPayload))
        : null;
      const verified = direct || singleOutputDirect || visualizationFromPreviews(outputPreviews, {
        id: mapIdFor(
          toolName,
          args,
          activityId,
          originalPayload,
          canonicalOutputs.length > 1 ? outputId : "",
        ),
        title: text(output?.title, 500) || (args?.job_id ? `Job ${args.job_id} result` : "Geospatial result"),
        sourceTool: toolName,
        baseUrl: originalPayload.server?.base_url,
      });
      if (verified) visualizationsByOutput.set(outputId, verified);
    });
    let manifest = normalizeCanonicalManifest(browserCanonical, fallbackExecution, manifestId);
    const trustedOverallState = manifest.overallState;
    manifest = applyBrowserPresentation(manifest, visualizationsByOutput);
    const presentableOutputIds = new Set(
      manifest.outputs
        .filter((output) => output.presentations.some((presentation) => (
          presentation.kind === "map" && ["ready", "partial"].includes(presentation.state)
        )))
        .map((output) => output.id),
    );
    const presentableVisualizations = [...visualizationsByOutput.entries()]
      .filter(([outputId]) => presentableOutputIds.has(outputId));
    let visualization = presentableVisualizations.length === 1
      ? presentableVisualizations[0][1]
      : presentableVisualizations.length > 1
        ? visualizationFromPreviews(
          previews.filter((preview) => presentableOutputIds.has(preview.id)),
          {
            id: mapIdFor(toolName, args, activityId, originalPayload),
            title: args?.job_id ? `Job ${args.job_id} result` : "Geospatial result",
            sourceTool: toolName,
            baseUrl: originalPayload.server?.base_url,
          },
        )
        : null;
    visualization = browserSafeVisualization(visualization);
    manifest.overallState = monotonicOverallState(
      trustedOverallState,
      deriveOverallState(manifest.outputs, manifest.execution),
    );
    const registeredManifest = registerManifestArtifacts(manifest, sessionId);
    return {
      manifest: registeredManifest,
      visualization,
      modelContext: compactVerifiedResultContext(registeredManifest),
      artifactEvents: artifactStatusEvents(registeredManifest),
    };
  }

  const statusCode = responseStatus(originalPayload);
  if (statusCode && statusCode >= 300 && statusCode < 400 && text(originalPayload?.response?.location || originalPayload?.guidance?.location)) {
    const manifest = legacyRedirectOutput(originalPayload, fallbackExecution, manifestId);
    const registeredManifest = registerManifestArtifacts(manifest, sessionId);
    return {
      manifest: registeredManifest,
      visualization: null,
      modelContext: compactVerifiedResultContext(registeredManifest),
      artifactEvents: artifactStatusEvents(registeredManifest),
    };
  }

  const hydrated = await hydrateProxyMemory(originalPayload, toolName, callTool);
  const effectivePayload = hydrated.payload;
  const execution = executionFrom(originalPayload, toolName, args, Boolean(result?.isError));
  if (hydrated.failed) {
    const output = {
      id: "result",
      title: "Process output",
      status: "failed",
      retrieval: {
        state: "failed",
        source: "memory",
        error: { code: "memory_retrieval_failed", message: hydrated.error, phase: "retrieval", retryable: true },
      },
      interpretation: { state: "pending", semanticType: "unknown", crs: { status: "missing" } },
      presentations: [{
        id: "result-text",
        kind: "text",
        state: "unavailable",
        reason: "Output retrieval must succeed before a preview can be prepared.",
      }],
      provenance: { serverId: execution.serverId },
    };
    const manifest = {
      schemaVersion: OUTPUT_MANIFEST_SCHEMA_VERSION,
      manifestId,
      execution,
      overallState: "unavailable",
      outputs: [output],
      warnings: [hydrated.error],
    };
    const registeredManifest = registerManifestArtifacts(manifest, sessionId);
    return {
      manifest: registeredManifest,
      visualization: null,
      modelContext: compactVerifiedResultContext(registeredManifest),
      artifactEvents: artifactStatusEvents(registeredManifest),
    };
  }

  const candidates = legacyCandidates(effectivePayload);
  const prepared = candidates.map((candidate) => {
    if (candidate.referenceOnly) {
      const retrieval = {
        state: "resolving",
        source: "reference",
        ...(candidate.declaredMediaType ? { declaredMediaType: candidate.declaredMediaType } : {}),
      };
      const interpretation = {
        state: "pending",
        semanticType: "unknown",
        crs: { status: "missing" },
      };
      const presentations = [{
        id: `${candidate.id}-text`,
        kind: "text",
        state: "preparing",
        reason: "The trusted standardized server must resolve this output reference before it can be presented.",
      }];
      return {
        output: {
          id: candidate.id,
          title: candidate.title,
          status: "pending",
          retrieval,
          interpretation,
          representations: [{
            id: `${candidate.id}-original`,
            role: "original",
            mediaType: candidate.declaredMediaType || "application/octet-stream",
          }],
          presentations,
          provenance: {
            serverId: execution.serverId,
            ...(text(originalPayload?.request?.path, 2_000)
              ? { requestPath: text(originalPayload.request.path, 2_000) }
              : {}),
          },
          warnings: ["An output reference was returned, but the gateway did not expose or fetch its upstream URL."],
        },
        visualization: null,
      };
    }
    const declaredMediaType = candidate.declaredMediaType
      || text(effectivePayload?.response?.content_type || originalPayload?.response?.content_type, 300);
    const interpretationResult = interpretValue(candidate.value, declaredMediaType);
    const retrieval = {
      state: hydrated.partial ? "partial" : "retrieved",
      source: hydrated.source,
      ...(declaredMediaType ? { declaredMediaType } : {}),
      detectedMediaType: interpretationResult.interpretation.format,
      bytes: byteLength(candidate.value),
      ...(responseStatus(originalPayload) ? { httpStatus: responseStatus(originalPayload) } : {}),
    };
    const localVisualization = visualizationFromPreviews(
      interpretationResult.previewData === null ? [] : [{ id: candidate.id, data: interpretationResult.previewData }],
      {
        id: mapIdFor(
          toolName,
          args,
          activityId,
          originalPayload,
          candidates.length > 1 ? candidate.id : "",
        ),
        title: args?.job_id ? `Job ${args.job_id} result` : candidate.title,
        sourceTool: toolName,
        baseUrl: originalPayload.server?.base_url,
      },
    );
    const interpretation = {
      ...interpretationResult.interpretation,
      ...geometryFacts(localVisualization),
      ...(interpretationResult.nativeCrs ? {
        crs: {
          status: "inferred",
          value: localVisualization?.crs || "OGC:CRS84",
          nativeValue: interpretationResult.nativeCrs,
          axisOrder: "as supplied by the service",
        },
      } : {}),
      ...(interpretationResult.warnings.length
        ? { warnings: interpretationResult.warnings }
        : {}),
    };
    if (interpretation.semanticType === "vector" && !localVisualization && interpretation.state === "recognized") {
      interpretation.state = "failed";
      interpretation.error = {
        code: "spatial_preview_failed",
        message: "The spatial output was recognized but did not produce a validated drawable layer.",
        phase: "presentation",
      };
    }
    const presentationArtifactRef = interpretationResult.parser === "gateway-gml-simple-features"
      ? `${candidate.id}-canonical`
      : `${candidate.id}-original`;
    const presentations = presentationForSemantic(
      candidate.id,
      interpretation.semanticType,
      localVisualization,
      interpretation.state,
      presentationArtifactRef,
    );
    const representations = [{
      id: `${candidate.id}-original`,
      role: "original",
      mediaType: declaredMediaType || interpretation.format,
      sizeBytes: byteLength(candidate.value),
      ...(candidate.encoding ? { encoding: candidate.encoding } : {}),
      ...(hydrated.handle ? { handle: hydrated.handle } : {}),
      ...(byteLength(candidate.value) <= MAX_INLINE_BYTES ? { data: candidate.value } : {}),
    }];
    if (interpretationResult.parser === "gateway-gml-simple-features") {
      representations.push({
        id: `${candidate.id}-canonical`,
        role: "canonical",
        mediaType: "application/geo+json",
        sizeBytes: byteLength(interpretationResult.previewData),
        data: interpretationResult.previewData,
      });
    }
    return {
      output: {
        id: candidate.id,
        title: candidate.title,
        status: outputState(retrieval, interpretation, presentations),
        retrieval,
        interpretation,
        representations,
        presentations,
        provenance: {
          serverId: execution.serverId,
          ...(text(originalPayload?.request?.path, 2_000)
            ? { requestPath: text(originalPayload.request.path, 2_000) }
            : {}),
          retrievedAt: new Date().toISOString(),
          parser: interpretationResult.parser,
          ...(interpretationResult.parser === "gateway-gml-simple-features"
            ? { transformations: ["GML Simple Features converted to a bounded GeoJSON map preview"] }
            : []),
        },
        ...(uniqueWarnings(
          interpretationResult.warnings,
          hydrated.partial ? `Only the first ${HYDRATION_LIMIT.toLocaleString("en-US")} stored items were retrieved.` : [],
        ).length
          ? {
            warnings: uniqueWarnings(
              interpretationResult.warnings,
              hydrated.partial ? `Only the first ${HYDRATION_LIMIT.toLocaleString("en-US")} stored items were retrieved.` : [],
            ),
          }
          : {}),
      },
      visualization: localVisualization,
    };
  });

  const outputs = prepared.map((item) => item.output);
  const visualizations = prepared.map((item) => item.visualization).filter(Boolean);
  let visualization = visualizations.length === 1
    ? visualizations[0]
    : visualizationFromPreviews(
      candidates
        .filter((candidate) => !candidate.referenceOnly)
        .map((candidate) => {
          const interpreted = interpretValue(candidate.value, candidate.declaredMediaType);
          return interpreted.previewData === null ? null : { id: candidate.id, data: interpreted.previewData };
        })
        .filter(Boolean),
      {
        id: mapIdFor(toolName, args, activityId, originalPayload),
        title: args?.job_id ? `Job ${args.job_id} result` : "Geospatial result",
        sourceTool: toolName,
        baseUrl: originalPayload.server?.base_url,
      },
    );
  visualization = browserSafeVisualization(visualization);

  const manifest = {
    schemaVersion: OUTPUT_MANIFEST_SCHEMA_VERSION,
    manifestId,
    execution,
    overallState: deriveOverallState(outputs, execution),
    outputs,
    ...(!outputs.length
      ? { warnings: ["Execution returned no declared or interpretable outputs."] }
      : {}),
  };
  const registeredManifest = registerManifestArtifacts(manifest, sessionId);
  return {
    manifest: registeredManifest,
    visualization,
    modelContext: compactVerifiedResultContext(registeredManifest),
    artifactEvents: artifactStatusEvents(registeredManifest),
  };
}

export function compactVerifiedResultContext(manifest) {
  if (!isObject(manifest)) return null;
  return {
    authority: "gateway_verified_output_manifest",
    instruction: "Treat execution, retrieval, interpretation, and presentation as separate facts. Do not claim an output was retrieved, interpreted, or mapped unless that stage is ready.",
    manifestId: manifest.manifestId,
    execution: {
      state: manifest.execution?.state,
      serverId: manifest.execution?.serverId,
      ...(manifest.execution?.processId ? { processId: manifest.execution.processId } : {}),
      ...(manifest.execution?.jobId ? { jobId: manifest.execution.jobId } : {}),
    },
    overallState: manifest.overallState,
    outputs: (manifest.outputs || []).slice(0, 20).map((output) => ({
      id: output.id,
      status: output.status,
      retrieval: {
        state: output.retrieval?.state,
        source: output.retrieval?.source,
        ...(output.retrieval?.declaredMediaType ? { declaredMediaType: output.retrieval.declaredMediaType } : {}),
        ...(output.retrieval?.detectedMediaType ? { detectedMediaType: output.retrieval.detectedMediaType } : {}),
        ...(output.retrieval?.error ? { error: output.retrieval.error.message } : {}),
      },
      interpretation: {
        state: output.interpretation?.state,
        semanticType: output.interpretation?.semanticType,
        ...(output.interpretation?.format ? { format: output.interpretation.format } : {}),
        ...(output.interpretation?.crs ? { crs: output.interpretation.crs } : {}),
        ...(output.interpretation?.featureCount !== undefined ? { featureCount: output.interpretation.featureCount } : {}),
        ...(output.interpretation?.geometryTypes?.length ? { geometryTypes: output.interpretation.geometryTypes } : {}),
        ...(output.interpretation?.error ? { error: output.interpretation.error.message } : {}),
      },
      presentations: (output.presentations || []).map((presentation) => ({
        kind: presentation.kind,
        state: presentation.state,
        ...(presentation.reason ? { reason: presentation.reason } : {}),
      })),
      ...(output.clarificationRequest ? {
        clarificationRequest: {
          blocking: output.clarificationRequest.blocking,
          scope: output.clarificationRequest.scope,
          issues: output.clarificationRequest.issues.map((issue) => ({
            kind: issue.kind,
            fieldPath: issue.fieldPath,
            question: issue.question,
            whyItMatters: issue.whyItMatters,
          })),
        },
      } : {}),
      warnings: uniqueWarnings(output.warnings, output.interpretation?.warnings),
    })),
    warnings: uniqueWarnings(manifest.warnings),
  };
}

export function appendVerifiedResultContext(original, modelContext) {
  if (!modelContext) return original;
  return `${String(original || "")}\n\n[GATEWAY VERIFIED OUTPUT STATE — AUTHORITATIVE]\n${JSON.stringify(modelContext)}`;
}

function stageStatus(state, completed, failed) {
  if (failed.includes(state)) return "error";
  if (completed.includes(state)) return "complete";
  return "running";
}

export function artifactStatusEvents(manifest) {
  if (!isObject(manifest)) return [];
  const events = [{
    manifestId: manifest.manifestId,
    outputId: "__execution__",
    stage: "execution",
    status: stageStatus(
      manifest.execution?.state,
      ["succeeded", "cancelled"],
      ["failed"],
    ),
    detail: `Process execution: ${manifest.execution?.state || "unknown"}.`,
  }];
  for (const output of manifest.outputs || []) {
    events.push({
      manifestId: manifest.manifestId,
      outputId: output.id,
      stage: "retrieval",
      status: stageStatus(output.retrieval?.state, ["retrieved", "partial"], ["failed", "blocked"]),
      detail: output.retrieval?.error?.message
        || `Output retrieval: ${output.retrieval?.state || "unknown"} (${output.retrieval?.source || "unknown source"}).`,
    });
    events.push({
      manifestId: manifest.manifestId,
      outputId: output.id,
      stage: "interpretation",
      status: output.clarificationRequest
        ? "waiting"
        : stageStatus(output.interpretation?.state, ["recognized", "unsupported", "ambiguous"], ["failed"]),
      detail: output.clarificationRequest?.issues?.[0]?.question
        || output.interpretation?.error?.message
        || `Output interpretation: ${output.interpretation?.state || "unknown"} as ${output.interpretation?.semanticType || "unknown"}.`,
    });
    for (const presentation of output.presentations || []) {
      events.push({
        manifestId: manifest.manifestId,
        outputId: output.id,
        stage: "presentation",
        status: stageStatus(presentation.state, ["ready", "partial", "unavailable"], []),
        detail: presentation.reason || `${titleFor(presentation.kind)} presentation: ${presentation.state}.`,
        presentationKind: presentation.kind,
      });
    }
  }
  return events;
}

export function manifestActivitySummary(manifest) {
  if (!manifest) return "";
  const outputs = manifest.outputs || [];
  const retrieved = outputs.filter((output) => ["retrieved", "partial"].includes(output.retrieval?.state)).length;
  const interpreted = outputs.filter((output) => output.interpretation?.state === "recognized").length;
  const mapped = outputs.filter((output) => (
    output.presentations?.some((presentation) => presentation.kind === "map" && presentation.state === "ready")
  )).length;
  if (manifest.execution?.state === "failed") return "Process execution failed; no successful output is being claimed.";
  if (manifest.execution?.state === "submitted" || manifest.execution?.state === "running") {
    return "Process execution was submitted; output retrieval and presentation are still pending.";
  }
  if (!outputs.length) return "Process execution completed, but no declared output was returned.";
  return `Execution ${manifest.execution?.state}; ${retrieved}/${outputs.length} output${outputs.length === 1 ? "" : "s"} retrieved, ${interpreted}/${outputs.length} interpreted, ${mapped}/${outputs.length} map-ready.`;
}
