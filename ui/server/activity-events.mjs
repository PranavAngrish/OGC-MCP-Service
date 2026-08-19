const SECRET_KEY = /^(?:authorization|proxy-authorization|cookie|set-cookie|password|passwd|x-api-key|api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|client[_-]?secret|credentials?)$/i;
const JSON_ARGUMENT = /(?:^|_)json$/i;
const MAX_ARGUMENT_STRING = 2_000;
const MAX_RESULT_STRING = 800;
const MAX_PREVIEW = 1_600;

function redactString(value, maximum) {
  const redacted = value
    .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi, "Bearer [redacted]")
    .replace(
      /([?&](?:api[_-]?key|apikey|key|access[_-]?token|token|signature|sig)=)[^&#\s]*/gi,
      "$1[redacted]",
    );
  return redacted.length > maximum ? `${redacted.slice(0, maximum)}…` : redacted;
}

function safeValue(
  value,
  {
    key = "",
    depth = 0,
    maxDepth = 7,
    maxEntries = 40,
    maxItems = 30,
    maxString = MAX_ARGUMENT_STRING,
    parseJson = false,
  } = {},
) {
  if (SECRET_KEY.test(key)) return "[redacted]";
  if (value === undefined) return undefined;
  if (value === null || typeof value === "number" || typeof value === "boolean") return value;
  if (typeof value === "string") {
    if (parseJson && JSON_ARGUMENT.test(key)) {
      try {
        return safeValue(JSON.parse(value), {
          depth,
          maxDepth,
          maxEntries,
          maxItems,
          maxString,
        });
      } catch {
        // Invalid JSON is still useful as display text.
      }
    }
    return redactString(value, maxString);
  }
  if (depth >= maxDepth) return "[nested data omitted]";
  if (Array.isArray(value)) {
    const items = value
      .slice(0, maxItems)
      .map((item) => safeValue(item, {
        depth: depth + 1,
        maxDepth,
        maxEntries,
        maxItems,
        maxString,
        parseJson,
      }));
    if (value.length > maxItems) items.push(`[${value.length - maxItems} more items]`);
    return items;
  }
  if (typeof value === "object") {
    const entries = Object.entries(value);
    const safe = Object.fromEntries(
      entries.slice(0, maxEntries).map(([childKey, childValue]) => [
        childKey,
        safeValue(childValue, {
          key: childKey,
          depth: depth + 1,
          maxDepth,
          maxEntries,
          maxItems,
          maxString,
          parseJson,
        }),
      ]),
    );
    if (entries.length > maxEntries) safe._omitted = `${entries.length - maxEntries} more fields`;
    return safe;
  }
  return redactString(String(value), maxString);
}

function valueLabel(value, fallback = "") {
  if (value === undefined || value === null || value === "") return fallback;
  return String(value);
}

function parsedJsonArgument(args, key) {
  const value = args?.[key];
  if (!value) return {};
  if (typeof value === "object" && !Array.isArray(value)) return value;
  if (typeof value !== "string") return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function serverPhrase(args) {
  const server = valueLabel(args?.server_id);
  return server ? ` on “${server}”` : "";
}

function identifier(value, fallback) {
  const label = valueLabel(value, fallback);
  return `“${label}”`;
}

/** Build a deterministic, user-safe explanation of why an MCP tool is being called. */
export function summarizeToolPurpose(name, args = {}) {
  const server = serverPhrase(args);
  switch (name) {
    case "ogc_servers_list":
      return "Discover the OGC servers and service types available to this workspace.";
    case "ogc_proxy_get_capabilities":
      return `Check which OGC capabilities and fallbacks are available${server}.`;
    case "ogc_features_list_collections":
      return `Discover available feature datasets${server}.`;
    case "ogc_features_describe_collection":
      return `Inspect metadata for collection ${identifier(args.collection_id, "unknown")}${server}.`;
    case "ogc_features_describe_query_surface":
      return `Discover filterable and returnable fields for collection ${identifier(args.collection_id, "unknown")}${server}.`;
    case "ogc_features_query": {
      const plan = parsedJsonArgument(args, "query_plan_json");
      return `Run a validated, automatically paginated query on collection ${identifier(plan.collection_id, "unknown")}${plan.server_id ? ` on “${plan.server_id}”` : ""}.`;
    }
    case "ogc_features_get_items": {
      const limit = Number(args.limit);
      const amount = Number.isFinite(limit) && limit > 0 ? `up to ${limit} features` : "features";
      return `Retrieve ${amount} from collection ${identifier(args.collection_id, "unknown")}${server}.`;
    }
    case "ogc_features_get_item":
      return `Retrieve feature ${identifier(args.item_id, "unknown")} from collection ${identifier(args.collection_id, "unknown")}${server}.`;
    case "ogc_records_list_collections":
      return `Discover available record catalogues${server}.`;
    case "ogc_records_search":
      return `Search catalogue ${identifier(args.collection_id, "default")}${server}.`;
    case "ogc_records_get_record":
      return `Retrieve catalogue record ${identifier(args.record_id, "unknown")}${server}.`;
    case "ogc_processes_list": {
      const search = valueLabel(args.search_text);
      return search
        ? `Search${server} for processes matching “${search}”.`
        : `Discover available geospatial processes${server}.`;
    }
    case "ogc_processes_describe":
      return `Inspect the required inputs and outputs for process ${identifier(args.process_id, "unknown")}${server}.`;
    case "ogc_proxy_create_plan": {
      const plan = parsedJsonArgument(args, "plan_request_json");
      const process = plan.process_id || "the selected process";
      return `Validate a human-confirmed execution plan for ${identifier(process, "the selected process")}.`;
    }
    case "ogc_proxy_update_plan":
      return `Update and revalidate plan ${identifier(args.plan_id, "unknown")}.`;
    case "ogc_proxy_get_plan":
      return `Check the current state and validated inputs for plan ${identifier(args.plan_id, "unknown")}.`;
    case "ogc_proxy_list_plans":
      return "Find existing plans that may be awaiting clarification or approval.";
    case "ogc_proxy_confirm_plan":
      return args.approved
        ? `Record the user’s explicit approval for plan ${identifier(args.plan_id, "unknown")}.`
        : `Record the user’s rejection of plan ${identifier(args.plan_id, "unknown")}.`;
    case "ogc_proxy_execute_plan":
      return `Execute approved plan ${identifier(args.plan_id, "unknown")}.`;
    case "ogc_processes_execute":
      return `Execute process ${identifier(args.process_id, "unknown")}${server}.`;
    case "ogc_jobs_list":
      return `Check asynchronous jobs${server}.`;
    case "ogc_jobs_get_status":
      return `Check the status of background job ${identifier(args.job_id, "unknown")}${server}.`;
    case "ogc_jobs_get_results":
      return `Retrieve the completed outputs for background job ${identifier(args.job_id, "unknown")}${server}.`;
    case "ogc_jobs_dismiss":
      return `Cancel background job ${identifier(args.job_id, "unknown")}${server}.`;
    case "ogc_proxy_memory_list":
      return "Inspect the metadata for stored, model-safe result payloads.";
    case "ogc_proxy_memory_retrieve":
      return `Retrieve a bounded page from stored result ${identifier(args.handle, "unknown")}.`;
    case "ogc_proxy_artifact_retrieve":
      return `Retrieve protected output representation ${identifier(args.handle, "unknown")} through the trusted gateway.`;
    case "ogc_common_get_landing_page":
      return `Inspect the OGC landing page${server}.`;
    case "ogc_common_get_conformance":
      return `Check advertised OGC conformance classes${server}.`;
    case "ogc_common_get_resource":
      return `Retrieve the requested OGC resource${server}.`;
    default:
      return "Call the selected OGC capability needed for the next step.";
  }
}

export function safeToolArguments(args) {
  return safeValue(args ?? {}, { parseJson: true });
}

function firstNamedValue(value, names, depth = 0) {
  if (!value || depth > 5) return undefined;
  if (Array.isArray(value)) {
    for (const item of value.slice(0, 30)) {
      const found = firstNamedValue(item, names, depth + 1);
      if (found !== undefined) return found;
    }
    return undefined;
  }
  if (typeof value !== "object") return undefined;
  for (const [key, item] of Object.entries(value).slice(0, 60)) {
    if (names.has(key.toLowerCase())) return item;
  }
  for (const item of Object.values(value).slice(0, 60)) {
    const found = firstNamedValue(item, names, depth + 1);
    if (found !== undefined) return found;
  }
  return undefined;
}

function errorMessage(payload) {
  const error = payload?.error;
  if (typeof error === "string") return error;
  if (error && typeof error === "object") {
    return valueLabel(error.message || error.detail || error.code, "The OGC tool reported an error.");
  }
  return "The OGC tool call failed.";
}

function countFrom(payload) {
  const summary = payload?.data?.summary || payload?.summary || payload?.data;
  const count = firstNamedValue(
    summary,
    new Set(["count", "numberreturned", "returned", "total_features", "total"]),
  );
  const number = Number(count);
  return Number.isFinite(number) && number >= 0 ? number : null;
}

function processMatchFrom(payload) {
  return payload?.data?.id || firstNamedValue(
    payload?.guidance || payload?.data || payload,
    new Set(["matched_process_id", "process_id", "processid"]),
  );
}

function jobStatusFrom(payload) {
  return firstNamedValue(payload?.data || payload, new Set(["status", "state"]));
}

function serverSuffix(payload) {
  const server = payload?.server?.title || payload?.server?.id;
  return server ? ` from ${server}` : "";
}

/** Build a concise outcome sentence from the standardized MCP result envelope. */
export function summarizeToolOutcome(name, payload, isError = false, outputManifest = null) {
  if (isError || payload?.ok === false) {
    return `Failed: ${redactString(errorMessage(payload), MAX_RESULT_STRING)}`;
  }
  if (outputManifest?.execution) {
    const outputs = Array.isArray(outputManifest.outputs) ? outputManifest.outputs : [];
    const retrieved = outputs.filter((output) => ["retrieved", "partial"].includes(output?.retrieval?.state)).length;
    const interpreted = outputs.filter((output) => output?.interpretation?.state === "recognized").length;
    const mapped = outputs.filter((output) => (
      Array.isArray(output?.presentations)
      && output.presentations.some((presentation) => presentation?.kind === "map" && presentation?.state === "ready")
    )).length;
    const execution = outputManifest.execution.state;
    if (execution === "failed") return "Process execution failed; no output retrieval or presentation is being claimed.";
    if (["submitted", "running"].includes(execution)) {
      return "Process submitted; output retrieval, interpretation, and presentation are still pending.";
    }
    if (outputs.length) {
      return `Execution ${execution}; ${retrieved}/${outputs.length} output${outputs.length === 1 ? "" : "s"} retrieved, ${interpreted}/${outputs.length} interpreted, ${mapped}/${outputs.length} map-ready.`;
    }
    return `Execution ${execution}; no declared output was returned.`;
  }
  const suffix = serverSuffix(payload);
  const count = countFrom(payload);
  switch (name) {
    case "ogc_servers_list": {
      const servers = Array.isArray(payload?.servers) ? payload.servers.length : count;
      return `${servers ?? 0} configured OGC server${servers === 1 ? "" : "s"} found.`;
    }
    case "ogc_features_list_collections":
      return count === null
        ? `Feature collections discovered${suffix}.`
        : `${count} feature collection${count === 1 ? "" : "s"} found${suffix}.`;
    case "ogc_processes_list": {
      const match = processMatchFrom(payload);
      if (match) return `Process ${identifier(match, "unknown")} found${suffix}.`;
      return count === null
        ? `Available processes discovered${suffix}.`
        : `${count} process${count === 1 ? "" : "es"} found${suffix}.`;
    }
    case "ogc_features_get_items":
      return count === null
        ? `Feature data retrieved${suffix}.`
        : `${count} feature${count === 1 ? "" : "s"} returned${suffix}.`;
    case "ogc_features_describe_query_surface": {
      const fields = Array.isArray(payload?.fields) ? payload.fields.length : 0;
      return `${fields} query-surface field${fields === 1 ? "" : "s"} discovered${suffix}.`;
    }
    case "ogc_features_query": {
      const retrieved = Number(payload?.data?.pagination?.retrieved) || 0;
      const complete = payload?.data?.evidence?.safeToAnswer === true;
      return `${retrieved} feature${retrieved === 1 ? "" : "s"} retrieved${suffix}; evidence ${complete ? "is complete" : "needs refinement"}.`;
    }
    case "ogc_features_get_item":
      return `Feature retrieved${suffix}.`;
    case "ogc_processes_describe": {
      const process = processMatchFrom(payload);
      return process
        ? `Inputs and outputs loaded for process ${identifier(process, "unknown")}${suffix}.`
        : `Process inputs and outputs loaded${suffix}.`;
    }
    case "ogc_proxy_create_plan":
    case "ogc_proxy_update_plan":
    case "ogc_proxy_get_plan":
    case "ogc_proxy_confirm_plan": {
      const status = payload?.plan?.status || payload?.workflow?.status;
      const unresolved = Array.isArray(payload?.plan?.unresolved)
        ? payload.plan.unresolved.length
        : firstNamedValue(payload, new Set(["unresolved_count"]));
      if (status === "needs_resolution" || payload?.resolution_required === true) {
        return `Plan needs ${Number(unresolved) || "additional"} user input${Number(unresolved) === 1 ? "" : "s"} before approval.`;
      }
      if (status === "ready_for_confirmation" || payload?.confirmation_required === true) {
        return "Plan validated and ready for explicit user approval.";
      }
      return status ? `Plan status: ${status}.` : "Plan state retrieved.";
    }
    case "ogc_proxy_execute_plan":
    case "ogc_processes_execute": {
      const status = jobStatusFrom(payload);
      const statusCode = Number(payload?.response?.status_code);
      if (["accepted", "queued", "running"].includes(String(status).toLowerCase()) || [201, 202].includes(statusCode)) {
        return `Process accepted as a background job${suffix}.`;
      }
      return `Process execution completed${suffix}.`;
    }
    case "ogc_jobs_get_status": {
      const status = jobStatusFrom(payload);
      return status ? `Background job status: ${status}.` : "Background job status retrieved.";
    }
    case "ogc_jobs_get_results":
      return count === null
        ? `Completed job outputs retrieved${suffix}.`
        : `Completed job output contains ${count} feature${count === 1 ? "" : "s"}${suffix}.`;
    case "ogc_proxy_memory_retrieve":
      return count === null
        ? "Stored result page retrieved."
        : `${count} stored feature${count === 1 ? "" : "s"} retrieved.`;
    case "ogc_proxy_artifact_retrieve":
      return "Protected output representation retrieved.";
    default: {
      const operation = valueLabel(payload?.operation);
      return operation ? `${operation} completed${suffix}.` : `OGC tool completed${suffix}.`;
    }
  }
}

function compactPlan(plan) {
  if (!plan || typeof plan !== "object") return undefined;
  const compact = {};
  for (const key of ["plan_id", "operation", "server_id", "process_id", "status"]) {
    if (plan[key] !== undefined) compact[key] = plan[key];
  }
  if (Array.isArray(plan.unresolved)) compact.unresolved = plan.unresolved;
  if (plan.execute_request !== undefined) compact.execute_request = plan.execute_request;
  if (plan.input_context !== undefined) compact.input_context = plan.input_context;
  return safeValue(compact, {
    maxDepth: 7,
    maxEntries: 30,
    maxItems: 20,
    maxString: MAX_RESULT_STRING,
  });
}

/** Select a small structured subset suitable for the live-activity UI. */
export function compactToolResult(payload, preparedOutputManifest = null) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  const compact = {
    ok: payload.ok !== false,
    ...(payload.operation ? { operation: payload.operation } : {}),
  };
  if (payload.server) {
    compact.server = safeValue({
      id: payload.server.id,
      title: payload.server.title,
    });
  }
  if (payload.request) compact.request = safeValue(payload.request);
  if (payload.response) {
    compact.response = safeValue({
      status_code: payload.response.status_code,
      content_type: payload.response.content_type,
      location: payload.response.location,
    });
  }
  if (payload.workflow) compact.workflow = safeValue(payload.workflow);
  if (payload.plan) compact.plan = compactPlan(payload.plan);
  if (payload.resolution_required !== undefined) {
    compact.resolution_required = Boolean(payload.resolution_required);
  }
  if (payload.confirmation_required !== undefined) {
    compact.confirmation_required = Boolean(payload.confirmation_required);
  }
  if (payload.data?.boundary === "tool_result_data_only") {
    compact.data = safeValue(payload.data, {
      maxDepth: 6,
      maxEntries: 30,
      maxItems: 10,
      maxString: MAX_RESULT_STRING,
    });
  } else if (payload.data !== undefined) {
    const dataStatus = {};
    for (const key of ["status", "state", "jobID", "job_id", "id", "type"]) {
      if (payload.data?.[key] !== undefined) dataStatus[key] = payload.data[key];
    }
    if (Object.keys(dataStatus).length) compact.data = safeValue(dataStatus);
  }
  if (payload.memory) compact.memory = safeValue(payload.memory);
  if (payload.error) compact.error = safeValue(payload.error, {
    maxString: MAX_RESULT_STRING,
  });
  const outputManifest = preparedOutputManifest
    || payload.output_manifest
    || payload.outputManifest
    || payload.data?.output_manifest
    || payload.data?.outputManifest;
  if (outputManifest?.schemaVersion === "ogc-output-manifest/1") {
    compact.outputManifest = safeValue({
      schemaVersion: outputManifest.schemaVersion,
      manifestId: outputManifest.manifestId,
      execution: outputManifest.execution,
      overallState: outputManifest.overallState,
      outputs: Array.isArray(outputManifest.outputs)
        ? outputManifest.outputs.map((output) => ({
          id: output.id,
          title: output.title,
          status: output.status,
          retrieval: output.retrieval,
          interpretation: output.interpretation,
          presentations: output.presentations,
          warnings: output.warnings,
        }))
        : [],
      warnings: outputManifest.warnings,
    }, {
      maxDepth: 8,
      maxEntries: 40,
      maxItems: 20,
      maxString: MAX_RESULT_STRING,
    });
  }
  return compact;
}

export function activityWarnings(payload, preparedOutputManifest = null) {
  const candidates = [
    payload?.warnings,
    payload?.guidance?.warnings,
    payload?.data?.summary?.warnings,
    payload?.output_manifest?.warnings,
    payload?.outputManifest?.warnings,
    preparedOutputManifest?.warnings,
    ...(Array.isArray(preparedOutputManifest?.outputs)
      ? preparedOutputManifest.outputs.flatMap((output) => [
        output?.warnings,
        output?.interpretation?.warnings,
      ])
      : []),
  ].flatMap((value) => (Array.isArray(value) ? value : value ? [value] : []));
  return [...new Set(
    candidates
      .filter((value) => typeof value === "string" && value.trim())
      .map((value) => redactString(value.trim(), MAX_RESULT_STRING)),
  )].slice(0, 10);
}

export function activityResultPreview(payload, fallback = "") {
  const value = payload
    ? safeValue(payload, {
      maxDepth: 6,
      maxEntries: 35,
      maxItems: 12,
      maxString: MAX_RESULT_STRING,
    })
    : redactString(String(fallback), MAX_PREVIEW);
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return text.length > MAX_PREVIEW ? `${text.slice(0, MAX_PREVIEW)}…` : text;
}

export function eventTiming(turnStartedAt, now = Date.now()) {
  const timestamp = new Date(now).toISOString();
  return {
    timestamp,
    elapsedMs: Math.max(0, now - turnStartedAt),
  };
}
