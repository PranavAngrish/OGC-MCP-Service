import type {
  MapBounds,
  MapLayer,
  MapVisualization,
  OutputArtifact,
  OutputClarificationRequest,
  OutputManifestV1,
  OutputPresentation,
  OutputRepresentation,
} from "../types";

type JsonRecord = Record<string, unknown>;

const isRecord = (value: unknown): value is JsonRecord =>
  value !== null && typeof value === "object" && !Array.isArray(value);

const text = (value: unknown, fallback = ""): string =>
  typeof value === "string" && value.trim() ? value.trim() : fallback;

const finiteNumber = (value: unknown): number | undefined =>
  typeof value === "number" && Number.isFinite(value) ? value : undefined;

const stringList = (value: unknown): string[] | undefined => {
  if (!Array.isArray(value)) return undefined;
  const result = value.filter((item): item is string => typeof item === "string" && Boolean(item.trim()));
  return result.length ? result.slice(0, 100) : undefined;
};

const normalizeBounds = (value: unknown): MapBounds | undefined => {
  if (!Array.isArray(value) || value.length !== 4) return undefined;
  const numbers = value.map(finiteNumber);
  if (numbers.some((item) => item === undefined)) return undefined;
  const [west, south, east, north] = numbers as MapBounds;
  if (west > east || south > north) return undefined;
  return [west, south, east, north];
};

const normalizeMapBounds = (value: unknown): MapBounds | undefined => {
  const bounds = normalizeBounds(value);
  if (!bounds) return undefined;
  const [west, south, east, north] = bounds;
  return west >= -180 && east <= 180 && south >= -90 && north <= 90 ? bounds : undefined;
};

const boundedObservedValue = (value: unknown): unknown => {
  try {
    const encoded = JSON.stringify(value);
    if (!encoded || new TextEncoder().encode(encoded).byteLength > 4_000) return undefined;
    return JSON.parse(encoded);
  } catch {
    return undefined;
  }
};

const normalizeClarificationRequest = (value: unknown): OutputClarificationRequest | undefined => {
  if (!isRecord(value) || !Array.isArray(value.issues)) return undefined;
  const issues = value.issues.slice(0, 100).flatMap((candidate, index) => {
    if (!isRecord(candidate)) return [];
    const fieldPath = text(candidate.fieldPath).slice(0, 500);
    const question = text(candidate.question).slice(0, 2_000);
    const whyItMatters = text(candidate.whyItMatters).slice(0, 4_000);
    if (!fieldPath || !question || !whyItMatters) return [];
    const observedValue = boundedObservedValue(candidate.observedValue);
    return [{
      id: text(candidate.id, `output-issue-${index + 1}`).slice(0, 200),
      kind: text(candidate.kind, "presentation").slice(0, 100),
      fieldPath,
      question,
      whyItMatters,
      allowFreeText: candidate.allowFreeText !== false,
      ...(observedValue !== undefined ? { observedValue } : {}),
    }];
  });
  if (!issues.length) return undefined;
  const scope = text(value.scope, "interpretation");
  return {
    blocking: value.blocking === true,
    scope: ["execution", "interpretation", "presentation"].includes(scope)
      ? scope as OutputClarificationRequest["scope"]
      : "interpretation",
    issues,
  };
};

/**
 * Treat manifests as an untrusted browser boundary. The server validates the
 * complete schema; this bounded normalizer makes malformed/replayed SSE data
 * safe to render without discarding compatible future fields.
 */
export function normalizeOutputManifest(value: unknown): OutputManifestV1 | null {
  if (!isRecord(value) || value.schemaVersion !== "ogc-output-manifest/1") return null;
  if (!text(value.manifestId) || !isRecord(value.execution) || !Array.isArray(value.outputs)) return null;
  const execution = value.execution;
  const serverId = text(execution.serverId);
  if (!serverId) return null;

  const outputs = value.outputs.slice(0, 100).flatMap((candidate, index): OutputArtifact[] => {
    if (!isRecord(candidate)) return [];
    const retrieval = isRecord(candidate.retrieval) ? candidate.retrieval : {};
    const interpretation = isRecord(candidate.interpretation) ? candidate.interpretation : {};
    const provenance = isRecord(candidate.provenance) ? candidate.provenance : {};
    const representations = Array.isArray(candidate.representations)
      ? candidate.representations.slice(0, 20).flatMap((item, representationIndex): OutputRepresentation[] => {
        if (!isRecord(item)) return [];
        const id = text(item.id, `representation-${representationIndex + 1}`);
        const mediaType = text(item.mediaType, "application/octet-stream");
        return [{
          ...item,
          id,
          role: text(item.role, "original") as OutputRepresentation["role"],
          mediaType,
          handle: text(item.handle) || undefined,
          href: text(item.href) || undefined,
          sizeBytes: finiteNumber(item.sizeBytes),
          encoding: text(item.encoding) || undefined,
          data: item.data,
        }];
      })
      : undefined;
    const presentations = Array.isArray(candidate.presentations)
      ? candidate.presentations.slice(0, 20).flatMap((item, presentationIndex): OutputPresentation[] => {
        if (!isRecord(item)) return [];
        return [{
          ...item,
          id: text(item.id, `presentation-${presentationIndex + 1}`),
          kind: text(item.kind, "unknown"),
          state: text(item.state, "unavailable") as OutputPresentation["state"],
          artifactRef: text(item.artifactRef) || undefined,
          reason: text(item.reason) || undefined,
        }];
      })
      : [];

    return [{
      ...candidate,
      id: text(candidate.id, `output-${index + 1}`),
      title: text(candidate.title, `Output ${index + 1}`),
      description: text(candidate.description) || undefined,
      status: text(candidate.status, "unresolved") as OutputArtifact["status"],
      retrieval: {
        ...retrieval,
        state: text(retrieval.state, "pending") as OutputArtifact["retrieval"]["state"],
        source: text(retrieval.source, "inline") as OutputArtifact["retrieval"]["source"],
        declaredMediaType: text(retrieval.declaredMediaType) || undefined,
        detectedMediaType: text(retrieval.detectedMediaType) || undefined,
        bytes: finiteNumber(retrieval.bytes),
        httpStatus: finiteNumber(retrieval.httpStatus),
        redirectCount: finiteNumber(retrieval.redirectCount),
        error: isRecord(retrieval.error)
          ? {
            code: text(retrieval.error.code, "retrieval_error"),
            message: text(retrieval.error.message, "The output could not be retrieved."),
            phase: text(retrieval.error.phase) || undefined,
            retryable: typeof retrieval.error.retryable === "boolean" ? retrieval.error.retryable : undefined,
          }
          : undefined,
      },
      interpretation: {
        ...interpretation,
        state: text(interpretation.state, "pending") as OutputArtifact["interpretation"]["state"],
        semanticType: text(interpretation.semanticType, "unknown"),
        format: text(interpretation.format) || undefined,
        crs: isRecord(interpretation.crs)
          ? {
            value: text(interpretation.crs.value) || undefined,
            status: text(interpretation.crs.status, "missing"),
            axisOrder: text(interpretation.crs.axisOrder) || undefined,
            nativeValue: text(interpretation.crs.nativeValue) || undefined,
          }
          : undefined,
        bbox: normalizeBounds(interpretation.bbox),
        featureCount: finiteNumber(interpretation.featureCount),
        rowCount: finiteNumber(interpretation.rowCount),
        geometryTypes: stringList(interpretation.geometryTypes),
        units: Array.isArray(interpretation.units)
          ? interpretation.units.slice(0, 100).flatMap((unit) =>
            isRecord(unit)
              ? [{
                quantity: text(unit.quantity) || undefined,
                value: text(unit.value) || undefined,
                status: text(unit.status, "missing"),
              }]
              : []
          )
          : undefined,
        warnings: stringList(interpretation.warnings),
        error: isRecord(interpretation.error)
          ? {
            code: text(interpretation.error.code, "interpretation_error"),
            message: text(interpretation.error.message, "The output could not be interpreted."),
            phase: text(interpretation.error.phase) || undefined,
            retryable: typeof interpretation.error.retryable === "boolean" ? interpretation.error.retryable : undefined,
          }
          : undefined,
      },
      representations,
      presentations,
      clarificationRequest: normalizeClarificationRequest(candidate.clarificationRequest),
      provenance: {
        ...provenance,
        serverId: text(provenance.serverId, serverId),
        requestPath: text(provenance.requestPath) || undefined,
        retrievedAt: text(provenance.retrievedAt) || undefined,
        parser: text(provenance.parser) || undefined,
        transformations: stringList(provenance.transformations),
        sha256: text(provenance.sha256) || undefined,
      },
      warnings: stringList(candidate.warnings),
    }];
  });

  return {
    ...value,
    schemaVersion: "ogc-output-manifest/1",
    manifestId: text(value.manifestId),
    execution: {
      ...execution,
      state: text(execution.state, "running") as OutputManifestV1["execution"]["state"],
      serverId,
      processId: text(execution.processId) || undefined,
      planId: text(execution.planId) || undefined,
      jobId: text(execution.jobId) || undefined,
      reportedStatus: text(execution.reportedStatus) || undefined,
      sourceTool: text(execution.sourceTool) || undefined,
    },
    overallState: text(value.overallState, "pending") as OutputManifestV1["overallState"],
    outputs,
    warnings: stringList(value.warnings),
  };
}

export function upsertOutputManifest(
  current: OutputManifestV1[],
  manifest: OutputManifestV1,
): OutputManifestV1[] {
  const sameLifecycle = (candidate: OutputManifestV1): boolean => {
    const serverId = candidate.execution.serverId;
    const jobId = candidate.execution.jobId;
    const planId = candidate.execution.planId;
    if (serverId !== manifest.execution.serverId) return false;
    // Async submission and later job-result manifests can have different
    // server-generated IDs. They nevertheless describe one job and must
    // occupy one UI card so a completed map cannot sit beside a stale spinner.
    if (jobId && manifest.execution.jobId) return jobId === manifest.execution.jobId;
    // A plan is executed at most once by the confirmation-gated workflow, so
    // it is a safe fallback while an upstream server has not yet supplied a
    // job identifier in one of the two responses.
    return Boolean(planId && manifest.execution.planId && planId === manifest.execution.planId);
  };
  const index = current.findIndex((item) => (
    item.manifestId === manifest.manifestId || sameLifecycle(item)
  ));
  if (index < 0) return [...current, manifest].slice(-8);
  return current.map((item, itemIndex) => itemIndex === index ? manifest : item);
}

export function representationForPresentation(
  output: OutputArtifact,
  presentation: OutputPresentation,
): OutputRepresentation | undefined {
  const representations = output.representations || [];
  if (presentation.artifactRef) {
    const exact = representations.find((item) =>
      item.id === presentation.artifactRef || item.handle === presentation.artifactRef
    );
    if (exact) return exact;
  }
  const roleOrder = presentation.kind === "download"
    ? ["original", "canonical", "preview", "tiles"]
    : ["preview", "canonical", "tiles", "original"];
  return roleOrder.flatMap((role) => representations.filter((item) => item.role === role))[0]
    || representations[0];
}

function candidateVisualization(value: unknown): Partial<MapVisualization> | null {
  if (!isRecord(value)) return null;
  if (Array.isArray(value.layers)) return value as Partial<MapVisualization>;
  for (const key of ["visualization", "map", "mapVisualization"]) {
    const nested = value[key];
    if (isRecord(nested) && Array.isArray(nested.layers)) {
      return nested as Partial<MapVisualization>;
    }
  }
  return null;
}

function geometryHasCoordinates(value: unknown): boolean {
  if (!isRecord(value) || typeof value.type !== "string") return false;
  if (value.type === "GeometryCollection") {
    return Array.isArray(value.geometries) && value.geometries.some(geometryHasCoordinates);
  }
  const visit = (candidate: unknown): boolean => {
    if (!Array.isArray(candidate)) return false;
    if (
      candidate.length >= 2
      && typeof candidate[0] === "number"
      && Number.isFinite(candidate[0])
      && typeof candidate[1] === "number"
      && Number.isFinite(candidate[1])
      && candidate[0] >= -180
      && candidate[0] <= 180
      && candidate[1] >= -90
      && candidate[1] <= 90
    ) return true;
    return candidate.some(visit);
  };
  return visit(value.coordinates);
}

function geoJsonHasDrawableFeature(value: unknown): boolean {
  if (!isRecord(value)) return false;
  if (value.type === "FeatureCollection") {
    return Array.isArray(value.features) && value.features.some((feature) =>
      isRecord(feature) && feature.type === "Feature" && geometryHasCoordinates(feature.geometry)
    );
  }
  if (value.type === "Feature") return geometryHasCoordinates(value.geometry);
  return geometryHasCoordinates(value);
}

function geoJsonHasDrawablePoint(value: unknown): boolean {
  if (!isRecord(value)) return false;
  const pointGeometry = (candidate: unknown) =>
    isRecord(candidate)
    && ["Point", "MultiPoint"].includes(String(candidate.type))
    && geometryHasCoordinates(candidate);
  if (value.type === "FeatureCollection") {
    return Array.isArray(value.features) && value.features.some((feature) =>
      isRecord(feature) && pointGeometry(feature.geometry)
    );
  }
  if (value.type === "Feature") return pointGeometry(value.geometry);
  return pointGeometry(value);
}

function validBounds(value: unknown): value is MapBounds {
  return Boolean(normalizeMapBounds(value));
}

function tileTemplate(value: unknown): boolean {
  return typeof value === "string"
    && /\{z\}/i.test(value)
    && (/\{x\}/i.test(value) || /\{quadkey\}/i.test(value))
    && (/\{y\}/i.test(value) || /\{-y\}/i.test(value) || /\{quadkey\}/i.test(value));
}

export function mapVisualizationHasDrawableLayer(
  value: MapVisualization | null | undefined,
  gatewayOnlyRemote = false,
): boolean {
  if (!value || !Array.isArray(value.layers)) return false;
  return value.layers.some((layer) => {
    if (!layer || typeof layer !== "object") return false;
    if (layer.kind === "vector") return geoJsonHasDrawableFeature(layer.data);
    if (layer.kind === "heatmap") return geoJsonHasDrawablePoint(layer.data);
    if (layer.kind === "raster") {
      return typeof layer.href === "string"
        && Boolean(gatewayOnlyRemote ? safeArtifactHref(layer.href) : layer.href)
        && validBounds(layer.bounds);
    }
    if (layer.kind === "tiles") {
      return tileTemplate(layer.href)
        && (!gatewayOnlyRemote || Boolean(safeArtifactHref(layer.href)));
    }
    return false;
  });
}

export function mapVisualizationForPresentation(
  output: OutputArtifact,
  presentation: OutputPresentation,
): MapVisualization | null {
  const preferred = representationForPresentation(output, presentation);
  const representations = [
    ...(preferred ? [preferred] : []),
    ...(output.representations || []).filter((item) => item !== preferred),
  ];
  const visualizationRepresentation = representations.find((item) =>
    Boolean(candidateVisualization(item.data)?.layers)
  );
  const candidate = candidateVisualization(visualizationRepresentation?.data);
  if (candidate?.layers) {
    return {
      id: text(candidate.id, `${output.id}-${presentation.id}`),
      title: text(candidate.title, output.title),
      sourceTool: text(candidate.sourceTool) || output.provenance.parser,
      layers: candidate.layers as MapLayer[],
      bounds: normalizeMapBounds(candidate.bounds) || normalizeMapBounds(output.interpretation.bbox),
      crs: text(candidate.crs) || output.interpretation.crs?.value,
      warnings: [
        ...(candidate.warnings || []),
        ...(output.interpretation.warnings || []),
        ...(output.warnings || []),
      ],
      stats: candidate.stats,
    };
  }

  const representation = representations.find((item) => geoJsonHasDrawableFeature(item.data))
    || representations.find((item) => Boolean(item.href))
    || preferred;
  const data = representation?.data;
  const semanticType = output.interpretation.semanticType;
  if (geoJsonHasDrawableFeature(data)) {
    const collection = isRecord(data) && data.type === "FeatureCollection"
      ? data
      : isRecord(data) && data.type === "Feature"
        ? { type: "FeatureCollection", features: [data] }
        : {
          type: "FeatureCollection",
          features: [{ type: "Feature", geometry: data, properties: {} }],
        };
    return {
      id: `${output.id}-${presentation.id}`,
      title: output.title,
      sourceTool: output.provenance.parser,
      layers: [{
        id: output.id,
        label: output.title,
        kind: "vector",
        description: output.description,
        data: collection as unknown as MapLayer["data"],
        bounds: normalizeMapBounds(output.interpretation.bbox),
        format: output.interpretation.format || representation?.mediaType,
        crs: output.interpretation.crs?.value,
        units: output.interpretation.units?.map((unit) => unit.value).filter(Boolean).join(", "),
        featureCount: output.interpretation.featureCount,
      }],
      bounds: normalizeMapBounds(output.interpretation.bbox),
      crs: output.interpretation.crs?.value,
      warnings: [...(output.interpretation.warnings || []), ...(output.warnings || [])],
      stats: {
        featureCount: output.interpretation.featureCount,
        geometryTypes: output.interpretation.geometryTypes
          ? Object.fromEntries(output.interpretation.geometryTypes.map((kind) => [kind, 0]))
          : undefined,
        layerCount: 1,
      },
    };
  }

  const controlledHref = safeArtifactHref(representation?.href);
  if (representation && controlledHref && ["raster", "coverage", "image", "tiles"].includes(semanticType)) {
    const layerKind: MapLayer["kind"] = semanticType === "tiles" || representation.role === "tiles"
      ? "tiles"
      : "raster";
    return {
      id: `${output.id}-${presentation.id}`,
      title: output.title,
      layers: [{
        id: output.id,
        label: output.title,
        kind: layerKind,
        href: controlledHref,
        bounds: normalizeMapBounds(output.interpretation.bbox),
        format: output.interpretation.format || representation.mediaType,
        crs: output.interpretation.crs?.value,
      }],
      bounds: normalizeMapBounds(output.interpretation.bbox),
      crs: output.interpretation.crs?.value,
      warnings: [...(output.interpretation.warnings || []), ...(output.warnings || [])],
    };
  }
  return null;
}

export function manifestHasReadyMap(manifests: OutputManifestV1[] | undefined): boolean {
  return Boolean(manifests?.some((manifest) => manifest.outputs.some((output) =>
    output.presentations.some((presentation) =>
      presentation.kind === "map"
      && ["ready", "partial"].includes(presentation.state)
      && mapVisualizationHasDrawableLayer(mapVisualizationForPresentation(output, presentation), true)
    )
  )));
}

export type OutputTable = {
  columns: string[];
  rows: Array<Record<string, unknown>>;
  totalRows: number;
  truncated: boolean;
};

export function tableFromRepresentation(value: unknown): OutputTable | null {
  let rows: unknown[] = [];
  if (isRecord(value) && value.type === "FeatureCollection" && Array.isArray(value.features)) {
    rows = value.features.map((feature, index) => {
      const record = isRecord(feature) ? feature : {};
      const properties = isRecord(record.properties) ? record.properties : {};
      return {
        Feature: record.id ?? index + 1,
        Geometry: isRecord(record.geometry) ? record.geometry.type : "None",
        ...properties,
      };
    });
  } else if (Array.isArray(value)) {
    rows = value;
  } else if (isRecord(value) && Array.isArray(value.rows)) {
    const columns = Array.isArray(value.columns)
      ? value.columns.map((column) => isRecord(column) ? text(column.name || column.label) : text(column))
      : [];
    rows = value.rows.map((row) => {
      if (isRecord(row)) return row;
      if (Array.isArray(row) && columns.length) {
        return Object.fromEntries(columns.map((column, index) => [column || `Column ${index + 1}`, row[index]]));
      }
      return { Value: row };
    });
  } else if (isRecord(value)) {
    rows = [value];
  } else if (value !== undefined) {
    rows = [{ Value: value }];
  }
  if (!rows.length) return null;
  const normalizedRows = rows.slice(0, 100).map((row) =>
    isRecord(row) ? row : { Value: row }
  );
  const columns = [...new Set(normalizedRows.flatMap((row) => Object.keys(row)))].slice(0, 12);
  return {
    columns,
    rows: normalizedRows,
    totalRows: rows.length,
    truncated: rows.length > normalizedRows.length || columns.some((column) => !column),
  };
}

export function safeArtifactHref(value: string | undefined): string | undefined {
  if (!value) return undefined;
  if (value.startsWith("/") && !value.startsWith("//")) return value;
  try {
    const browserOrigin = typeof window === "undefined" ? "https://local.invalid" : window.location.origin;
    const url = new URL(value, browserOrigin);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) return undefined;
    // Browser downloads and previews must pass through the gateway's controlled
    // artifact endpoint. Arbitrary upstream references remain server-side.
    return url.origin === browserOrigin ? url.href : undefined;
  } catch {
    return undefined;
  }
}

export function safeImageHref(value: string | undefined): string | undefined {
  if (value && /^data:image\/(?:png|jpeg|webp|gif|avif);base64,[a-z0-9+/=\s]+$/i.test(value)) return value;
  return safeArtifactHref(value);
}

export function formatBytes(value: number | undefined): string | undefined {
  if (value === undefined || !Number.isFinite(value) || value < 0) return undefined;
  if (value < 1_000) return `${Math.round(value)} B`;
  if (value < 1_000_000) return `${(value / 1_000).toFixed(value < 10_000 ? 1 : 0)} KB`;
  if (value < 1_000_000_000) return `${(value / 1_000_000).toFixed(value < 10_000_000 ? 1 : 0)} MB`;
  return `${(value / 1_000_000_000).toFixed(1)} GB`;
}

export function humanizeOutputState(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function printableValue(value: unknown, maximum = 2_400): string {
  if (typeof value === "string") return value.slice(0, maximum);
  if (value === undefined) return "No inline preview was provided.";
  try {
    const serialized = JSON.stringify(value, null, 2);
    return serialized.length > maximum ? `${serialized.slice(0, maximum)}\n…` : serialized;
  } catch {
    return "This value cannot be previewed in the browser.";
  }
}
