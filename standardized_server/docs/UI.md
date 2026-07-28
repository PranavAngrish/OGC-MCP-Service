# React User Interface

The repository includes a React-based conversational interface in [`../../ui`](../../ui/).

It gives end users a chat workspace while a server-side gateway connects a
Gemini reasoning model to the existing OGC MCP tool surface through Gemini's
OpenAI-compatible API. The browser receives streamed lifecycle status, safe
progress summaries, MCP tool calls, tool-result
previews, and the final answer.

Private chain-of-thought is not exposed. The activity panel uses concise reasoning
summaries produced for display and concrete execution events from the gateway.

A separate, session-scoped event stream keeps tracking confirmed asynchronous
jobs after the chat response has finished. Successful jobs retrieve their
results and update the originating assistant message; terminal failures and
timeouts remain visible as activity statuses.

Supported geospatial outputs are shown in an interactive result card. The
gateway hydrates proxy-memory results outside model context and emits a bounded
map artifact for GeoJSON, explicit longitude/latitude records, extents, basic
WKT, small numeric grids, and georeferenced remote references. Vector geometry
is drawn directly; dense point data becomes a heatmap; raster or tile URLs need
an explicit user action before the browser loads them. Unknown coordinate
systems and non-spatial statistics remain textual instead of being guessed onto
a map.

## Local startup

```bash
cd ui
cp .env.example .env
# Add GEMINI_API_KEY to .env
npm install
npm run dev
```

The React development server runs at `http://localhost:5173`. Its `/api` requests
are proxied to the local gateway on port `8787`.

See the [UI README](../../ui/README.md) for architecture, environment variables,
production build commands, and deployment limitations.
