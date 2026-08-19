# Terra Console

Terra Console is the React interface for the OGC API MCP bridge. It combines:

- a responsive conversational UI;
- a server-side Gemini gateway using the OpenAI JavaScript SDK;
- the existing Python MCP server over a local stdio connection;
- streamed progress summaries, tool activity, and final answers;
- interactive maps for supported geospatial result outputs;
- the existing confirmation-gated OGC process workflow.

The browser never receives the Gemini API key or starts the MCP process itself.

## Architecture

```text
React browser
  -> POST /api/chat (SSE response)
  -> POST /api/sessions/:id/approvals/:challenge (explicit human decision)
  -> GET /api/sessions/:id/events (background-job SSE)
  -> Node gateway
     -> Gemini OpenAI-compatible Chat Completions API
     -> local MCP client
        -> Python OGC MCP server over stdio
           -> registered OGC APIs
```

The gateway exposes MCP tools to Gemini as Chat Completions function tools. It
executes requested calls through the official MCP client, returns tool output to
the same conversation, and streams safe progress events to the browser. The
OpenAI SDK is configured with Gemini's compatibility `baseURL`; the provider is
Gemini, not OpenAI.

`ogc_proxy_confirm_plan` is deliberately absent from Gemini's tool list. A
validated plan produces a browser approval card containing the exact request
and its fingerprint. The gateway re-fetches that plan before applying the
one-time user decision, then automatically starts a continuation turn.

## Setup

From `ui/`:

```bash
cp .env.example .env
```

Set at least:

```text
GEMINI_API_KEY=your-api-key
```

The defaults assume the repository virtual environment exists at `../venv` and
use `../standardized_server/config.example.json`. Override `OGC_MCP_PYTHON` and
`OGC_MCP_CONFIG` when your paths differ.

Install and run:

```bash
npm install
npm run dev
```

Open `http://localhost:5173`.

For a production-style local build:

```bash
npm run build
npm start
```

The gateway then serves both the API and `dist/` application at
`http://127.0.0.1:8787`.

## Progress and “thinking” UI

The interface deliberately does not expose private chain-of-thought. It displays:

- server-generated lifecycle status;
- safe planning summaries and any user-facing tool commentary from Gemini;
- MCP tool names and arguments;
- bounded tool-result previews;
- the final model answer as a separate message.

This gives users continuous, auditable feedback without presenting hidden model
reasoning as if it were a reliable execution log.

The gateway publishes every foreground turn and tracked background job through
the shared [`activity/2`](../spec/ogc-workflow-event.schema.json) envelope. Each
run has monotonic sequence numbers and explicit session, turn, target-message,
activity, and optional run identifiers. Intent, tool steps, approvals,
clarifications, job progress, output-manifest updates, presentation phases, and
terminal outcomes use this versioned stream. The older named SSE events remain
dual-published during migration so existing clients continue to work.
Large manifests are not copied wholesale into `activity/2`: once a manifest is
larger than 64 KiB, the workflow event carries a bounded lifecycle and
presentation summary without inline representations or coordinates. The legacy
manifest event and opaque artifact/memory handles remain available during the
migration.

For factual OGC Features questions, the agent first discovers a collection's
query surface and then uses the structured, automatically paginated feature
query. The gateway enforces the returned evidence gate: an incomplete or
truncated query cannot become a factual final answer. Geometry stays in proxy
memory for maps and downstream processes; the model receives only bounded
coordinate-free fact rows and required scope qualifications.

## Geospatial result maps

When a tool returns a completed result, the gateway looks for supported spatial
outputs and streams a separate `map_data` artifact to the conversation. Summary
mode remains enabled for the model: if the result has a proxy-memory handle, the
gateway retrieves the bounded full payload directly for visualization rather
than adding raw coordinate arrays to the model's messages.

The renderer supports these result forms:

| Result output | Map treatment |
| --- | --- |
| GeoJSON Feature, FeatureCollection, or Geometry | Points, lines, and polygon fill/outline layers, including multi-geometries and geometry collections. Dense point sets use a heatmap layer. |
| Explicit longitude/latitude objects | Point features with their remaining fields available in the feature details panel. |
| Bounding boxes | An extent polygon used for display and initial map framing. |
| WKT geometry | Geometry with an explicit supported CRS/SRID is converted into a vector layer. CRS-less WKT remains downloadable and asks for clarification. |
| Small numeric grids with an extent | Grid cells become a heatmap layer. Units and descriptive fields remain visible alongside the map. |
| Georeferenced PNG/JPEG or XYZ tile references | An optional remote layer. The browser loads it only after the user explicitly enables it. |
| GeoTIFF/COG and other spatial references | A safe reference/download card. A production tile service is needed before MapLibre can display these formats directly. |

For a confirmed plan that returns an asynchronous `201/202` response, the
gateway records the exact job and server IDs and polls `ogc_jobs_get_status` on
the user's session. The browser keeps a separate session event stream open, so
the original answer can finish while the job continues. A successful job
automatically triggers `ogc_jobs_get_results`, bounded memory hydration, and a
map update on the original assistant message. Failed, dismissed, and timed-out
jobs become visible status rows instead of silently disappearing.
Successful status responses whose artifacts are still marked retryable are
also retried within the same bounded result window. An async response without a
trackable job ID is shown as unavailable instead of loading forever.

Pure statistics without geometry are left to the textual answer instead of
being placed on a misleading map. Ambiguous coordinate arrays and generic
`x`/`y` columns are also left unmapped unless their surrounding output declares
their geometry semantics. Their structured clarification questions appear with
the retained table or download.

GeoJSON is interpreted as CRS84 longitude/latitude. Explicit EPSG:3857 geometry
is reprojected to CRS84; coordinates in any other unknown or unsupported
projected CRS are not guessed. Result normalization is bounded
by feature/vertex/layer limits, and the card reports warnings when it has to
truncate or skip content. Properties are rendered as text, never as HTML.

When `VITE_MAP_STYLE_URL` is omitted, the UI uses MapLibre's public demo style
so local validation shows geographic context immediately. Set it to a trusted
MapLibre style at build time for deployment, or define it with an empty value
to use the network-free privacy canvas. A remote style that errors or does not
load its initial sources and tiles within the bounded readiness window falls
back once to that local canvas; the UI
then reports the basemap as unavailable without blocking validated result
layers. Production deployments should configure a tile provider and
attribution appropriate to their privacy policy and expected traffic.
Result-controlled raster and tile URLs are never loaded automatically; users
must explicitly enable each layer.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `GEMINI_API_KEY` | required | Server-side Gemini credential. |
| `GEMINI_MODEL` | `gemini-3.1-flash-lite` | Gemini model exposed through OpenAI compatibility. |
| `GEMINI_REASONING_EFFORT` | `medium` | Gemini thinking effort for each model turn. |
| `OGC_MCP_CONFIG` | example config | Existing OGC MCP registry configuration. |
| `OGC_MCP_PYTHON` | repository `venv` | Python executable used for the stdio server. |
| `OGC_MCP_TOOL_TIMEOUT_MS` | `180000` | MCP tool-call timeout, including paginated remote catalogue searches (clamped to 10 seconds–15 minutes). |
| `UI_GATEWAY_PORT` | `8787` | Gateway and production UI port. |
| `OGC_JOB_POLL_INTERVAL_MS` | `3000` | Interval for checking confirmed background jobs (clamped to 1–60 seconds). |
| `OGC_JOB_MONITOR_TIMEOUT_MS` | `1800000` | Maximum background monitoring duration (clamped to 30 seconds–24 hours). |
| `OGC_JOB_RESULT_RETRY_INTERVAL_MS` | `1500` | Delay between bounded result-publication retries after a job reports success (clamped to 0.25–60 seconds). |
| `OGC_JOB_RESULT_TIMEOUT_MS` | `60000` | Maximum time spent waiting for a successful job's result endpoint to become ready (clamped to 1 second–10 minutes). |
| `VITE_MAP_STYLE_URL` | MapLibre public demo style when omitted | Trusted MapLibre style URL compiled into the browser app; define it as empty for the network-free privacy canvas. |

For a smooth migration, the gateway also accepts a key from the legacy
`OPENAI_API_KEY` variable, but new environments should use `GEMINI_API_KEY`.

## Production work still required

The current gateway is designed for local, single-user use. Before exposing it
as a shared service, add authentication, per-user session/state isolation,
persistent conversation storage, rate limits, CSRF/origin controls, structured
audit logs, and an explicit approval UI for any additional state-changing tools.
Background-job registrations and undelivered events are currently in-process,
so production deployments also need a durable per-user job/event store and
cross-replica delivery. Route user-provided remote raster and tile references
through an allowlisted, SSRF-resistant media proxy; the browser-side URL checks
and explicit load consent are useful safeguards, but cannot prevent DNS
rebinding or enforce an organization-wide host policy.
