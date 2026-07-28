import { buildMapVisualization } from "./geospatial.mjs";

export const MAP_SOURCE_TOOLS = new Set([
  "ogc_jobs_get_results",
  "ogc_processes_execute",
  "ogc_proxy_execute_plan",
  "ogc_proxy_memory_retrieve",
  "ogc_common_get_resource",
  "ogc_features_get_items",
  "ogc_features_get_item",
  "ogc_records_search",
  "ogc_records_get_record",
]);

const HYDRATION_LIMIT = 1_000;

export function structuredToolPayload(result) {
  if (result?.structuredContent && typeof result.structuredContent === "object") {
    return result.structuredContent;
  }

  if (!Array.isArray(result?.content)) return null;
  for (const item of result.content) {
    if (item?.type !== "text" || typeof item.text !== "string") continue;
    try {
      const parsed = JSON.parse(item.text);
      if (parsed && typeof parsed === "object") return parsed;
    } catch {
      // A normal text result is not a structured geospatial payload.
    }
  }
  return null;
}

export function findMemoryHandle(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return "";
  const handle = payload.memory?.handle;
  return typeof handle === "string" && /^mem_[a-f0-9]{32}$/.test(handle) ? handle : "";
}

function resultTitle(toolName, args) {
  if (toolName === "ogc_jobs_get_results" && args?.job_id) {
    return `Job ${String(args.job_id)} result`;
  }
  if (args?.collection_id) return `${String(args.collection_id)} result`;
  if (args?.record_id) return `Record ${String(args.record_id)}`;
  return "Geospatial result";
}

function artifactId(toolName, args, activityId, payload) {
  if (toolName === "ogc_jobs_get_results" && args?.job_id) {
    const server = String(payload?.server?.id || args.server_id || "default").replace(/[^a-zA-Z0-9_-]+/g, "-").slice(0, 64);
    const job = String(args.job_id).replace(/[^a-zA-Z0-9_.~-]+/g, "-").slice(0, 120);
    return `job-${server}-${job}-map`;
  }
  return `${activityId}-map`;
}

function appendWarning(visualization, warning) {
  if (!warning) return visualization;
  return {
    ...visualization,
    warnings: [...new Set([...(visualization.warnings || []), warning])],
    stats: {
      ...(visualization.stats || {}),
      truncated: true,
    },
  };
}

/**
 * Prepare a browser-safe map artifact from a successful MCP result.
 *
 * Proxy-memory hydration deliberately happens outside the model message list.
 * `callTool` is injected by the caller to keep this boundary easy to test.
 */
export async function prepareMapArtifact({
  toolName,
  args = {},
  activityId,
  result,
  callTool,
}) {
  if (!MAP_SOURCE_TOOLS.has(toolName) || result?.isError) return null;

  const originalPayload = structuredToolPayload(result);
  if (!originalPayload || originalPayload.ok === false) return null;

  let payload = originalPayload;
  let hydrationTruncated = originalPayload.has_more === true;
  let hydrationFailed = false;
  const handle = toolName === "ogc_proxy_memory_retrieve" ? "" : findMemoryHandle(payload);

  if (handle) {
    try {
      const hydratedResult = await callTool("ogc_proxy_memory_retrieve", {
        handle,
        offset: 0,
        limit: HYDRATION_LIMIT,
      });
      const hydratedPayload = structuredToolPayload(hydratedResult);
      if (!hydratedResult?.isError && hydratedPayload && hydratedPayload.ok !== false) {
        payload = hydratedPayload;
        hydrationTruncated = hydratedPayload.has_more === true;
      } else {
        hydrationFailed = true;
      }
    } catch {
      // Map preparation is best effort and must never turn a successful tool
      // execution into a failed conversational turn.
      hydrationFailed = true;
    }
  }

  // Summary payloads intentionally omit coordinates. Rendering one after its
  // memory handle failed would make a partial preview look authoritative.
  if (hydrationFailed) return null;

  let visualization;
  try {
    visualization = buildMapVisualization(payload, {
      id: artifactId(toolName, args, activityId, originalPayload),
      title: resultTitle(toolName, args),
      sourceTool: toolName,
      baseUrl: originalPayload.server?.base_url,
    });
  } catch {
    return null;
  }

  if (!visualization?.layers?.length) return null;
  if (hydrationTruncated) {
    return appendWarning(
      visualization,
      `Only the first ${HYDRATION_LIMIT.toLocaleString("en-US")} features were loaded from this result.`,
    );
  }
  return visualization;
}
