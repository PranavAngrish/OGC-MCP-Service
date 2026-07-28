import type { FeatureCollection, GeoJsonProperties, Geometry } from "geojson";

export type ActivityStatus = "running" | "waiting" | "complete" | "error" | "cancelled";

export type Activity = {
  id: string;
  kind: "status" | "reasoning" | "tool";
  title: string;
  detail?: string;
  status: ActivityStatus;
  toolName?: string;
  arguments?: unknown;
  resultPreview?: string;
  purpose?: string;
  outputSummary?: string;
  result?: unknown;
  warnings?: string[];
  startedAt?: string;
  completedAt?: string;
  durationMs?: number;
  round?: number;
};

export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: Date;
  pending?: boolean;
  error?: string;
  activities?: Activity[];
  maps?: MapVisualization[];
};

export type MapBounds = [west: number, south: number, east: number, north: number];

export type MapLayerKind = "vector" | "heatmap" | "raster" | "tiles" | "reference";

export type MapLayer = {
  id: string;
  label: string;
  kind: MapLayerKind;
  description?: string;
  data?: FeatureCollection<Geometry, GeoJsonProperties>;
  href?: string;
  bounds?: MapBounds;
  format?: string;
  attribution?: string;
  crs?: string;
  units?: string;
  time?: string;
  featureCount?: number;
  style?: {
    color?: string;
    opacity?: number;
    radius?: number;
  };
};

export type MapVisualization = {
  id: string;
  title: string;
  sourceTool?: string;
  layers: MapLayer[];
  bounds?: MapBounds;
  crs?: string;
  warnings?: string[];
  stats?: {
    featureCount?: number;
    geometryTypes?: Record<string, number>;
    layerCount?: number;
    truncated?: boolean;
  };
};

export type GatewayHealth = {
  ok: boolean;
  model?: string;
  provider?: string;
  mcpConnected?: boolean;
  providerConfigured?: boolean;
  toolCount?: number;
  backgroundJobs?: number;
  error?: string;
};

export type StreamEvent = {
  event: string;
  data: Record<string, unknown>;
};
