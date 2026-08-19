import type {
  Activity,
  ActivityStatus,
  ArtifactWorkflowStage,
  OutputArtifact,
  OutputManifestV1,
  StreamEvent,
} from "../types";

export type ActivityFact = {
  label: string;
  value: string;
  meta?: string;
};

export type ActivityPanelState = "working" | "waiting" | "complete" | "issues" | "stopped";

const ACTIVITY_STATUSES = new Set<ActivityStatus>([
  "running",
  "waiting",
  "complete",
  "error",
  "cancelled",
]);
const SECRET_KEY = /(api[_-]?key|authorization|cookie|credential|password|secret|token)/i;
const MAX_FACTS = 12;
const MAX_FACT_VALUE = 220;
const MAX_REASONING_LENGTH = 2_400;

const asRecord = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;

const normalizeStatus = (
  value: unknown,
  fallback: ActivityStatus = "running",
): ActivityStatus => {
  const candidate = String(value || "");
  return ACTIVITY_STATUSES.has(candidate as ActivityStatus)
    ? candidate as ActivityStatus
    : fallback;
};

const stringValue = (value: unknown): string | undefined => {
  if (value === undefined || value === null || value === "") return undefined;
  return String(value);
};

const numberValue = (value: unknown): number | undefined => {
  const candidate = Number(value);
  return Number.isFinite(candidate) && candidate >= 0 ? candidate : undefined;
};

const warningValues = (value: unknown): string[] | undefined => {
  if (!Array.isArray(value)) return undefined;
  const warnings = value
    .filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    .slice(0, 8);
  return warnings.length ? warnings : undefined;
};

const artifactActivityStatus = (value: unknown): ActivityStatus => {
  const state = String(value || "").toLowerCase();
  if (["pending", "preparing", "resolving", "running", "submitted", "monitoring"].includes(state)) {
    return "running";
  }
  if (["awaiting_input", "awaiting_approval", "unresolved", "ambiguous"].includes(state)) {
    return "waiting";
  }
  if (["failed", "blocked", "unsupported", "unavailable"].includes(state)) return "error";
  if (["cancelled", "stopped"].includes(state)) return "cancelled";
  return "complete";
};

const artifactStageTitle = (value: unknown): string => {
  const stage = String(value || "presentation");
  const titles: Record<string, string> = {
    execution: "Checking process execution",
    submitted: "Analysis submitted",
    monitoring: "Monitoring the analysis",
    retrieval: "Retrieving process output",
    detection: "Detecting output format",
    interpretation: "Understanding output data",
    conversion: "Preparing a compatible preview",
    presentation: "Preparing output presentation",
    storage: "Securing the output artifact",
    complete: "Output preparation complete",
  };
  return titles[stage] || stage.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
};

const artifactStagePurpose = (stage: string): string => {
  const purposes: Record<string, string> = {
    execution: "Separate the process execution state from output retrieval and presentation readiness.",
    submitted: "Record the submitted process and begin tracking its output.",
    monitoring: "Wait for the background process to reach a final execution state.",
    retrieval: "Retrieve the actual process output, including any controlled output reference.",
    detection: "Compare advertised media types with the returned content and identify its real format.",
    interpretation: "Parse the retrieved value into a known semantic output such as vector data, a table, or a scalar.",
    conversion: "Create a bounded browser-safe representation while preserving the original artifact.",
    presentation: "Select a suitable renderer and verify that it has valid content to display.",
    storage: "Store the original or converted output behind a controlled artifact reference.",
    complete: "Publish the verified output manifest to the answer.",
  };
  return purposes[stage] || "Advance the output through the verified artifact pipeline.";
};

export function resultNeedsUser(result: unknown): boolean {
  const record = asRecord(result);
  if (!record) return false;
  if (record.confirmation_required === true || record.resolution_required === true) return true;
  const workflow = asRecord(record.workflow);
  const plan = asRecord(record.plan);
  return ["awaiting_human_confirmation", "needs_resolution", "ready_for_confirmation"].includes(
    String(workflow?.status || plan?.status || ""),
  );
}

function upsertActivity(current: Activity[], activity: Activity): Activity[] {
  const index = current.findIndex((item) => item.id === activity.id);
  if (index < 0) return [...current, activity];
  return current.map((item, itemIndex) =>
    itemIndex === index ? { ...item, ...activity } : item
  );
}

export function updateActivities(current: Activity[], event: StreamEvent): Activity[] {
  const data = event.data;

  if (event.event === "reasoning_delta") {
    const id = `reasoning-${String(data.id || "summary")}`;
    const delta = String(data.delta || "");
    if (!delta) return current;
    const existing = current.find((item) => item.id === id);
    if (existing) {
      const detail = `${existing.detail || ""}${delta}`.slice(-MAX_REASONING_LENGTH);
      return current.map((item) =>
        item.id === id ? { ...item, detail, status: "running" } : item
      );
    }
    return [
      ...current,
      {
        id,
        kind: "reasoning",
        title: "Decision summary",
        detail: delta.slice(-MAX_REASONING_LENGTH),
        status: "running",
        startedAt: stringValue(data.timestamp),
      },
    ];
  }

  if (event.event === "status") {
    const activity: Activity = {
      id: String(data.id || `status-${current.length}`),
      kind: "status",
      title: String(data.title || "Workflow update"),
      detail: stringValue(data.detail),
      status: normalizeStatus(data.status),
      startedAt: stringValue(data.startedAt || data.timestamp),
      completedAt: stringValue(data.completedAt),
      durationMs: numberValue(data.durationMs),
    };
    return upsertActivity(current, activity);
  }

  if (event.event === "tool_start") {
    const activity: Activity = {
      id: String(data.id || `tool-${current.length}`),
      kind: "tool",
      title: String(data.title || "Calling an OGC service"),
      toolName: stringValue(data.name),
      arguments: data.arguments,
      purpose: stringValue(data.purpose),
      status: "running",
      startedAt: stringValue(data.startedAt || data.timestamp),
      round: numberValue(data.round),
    };
    const completedReasoning = current.map((item) =>
      item.kind === "reasoning" && item.status === "running"
        ? { ...item, status: "complete" as const }
        : item
    );
    return upsertActivity(completedReasoning, activity);
  }

  if (event.event === "tool_result") {
    const id = String(data.id || `tool-result-${current.length}`);
    const result = data.result;
    const providerStatus = normalizeStatus(
      data.status,
      data.isError ? "error" : "complete",
    );
    const status = providerStatus === "complete" && resultNeedsUser(result)
      ? "waiting"
      : providerStatus;
    const patch: Activity = {
      id,
      kind: "tool",
      title: String(data.title || "OGC service response"),
      toolName: stringValue(data.name),
      status,
      resultPreview: stringValue(data.preview),
      outputSummary: stringValue(data.summary),
      result,
      warnings: warningValues(data.warnings),
      startedAt: stringValue(data.startedAt),
      completedAt: stringValue(data.completedAt || data.timestamp),
      durationMs: numberValue(data.durationMs),
    };
    const existing = current.find((item) => item.id === id);
    return upsertActivity(current, existing ? { ...existing, ...patch } : patch);
  }

  if (event.event === "job_status") {
    const id = `background-job-${String(data.serverId || "default")}-${String(data.jobId || "unknown")}`;
    const result = data.result;
    const activity: Activity = {
      id,
      kind: "tool",
      title: String(data.title || "Background process"),
      detail: stringValue(data.detail),
      toolName: "background_job",
      arguments: data.input,
      purpose: stringValue(data.purpose),
      outputSummary: stringValue(data.summary || data.detail),
      result,
      warnings: warningValues(asRecord(asRecord(result)?.map)?.warnings),
      status: normalizeStatus(data.status),
      startedAt: stringValue(data.startedAt),
      completedAt: normalizeStatus(data.status) === "running"
        ? undefined
        : stringValue(data.timestamp),
      durationMs: numberValue(data.durationMs),
    };
    return upsertActivity(current, activity);
  }

  if (event.event === "artifact_status") {
    const manifestId = String(data.manifestId || "manifest");
    const outputId = String(data.outputId || "output");
    const stage = String(data.stage || "presentation") as ArtifactWorkflowStage;
    const state = String(data.status || "running");
    const detail = stringValue(data.detail);
    const status = artifactActivityStatus(state);
    const activity: Activity = {
      id: `artifact-${String(data.activityId || `${manifestId}-${outputId}`)}-${stage}`,
      kind: "artifact",
      title: artifactStageTitle(stage),
      detail,
      toolName: "output_artifact",
      arguments: {
        output: outputId,
        stage,
        manifest: manifestId,
      },
      purpose: artifactStagePurpose(stage),
      outputSummary: detail || `Artifact stage: ${state.replaceAll("_", " ")}.`,
      result: { manifestId, outputId, stage, state, detail },
      status,
      artifactStage: stage,
      manifestId,
      outputId,
      startedAt: stringValue(data.startedAt || data.timestamp),
      completedAt: status === "running" ? undefined : stringValue(data.timestamp),
    };
    const updated = upsertActivity(current, activity);
    const manifestSummaryId = `artifact-${manifestId}-${outputId}-manifest`;
    const summary = updated.find((item) => item.id === manifestSummaryId);
    return summary
      ? [...updated.filter((item) => item.id !== manifestSummaryId), summary]
      : updated;
  }

  if (event.event === "output_manifest") {
    const manifest = asRecord(data.manifest) as OutputManifestV1 | null;
    if (!manifest || manifest.schemaVersion !== "ogc-output-manifest/1" || !Array.isArray(manifest.outputs)) {
      return current;
    }
    return manifest.outputs.reduce((activities, outputValue) => {
      const output = outputValue as OutputArtifact;
      const status = artifactActivityStatus(output.status);
      const readyPresentations = Array.isArray(output.presentations)
        ? output.presentations.filter((presentation) => ["ready", "partial"].includes(presentation.state)).length
        : 0;
      const warnings = [
        ...(Array.isArray(output.interpretation?.warnings) ? output.interpretation.warnings : []),
        ...(Array.isArray(output.warnings) ? output.warnings : []),
      ].slice(0, 8);
      const activity: Activity = {
        id: `artifact-${manifest.manifestId}-${output.id}-manifest`,
        kind: "artifact",
        title: status === "complete" ? `Output ready: ${output.title}` : `Output update: ${output.title}`,
        toolName: "output_artifact",
        purpose: "Publish the verified output, its interpretation, and every available presentation.",
        outputSummary: readyPresentations
          ? `${readyPresentations} verified ${readyPresentations === 1 ? "presentation is" : "presentations are"} ready.`
          : "The output is retained, but no browser presentation is ready.",
        arguments: {
          server: manifest.execution.serverId,
          process: manifest.execution.processId,
          job: manifest.execution.jobId,
          output: output.id,
        },
        result: {
          status: output.status,
          retrieval: output.retrieval,
          interpretation: output.interpretation,
          presentations: output.presentations,
        },
        warnings: warnings.length ? warnings : undefined,
        status,
        artifactStage: "complete",
        manifestId: manifest.manifestId,
        outputId: output.id,
        completedAt: stringValue(data.timestamp),
      };
      return upsertActivity(activities, activity);
    }, current);
  }

  if (event.event === "workflow_event") {
    const workflow = asRecord(data.event) || data;
    if (workflow.schemaVersion !== "activity/2") return current;
    const payload = asRecord(workflow.payload) || {};
    const type = String(workflow.type || "step_started");
    if (type === "output_manifest_upserted") {
      return updateActivities(current, {
        event: "output_manifest",
        data: { ...payload, timestamp: workflow.timestamp },
      });
    }
    if (type === "presentation_status") {
      return updateActivities(current, {
        event: "artifact_status",
        data: {
          ...payload,
          activityId: workflow.activityId,
          timestamp: workflow.timestamp,
        },
      });
    }
    if (type === "job_progress") {
      return updateActivities(current, {
        event: "job_status",
        data: { ...payload, timestamp: workflow.timestamp },
      });
    }
    const status = type === "workflow_failed"
      ? "error"
      : ["clarification_required", "approval_required"].includes(type)
        ? "waiting"
        : ["workflow_completed", "step_completed", "intent_recognized", "decision_recorded", "output_manifest_upserted"].includes(type)
          ? "complete"
          : type === "step_started" || type === "job_progress" || type === "presentation_status"
            ? artifactActivityStatus(payload.status || "running")
            : artifactActivityStatus(payload.status);
    const activity: Activity = {
      id: String(workflow.activityId || workflow.eventId),
      kind: type === "decision_recorded" ? "reasoning" : "status",
      title: String(payload.title || type.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase())),
      detail: stringValue(payload.detail || payload.summary),
      status,
      startedAt: stringValue(workflow.timestamp),
      completedAt: ["complete", "error", "cancelled"].includes(status) ? stringValue(workflow.timestamp) : undefined,
    };
    const existing = current.find((item) => item.id === activity.id);
    return upsertActivity(current, existing ? {
      ...activity,
      ...existing,
      status: activity.status,
      detail: activity.detail || existing.detail,
      startedAt: existing.startedAt || activity.startedAt,
      completedAt: activity.completedAt || existing.completedAt,
    } : activity);
  }

  return current;
}

export function activityPanelState(
  activities: Activity[],
  requestActive: boolean,
): ActivityPanelState {
  if (activities.some((activity) => activity.status === "running") || requestActive) {
    return "working";
  }
  if (activities.some((activity) => activity.status === "waiting")) return "waiting";
  if (activities.some((activity) => activity.status === "error")) return "issues";
  if (activities.some((activity) => activity.status === "cancelled")) return "stopped";
  return "complete";
}

const labelAliases: Record<string, string> = {
  server_id: "Server",
  collection_id: "Collection",
  process_id: "Process",
  search_text: "Search term",
  response_mode: "Response mode",
  summary_fields_json: "Summary fields",
  plan_request_json: "Plan request",
  execute_request_json: "Execution request",
  plan_id: "Plan",
  job_id: "Job",
  item_id: "Feature",
  record_id: "Record",
  href: "Data URL",
  bbox: "Bounding box",
  limit: "Maximum results",
  offset: "Starting offset",
  execution_mode: "Execution mode",
  wait_seconds: "Wait time",
  BufferDistance: "Buffer distance",
  InputPolygon: "Input polygon",
  InputPoints: "Input points",
  origin: "Input origin",
  units: "Units",
  unit: "Unit",
  crs: "CRS",
  axisOrder: "Axis order",
};

function displayLabel(path: string[]): string {
  const joined = path.join(".");
  const contextualAliases: Record<string, string> = {
    "server.id": "Server ID",
    "server.title": "Server",
    "request.method": "Request method",
    "request.path": "Request path",
    "response.status_code": "HTTP status",
    "response.content_type": "Response format",
    "workflow.status": "Workflow status",
    "plan.plan_id": "Plan",
    "plan.status": "Plan status",
    "plan.process_id": "Process",
    "data.summary.count": "Items returned",
    "data.summary.numberReturned": "Items returned",
    "data.summary.type": "Result type",
    "data.summary.truncated": "Result truncated",
  };
  if (contextualAliases[joined]) return contextualAliases[joined];
  const key = path.at(-1) || "value";
  const alias = labelAliases[key];
  if (alias) return alias;
  return key
    .replace(/_json$/i, "")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .replace(/\b(id|url|uri|crs|bbox|ogc|mcp)\b/gi, (value) => value.toUpperCase())
    .replace(/\b\w/g, (value) => value.toUpperCase());
}

function parseNestedJson(value: unknown, key: string): unknown {
  if (typeof value !== "string" || !/_json$/i.test(key)) return value;
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

function sanitizeUrl(value: string): string {
  if (!/^https?:\/\//i.test(value)) return value;
  try {
    const url = new URL(value);
    for (const key of [...url.searchParams.keys()]) {
      if (SECRET_KEY.test(key)) url.searchParams.set(key, "[redacted]");
    }
    return url.toString();
  } catch {
    return value;
  }
}

function compactValue(value: unknown): string {
  if (value === null) return "None";
  if (value === undefined) return "Not provided";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return String(value);
  if (typeof value === "string") {
    const sanitized = sanitizeUrl(value);
    return sanitized.length > MAX_FACT_VALUE
      ? `${sanitized.slice(0, MAX_FACT_VALUE - 1)}…`
      : sanitized;
  }
  try {
    const serialized = JSON.stringify(value);
    return serialized.length > MAX_FACT_VALUE
      ? `${serialized.slice(0, MAX_FACT_VALUE - 1)}…`
      : serialized;
  } catch {
    return "[Unserializable value]";
  }
}

function collectFacts(
  value: unknown,
  path: string[],
  facts: ActivityFact[],
  depth: number,
): void {
  if (facts.length >= MAX_FACTS) return;
  const key = path.at(-1) || "";
  const parsed = parseNestedJson(value, key);
  if (key && SECRET_KEY.test(key)) {
    facts.push({ label: displayLabel(path), value: "[redacted]" });
    return;
  }
  if (parsed === null || typeof parsed !== "object") {
    facts.push({ label: displayLabel(path), value: compactValue(parsed) });
    return;
  }
  if (!Array.isArray(parsed)) {
    const annotated = parsed as Record<string, unknown>;
    const annotationKeys = ["origin", "source", "units", "unit", "crs"];
    if ("value" in annotated && annotationKeys.some((annotation) => annotated[annotation] !== undefined)) {
      const originLabels: Record<string, string> = {
        user: "User supplied",
        server_default: "Server default",
        system_proposed: "Suggested by Terra",
        derived: "Derived from an earlier output",
        missing: "Still missing",
      };
      const origin = stringValue(annotated.origin || annotated.source);
      const unit = stringValue(annotated.units || annotated.unit);
      const crsValue = asRecord(annotated.crs)?.value || annotated.crs;
      const meta = [
        origin ? (originLabels[origin] || displayLabel([origin])) : undefined,
        unit ? `Units: ${unit}` : undefined,
        crsValue ? `CRS: ${compactValue(crsValue)}` : undefined,
      ].filter(Boolean).join(" · ");
      facts.push({
        label: displayLabel(path),
        value: compactValue(annotated.value),
        meta: meta || undefined,
      });
      return;
    }
  }
  if (Array.isArray(parsed)) {
    if (parsed.length === 0) {
      facts.push({ label: displayLabel(path), value: "None" });
      return;
    }
    if (parsed.every((item) => item === null || typeof item !== "object")) {
      facts.push({
        label: displayLabel(path),
        value: compactValue(parsed.slice(0, 8).join(", ")),
      });
      return;
    }
    if (depth >= 3) {
      facts.push({ label: displayLabel(path), value: `${parsed.length} items` });
      return;
    }
    parsed.slice(0, 3).forEach((item, index) =>
      collectFacts(item, [...path, `${key || "item"} ${index + 1}`], facts, depth + 1)
    );
    if (parsed.length > 3 && facts.length < MAX_FACTS) {
      facts.push({ label: displayLabel(path), value: `${parsed.length} items total` });
    }
    return;
  }

  const entries = Object.entries(parsed as Record<string, unknown>);
  if (entries.length === 0) {
    facts.push({ label: displayLabel(path), value: "None" });
    return;
  }
  if (depth >= 3) {
    facts.push({ label: displayLabel(path), value: compactValue(parsed) });
    return;
  }
  for (const [childKey, childValue] of entries) {
    if (facts.length >= MAX_FACTS) break;
    collectFacts(childValue, [...path, childKey], facts, depth + 1);
  }
}

export function activityFacts(value: unknown): ActivityFact[] {
  const record = asRecord(value);
  if (!record) {
    return value === undefined ? [] : [{ label: "Value", value: compactValue(value) }];
  }
  const facts: ActivityFact[] = [];
  for (const [key, childValue] of Object.entries(record)) {
    collectFacts(childValue, [key], facts, 0);
  }
  return facts;
}

function addFact(
  facts: ActivityFact[],
  label: string,
  value: unknown,
): void {
  if (value === undefined || value === null || value === "" || facts.length >= MAX_FACTS) return;
  facts.push({ label, value: compactValue(value) });
}

/** Extract the result facts a non-technical user is most likely to need first. */
export function activityResultFacts(value: unknown): ActivityFact[] {
  const record = asRecord(value);
  if (!record) return activityFacts(value);
  const facts: ActivityFact[] = [];
  const server = asRecord(record.server);
  const response = asRecord(record.response);
  const workflow = asRecord(record.workflow);
  const plan = asRecord(record.plan);
  const data = asRecord(record.data);
  const summary = asRecord(data?.summary);
  const map = asRecord(record.map || asRecord(record.result)?.map);

  addFact(facts, "Server", server?.title || server?.id);
  addFact(facts, "Process", plan?.process_id || data?.process_id || data?.id);
  addFact(facts, "Plan", plan?.plan_id);
  addFact(facts, "Plan status", plan?.status || workflow?.status);
  addFact(facts, "HTTP status", response?.status_code);
  addFact(facts, "Response format", response?.content_type);
  addFact(
    facts,
    "Items returned",
    summary?.count ?? summary?.numberReturned ?? data?.returned ?? data?.total_features,
  );
  addFact(facts, "Result type", summary?.type || data?.type);
  addFact(facts, "Result truncated", summary?.truncated);
  addFact(facts, "Process status", record.processStatus || data?.status || data?.state);
  addFact(facts, "Spatial output", record.spatialOutput);
  addFact(facts, "Map layers", map?.layerCount);
  addFact(facts, "Mapped features", map?.featureCount);

  const items = Array.isArray(summary?.items) ? summary.items : [];
  const matches = items.slice(0, 4).map((item) => {
    const candidate = asRecord(item);
    return candidate?.title || candidate?.id || candidate?.name;
  }).filter(Boolean);
  if (matches.length) addFact(facts, "Matches", matches.join(", "));

  if (record.resolution_required === true) addFact(facts, "Needs information", true);
  if (record.confirmation_required === true) addFact(facts, "Needs approval", true);
  if (record.error) addFact(facts, "Error", asRecord(record.error)?.message || record.error);

  if (facts.length) return facts.slice(0, MAX_FACTS);
  return activityFacts(
    Object.fromEntries(
      Object.entries(record).filter(([key]) => !["ok", "memory"].includes(key)),
    ),
  );
}

const toolPurposeFallbacks: Record<string, string> = {
  ogc_servers_list: "Check which trusted OGC services are connected.",
  ogc_common_get_landing_page: "Inspect the selected service and its advertised links.",
  ogc_proxy_get_capabilities: "Check which OGC capabilities and safe fallbacks are available.",
  ogc_features_list_collections: "Discover datasets that may contain the requested geography.",
  ogc_features_describe_collection: "Inspect the selected dataset before using it.",
  ogc_features_get_items: "Retrieve a bounded set of geographic features.",
  ogc_features_get_item: "Retrieve the selected geographic feature.",
  ogc_records_search: "Search the connected catalogue for a suitable dataset.",
  ogc_records_get_record: "Inspect the selected catalogue record and its data links.",
  ogc_processes_list: "Search for an analysis process that can perform the requested operation.",
  ogc_processes_describe: "Inspect the selected process’s required inputs and outputs.",
  ogc_proxy_create_plan: "Validate the proposed analysis setup without executing it.",
  ogc_proxy_update_plan: "Revalidate the analysis after applying the supplied changes.",
  ogc_proxy_confirm_plan: "Record the user’s explicit approval or rejection.",
  ogc_proxy_execute_plan: "Submit the confirmed analysis to the OGC process server.",
  ogc_jobs_get_status: "Check whether the background process has finished.",
  ogc_jobs_get_results: "Retrieve the completed process output.",
  ogc_proxy_memory_retrieve: "Retrieve a bounded portion of a stored result.",
};

export function activityPurpose(activity: Activity): string {
  if (activity.purpose) return activity.purpose;
  if (activity.kind === "artifact") {
    return artifactStagePurpose(activity.artifactStage || "presentation");
  }
  if (activity.kind !== "tool") return activity.detail || "";
  const base = activity.toolName ? toolPurposeFallbacks[activity.toolName] : undefined;
  if (activity.toolName === "ogc_processes_list") {
    const search = asRecord(activity.arguments)?.search_text;
    if (typeof search === "string" && search) {
      return `Search the registered process server for an analysis matching “${search}”.`;
    }
  }
  return base || "Use a trusted OGC service to advance the request.";
}

const toolDisplayTitles: Record<string, string> = {
  ogc_servers_list: "Discovering connected services",
  ogc_common_get_landing_page: "Inspecting the selected service",
  ogc_proxy_get_capabilities: "Checking available capabilities",
  ogc_features_list_collections: "Looking for suitable datasets",
  ogc_features_describe_collection: "Checking dataset details",
  ogc_features_get_items: "Retrieving geographic features",
  ogc_features_get_item: "Retrieving a geographic feature",
  ogc_records_search: "Searching the data catalogue",
  ogc_records_get_record: "Inspecting a catalogue result",
  ogc_processes_list: "Searching for a suitable analysis",
  ogc_processes_describe: "Checking analysis requirements",
  ogc_proxy_create_plan: "Validating the analysis setup",
  ogc_proxy_update_plan: "Updating the analysis setup",
  ogc_proxy_get_plan: "Checking the analysis plan",
  ogc_proxy_confirm_plan: "Recording your decision",
  ogc_proxy_execute_plan: "Starting the approved analysis",
  ogc_processes_execute: "Starting the analysis",
  ogc_jobs_get_status: "Checking background progress",
  ogc_jobs_get_results: "Retrieving completed outputs",
  ogc_proxy_memory_retrieve: "Preparing detailed results",
  background_job: "Monitoring the background process",
};

export function activityDisplayTitle(activity: Activity): string {
  if (activity.kind === "artifact") return artifactStageTitle(activity.artifactStage || activity.title);
  if (activity.kind !== "tool") return activity.title;
  if (activity.toolName === "ogc_processes_list") {
    const search = asRecord(activity.arguments)?.search_text;
    if (typeof search === "string" && search) return `Searching for “${search}” analysis`;
  }
  return (activity.toolName && toolDisplayTitles[activity.toolName]) || activity.title;
}

function resultRecord(activity: Activity): Record<string, unknown> | null {
  return asRecord(activity.result);
}

export function activityOutputSummary(activity: Activity): string {
  if (activity.outputSummary) return activity.outputSummary;
  if (activity.status === "running") return "Waiting for the service to respond…";
  if (activity.status === "cancelled") return "This step was stopped.";
  const result = resultRecord(activity);
  if (activity.status === "error") {
    const error = result?.error || result?.message;
    return typeof error === "string" ? error : "The service could not complete this step.";
  }
  if (activity.status === "waiting") {
    if (result?.confirmation_required === true) {
      return "The setup is valid and now requires your explicit approval.";
    }
    return "The workflow needs information from you before it can continue.";
  }
  if (activity.kind === "artifact") {
    return activity.detail || "This artifact stage completed.";
  }
  return activity.resultPreview
    ? "The service returned a result. See the readable facts and technical response below."
    : "This step completed.";
}

export function activityNextStep(activity: Activity): string | undefined {
  const result = resultRecord(activity);
  if (activity.status === "running") return "Waiting for the OGC service to respond.";
  if (activity.status === "error") return "Review this error before retrying or changing the request.";
  if (activity.status === "cancelled") return "No further action will be taken for this step.";
  if (activity.status === "waiting") {
    return result?.confirmation_required === true
      ? "Waiting for your approval; nothing has been executed."
      : "Waiting for the missing value; nothing has been executed.";
  }
  if (activity.kind === "artifact") {
    const nextByStage: Record<string, string> = {
      submitted: "Monitor the process until it finishes.",
      monitoring: "Retrieve the process outputs when execution reaches a final state.",
      retrieval: "Detect the real format of the retrieved content.",
      detection: "Interpret the output using the matching parser.",
      interpretation: "Prepare safe, bounded browser representations.",
      conversion: "Verify the available presentations.",
      presentation: "Publish the output manifest with honest renderer status.",
      storage: "Expose only a controlled artifact reference.",
      complete: "Review the verified presentations below.",
    };
    return nextByStage[activity.artifactStage || "presentation"];
  }
  if (activity.toolName === "background_job") {
    const spatialOutput = result?.spatialOutput;
    if (activity.status === "complete" && spatialOutput === true) {
      return "The completed geospatial output is ready on the map below.";
    }
    if (activity.status === "complete") return "Review the completed non-spatial output.";
    return "Continue monitoring until the process and output retrieval finish.";
  }
  const nextTools = asRecord(result?.guidance)?.next_tools;
  if (Array.isArray(nextTools) && nextTools.length) {
    return `Next available action: ${String(nextTools[0]).replace(/^ogc_/, "").replaceAll("_", " ")}.`;
  }
  const nextByTool: Record<string, string> = {
    ogc_servers_list: "Choose the appropriate data or processing service.",
    ogc_features_list_collections: "Inspect the most relevant dataset.",
    ogc_features_describe_collection: "Retrieve the required features.",
    ogc_features_get_items: "Use these features as an analysis input or prepare them for the map.",
    ogc_features_get_item: "Use this feature as an analysis input or prepare it for the map.",
    ogc_processes_list: "Inspect the selected process’s required inputs and outputs.",
    ogc_processes_describe: "Build and validate an execution plan.",
    ogc_proxy_create_plan: "Resolve missing inputs or ask for approval of the exact request.",
    ogc_proxy_update_plan: "Review the updated request and ask for approval.",
    ogc_proxy_confirm_plan: "Submit the plan only if it was explicitly approved.",
    ogc_proxy_execute_plan: "Monitor the job or retrieve the completed result.",
    ogc_jobs_get_status: "Continue monitoring until the process reaches a final state.",
    ogc_jobs_get_results: "Prepare any geospatial output for the map.",
  };
  return activity.toolName ? nextByTool[activity.toolName] : undefined;
}

export function formatDuration(milliseconds?: number): string | undefined {
  if (milliseconds === undefined || !Number.isFinite(milliseconds)) return undefined;
  if (milliseconds < 1_000) return `${Math.max(0, Math.round(milliseconds))} ms`;
  if (milliseconds < 60_000) return `${(milliseconds / 1_000).toFixed(milliseconds < 10_000 ? 1 : 0)} s`;
  const minutes = Math.floor(milliseconds / 60_000);
  const seconds = Math.round((milliseconds % 60_000) / 1_000);
  return `${minutes}m ${seconds}s`;
}

function sanitizeForTechnicalDetails(
  value: unknown,
  seen = new WeakSet<object>(),
  depth = 0,
): unknown {
  if (depth > 8) return "[depth limit]";
  if (value === null || typeof value !== "object") {
    return typeof value === "string" ? sanitizeUrl(value) : value;
  }
  if (seen.has(value)) return "[circular]";
  seen.add(value);
  if (Array.isArray(value)) {
    return value.slice(0, 50).map((item) =>
      sanitizeForTechnicalDetails(item, seen, depth + 1)
    );
  }
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).slice(0, 80).map(([key, child]) => [
      key,
      SECRET_KEY.test(key)
        ? "[redacted]"
        : sanitizeForTechnicalDetails(child, seen, depth + 1),
    ]),
  );
}

export function technicalJson(value: unknown): string {
  try {
    const text = JSON.stringify(sanitizeForTechnicalDetails(value), null, 2);
    return text.length > 12_000 ? `${text.slice(0, 12_000)}\n… [truncated]` : text;
  } catch {
    return "[Unable to format technical details]";
  }
}
