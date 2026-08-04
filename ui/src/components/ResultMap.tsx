import {
  AlertTriangle,
  Check,
  Download,
  Eye,
  EyeOff,
  Layers,
  LocateFixed,
  MapPin,
  RotateCcw,
  X,
} from "lucide-react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useMemo, useRef, useState } from "react";
import type { MapLayer, MapVisualization } from "../types";
import "./ResultMap.css";

type JsonRecord = Record<string, unknown>;
type Bounds = [number, number, number, number];

type GeoJsonGeometry = JsonRecord & {
  type: string;
  coordinates?: unknown;
  geometries?: unknown[];
};

type GeoJsonFeature = JsonRecord & {
  type: "Feature";
  geometry: GeoJsonGeometry | null;
  properties?: JsonRecord | null;
  id?: string | number;
};

type GeoJsonFeatureCollection = JsonRecord & {
  type: "FeatureCollection";
  features: GeoJsonFeature[];
};

type NormalizedLayer = {
  key: string;
  sourceId: string;
  id: string;
  label: string;
  description?: string;
  kind: "vector" | "heatmap" | "raster" | "tiles" | "reference";
  data?: GeoJsonFeatureCollection;
  href?: string;
  bounds?: Bounds;
  format?: string;
  attribution?: string;
  style: {
    color: string;
    opacity: number;
    radius: number;
  };
  raw: MapLayer;
};

type NormalizedVisualization = {
  id: string;
  title: string;
  sourceTool?: string;
  layers: NormalizedLayer[];
  bounds?: Bounds;
  crs: string;
  warnings: string[];
  truncated: boolean;
  featureCount: number;
  coordinateCount: number;
  geometryTypes: Record<string, number>;
};

type SelectedFeature = {
  layer: string;
  geometry: string;
  id?: string | number;
  properties: Array<[string, string]>;
  omittedProperties: number;
};

type ResultMapProps = {
  visualization: MapVisualization;
  className?: string;
};

const VECTOR_COLORS = ["#b9e66c", "#70d6ad", "#f2a765", "#8cb8ff", "#dca6ff"];
const MAX_VISIBLE_PROPERTIES = 40;
const MAX_PROPERTY_LENGTH = 700;

const GEOMETRY_TYPES = new Set([
  "Point",
  "MultiPoint",
  "LineString",
  "MultiLineString",
  "Polygon",
  "MultiPolygon",
  "GeometryCollection",
]);

let mapInstanceSequence = 0;
const DEFAULT_BASEMAP_STYLE_URL = "https://demotiles.maplibre.org/style.json";
const MAP_STYLE_LOAD_TIMEOUT_MS = 8_000;
const BASEMAP_RESOURCE_TIMEOUT_MS = 5_000;
const LOCAL_CANVAS_LOAD_TIMEOUT_MS = 2_500;

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function finiteNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function optionalString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function safeColor(value: unknown, fallback: string): string {
  const candidate = optionalString(value);
  if (!candidate) return fallback;
  if (/^#[0-9a-f]{3,8}$/i.test(candidate) || /^(?:rgb|hsl)a?\([\d\s.,%+-]+\)$/i.test(candidate)) {
    return candidate;
  }
  return fallback;
}

function normalizeBounds(value: unknown): Bounds | undefined {
  if (!Array.isArray(value) || value.length !== 4) return undefined;
  const numbers = value.map(finiteNumber);
  if (numbers.some((item) => item === undefined)) return undefined;
  const [west, south, east, north] = numbers as Bounds;
  if (west < -180 || east > 180 || south < -90 || north > 90 || west > east || south > north) {
    return undefined;
  }
  return [west, south, east, north];
}

function normalizeGeometry(value: unknown): GeoJsonGeometry | null {
  if (!isRecord(value) || typeof value.type !== "string" || !GEOMETRY_TYPES.has(value.type)) {
    return null;
  }
  if (value.type === "GeometryCollection") {
    if (!Array.isArray(value.geometries)) return null;
  } else if (!("coordinates" in value)) {
    return null;
  }
  return value as GeoJsonGeometry;
}

function normalizeFeature(value: unknown): GeoJsonFeature | null {
  if (!isRecord(value) || value.type !== "Feature") return null;
  const geometry = value.geometry === null ? null : normalizeGeometry(value.geometry);
  if (value.geometry !== null && !geometry) return null;
  return {
    ...value,
    type: "Feature",
    geometry,
    properties: isRecord(value.properties) ? value.properties : {},
  } as GeoJsonFeature;
}

function normalizeFeatureCollection(value: unknown): GeoJsonFeatureCollection | undefined {
  if (!isRecord(value)) return undefined;
  if (value.type === "FeatureCollection" && Array.isArray(value.features)) {
    const features = value.features.map(normalizeFeature).filter((item): item is GeoJsonFeature => Boolean(item));
    return { ...value, type: "FeatureCollection", features } as GeoJsonFeatureCollection;
  }
  const feature = normalizeFeature(value);
  if (feature) return { type: "FeatureCollection", features: [feature] };
  const geometry = normalizeGeometry(value);
  if (geometry) {
    return {
      type: "FeatureCollection",
      features: [{ type: "Feature", geometry, properties: {} }],
    };
  }
  return undefined;
}

function stableHash(value: string): string {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}

function safeId(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48) || "layer";
}

function makeNamespace(): string {
  mapInstanceSequence += 1;
  return `ogc-result-${mapInstanceSequence.toString(36)}`;
}

function normalizeLayer(value: MapLayer, index: number, namespace: string): NormalizedLayer | null {
  const layer = value as unknown as JsonRecord;
  const rawKind = optionalString(layer.kind)?.toLowerCase();
  if (!rawKind || !["vector", "heatmap", "raster", "tiles", "reference"].includes(rawKind)) {
    return null;
  }
  const kind = rawKind as NormalizedLayer["kind"];
  const id = optionalString(layer.id) || `layer-${index + 1}`;
  const label = optionalString(layer.label) || optionalString(layer.title) || `Layer ${index + 1}`;
  const layerStyle = isRecord(layer.style) ? layer.style : {};
  const color = safeColor(layerStyle.color, VECTOR_COLORS[index % VECTOR_COLORS.length]);
  const opacity = clamp(finiteNumber(layerStyle.opacity) ?? (kind === "heatmap" ? 0.8 : 0.72), 0, 1);
  const radius = clamp(finiteNumber(layerStyle.radius) ?? 6, 1, 40);
  const key = `${safeId(id)}-${index}-${stableHash(`${id}:${index}`)}`;
  return {
    key,
    sourceId: `${namespace}-source-${key}`,
    id,
    label,
    description: optionalString(layer.description),
    kind,
    data: normalizeFeatureCollection(layer.data),
    href: optionalString(layer.href),
    bounds: normalizeBounds(layer.bounds),
    format: optionalString(layer.format),
    attribution: optionalString(layer.attribution),
    style: { color, opacity, radius },
    raw: value,
  };
}

function walkCoordinatePairs(value: unknown, visitor: (longitude: number, latitude: number) => void): number {
  if (!Array.isArray(value)) return 0;
  if (
    value.length >= 2
    && typeof value[0] === "number"
    && Number.isFinite(value[0])
    && typeof value[1] === "number"
    && Number.isFinite(value[1])
  ) {
    visitor(value[0], value[1]);
    return 1;
  }
  return value.reduce((count, item) => count + walkCoordinatePairs(item, visitor), 0);
}

function visitGeometry(geometry: GeoJsonGeometry | null, visitor: (geometry: GeoJsonGeometry) => void): void {
  if (!geometry) return;
  visitor(geometry);
  if (geometry.type === "GeometryCollection" && Array.isArray(geometry.geometries)) {
    for (const child of geometry.geometries) {
      visitGeometry(normalizeGeometry(child), visitor);
    }
  }
}

function analyzeGeoJson(layers: NormalizedLayer[]) {
  let featureCount = 0;
  let coordinateCount = 0;
  const geometryTypes: Record<string, number> = {};
  let west = Number.POSITIVE_INFINITY;
  let south = Number.POSITIVE_INFINITY;
  let east = Number.NEGATIVE_INFINITY;
  let north = Number.NEGATIVE_INFINITY;

  for (const layer of layers) {
    if (!layer.data) continue;
    featureCount += layer.data.features.length;
    for (const feature of layer.data.features) {
      visitGeometry(feature.geometry, (geometry) => {
        geometryTypes[geometry.type] = (geometryTypes[geometry.type] || 0) + 1;
        if (geometry.type === "GeometryCollection") return;
        coordinateCount += walkCoordinatePairs(geometry.coordinates, (longitude, latitude) => {
          if (longitude < -180 || longitude > 180 || latitude < -90 || latitude > 90) return;
          west = Math.min(west, longitude);
          south = Math.min(south, latitude);
          east = Math.max(east, longitude);
          north = Math.max(north, latitude);
        });
      });
    }
  }

  const bounds: Bounds | undefined = Number.isFinite(west) ? [west, south, east, north] : undefined;
  return { featureCount, coordinateCount, geometryTypes, bounds };
}

function normalizeVisualization(value: MapVisualization, namespace: string): NormalizedVisualization {
  const visualization = value as unknown as JsonRecord;
  const rawLayers = Array.isArray(visualization.layers) ? visualization.layers : [];
  const layers = rawLayers
    .map((layer, index) => normalizeLayer(layer as MapLayer, index, namespace))
    .filter((layer): layer is NormalizedLayer => Boolean(layer));
  const analysis = analyzeGeoJson(layers);
  const suppliedStats = isRecord(visualization.stats) ? visualization.stats : {};
  const suppliedGeometryTypes = isRecord(suppliedStats.geometryTypes)
    ? Object.fromEntries(
      Object.entries(suppliedStats.geometryTypes)
        .filter((entry): entry is [string, number] => typeof entry[1] === "number" && Number.isFinite(entry[1]))
        .map(([key, count]) => [key, Math.max(0, Math.floor(count))]),
    )
    : undefined;

  return {
    id: optionalString(visualization.id) || "map-result",
    title: optionalString(visualization.title) || "Geospatial result",
    sourceTool: optionalString(visualization.sourceTool),
    layers,
    bounds: normalizeBounds(visualization.bounds) || analysis.bounds,
    crs: optionalString(visualization.crs) || "OGC:CRS84",
    warnings: Array.isArray(visualization.warnings)
      ? visualization.warnings.filter((warning): warning is string => typeof warning === "string" && Boolean(warning.trim()))
      : [],
    truncated: suppliedStats.truncated === true,
    featureCount: Math.max(0, Math.floor(finiteNumber(suppliedStats.featureCount) ?? analysis.featureCount)),
    coordinateCount: analysis.coordinateCount,
    geometryTypes: suppliedGeometryTypes || analysis.geometryTypes,
  };
}

function createDefaultStyle() {
  return {
    version: 8 as const,
    sources: {},
    layers: [{ id: "private-background", type: "background" as const, paint: { "background-color": "#07110f" } }],
  };
}

type MapStyleConfiguration = {
  mode: "configured" | "default" | "privacy";
  style: string | ReturnType<typeof createDefaultStyle>;
};

function configuredMapStyle(): MapStyleConfiguration {
  const environment = (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env;
  const explicitlyConfigured = Boolean(
    environment && Object.prototype.hasOwnProperty.call(environment, "VITE_MAP_STYLE_URL"),
  );
  if (explicitlyConfigured) {
    const configured = environment?.VITE_MAP_STYLE_URL?.trim();
    return configured
      ? { mode: "configured", style: configured }
      : { mode: "privacy", style: createDefaultStyle() };
  }
  return { mode: "default", style: DEFAULT_BASEMAP_STYLE_URL };
}

function escapeAttribution(value: string | undefined): string | undefined {
  if (!value) return undefined;
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function safeRemoteUrl(value: string | undefined): URL | undefined {
  if (!value) return undefined;
  try {
    const base = typeof window === "undefined" ? "https://local.invalid/" : window.location.href;
    const parsed = new URL(value, base);
    const sameOrigin = parsed.origin === new URL(base).origin;
    if (
      !["http:", "https:"].includes(parsed.protocol)
      || parsed.username
      || parsed.password
      || !sameOrigin
    ) {
      return undefined;
    }
    return parsed;
  } catch {
    return undefined;
  }
}

function safeTileTemplate(value: string | undefined): string | undefined {
  const url = safeRemoteUrl(value);
  if (!url) return undefined;
  const template = url.href.replace(/%7B(z|x|y|-y|ratio|quadkey)%7D/gi, (_match, token: string) => `{${token}}`);
  const hasZoom = /\{z\}/i.test(template);
  const hasColumn = /\{x\}|\{quadkey\}/i.test(template);
  const hasRow = /\{y\}|\{-y\}|\{quadkey\}/i.test(template);
  return hasZoom && hasColumn && hasRow ? template : undefined;
}

function formatRemoteLocation(value: string | undefined): string {
  const url = safeRemoteUrl(value);
  if (!url) return "Unavailable URL";
  const finalSegment = url.pathname.split("/").filter(Boolean).at(-1);
  let decodedSegment = finalSegment;
  if (finalSegment) {
    try {
      decodedSegment = decodeURIComponent(finalSegment);
    } catch {
      decodedSegment = finalSegment;
    }
  }
  return decodedSegment ? `${url.hostname} / ${decodedSegment.slice(0, 48)}` : url.hostname;
}

function layerCanRender(layer: NormalizedLayer): boolean {
  if (layer.kind === "vector" || layer.kind === "heatmap") {
    return Boolean(layer.data?.features.some((feature) => {
      let drawable = false;
      visitGeometry(feature.geometry, (geometry) => {
        if (geometry.type === "GeometryCollection") return;
        if (layer.kind === "heatmap" && !["Point", "MultiPoint"].includes(geometry.type)) return;
        walkCoordinatePairs(geometry.coordinates, (longitude, latitude) => {
          if (longitude >= -180 && longitude <= 180 && latitude >= -90 && latitude <= 90) {
            drawable = true;
          }
        });
      });
      return drawable;
    }));
  }
  if (layer.kind === "raster") return Boolean(safeRemoteUrl(layer.href) && layer.bounds);
  if (layer.kind === "tiles") return Boolean(safeTileTemplate(layer.href));
  return false;
}

function paddedBounds(bounds: Bounds): Bounds {
  const [west, south, east, north] = bounds;
  if (west !== east || south !== north) return bounds;
  const longitudePadding = Math.max(0.005, Math.abs(west) * 0.0001);
  const latitudePadding = Math.max(0.005, Math.abs(south) * 0.0001);
  return [west - longitudePadding, south - latitudePadding, east + longitudePadding, north + latitudePadding];
}

function fitMap(map: maplibregl.Map, bounds: Bounds | undefined, animate = true): void {
  if (!bounds) return;
  const motionAllowed = typeof window === "undefined"
    || !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  map.fitBounds(paddedBounds(bounds), {
    padding: { top: 54, right: 54, bottom: 54, left: 54 },
    duration: animate && motionAllowed ? 650 : 0,
    maxZoom: 14,
  });
}

function addLayerToMap(map: maplibregl.Map, layer: NormalizedLayer, namespace: string): { rendered: string[]; interactive: string[] } {
  if (map.getSource(layer.sourceId)) return { rendered: [], interactive: [] };
  const rendered: string[] = [];
  const interactive: string[] = [];
  const nextLayerId = (suffix: string) => `${namespace}-${layer.key}-${suffix}`;

  if ((layer.kind === "vector" || layer.kind === "heatmap") && layer.data) {
    map.addSource(layer.sourceId, { type: "geojson", data: layer.data as never });
    if (layer.kind === "heatmap") {
      const id = nextLayerId("heat");
      map.addLayer({
        id,
        type: "heatmap",
        source: layer.sourceId,
        maxzoom: 24,
        paint: {
          "heatmap-weight": [
            "case",
            ["has", "_heatmap_weight"],
            ["to-number", ["get", "_heatmap_weight"], 1],
            1,
          ],
          "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 0, 0.65, 14, 1.8],
          "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 0, layer.style.radius * 1.8, 14, layer.style.radius * 4],
          "heatmap-opacity": layer.style.opacity,
          "heatmap-color": [
            "interpolate", ["linear"], ["heatmap-density"],
            0, "rgba(7,17,15,0)",
            0.22, "#315f50",
            0.45, layer.style.color,
            0.72, "#f2d16b",
            1, "#ff765f",
          ],
        },
      });
      rendered.push(id);
      interactive.push(id);
      return { rendered, interactive };
    }

    const fillId = nextLayerId("fill");
    const lineId = nextLayerId("line");
    const pointHaloId = nextLayerId("point-halo");
    const pointId = nextLayerId("point");
    map.addLayer({
      id: fillId,
      type: "fill",
      source: layer.sourceId,
      paint: {
        "fill-color": layer.style.color,
        "fill-opacity": Math.min(layer.style.opacity, 0.54),
      },
    });
    map.addLayer({
      id: lineId,
      type: "line",
      source: layer.sourceId,
      paint: {
        "line-color": layer.style.color,
        "line-opacity": Math.min(1, layer.style.opacity + 0.18),
        "line-width": ["interpolate", ["linear"], ["zoom"], 3, 1.25, 14, 3],
      },
    });
    map.addLayer({
      id: pointHaloId,
      type: "circle",
      source: layer.sourceId,
      paint: {
        "circle-radius": layer.style.radius + 3,
        "circle-color": "rgba(7,17,15,0.84)",
        "circle-stroke-color": "rgba(255,255,255,0.16)",
        "circle-stroke-width": 1,
      },
    });
    map.addLayer({
      id: pointId,
      type: "circle",
      source: layer.sourceId,
      paint: {
        "circle-radius": layer.style.radius,
        "circle-color": layer.style.color,
        "circle-opacity": layer.style.opacity,
        "circle-stroke-color": "#07110f",
        "circle-stroke-width": 1.3,
      },
    });
    rendered.push(fillId, lineId, pointHaloId, pointId);
    interactive.push(fillId, lineId, pointId);
    return { rendered, interactive };
  }

  const remoteUrl = safeRemoteUrl(layer.href);
  if (!remoteUrl) throw new Error("This remote URL is not permitted.");
  const rasterId = nextLayerId("raster");
  if (layer.kind === "raster") {
    if (!layer.bounds) throw new Error("A georeferenced image requires a valid WGS84 bounding box.");
    const [west, south, east, north] = layer.bounds;
    map.addSource(layer.sourceId, {
      type: "image",
      url: remoteUrl.href,
      coordinates: [[west, north], [east, north], [east, south], [west, south]],
    });
  } else if (layer.kind === "tiles") {
    const tileTemplate = safeTileTemplate(layer.href);
    if (!tileTemplate) throw new Error("This tile URL is not permitted.");
    map.addSource(layer.sourceId, {
      type: "raster",
      tiles: [tileTemplate],
      tileSize: 256,
      attribution: escapeAttribution(layer.attribution),
    });
  } else {
    throw new Error("This layer cannot be rendered on the map.");
  }
  map.addLayer({
    id: rasterId,
    type: "raster",
    source: layer.sourceId,
    paint: { "raster-opacity": layer.style.opacity },
  });
  rendered.push(rasterId);
  return { rendered, interactive };
}

function stringifyProperty(value: unknown): string {
  if (value === null) return "null";
  if (value === undefined) return "—";
  if (typeof value === "string") return value.slice(0, MAX_PROPERTY_LENGTH);
  if (["number", "boolean", "bigint"].includes(typeof value)) return String(value);
  try {
    const serialized = JSON.stringify(value);
    return (serialized || String(value)).slice(0, MAX_PROPERTY_LENGTH);
  } catch {
    return "[unavailable value]";
  }
}

function sanitizeMapError(value: string): string {
  return value
    .replace(/https?:\/\/[^\s"')]+/gi, "[remote resource]")
    .replace(/[\r\n\t]+/g, " ")
    .slice(0, 180);
}

function selectedFeatureFromData(feature: {
  properties?: unknown;
  geometry?: { type?: unknown } | null;
  id?: unknown;
}, label: string): SelectedFeature {
  const properties = isRecord(feature.properties) ? feature.properties : {};
  const entries = Object.entries(properties);
  return {
    layer: label,
    geometry: optionalString(feature.geometry?.type) || "Geometry",
    id: typeof feature.id === "string" || typeof feature.id === "number" ? feature.id : undefined,
    properties: entries.slice(0, MAX_VISIBLE_PROPERTIES).map(([key, value]) => [key.slice(0, 120), stringifyProperty(value)]),
    omittedProperties: Math.max(0, entries.length - MAX_VISIBLE_PROPERTIES),
  };
}

function featureOptionLabel(feature: GeoJsonFeature, index: number): string {
  const properties = isRecord(feature.properties) ? feature.properties : {};
  const candidate = properties.name ?? properties.title ?? properties.label ?? feature.id;
  return candidate === undefined
    ? `Feature ${index + 1} · ${feature.geometry?.type || "Geometry"}`
    : `${stringifyProperty(candidate).slice(0, 80)} · ${feature.geometry?.type || "Geometry"}`;
}

function geometryLabel(value: string): string {
  return value.replace(/([a-z])([A-Z])/g, "$1 $2");
}

function formatCount(value: number): string {
  return new Intl.NumberFormat(undefined, { notation: value >= 10_000 ? "compact" : "standard" }).format(value);
}

function exportFileName(title: string): string {
  const base = title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 56);
  return `${base || "geospatial-result"}.geojson`;
}

export default function ResultMap({ visualization, className }: ResultMapProps) {
  const [namespace] = useState(makeNamespace);
  const normalized = useMemo(() => normalizeVisualization(visualization, namespace), [namespace, visualization]);
  const mapNode = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const renderedLayerIds = useRef(new Map<string, string[]>());
  const interactiveLayerIds = useRef<string[]>([]);
  const renderedIdLabels = useRef(new Map<string, string>());
  const [mapReady, setMapReady] = useState(false);
  const [mapLoading, setMapLoading] = useState(true);
  const [basemapState, setBasemapState] = useState<"loading" | "ready" | "privacy" | "unavailable">("loading");
  const [renderedResultLayerCount, setRenderedResultLayerCount] = useState(0);
  const [initialLayersProcessed, setInitialLayersProcessed] = useState(false);
  const [fatalError, setFatalError] = useState<string>();
  const [mapWarnings, setMapWarnings] = useState<string[]>([]);
  const [selectedFeature, setSelectedFeature] = useState<SelectedFeature>();
  const [visibleLayers, setVisibleLayers] = useState<Set<string>>(() => new Set());
  const [loadedRemoteLayers, setLoadedRemoteLayers] = useState<Set<string>>(() => new Set());
  const [loadingRemoteLayer, setLoadingRemoteLayer] = useState<string>();

  const vectorLayers = normalized.layers.filter((layer) => layer.kind === "vector" || layer.kind === "heatmap");
  const remoteLayers = normalized.layers.filter((layer) => layer.kind === "raster" || layer.kind === "tiles");
  const referenceLayers = normalized.layers.filter((layer) => layer.kind === "reference");
  const exportableLayers = vectorLayers.filter((layer) => layer.data);
  const hasMappableLayer = normalized.layers.some(layerCanRender);
  const visibleRenderedLayerCount = normalized.layers.filter((layer) =>
    visibleLayers.has(layer.key)
    && (renderedLayerIds.current.get(layer.key)?.length || 0) > 0
  ).length;
  const inspectableFeatures = useMemo(() => normalized.layers
    .filter((layer) => (layer.kind === "vector" || layer.kind === "heatmap") && layer.data)
    .flatMap((layer) => (layer.data?.features || []).map((feature) => ({ feature, layer: layer.label })))
    .slice(0, 100), [normalized]);

  useEffect(() => {
    setVisibleLayers(new Set(vectorLayers.filter(layerCanRender).map((layer) => layer.key)));
    setLoadedRemoteLayers(new Set());
    setLoadingRemoteLayer(undefined);
    setSelectedFeature(undefined);
    setRenderedResultLayerCount(0);
    setInitialLayersProcessed(false);
  }, [normalized]);

  useEffect(() => {
    if (!mapNode.current) return undefined;
    if (!hasMappableLayer) {
      setMapReady(false);
      setMapLoading(false);
      setBasemapState("unavailable");
      setRenderedResultLayerCount(0);
      setInitialLayersProcessed(true);
      setFatalError(undefined);
      return undefined;
    }
    setMapReady(false);
    setMapLoading(true);
    setBasemapState("loading");
    setRenderedResultLayerCount(0);
    setInitialLayersProcessed(false);
    setFatalError(undefined);
    setMapWarnings([]);
    renderedLayerIds.current.clear();
    interactiveLayerIds.current = [];
    renderedIdLabels.current.clear();

    let disposed = false;
    let styleFallbackAttempted = false;
    let baseStyleReady = false;
    let resultLayersAdded = false;
    let styleWatchdog: number | undefined;
    const styleConfiguration = configuredMapStyle();
    const usesRemoteStyle = styleConfiguration.mode !== "privacy";

    try {
      const map = new maplibregl.Map({
        container: mapNode.current,
        style: styleConfiguration.style,
        center: [0, 18],
        zoom: 1.25,
        minZoom: 0,
        attributionControl: false,
        cooperativeGestures: true,
      });
      mapRef.current = map;
      map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
      map.addControl(new maplibregl.ScaleControl({ maxWidth: 110, unit: "metric" }), "bottom-left");
      map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");

      const appendMapWarning = (message: string) => {
        if (disposed) return;
        setMapWarnings((current) => current.includes(message) ? current : [...current, message].slice(-3));
      };
      const clearStyleWatchdog = () => {
        if (styleWatchdog !== undefined) {
          window.clearTimeout(styleWatchdog);
          styleWatchdog = undefined;
        }
      };
      const scheduleLocalCanvasWatchdog = () => {
        clearStyleWatchdog();
        styleWatchdog = window.setTimeout(() => {
          styleWatchdog = undefined;
          if (disposed || baseStyleReady) return;
          setMapReady(false);
          setMapLoading(false);
          setBasemapState("unavailable");
          setFatalError("The local map canvas could not become ready. Result metadata and downloads remain available.");
        }, LOCAL_CANVAS_LOAD_TIMEOUT_MS);
      };
      const fallbackToSafeCanvas = (reason: string): boolean => {
        if (disposed || !usesRemoteStyle || styleFallbackAttempted) return false;
        styleFallbackAttempted = true;
        clearStyleWatchdog();
        baseStyleReady = false;
        resultLayersAdded = false;
        renderedLayerIds.current.clear();
        interactiveLayerIds.current = [];
        renderedIdLabels.current.clear();
        setRenderedResultLayerCount(0);
        setInitialLayersProcessed(false);
        setMapReady(false);
        setMapLoading(true);
        setBasemapState("unavailable");
        appendMapWarning(`${reason} Results are shown on the local privacy canvas without basemap context.`);
        try {
          map.setStyle(createDefaultStyle());
          if (!baseStyleReady) scheduleLocalCanvasWatchdog();
          return true;
        } catch (error) {
          const detail = error instanceof Error
            ? sanitizeMapError(error.message)
            : "The local map canvas could not be initialized.";
          setFatalError(detail);
          setMapLoading(false);
          return false;
        }
      };

      if (styleConfiguration.mode === "privacy") {
        appendMapWarning("Basemap network access is disabled by configuration. Results are shown on the local privacy canvas.");
        scheduleLocalCanvasWatchdog();
      } else {
        styleWatchdog = window.setTimeout(() => {
          fallbackToSafeCanvas("The basemap did not become ready within 8 seconds.");
        }, MAP_STYLE_LOAD_TIMEOUT_MS);
      }

      const onMapError = (event: maplibregl.ErrorEvent) => {
        const detail = event.error instanceof Error
          ? sanitizeMapError(event.error.message)
          : "A map resource could not be loaded.";
        const eventRecord = event as unknown as JsonRecord;
        const sourceId = optionalString(eventRecord.sourceId)
          || optionalString(isRecord(eventRecord.source) ? eventRecord.source.id : undefined);
        const resultSourceIds = new Set(remoteLayers.map((layer) => layer.sourceId));
        if (sourceId && resultSourceIds.has(sourceId)) {
          appendMapWarning(detail || "A remote result layer could not be loaded.");
          return;
        }
        if (fallbackToSafeCanvas(
          baseStyleReady
            ? "A basemap tile or source failed to load."
            : "The basemap style failed to load.",
        )) {
          return;
        }
        appendMapWarning(detail || "A map resource could not be loaded.");
      };

      const addInitialLayers = () => {
        if (disposed || resultLayersAdded) return;
        resultLayersAdded = true;
        let renderedResults = 0;
        for (const layer of vectorLayers) {
          if (!layerCanRender(layer)) continue;
          try {
            const added = addLayerToMap(map, layer, namespace);
            renderedLayerIds.current.set(layer.key, added.rendered);
            if (added.rendered.length > 0) renderedResults += 1;
            interactiveLayerIds.current.push(...added.interactive);
            for (const id of added.interactive) renderedIdLabels.current.set(id, layer.label);
          } catch (error) {
            appendMapWarning(`${layer.label}: ${(error as Error).message}`);
          }
        }
        if (renderedResults > 0) fitMap(map, normalized.bounds, false);
        setRenderedResultLayerCount(renderedResults);
        setInitialLayersProcessed(true);
        setMapReady(true);
        setMapLoading(false);
      };

      const onStyleLoad = () => {
        baseStyleReady = true;
        clearStyleWatchdog();
        if (styleFallbackAttempted) {
          setBasemapState("unavailable");
        } else if (styleConfiguration.mode === "privacy") {
          setBasemapState("privacy");
        } else {
          setBasemapState("loading");
          styleWatchdog = window.setTimeout(() => {
            fallbackToSafeCanvas("The basemap sources did not become ready within 5 seconds.");
          }, BASEMAP_RESOURCE_TIMEOUT_MS);
        }
        if (!resultLayersAdded && map.isStyleLoaded()) addInitialLayers();
      };
      const onMapIdle = () => {
        if (
          disposed
          || !baseStyleReady
          || styleFallbackAttempted
          || styleConfiguration.mode === "privacy"
        ) return;
        clearStyleWatchdog();
        setBasemapState("ready");
      };
      const onMapClick = (event: maplibregl.MapMouseEvent) => {
        const ids = interactiveLayerIds.current.filter((id) => Boolean(map.getLayer(id)));
        if (!ids.length) {
          setSelectedFeature(undefined);
          return;
        }
        const features = map.queryRenderedFeatures(event.point, { layers: ids });
        const feature = features[0];
        if (!feature) {
          setSelectedFeature(undefined);
          return;
        }
        setSelectedFeature(selectedFeatureFromData(feature, renderedIdLabels.current.get(feature.layer.id) || "Result layer"));
      };
      const onMapMouseMove = (event: maplibregl.MapMouseEvent) => {
        const ids = interactiveLayerIds.current.filter((id) => Boolean(map.getLayer(id)));
        map.getCanvas().style.cursor = ids.length && map.queryRenderedFeatures(event.point, { layers: ids }).length
          ? "pointer"
          : "";
      };

      map.on("error", onMapError);
      map.on("load", addInitialLayers);
      map.on("style.load", onStyleLoad);
      map.on("idle", onMapIdle);
      map.on("click", onMapClick);
      map.on("mousemove", onMapMouseMove);
      if (map.isStyleLoaded()) onStyleLoad();

      const resizeObserver = typeof ResizeObserver === "undefined" ? undefined : new ResizeObserver(() => map.resize());
      if (resizeObserver && mapNode.current) resizeObserver.observe(mapNode.current);

      return () => {
        disposed = true;
        clearStyleWatchdog();
        resizeObserver?.disconnect();
        map.off("error", onMapError);
        map.off("load", addInitialLayers);
        map.off("style.load", onStyleLoad);
        map.off("idle", onMapIdle);
        map.off("click", onMapClick);
        map.off("mousemove", onMapMouseMove);
        mapRef.current = null;
        renderedLayerIds.current.clear();
        interactiveLayerIds.current = [];
        renderedIdLabels.current.clear();
        map.remove();
      };
    } catch (error) {
      if (styleWatchdog !== undefined) window.clearTimeout(styleWatchdog);
      try {
        mapRef.current?.remove();
      } catch {
        // Preserve the original initialization error in the visible fallback.
      }
      const detail = error instanceof Error
        ? sanitizeMapError(error.message)
        : "The browser could not initialize the map engine.";
      setFatalError(
        detail
          ? `The interactive map could not be started in this browser: ${detail}`
          : "The interactive map could not be started in this browser.",
      );
      setBasemapState("unavailable");
      setMapLoading(false);
      mapRef.current = null;
      return undefined;
    }
  }, [namespace, normalized]);

  const toggleLayer = (layer: NormalizedLayer) => {
    const renderedIds = renderedLayerIds.current.get(layer.key) || [];
    const isVisible = visibleLayers.has(layer.key);
    const nextVisibility = isVisible ? "none" : "visible";
    for (const id of renderedIds) {
      if (mapRef.current?.getLayer(id)) mapRef.current.setLayoutProperty(id, "visibility", nextVisibility);
    }
    setVisibleLayers((current) => {
      const next = new Set(current);
      if (isVisible) next.delete(layer.key);
      else next.add(layer.key);
      return next;
    });
    if (isVisible && selectedFeature?.layer === layer.label) setSelectedFeature(undefined);
  };

  const loadRemoteLayer = (layer: NormalizedLayer) => {
    const map = mapRef.current;
    if (!map || !mapReady || loadingRemoteLayer) return;
    setLoadingRemoteLayer(layer.key);
    try {
      const wasLoaded = renderedLayerIds.current.has(layer.key);
      const added = addLayerToMap(map, layer, namespace);
      renderedLayerIds.current.set(layer.key, added.rendered);
      interactiveLayerIds.current.push(...added.interactive);
      for (const id of added.interactive) renderedIdLabels.current.set(id, layer.label);
      setLoadedRemoteLayers((current) => new Set(current).add(layer.key));
      setVisibleLayers((current) => new Set(current).add(layer.key));
      if (added.rendered.length > 0 && !wasLoaded) {
        setRenderedResultLayerCount((current) => current + 1);
      }
      if (layer.bounds) fitMap(map, layer.bounds);
    } catch (error) {
      const message = `${layer.label}: ${(error as Error).message}`;
      setMapWarnings((current) => current.includes(message) ? current : [...current, message].slice(-3));
    } finally {
      setLoadingRemoteLayer(undefined);
    }
  };

  const exportGeoJson = () => {
    if (!exportableLayers.length) return;
    const features = exportableLayers.flatMap((layer) =>
      (layer.data?.features || []).map((feature) => ({
        ...feature,
        properties: {
          ...(isRecord(feature.properties) ? feature.properties : {}),
          _map_layer: layer.label,
        },
      })),
    );
    const blob = new Blob([JSON.stringify({ type: "FeatureCollection", features }, null, 2)], {
      type: "application/geo+json;charset=utf-8",
    });
    const href = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = exportFileName(normalized.title);
    anchor.hidden = true;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(href), 1_000);
  };

  const allWarnings = normalized.truncated
    ? [...normalized.warnings, "This preview is truncated; the exported map may not contain the complete source result."]
    : normalized.warnings;

  return (
    <section className={`result-map ${className || ""}`} aria-label={`Map: ${normalized.title}`}>
      <span className="result-map__sr-status" aria-live="polite">
        {visibleRenderedLayerCount > 0
          ? `Result map ready with ${visibleRenderedLayerCount} visible result ${visibleRenderedLayerCount === 1 ? "layer" : "layers"} and ${normalized.featureCount} features.`
          : mapReady
            ? "The map engine is ready, but no result layer is rendered."
            : "Preparing the map engine."}
      </span>
      <header className="result-map__header">
        <div className="result-map__heading">
          <span className="result-map__eyebrow"><MapPin size={12} /> Process output</span>
          <h3>{normalized.title}</h3>
          {normalized.sourceTool && <span className="result-map__source">via {normalized.sourceTool}</span>}
        </div>
        <div className="result-map__actions">
          <button
            type="button"
            className="result-map__button"
            onClick={() => mapRef.current && fitMap(mapRef.current, normalized.bounds)}
            disabled={!mapReady || visibleRenderedLayerCount === 0 || !normalized.bounds}
            title="Fit the map to all result data"
          >
            <LocateFixed size={14} /> Fit results
          </button>
          <button
            type="button"
            className="result-map__button result-map__button--accent"
            onClick={exportGeoJson}
            disabled={!exportableLayers.length}
            title="Download all vector layers as GeoJSON"
          >
            <Download size={14} /> GeoJSON
          </button>
        </div>
      </header>

      <div className="result-map__stats" aria-label="Result statistics">
        <span><strong>{formatCount(normalized.featureCount)}</strong> features</span>
        <span><strong>{formatCount(normalized.coordinateCount)}</strong> coordinates</span>
        <span><strong>{visibleRenderedLayerCount}</strong> visible result {visibleRenderedLayerCount === 1 ? "layer" : "layers"}</span>
        {renderedResultLayerCount !== visibleRenderedLayerCount && (
          <span><strong>{renderedResultLayerCount}</strong> loaded</span>
        )}
        <span>
          Basemap · <strong>
            {basemapState === "privacy" ? "privacy canvas" : basemapState}
          </strong>
        </span>
        {Object.entries(normalized.geometryTypes).slice(0, 4).map(([geometry, count]) => (
          <span className="result-map__geometry-stat" key={geometry}>{geometryLabel(geometry)} · {formatCount(count)}</span>
        ))}
      </div>

      {(allWarnings.length > 0 || mapWarnings.length > 0) && (
        <div className="result-map__warnings" role="status">
          <AlertTriangle size={15} aria-hidden="true" />
          <div>
            {[...allWarnings, ...mapWarnings].map((warning, index) => <p key={`${warning}-${index}`}>{warning}</p>)}
          </div>
        </div>
      )}

      <div className="result-map__workspace">
        <div className="result-map__canvas-wrap">
          <div ref={mapNode} className="result-map__canvas" aria-label="Interactive geospatial result map" />
          {mapLoading && !fatalError && (
            <div className="result-map__loading" role="status">
              <span className="result-map__spinner" /> Preparing map engine
            </div>
          )}
          {fatalError && (
            <div className="result-map__fallback" role="alert">
              <div><AlertTriangle size={21} /></div>
              <strong>Map preview unavailable</strong>
              <p>{fatalError}</p>
              <p>Layer metadata and downloads remain available.</p>
            </div>
          )}
          {!mapLoading && !fatalError && !hasMappableLayer && (
            <div className="result-map__empty-map">
              <Layers size={20} />
              <strong>No directly mappable layer</strong>
              <span>Use the reference downloads to inspect this process output.</span>
            </div>
          )}
          {!mapLoading
            && !fatalError
            && hasMappableLayer
            && initialLayersProcessed
            && renderedResultLayerCount === 0 && (
            <div className="result-map__empty-map" role="status">
              <Layers size={20} />
              <strong>{remoteLayers.some(layerCanRender) ? "Result layer not loaded yet" : "No result layer could be rendered"}</strong>
              <span>
                {remoteLayers.some(layerCanRender)
                  ? "Use the Layers panel to load the validated remote result. The basemap alone is not treated as a completed map."
                  : "The map remains covered because zero validated output layers were added."}
              </span>
            </div>
          )}
          {!mapLoading
            && !fatalError
            && renderedResultLayerCount > 0
            && visibleRenderedLayerCount === 0 && (
            <div className="result-map__empty-map" role="status">
              <EyeOff size={20} />
              <strong>All result layers are hidden</strong>
              <span>Show a layer in the Layers panel to restore the result map.</span>
            </div>
          )}
          {visibleRenderedLayerCount > 0 && !fatalError && <div className="result-map__map-hint">Scroll + ⌘/Ctrl to zoom</div>}
        </div>

        <aside className="result-map__sidebar" aria-label="Map layers and feature details">
          <div className="result-map__panel-heading">
            <span><Layers size={14} /> Layers</span>
            <small>{normalized.layers.length}</small>
          </div>
          <div className="result-map__layer-list">
            {normalized.layers.length === 0 && <p className="result-map__muted">No layers were returned.</p>}
            {[...vectorLayers, ...remoteLayers].map((layer) => {
              const loaded = layer.kind === "vector" || layer.kind === "heatmap" || loadedRemoteLayers.has(layer.key);
              const visible = visibleLayers.has(layer.key);
              const renderable = layerCanRender(layer);
              return (
                <div className="result-map__layer" key={layer.key}>
                  <span
                    className={`result-map__swatch ${layer.kind === "heatmap" ? "result-map__swatch--heat" : ""}`}
                    style={{
                      background: layer.kind === "heatmap"
                        ? `linear-gradient(135deg, #315f50, ${layer.style.color}, #f2d16b, #ff765f)`
                        : layer.style.color,
                    }}
                    aria-hidden="true"
                  />
                  <div className="result-map__layer-copy">
                    <strong>{layer.label}</strong>
                    <span>{layer.description || (layer.kind === "raster" ? "Georeferenced image" : layer.kind === "tiles" ? "XYZ raster tiles" : `${geometryLabel(layer.kind)} data`)}</span>
                    {(layer.kind === "raster" || layer.kind === "tiles") && (
                      <small title={formatRemoteLocation(layer.href)}>{formatRemoteLocation(layer.href)}</small>
                    )}
                  </div>
                  {loaded ? (
                    <button
                      type="button"
                      className="result-map__icon-button"
                      onClick={() => toggleLayer(layer)}
                      disabled={!renderable}
                      aria-label={`${visible ? "Hide" : "Show"} ${layer.label}`}
                      title={`${visible ? "Hide" : "Show"} layer`}
                    >
                      {visible ? <Eye size={15} /> : <EyeOff size={15} />}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="result-map__load-button"
                      onClick={() => loadRemoteLayer(layer)}
                      disabled={!renderable || !mapReady || Boolean(loadingRemoteLayer)}
                      title={!renderable ? "This URL or bounding box is not safe to load" : "Load this external resource into the map"}
                    >
                      {loadingRemoteLayer === layer.key ? <RotateCcw className="result-map__spin" size={12} /> : <Download size={12} />}
                      {renderable ? "Load layer" : "Blocked"}
                    </button>
                  )}
                </div>
              );
            })}
          </div>

          {selectedFeature ? (
            <div className="result-map__feature">
              <div className="result-map__panel-heading">
                <span><MapPin size={14} /> Selected feature</span>
                <button type="button" onClick={() => setSelectedFeature(undefined)} aria-label="Close selected feature"><X size={14} /></button>
              </div>
              <div className="result-map__feature-meta">
                <strong>{selectedFeature.layer}</strong>
                <span>{geometryLabel(selectedFeature.geometry)}{selectedFeature.id !== undefined ? ` · ID ${selectedFeature.id}` : ""}</span>
              </div>
              {selectedFeature.properties.length ? (
                <dl className="result-map__properties">
                  {selectedFeature.properties.map(([key, value], index) => (
                  <div key={`${key}-${index}`}>
                    <dt title={key}>{key}</dt>
                    <dd>{value}</dd>
                  </div>
                  ))}
                </dl>
              ) : <p className="result-map__muted">This feature has no properties.</p>}
              {selectedFeature.omittedProperties > 0 && (
                <p className="result-map__muted">{selectedFeature.omittedProperties} additional properties omitted from the preview.</p>
              )}
            </div>
          ) : (
            <div className="result-map__selection-hint">
              <MapPin size={15} />
              <div>
                <span>Select a point, line, or area to inspect its properties.</span>
                {inspectableFeatures.length > 0 && (
                  <label className="result-map__feature-picker">
                    <span>Keyboard feature list</span>
                    <select
                      value=""
                      onChange={(event) => {
                        const index = Number(event.target.value);
                        const selected = inspectableFeatures[index];
                        if (selected) setSelectedFeature(selectedFeatureFromData(selected.feature, selected.layer));
                      }}
                    >
                      <option value="">Choose a feature…</option>
                      {inspectableFeatures.map(({ feature, layer }, index) => (
                        <option key={`${layer}-${feature.id ?? index}-${index}`} value={index}>
                          {layer}: {featureOptionLabel(feature, index)}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
              </div>
            </div>
          )}

          {referenceLayers.length > 0 && (
            <div className="result-map__references">
              <div className="result-map__panel-heading">
                <span><Download size={14} /> References</span>
                <small>{referenceLayers.length}</small>
              </div>
              {referenceLayers.map((layer) => {
                const href = safeRemoteUrl(layer.href)?.href;
                return href ? (
                  <a key={layer.key} href={href} target="_blank" rel="noopener noreferrer" download>
                    <span><strong>{layer.label}</strong><small>{layer.format || formatRemoteLocation(href)}</small></span>
                    <Download size={13} />
                  </a>
                ) : (
                  <div className="result-map__reference-disabled" key={layer.key}>
                    <span><strong>{layer.label}</strong><small>Unsafe or unavailable URL</small></span>
                    <AlertTriangle size={13} />
                  </div>
                );
              })}
            </div>
          )}

          <div className="result-map__ready-note">
            {visibleRenderedLayerCount > 0 ? <Check size={12} /> : <AlertTriangle size={12} />}
            {normalized.crs} · {visibleRenderedLayerCount > 0
              ? `${visibleRenderedLayerCount} result ${visibleRenderedLayerCount === 1 ? "layer" : "layers"} visible`
              : "0 result layers rendered"}
          </div>
        </aside>
      </div>
    </section>
  );
}

export type { ResultMapProps };
