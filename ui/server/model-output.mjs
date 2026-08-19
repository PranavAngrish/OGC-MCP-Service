import { compactToolResult } from "./activity-events.mjs";
import { appendVerifiedResultContext } from "./result-artifacts.mjs";

export const STRICT_PROCESS_OUTPUT_TOOLS = new Set([
  "ogc_jobs_get_results",
  "ogc_processes_execute",
  "ogc_proxy_execute_plan",
]);

export const BOUNDED_SUMMARY_TOOLS = new Set([
  "ogc_servers_list",
  "ogc_proxy_get_capabilities",
  "ogc_features_list_collections",
  "ogc_features_describe_collection",
  "ogc_features_describe_query_surface",
  "ogc_features_query",
  "ogc_features_get_items",
  "ogc_features_get_item",
  "ogc_records_list_collections",
  "ogc_records_search",
  "ogc_records_get_record",
  "ogc_processes_list",
  "ogc_processes_describe",
  "ogc_jobs_list",
  "ogc_jobs_get_status",
  "ogc_proxy_memory_list",
  "ogc_proxy_memory_retrieve",
  "ogc_common_get_landing_page",
  "ogc_common_get_conformance",
  "ogc_common_get_resource",
]);

const SECRET_KEY = /^(?:authorization|proxy-authorization|cookie|set-cookie|password|passwd|x-api-key|api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|client[_-]?secret|credentials?|signature|sig)$/i;
const SPATIAL_KEY = /^(?:coordinates?|geometry|geometries|bbox|bounds|bounding_?box|extent|wkt|pos|poslist|x|y|z|lon|lng|long|longitude|lat|latitude|caplat|caplong|caplon|caplng|easting|northing)$/i;
const MANIFEST_KEY = /^(?:output_manifest|outputManifest)$/;
const SCHEMA_CONTAINER_KEY = /^(?:inputs?|outputs?|parameters?|properties|patternProperties|definitions|\$defs|schema|inputSchema|outputSchema)$/i;
const SCHEMA_DESCRIPTOR_KEY = /^(?:schema|type|title|description|contentMediaType|contentSchema|format|items|properties|required|enum|oneOf|anyOf|allOf|\$ref|minimum|maximum|minItems|maxItems|default|nullable)$/i;
const MAX_DEPTH = 7;
const MAX_ITEMS = 30;
const MAX_ENTRIES = 50;
const MAX_STRING = 2_000;

function redactText(value) {
  const redacted = String(value)
    .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi, "Bearer [redacted]")
    .replace(
      /([?&](?:api[_-]?key|apikey|key|access[_-]?token|token|signature|sig)=)[^&#\s]*/gi,
      "$1[redacted]",
    );
  return redacted.length > MAX_STRING ? `${redacted.slice(0, MAX_STRING)}…` : redacted;
}

function spatialDocument(value) {
  const trimmed = value.trim();
  return (
    /<(?:[\w.-]+:)?(?:FeatureCollection|featureMember|Point|LineString|Polygon)\b/i.test(trimmed)
    || /^(?:SRID=\d+;)?(?:POINT|MULTIPOINT|LINESTRING|MULTILINESTRING|POLYGON|MULTIPOLYGON|GEOMETRYCOLLECTION)\s*[\s(]/i.test(trimmed)
    || /"(?:coordinates|geometry)"\s*:/i.test(trimmed)
    || /(?:^|\n)\s*(?:longitude|lon|lng|x)\s*,\s*(?:latitude|lat|y)\b/i.test(trimmed)
  );
}

function runtimeSpatialObject(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  if (/^(?:Feature|FeatureCollection|Point|MultiPoint|LineString|MultiLineString|Polygon|MultiPolygon|GeometryCollection)$/i.test(String(value.type || ""))) {
    return true;
  }
  if (Array.isArray(value.coordinates) || Array.isArray(value.bbox) || Array.isArray(value.bounds)) return true;
  const keys = Object.keys(value);
  return keys.length > 0 && keys.every((item) => /^(?:x|y|z|lon|lng|lat|latitude|longitude|easting|northing)$/i.test(item));
}

function schemaDescriptorForSpatialId(value) {
  if (typeof value === "boolean") return true;
  if (typeof value === "string") return !spatialDocument(value);
  if (!value || typeof value !== "object" || Array.isArray(value) || runtimeSpatialObject(value)) return false;
  return Object.keys(value).some((item) => SCHEMA_DESCRIPTOR_KEY.test(item));
}

/** Keep useful identifiers and scalar facts while removing coordinate-bearing values. */
export function coordinateStrippedSummary(value, depth = 0, key = "", options = {}) {
  const schemaScope = options.preserveProcessSchema === true
    && (options.inSchema === true || SCHEMA_CONTAINER_KEY.test(key));
  const maxDepth = options.preserveProcessSchema === true ? 12 : MAX_DEPTH;
  if (SECRET_KEY.test(key)) return "[redacted]";
  if (
    SPATIAL_KEY.test(key)
    && !(schemaScope && schemaDescriptorForSpatialId(value))
  ) return "[spatial value omitted]";
  if (MANIFEST_KEY.test(key)) return "[output manifest summarized separately]";
  if (value === null || typeof value === "number" || typeof value === "boolean") return value;
  if (typeof value === "string") {
    return spatialDocument(value) ? "[spatial document omitted]" : redactText(value);
  }
  if (value === undefined) return undefined;
  if (depth >= maxDepth) return "[nested data omitted]";
  if (Array.isArray(value)) {
    if (
      value.length >= 2
      && value.every((item) => typeof item === "number" && Number.isFinite(item))
    ) {
      return "[numeric array omitted]";
    }
    const maxItems = Number.isInteger(options.maxItems) ? options.maxItems : MAX_ITEMS;
    const items = value.slice(0, maxItems).map((item) => (
      coordinateStrippedSummary(item, depth + 1, key, {
        ...options,
        inSchema: schemaScope,
      })
    ));
    if (value.length > maxItems) items.push(`[${value.length - maxItems} more items]`);
    return items;
  }
  if (typeof value !== "object") return redactText(value);
  const entries = Object.entries(value);
  const safe = {};
  for (const [childKey, childValue] of entries.slice(0, MAX_ENTRIES)) {
    safe[childKey] = coordinateStrippedSummary(childValue, depth + 1, childKey, {
      ...options,
      inSchema: schemaScope,
    });
  }
  if (entries.length > MAX_ENTRIES) safe._omitted = `${entries.length - MAX_ENTRIES} more fields`;
  return safe;
}

function scalarOutputs(manifest) {
  if (!Array.isArray(manifest?.outputs)) return [];
  return manifest.outputs.flatMap((output) => {
    if (output?.interpretation?.semanticType !== "scalar") return [];
    const representation = output.representations?.find((item) => (
      ["canonical", "preview", "original"].includes(item?.role)
      && (
        ["string", "number", "boolean"].includes(typeof item?.data)
        || (
          item?.data
          && typeof item.data === "object"
          && !Array.isArray(item.data)
          && Object.keys(item.data).length === 1
          && ["string", "number", "boolean"].includes(typeof Object.values(item.data)[0])
        )
      )
    ));
    if (!representation) return [];
    const scalar = coordinateStrippedSummary(representation.data);
    return [{
      id: output.id,
      title: output.title,
      value: scalar,
      ...(Array.isArray(output.interpretation?.units)
        ? { units: coordinateStrippedSummary(output.interpretation.units) }
        : {}),
    }];
  }).slice(0, 20);
}

function firstControlValue(value, names, depth = 0) {
  if (!value || depth > 5) return undefined;
  if (Array.isArray(value)) {
    for (const item of value.slice(0, 30)) {
      const found = firstControlValue(item, names, depth + 1);
      if (found !== undefined) return found;
    }
    return undefined;
  }
  if (typeof value !== "object") return undefined;
  for (const [key, item] of Object.entries(value).slice(0, 60)) {
    if (names.has(key.toLowerCase()) && ["string", "number", "boolean"].includes(typeof item)) {
      return coordinateStrippedSummary(item, depth + 1, key);
    }
  }
  for (const item of Object.values(value).slice(0, 60)) {
    const found = firstControlValue(item, names, depth + 1);
    if (found !== undefined) return found;
  }
  return undefined;
}

function executionControlFacts(payload) {
  const candidates = {
    jobId: firstControlValue(payload?.data, new Set(["jobid", "job_id"])),
    status: firstControlValue(payload?.data, new Set(["status", "state"])),
    processId: firstControlValue(payload?.data, new Set(["processid", "process_id"])),
    planId: firstControlValue(payload, new Set(["planid", "plan_id"])),
  };
  return Object.fromEntries(
    Object.entries(candidates).filter(([, value]) => value !== undefined && value !== ""),
  );
}

function strictManifestResult(payload, artifacts, preparationFailed, toolName, isError) {
  if (preparationFailed || !artifacts?.manifest) {
    return JSON.stringify({
      ok: payload?.ok !== false && !isError,
      operation: payload?.operation || toolName,
      server: payload?.server
        ? { id: payload.server.id, title: payload.server.title }
        : undefined,
      gatewayVerifiedOutputState: {
        state: "unavailable",
        error: "Output preparation failed; raw output was withheld from model context.",
      },
    });
  }
  const envelope = compactToolResult(payload, artifacts.manifest) || {
    ok: payload?.ok !== false && !isError,
    operation: payload?.operation || toolName,
  };
  delete envelope.data;
  if (envelope.response) delete envelope.response.location;
  const controlFacts = executionControlFacts(payload);
  if (Object.keys(controlFacts).length) envelope.executionControlFacts = controlFacts;
  const scalars = scalarOutputs(artifacts.manifest);
  if (scalars.length) envelope.verifiedScalarOutputs = scalars;
  return appendVerifiedResultContext(JSON.stringify(envelope), artifacts.modelContext);
}

export function modelToolResultText({
  toolName,
  payload,
  rawOutput,
  artifacts,
  preparationFailed = false,
  isError = false,
}) {
  if (STRICT_PROCESS_OUTPUT_TOOLS.has(toolName)) {
    return strictManifestResult(payload, artifacts, preparationFailed, toolName, isError);
  }
  if (BOUNDED_SUMMARY_TOOLS.has(toolName)) {
    const source = payload ?? rawOutput ?? null;
    const summary = coordinateStrippedSummary(source, 0, "", {
      preserveProcessSchema: toolName === "ogc_processes_describe",
      inSchema: false,
      maxItems: toolName === "ogc_features_query" ? 250 : MAX_ITEMS,
    });
    const serialized = JSON.stringify(summary);
    return artifacts?.modelContext
      ? appendVerifiedResultContext(serialized, artifacts.modelContext)
      : serialized;
  }
  if (preparationFailed) {
    return strictManifestResult(payload, artifacts, true, toolName, isError);
  }
  if (artifacts?.modelContext) {
    return appendVerifiedResultContext(
      JSON.stringify(coordinateStrippedSummary(payload ?? rawOutput ?? null)),
      artifacts.modelContext,
    );
  }
  return rawOutput;
}
