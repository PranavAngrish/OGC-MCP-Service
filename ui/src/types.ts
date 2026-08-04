import type { FeatureCollection, GeoJsonProperties, Geometry } from "geojson";

export type ActivityStatus = "running" | "waiting" | "complete" | "error" | "cancelled";

export type Activity = {
  id: string;
  kind: "status" | "reasoning" | "tool" | "artifact";
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
  artifactStage?: ArtifactWorkflowStage;
  manifestId?: string;
  outputId?: string;
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
  outputManifests?: OutputManifestV1[];
  approvalRequests?: ApprovalRequest[];
};

export type ApprovalRequest = {
  challengeId: string;
  planId: string;
  serverId: string;
  executeRequest: unknown;
  inputContext: unknown;
  steps: unknown[];
  digest: string;
  expiresAt: string;
  status: "pending" | "submitting" | "approved" | "rejected" | "error";
  error?: string;
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

export type OutputOverallState = "pending" | "ready" | "partial" | "unavailable";
export type OutputExecutionState =
  | "awaiting_input"
  | "awaiting_approval"
  | "submitted"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";
export type ArtifactState =
  | "pending"
  | "preparing"
  | "resolving"
  | "running"
  | "retrieved"
  | "recognized"
  | "converted"
  | "ready"
  | "complete"
  | "partial"
  | "empty"
  | "unresolved"
  | "ambiguous"
  | "blocked"
  | "failed"
  | "unavailable"
  | "unsupported"
  | "skipped";
export type ArtifactWorkflowStage =
  | "submitted"
  | "monitoring"
  | "retrieval"
  | "detection"
  | "interpretation"
  | "conversion"
  | "presentation"
  | "storage"
  | "complete"
  | (string & {});
export type OutputSemanticType =
  | "vector"
  | "raster"
  | "coverage"
  | "tiles"
  | "table"
  | "timeseries"
  | "scalar"
  | "image"
  | "document"
  | "binary"
  | "unknown"
  | (string & {});
export type OutputPresentationKind =
  | "map"
  | "table"
  | "metric"
  | "chart"
  | "text"
  | "image"
  | "download"
  | (string & {});

export type OutputCrs = {
  value?: string;
  status: "declared" | "inferred" | "missing" | "unsupported" | (string & {});
  axisOrder?: string;
  nativeValue?: string;
};

export type OutputUnit = {
  quantity?: string;
  value?: string;
  status: "declared" | "missing" | (string & {});
};

export type OutputError = {
  code: string;
  message: string;
  phase?: string;
  retryable?: boolean;
};

export type OutputRetrieval = {
  state: ArtifactState;
  source: "inline" | "reference" | "memory" | (string & {});
  declaredMediaType?: string;
  detectedMediaType?: string;
  bytes?: number;
  httpStatus?: number;
  redirectCount?: number;
  error?: OutputError;
};

export type OutputInterpretation = {
  state: ArtifactState;
  semanticType: OutputSemanticType;
  format?: string;
  crs?: OutputCrs;
  bbox?: MapBounds;
  featureCount?: number;
  rowCount?: number;
  geometryTypes?: string[];
  units?: OutputUnit[];
  warnings?: string[];
  error?: OutputError;
};

export type OutputRepresentation = {
  id: string;
  role: "original" | "canonical" | "preview" | "tiles" | (string & {});
  mediaType: string;
  handle?: string;
  href?: string;
  sizeBytes?: number;
  encoding?: string;
  data?: unknown;
};

export type OutputPresentation = {
  id: string;
  kind: OutputPresentationKind;
  state: ArtifactState;
  artifactRef?: string;
  reason?: string;
};

export type OutputProvenance = {
  serverId: string;
  requestPath?: string;
  retrievedAt?: string;
  parser?: string;
  transformations?: string[];
  sha256?: string;
  [key: string]: unknown;
};

export type OutputClarificationIssue = {
  id: string;
  kind:
    | "unit"
    | "crs"
    | "axis_order"
    | "input"
    | "output_format"
    | "presentation"
    | "remote_fetch"
    | (string & {});
  fieldPath: string;
  question: string;
  whyItMatters: string;
  observedValue?: unknown;
  allowFreeText?: boolean;
};

export type OutputClarificationRequest = {
  blocking: boolean;
  scope: "execution" | "interpretation" | "presentation" | (string & {});
  issues: OutputClarificationIssue[];
};

export type OutputArtifact = {
  id: string;
  title: string;
  description?: string;
  status: ArtifactState;
  retrieval: OutputRetrieval;
  interpretation: OutputInterpretation;
  representations?: OutputRepresentation[];
  presentations: OutputPresentation[];
  provenance: OutputProvenance;
  warnings?: string[];
  clarificationRequest?: OutputClarificationRequest;
};

export type OutputManifestV1 = {
  schemaVersion: "ogc-output-manifest/1";
  manifestId: string;
  execution: {
    state: OutputExecutionState;
    serverId: string;
    processId?: string;
    planId?: string;
    jobId?: string;
    reportedStatus?: string;
  };
  overallState: OutputOverallState;
  outputs: OutputArtifact[];
  warnings?: string[];
};

export type ArtifactStatusEventData = {
  targetMessageId?: string;
  activityId?: string;
  manifestId: string;
  outputId: string;
  stage: ArtifactWorkflowStage;
  status: ArtifactState | ActivityStatus | string;
  detail?: string;
  timestamp?: string;
};

export type WorkflowEventV2 = {
  schemaVersion: "activity/2";
  eventId: string;
  sequence: number;
  sessionId: string;
  turnId: string;
  targetMessageId: string;
  runId?: string;
  activityId: string;
  timestamp: string;
  type:
    | "intent_recognized"
    | "decision_recorded"
    | "step_started"
    | "step_completed"
    | "clarification_required"
    | "approval_required"
    | "job_progress"
    | "output_manifest_upserted"
    | "presentation_status"
    | "workflow_completed"
    | "workflow_failed";
  payload: Record<string, unknown>;
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
