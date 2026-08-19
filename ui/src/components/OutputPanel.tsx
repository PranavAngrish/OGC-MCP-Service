import {
  AlertTriangle,
  BarChart3,
  Check,
  ChevronDown,
  CircleEllipsis,
  Database,
  Download,
  File,
  FileImage,
  FileText,
  Grid3X3,
  Layers,
  LoaderCircle,
  MapPinned,
  PackageCheck,
  Sigma,
} from "lucide-react";
import {
  lazy,
  Suspense,
  type ComponentType,
  type ReactNode,
  useId,
  useMemo,
} from "react";
import type {
  OutputArtifact,
  OutputManifestV1,
  OutputPresentation,
  OutputRepresentation,
} from "../types";
import {
  formatBytes,
  humanizeOutputState,
  mapVisualizationForPresentation,
  mapVisualizationHasDrawableLayer,
  printableValue,
  representationForPresentation,
  safeArtifactHref,
  safeImageHref,
  tableFromRepresentation,
} from "../lib/outputs";
import "./OutputPanel.css";

const ResultMap = lazy(() => import("./ResultMap"));

type RendererProps = {
  output: OutputArtifact;
  presentation: OutputPresentation;
  representation?: OutputRepresentation;
};

type Renderer = ComponentType<RendererProps>;

const compactCell = (value: unknown): string => {
  if (value === null) return "None";
  if (value === undefined) return "—";
  if (typeof value === "string") return value.length > 180 ? `${value.slice(0, 179)}…` : value;
  if (["number", "boolean", "bigint"].includes(typeof value)) return String(value);
  try {
    const serialized = JSON.stringify(value);
    return serialized.length > 180 ? `${serialized.slice(0, 179)}…` : serialized;
  } catch {
    return "[unavailable]";
  }
};

function MapRenderer({ output, presentation }: RendererProps) {
  const visualization = useMemo(
    () => mapVisualizationForPresentation(output, presentation),
    [output, presentation],
  );
  if (!mapVisualizationHasDrawableLayer(visualization, true)) {
    return (
      <div className="output-presentation-fallback output-presentation-fallback--map" role="status">
        <MapPinned size={22} aria-hidden="true" />
        <div>
          <strong>No validated result layer to draw</strong>
          <p>
            The output is still available below, but a map is not mounted until at least one
            valid geometry, georeferenced raster, or tile layer is present.
          </p>
        </div>
      </div>
    );
  }
  return (
    <Suspense fallback={<div className="output-renderer-loading" role="status">Preparing validated map preview…</div>}>
      <ResultMap visualization={visualization!} className="result-map--artifact" />
    </Suspense>
  );
}

function TableRenderer({ output, representation }: RendererProps) {
  const table = tableFromRepresentation(representation?.data);
  if (!table) {
    return (
      <div className="output-presentation-fallback">
        <Grid3X3 size={20} aria-hidden="true" />
        <div>
          <strong>Table preview unavailable</strong>
          <p>{output.interpretation.rowCount === 0 ? "The output contains no rows." : "No bounded tabular preview was provided."}</p>
        </div>
      </div>
    );
  }
  return (
    <div className="output-table-wrap" tabIndex={0} role="region" aria-label={`${output.title} table`} >
      <table className="output-table">
        <thead>
          <tr>{table.columns.map((column) => <th scope="col" key={column}>{column}</th>)}</tr>
        </thead>
        <tbody>
          {table.rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {table.columns.map((column) => <td key={column}>{compactCell(row[column])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      {(table.truncated || output.interpretation.rowCount && output.interpretation.rowCount > table.rows.length) ? (
        <p className="output-preview-note">
          Showing {table.rows.length} of {output.interpretation.rowCount || table.totalRows} rows in this bounded preview.
        </p>
      ) : null}
    </div>
  );
}

function MetricRenderer({ output, representation }: RendererProps) {
  const value = representation?.data;
  if (value === undefined) {
    return (
      <div className="output-presentation-fallback">
        <Sigma size={20} aria-hidden="true" />
        <div><strong>Metric preview unavailable</strong><p>The scalar output is stored, but no bounded inline value was provided.</p></div>
      </div>
    );
  }
  const entries: Array<[string, unknown]> = value !== null && typeof value === "object" && !Array.isArray(value)
    ? Object.entries(value as Record<string, unknown>).slice(0, 12)
    : [["Value", value] as [string, unknown]];
  return (
    <dl className="output-metrics" aria-label={`${output.title} metrics`}>
      {entries.map(([label, metric]) => (
        <div key={label}>
          <dt>{humanizeOutputState(label)}</dt>
          <dd>{compactCell(metric)}</dd>
        </div>
      ))}
    </dl>
  );
}

type ChartSeries = {
  name: string;
  values: Array<number | null>;
};

type ChartData = {
  labels: string[];
  series: ChartSeries[];
  truncated: boolean;
};

function boundedChartData(value: unknown): ChartData | null {
  const MAX_POINTS = 80;
  const MAX_SERIES = 4;
  if (!Array.isArray(value) || value.length < 2) return null;
  const rows = value.slice(0, MAX_POINTS);
  if (rows.every((item) => typeof item === "number" && Number.isFinite(item))) {
    return {
      labels: rows.map((_item, index) => String(index + 1)),
      series: [{ name: "Value", values: rows as number[] }],
      truncated: value.length > rows.length,
    };
  }
  if (!rows.every((item) => item !== null && typeof item === "object" && !Array.isArray(item))) {
    return null;
  }
  const records = rows as Array<Record<string, unknown>>;
  const keys = [...new Set(records.flatMap((record) => Object.keys(record)))].slice(0, 30);
  const numericKeys = keys.filter((key) =>
    records.some((record) => typeof record[key] === "number" && Number.isFinite(record[key]))
  ).slice(0, MAX_SERIES);
  if (!numericKeys.length) return null;
  const labelKey = keys.find((key) =>
    !numericKeys.includes(key)
    && records.some((record) => ["string", "number"].includes(typeof record[key]))
  );
  return {
    labels: records.map((record, index) => compactCell(labelKey ? record[labelKey] : index + 1).slice(0, 32)),
    series: numericKeys.map((key) => ({
      name: humanizeOutputState(key),
      values: records.map((record) =>
        typeof record[key] === "number" && Number.isFinite(record[key])
          ? record[key] as number
          : null
      ),
    })),
    truncated: value.length > rows.length,
  };
}

function ChartRenderer({ output, representation }: RendererProps) {
  const chartTitleId = useId();
  const chartDescriptionId = useId();
  const chart = boundedChartData(representation?.data);
  if (!chart) {
    return (
      <div className="output-presentation-fallback">
        <BarChart3 size={20} aria-hidden="true" />
        <div><strong>Chart preview unavailable</strong><p>No bounded numeric time series was provided for this chart.</p></div>
      </div>
    );
  }
  const width = 720;
  const height = 280;
  const inset = { top: 22, right: 22, bottom: 38, left: 56 };
  const plotWidth = width - inset.left - inset.right;
  const plotHeight = height - inset.top - inset.bottom;
  const numericValues = chart.series.flatMap((series) =>
    series.values.filter((value): value is number => value !== null)
  );
  let minimum = Math.min(...numericValues);
  let maximum = Math.max(...numericValues);
  if (minimum === maximum) {
    const padding = Math.max(1, Math.abs(minimum) * 0.05);
    minimum -= padding;
    maximum += padding;
  }
  const pointX = (index: number) =>
    inset.left + (chart.labels.length === 1 ? plotWidth / 2 : index / (chart.labels.length - 1) * plotWidth);
  const pointY = (value: number) =>
    inset.top + (maximum - value) / (maximum - minimum) * plotHeight;
  const colors = ["#b9e66c", "#70d6ad", "#8cb8ff", "#f2a765"];
  const ticks = Array.from({ length: 5 }, (_item, index) => minimum + (maximum - minimum) * index / 4);
  const number = (value: number) =>
    new Intl.NumberFormat(undefined, { maximumFractionDigits: 2, notation: Math.abs(value) >= 100_000 ? "compact" : "standard" }).format(value);

  return (
    <figure className="output-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby={`${chartTitleId} ${chartDescriptionId}`}>
        <title id={chartTitleId}>{output.title}</title>
        <desc id={chartDescriptionId}>
          Bounded line chart with {chart.series.length} series and {chart.labels.length} points.
        </desc>
        {ticks.map((tick) => {
          const y = pointY(tick);
          return (
            <g key={tick}>
              <line x1={inset.left} x2={width - inset.right} y1={y} y2={y} className="output-chart__grid" />
              <text x={inset.left - 9} y={y + 3} textAnchor="end" className="output-chart__axis-label">{number(tick)}</text>
            </g>
          );
        })}
        <line x1={inset.left} x2={inset.left} y1={inset.top} y2={height - inset.bottom} className="output-chart__axis" />
        <line x1={inset.left} x2={width - inset.right} y1={height - inset.bottom} y2={height - inset.bottom} className="output-chart__axis" />
        {chart.series.map((series, seriesIndex) => {
          const points = series.values.flatMap((value, index) =>
            value === null ? [] : [`${pointX(index)},${pointY(value)}`]
          ).join(" ");
          return (
            <g key={series.name}>
              <polyline points={points} fill="none" stroke={colors[seriesIndex]} strokeWidth="2.2" vectorEffect="non-scaling-stroke" />
              {series.values.map((value, index) => value === null ? null : (
                <circle key={index} cx={pointX(index)} cy={pointY(value)} r="2.7" fill={colors[seriesIndex]}>
                  <title>{chart.labels[index]} · {series.name}: {number(value)}</title>
                </circle>
              ))}
            </g>
          );
        })}
        <text x={inset.left} y={height - 13} className="output-chart__axis-label">{chart.labels[0]}</text>
        <text x={width - inset.right} y={height - 13} textAnchor="end" className="output-chart__axis-label">
          {chart.labels.at(-1)}
        </text>
      </svg>
      <figcaption>
        <span className="output-chart__legend">
          {chart.series.map((series, index) => (
            <span key={series.name}><i style={{ background: colors[index] }} />{series.name}</span>
          ))}
        </span>
        {chart.truncated && <small>Showing the first {chart.labels.length} points.</small>}
      </figcaption>
    </figure>
  );
}

function TextRenderer({ output, representation }: RendererProps) {
  const content = printableValue(representation?.data);
  return (
    <div className="output-text-preview" role="region" aria-label={`${output.title} text preview`}>
      <pre>{content}</pre>
      {content.endsWith("…") && <p className="output-preview-note">Preview truncated for readability.</p>}
    </div>
  );
}

function ImageRenderer({ output, representation }: RendererProps) {
  const inlineData = typeof representation?.data === "string" ? representation.data : undefined;
  const src = safeImageHref(representation?.href || inlineData);
  if (!src) {
    return (
      <div className="output-presentation-fallback">
        <FileImage size={20} aria-hidden="true" />
        <div><strong>Image preview unavailable</strong><p>The image is stored, but no safe browser preview was provided.</p></div>
      </div>
    );
  }
  return (
    <figure className="output-image-preview">
      <img src={src} alt={`${output.title} output`} loading="lazy" />
      <figcaption>{representation?.mediaType || "Image output"}</figcaption>
    </figure>
  );
}

function DownloadRenderer({ output, representation }: RendererProps) {
  const href = safeArtifactHref(representation?.href);
  const size = formatBytes(representation?.sizeBytes);
  if (!href) {
    return (
      <div className="output-download output-download--disabled">
        <div><Database size={18} /><span><strong>Stored output</strong><small>{representation?.handle ? "Protected artifact handle" : "No browser download link"}</small></span></div>
        <span>{size || representation?.mediaType || "Stored securely"}</span>
      </div>
    );
  }
  return (
    <a className="output-download" href={href} target="_blank" rel="noopener noreferrer" download>
      <div><Download size={18} /><span><strong>Download {output.title}</strong><small>{representation?.mediaType || "Original output"}</small></span></div>
      <span>{size || "Open file"}</span>
    </a>
  );
}

function UnknownRenderer({ output, representation, presentation }: RendererProps) {
  const href = safeArtifactHref(representation?.href);
  return (
    <div className="output-presentation-fallback">
      <File size={20} aria-hidden="true" />
      <div>
        <strong>{presentation.reason || "No in-browser renderer is available"}</strong>
        <p>
          The output was not discarded. It is identified as{" "}
          {output.interpretation.format || output.interpretation.semanticType || representation?.mediaType || "an unknown format"}.
        </p>
        {href && <a href={href} target="_blank" rel="noopener noreferrer">Open stored output</a>}
      </div>
    </div>
  );
}

const rendererRegistry: Record<string, Renderer> = {
  map: MapRenderer,
  table: TableRenderer,
  metric: MetricRenderer,
  scalar: MetricRenderer,
  chart: ChartRenderer,
  text: TextRenderer,
  document: TextRenderer,
  image: ImageRenderer,
  download: DownloadRenderer,
  unknown: UnknownRenderer,
};

function presentationIcon(kind: string): ReactNode {
  if (kind === "map") return <MapPinned size={14} />;
  if (kind === "table") return <Grid3X3 size={14} />;
  if (kind === "chart") return <BarChart3 size={14} />;
  if (kind === "metric" || kind === "scalar") return <Sigma size={14} />;
  if (kind === "image") return <FileImage size={14} />;
  if (kind === "text" || kind === "document") return <FileText size={14} />;
  if (kind === "download") return <Download size={14} />;
  return <File size={14} />;
}

function PresentationView({
  output,
  presentation,
}: {
  output: OutputArtifact;
  presentation: OutputPresentation;
}) {
  const representation = representationForPresentation(output, presentation);
  const RendererComponent = rendererRegistry[presentation.kind] || UnknownRenderer;
  const isReady = ["ready", "partial"].includes(presentation.state);
  return (
    <section className={`output-presentation output-presentation--${presentation.kind}`} aria-label={`${humanizeOutputState(presentation.kind)} presentation`}>
      {presentation.kind !== "map" && (
        <header>
          <span>{presentationIcon(presentation.kind)} {humanizeOutputState(presentation.kind)}</span>
          <small className={`output-state output-state--${presentation.state}`}>{humanizeOutputState(presentation.state)}</small>
        </header>
      )}
      {isReady ? (
        <RendererComponent output={output} presentation={presentation} representation={representation} />
      ) : (
        <div className="output-presentation-fallback" role={presentation.state === "unavailable" ? "alert" : "status"}>
          {presentation.state === "preparing"
            ? <LoaderCircle className="output-spin" size={20} aria-hidden="true" />
            : <AlertTriangle size={20} aria-hidden="true" />}
          <div>
            <strong>{presentation.state === "preparing" ? "Preparing this presentation" : "Presentation unavailable"}</strong>
            <p>{presentation.reason || "The underlying output remains available in its other representations."}</p>
          </div>
        </div>
      )}
    </section>
  );
}

function Stage({
  label,
  state,
  detail,
}: {
  label: string;
  state: string;
  detail?: string;
}) {
  const settled = ["retrieved", "recognized", "ready", "complete", "partial"].includes(state);
  const failed = ["failed", "blocked", "unsupported", "unavailable", "ambiguous"].includes(state);
  return (
    <li className={`output-stage ${settled ? "is-settled" : ""} ${failed ? "is-issue" : ""}`}>
      <span aria-hidden="true">
        {settled ? <Check size={12} /> : failed ? <AlertTriangle size={12} /> : <CircleEllipsis size={12} />}
      </span>
      <div><strong>{label}</strong><small>{detail || humanizeOutputState(state)}</small></div>
    </li>
  );
}

function OutputCard({ output }: { output: OutputArtifact }) {
  const detailsId = useId();
  const warnings = [...(output.interpretation.warnings || []), ...(output.warnings || [])];
  const media = output.retrieval.detectedMediaType || output.retrieval.declaredMediaType || output.interpretation.format;
  const units = output.interpretation.units || [];
  const safeDownloadRepresentation = output.representations?.find((representation) =>
    Boolean(safeArtifactHref(representation.href))
  );
  const effectivePresentations = output.presentations.some((presentation) => presentation.kind === "download")
    || !safeDownloadRepresentation
    ? output.presentations
    : [
      ...output.presentations,
      {
        id: `${output.id}-gateway-download`,
        kind: "download",
        state: "ready",
        artifactRef: safeDownloadRepresentation.id,
      } satisfies OutputPresentation,
    ];
  const readyPresentations = effectivePresentations.filter((presentation) =>
    ["ready", "partial", "preparing", "unavailable"].includes(presentation.state)
  );
  const presentationState = effectivePresentations.some((item) => ["ready", "partial"].includes(item.state))
    ? "ready"
    : effectivePresentations.some((item) => item.state === "preparing")
      ? "preparing"
      : "unavailable";

  return (
    <article className={`output-card output-card--${output.status}`} aria-labelledby={detailsId}>
      <header className="output-card__header">
        <span className="output-card__icon" aria-hidden="true"><Layers size={17} /></span>
        <div>
          <span className="output-card__type">{humanizeOutputState(output.interpretation.semanticType)} output</span>
          <h4 id={detailsId}>{output.title}</h4>
          {output.description && <p>{output.description}</p>}
        </div>
        <span className={`output-state output-state--${output.status}`}>{humanizeOutputState(output.status)}</span>
      </header>

      <ol className="output-pipeline" aria-label="Output preparation stages">
        <Stage
          label="Retrieved"
          state={output.retrieval.state}
          detail={output.retrieval.error?.message || humanizeOutputState(output.retrieval.state)}
        />
        <Stage
          label="Understood"
          state={output.interpretation.state}
          detail={output.interpretation.error?.message || humanizeOutputState(output.interpretation.state)}
        />
        <Stage
          label="Presented"
          state={presentationState}
          detail={`${effectivePresentations.filter((item) => ["ready", "partial"].includes(item.state)).length} ready`}
        />
      </ol>

      <dl className="output-metadata">
        {media && <div><dt>Format</dt><dd>{media}</dd></div>}
        {output.interpretation.crs
          && ["vector", "raster", "coverage", "tiles"].includes(output.interpretation.semanticType)
          && (
          <div>
            <dt>CRS</dt>
            <dd>
              {output.interpretation.crs.value || "Not declared"}
              <small>{humanizeOutputState(output.interpretation.crs.status)}{output.interpretation.crs.axisOrder ? ` · ${output.interpretation.crs.axisOrder}` : ""}</small>
            </dd>
          </div>
        )}
        {output.interpretation.featureCount !== undefined && <div><dt>Features</dt><dd>{output.interpretation.featureCount.toLocaleString()}</dd></div>}
        {output.interpretation.rowCount !== undefined && <div><dt>Rows</dt><dd>{output.interpretation.rowCount.toLocaleString()}</dd></div>}
        {output.retrieval.bytes !== undefined && <div><dt>Size</dt><dd>{formatBytes(output.retrieval.bytes)}</dd></div>}
        {units.map((unit, index) => (
          <div key={`${unit.quantity}-${index}`} className={unit.status === "missing" ? "output-metadata--warning" : ""}>
            <dt>{unit.quantity || "Units"}</dt>
            <dd>{unit.value || "Not declared"}<small>{humanizeOutputState(unit.status)}</small></dd>
          </div>
        ))}
      </dl>

      {warnings.length > 0 && (
        <div className="output-warnings" role="status">
          <AlertTriangle size={15} aria-hidden="true" />
          <ul>{warnings.map((warning, index) => <li key={`${warning}-${index}`}>{warning}</li>)}</ul>
        </div>
      )}

      {output.clarificationRequest ? (
        <section className="output-clarification" role="status" aria-label="Output interpretation question">
          <CircleEllipsis size={18} aria-hidden="true" />
          <div>
            <strong>
              {output.clarificationRequest.blocking
                ? "Your input is required"
                : "Map interpretation needs clarification"}
            </strong>
            <p>
              The result is retained, but the system will not guess ambiguous
              coordinates, CRS, units, or output semantics.
            </p>
            <ol>
              {output.clarificationRequest.issues.map((issue) => (
                <li key={issue.id}>
                  <b>{issue.question}</b>
                  <small>{issue.whyItMatters}</small>
                </li>
              ))}
            </ol>
            <p className="output-clarification__reply">
              Reply in the conversation with the requested facts; a corrected
              process request or output interpretation can then be prepared safely.
            </p>
          </div>
        </section>
      ) : null}

      <div className="output-presentations">
        {readyPresentations.length
          ? readyPresentations.map((presentation) => (
            <PresentationView output={output} presentation={presentation} key={presentation.id} />
          ))
          : (
            <div className="output-presentation-fallback">
              <PackageCheck size={20} aria-hidden="true" />
              <div>
                <strong>Output retained without a preview</strong>
                <p>The result exists, but no presentation was advertised for it.</p>
              </div>
            </div>
          )}
      </div>

      <details className="output-provenance">
        <summary>Provenance and technical metadata <ChevronDown size={13} /></summary>
        <dl>
          <div><dt>Output ID</dt><dd>{output.id}</dd></div>
          <div><dt>Server</dt><dd>{output.provenance.serverId}</dd></div>
          {output.provenance.parser && <div><dt>Parser</dt><dd>{output.provenance.parser}</dd></div>}
          {output.provenance.transformations?.length ? (
            <div><dt>Transformations</dt><dd>{output.provenance.transformations.join(" → ")}</dd></div>
          ) : null}
          {output.representations?.map((representation) => (
            <div key={representation.id}>
              <dt>{humanizeOutputState(representation.role)}</dt>
              <dd>{representation.mediaType}{formatBytes(representation.sizeBytes) ? ` · ${formatBytes(representation.sizeBytes)}` : ""}</dd>
            </div>
          ))}
        </dl>
      </details>
    </article>
  );
}

function ManifestPanel({ manifest }: { manifest: OutputManifestV1 }) {
  const headingId = useId();
  const execution = manifest.execution;
  const sourceTool = execution.sourceTool || "";
  const outputFamily = sourceTool === "ogc_features_query"
    ? { plural: "Feature query outputs", singular: "feature query output" }
    : sourceTool.startsWith("ogc_features_")
      ? { plural: "Feature service outputs", singular: "feature service output" }
      : sourceTool.startsWith("ogc_records_")
        ? { plural: "Record outputs", singular: "record output" }
        : sourceTool.startsWith("ogc_common_")
          ? { plural: "OGC resource outputs", singular: "OGC resource output" }
          : sourceTool === "ogc_proxy_memory_retrieve"
            ? { plural: "Stored outputs", singular: "stored output" }
            : { plural: "Process outputs", singular: "process output" };
  const waitingForOutputs = manifest.outputs.length === 0
    && manifest.overallState === "pending"
    && ["submitted", "running"].includes(execution.state);
  const failedExecution = ["failed", "cancelled"].includes(execution.state);
  const monitoringUnavailable = execution.state === "running"
    && manifest.overallState === "unavailable";
  const emptyHeading = waitingForOutputs
    ? `Preparing ${outputFamily.plural.toLowerCase()}`
    : failedExecution
      ? "Operation ended without outputs"
      : monitoringUnavailable
        ? "Automatic monitoring stopped"
        : `No ${outputFamily.plural.toLowerCase()} were returned`;
  const emptyDetail = waitingForOutputs
    ? "Waiting for the operation to publish retrievable outputs."
    : failedExecution
      ? `The operation ${execution.state === "cancelled" ? "was cancelled" : "failed"} before an output could be presented.`
      : monitoringUnavailable
        ? "The process may still be running, but this session could not continue checking it automatically."
        : `The operation completed without a declared ${outputFamily.singular} that can be presented.`;
  return (
    <section className={`output-manifest output-manifest--${manifest.overallState}`} aria-labelledby={headingId}>
      <header className="output-manifest__header">
        <div className="output-manifest__heading">
          <span className="output-manifest__eyebrow"><PackageCheck size={13} /> {outputFamily.plural}</span>
          <h3 id={headingId}>
            {manifest.outputs.length
              ? `${manifest.outputs.length} ${manifest.outputs.length === 1 ? "output" : "outputs"} returned`
              : emptyHeading}
          </h3>
          <p>
            {execution.processId ? `${execution.processId} on ` : ""}
            {execution.serverId}
            {execution.jobId ? ` · Job ${execution.jobId}` : ""}
          </p>
          <span className={`output-manifest__execution is-${execution.state}`}>
            Execution · {humanizeOutputState(execution.state)}
            {execution.reportedStatus && execution.reportedStatus !== execution.state
              ? ` (server reported ${execution.reportedStatus})`
              : ""}
          </span>
        </div>
        <span className={`output-manifest__state is-${manifest.overallState}`} role="status" aria-live="polite">
          <i aria-hidden="true" /> {humanizeOutputState(manifest.overallState)}
        </span>
      </header>

      {manifest.warnings?.length ? (
        <div className="output-manifest__warnings" role="status">
          <AlertTriangle size={15} aria-hidden="true" />
          <ul>{manifest.warnings.map((warning, index) => <li key={`${warning}-${index}`}>{warning}</li>)}</ul>
        </div>
      ) : null}

      {manifest.outputs.length > 0 ? (
        <div className="output-manifest__list">
          {manifest.outputs.map((output) => <OutputCard output={output} key={output.id} />)}
        </div>
      ) : (
        <div className="output-manifest__empty" role="status">
          {waitingForOutputs
            ? <LoaderCircle className="output-spin" size={18} aria-hidden="true" />
            : <AlertTriangle size={18} aria-hidden="true" />}
          {emptyDetail}
        </div>
      )}
    </section>
  );
}

export default function OutputPanel({ manifests }: { manifests: OutputManifestV1[] }) {
  if (!manifests.length) return null;
  return (
    <div className="output-panels" aria-label="OGC output presentations">
      {manifests.map((manifest) => <ManifestPanel manifest={manifest} key={manifest.manifestId} />)}
    </div>
  );
}
