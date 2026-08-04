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
results and update the originating assistant message. If result publication
lags behind a successful process status, the gateway retries bounded transient
errors, pending manifests, and retryable artifact-publication failures.
Terminal failures and timeouts remain visible as
activity statuses with the last retrieval detail.

Plan confirmation is a real browser-side human action. The conversational model
cannot call `ogc_proxy_confirm_plan`. When a validated plan is ready, the UI
shows the exact execute request, input provenance, and a fingerprint in an
approval card. The gateway re-reads and hashes the current plan before recording
the user's one-time Approve or Reject decision, then resumes the conversation.

Every process result first becomes an output manifest. A renderer registry then
selects map, table, chart, metric, text, image, or download presentations per
named output. The gateway hydrates opaque preview artifacts outside model
context. Supported vector geometry is drawn directly; dense point data becomes
a heatmap. Raster or tile URLs need an explicit user action and a validated
gateway URL before the browser loads them. Unknown coordinate systems and
non-spatial statistics are never guessed onto a map.
Structured output clarification questions are shown when columns, CRS, axis
order, or units remain ambiguous.

The map is mounted only when at least one validated drawable result layer
exists. The default public MapLibre style supplies geographic context when
`VITE_MAP_STYLE_URL` is omitted. An explicitly empty variable selects a
network-free privacy canvas. Style errors and timeouts fall back once and
surface `Basemap: unavailable`; they do not leave the message loading forever.
For remote styles, readiness requires the initial sources and tiles to reach an
idle state, not merely the style JSON to load.

The activity panel separates safe decision summaries from private
chain-of-thought. Each service call can be expanded to show its purpose,
redacted inputs, bounded response facts, warnings, timing, and next step.
Artifact stages separately show retrieval, detection, interpretation,
conversion, and presentation state.

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
