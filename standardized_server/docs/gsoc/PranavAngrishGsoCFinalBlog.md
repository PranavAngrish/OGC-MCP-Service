# Final Update: Building a Safe and Visual MCP Bridge for OGC APIs with 52°North

Hi everyone,

I am Pranav Angrish, and this summer I worked with 52°North as part of Google
Summer of Code 2026 on the project **MCP for OGC APIs: Developing Model Context
Protocols for the Suite of OGC APIs**.

In my first blog post, I introduced the main idea behind the project: making
OGC APIs easier to use through the Model Context Protocol (MCP). In my midterm
update, I described the standardized Python MCP server, the discovery-first
workflow, the planner for process execution, and proxy memory for large
responses.

During the second half of the program, I focused on turning those backend
capabilities into a complete user-facing workflow. I built a React-based
conversational interface, connected it to Gemini through a Node.js gateway,
added safe human confirmation for process execution, prepared process outputs
as reusable artifacts, and added visual presentations for supported geospatial
results.

The result is no longer only an MCP server that exposes OGC API operations. It
is a prototype of an end-to-end geospatial assistant in which a user can ask a
question in natural language, the model can discover the right OGC API
capability, the server can validate and execute the operation safely, and the
interface can show the result as text, a map, a table, a chart, a metric, an
image, or a download.

## From an MCP Server to an End-to-End System

At midterm, the central implementation was the Python reference server. It
provides stable `ogc_*` MCP tools for OGC API - Common, Features, Records,
Processes, and Jobs. The important design principle was that the language model
should not guess endpoints, process IDs, or input names. Instead, it should
discover the registered server, inspect the available capabilities, and use the
exact metadata returned by the OGC API.

In the second half, I added the missing user-facing layer. The system is now
made of four cooperating parts:

- **React UI**: the browser application where the user writes requests, reviews
  a plan, and sees results.
- **Node.js gateway**: the application server that maintains the conversation,
  connects to Gemini, calls MCP tools, prepares safe output events, and streams
  updates back to the browser.
- **Gemini**: the reasoning component that decides which available MCP tool is
  relevant and writes the final natural-language explanation.
- **Python MCP server**: the authoritative OGC proxy that talks to registered
  OGC API deployments, validates requests, stores data, and prepares output
  artifacts.

This separation turned out to be important. The language model is useful for
understanding a user's request and selecting the next action, but it should not
be responsible for executing arbitrary HTTP requests, approving a process on
the user's behalf, or deciding whether raw geospatial data is safe to render.

## How a User Request Travels Through the System

A normal interaction starts in the React chat interface. The user can ask a
question such as:

> “Show wildfire risk near Seattle.”

React sends the message to the Node.js gateway. The gateway opens a streamed
response so that the user can see progress while the request is being handled.
It loads the MCP tools that Gemini is allowed to use and sends Gemini the
conversation plus the available tool schemas.

Gemini can then either write a response immediately or request a tool call. For
a geospatial request, it will usually begin with discovery. It may list the
configured OGC servers, inspect a landing page or conformance information,
search records, inspect a feature collection, list processes, or describe a
specific process.

When Gemini requests a tool, the Node gateway calls that tool on the Python MCP
server. The Python server then communicates only with OGC API deployments that
have been registered by the operator. It returns a structured result to Node.
Node prepares a safe version of that result for Gemini, sends it back into the
conversation, and asks Gemini whether another tool call is needed.

This creates a controlled tool loop:

```text
user request
  -> React UI
  -> Node gateway
  -> Gemini chooses a tool
  -> Node calls Python MCP tool
  -> Python calls a registered OGC API
  -> structured result returns to Node
  -> Gemini either chooses another tool or writes the final answer
  -> React shows the answer and any prepared visual output
```

The gateway limits this loop to a bounded number of rounds. This prevents an
uncontrolled sequence of tool calls while still allowing multi-step workflows,
such as discovering a dataset before choosing a process to run.

## Safe Process Execution With Human Confirmation

One of the most important parts of the project is the process-execution
workflow. OGC API - Processes operations can trigger real geospatial
computation, potentially using large inputs or long-running jobs. A model
should not send a guessed execution request directly to a server.

The workflow therefore follows these stages:

```text
discover process
  -> describe its exact schema
  -> create a plan
  -> resolve missing or ambiguous inputs
  -> show the exact request to the user
  -> record the user's decision
  -> execute the confirmed plan
```

The model starts by calling `ogc_processes_list` and
`ogc_processes_describe`. This gives it the exact process identifier, input
names, input types, and output information advertised by the OGC API server.
It then calls `ogc_proxy_create_plan` with the proposed execution request.

The Python planner validates the plan against the process description. It
checks required inputs, basic input types, source references, process and
collection identifiers, and material assumptions such as units, coordinate
reference systems, coordinate order, or values that were inferred rather than
explicitly given by the user.

If something is missing, the plan enters `needs_resolution`. The interface can
ask the user one specific question and update the same plan once the answer is
available. If the request is valid, the plan becomes
`ready_for_confirmation`.

At this stage, the React UI displays the exact `execute_request` in an approval
card. The Node gateway creates a fingerprint of the plan, its selected server,
the execution request, the input context, and the planned steps. When the user
clicks Approve or Reject, the browser sends that decision directly to Node. It
does not pass through Gemini.

Before recording approval, Node fetches the current plan again and compares its
fingerprint with the version that was shown to the user. If the plan changed,
the user has to review it again. If it is identical, Node records the decision
through `ogc_proxy_confirm_plan`. Only then can
`ogc_proxy_execute_plan` run the stored request using its `plan_id`.

This makes the workflow auditable and avoids treating a general natural-language
request as approval for a final, detailed process payload.

## Handling Large Geospatial Responses Carefully

Geospatial responses can be very large. A FeatureCollection may contain many
features and coordinate arrays; a process output can contain geometries, files,
tables, or references to additional results. Sending all of this into an LLM
context would be expensive, hard to reason over, and unsafe.

To address this, I continued the proxy-memory approach introduced at midterm.
Tools that can return large or unbounded responses use summary mode by default.
The Python server stores the complete response behind an opaque `mem_*` handle
and returns only a compact, sanitized summary to the MCP client.

For a feature collection, that summary can include the number of features,
feature IDs, geometry types, and selected property values. It deliberately does
not include full coordinate arrays. The original data remains available behind
the memory handle and can be retrieved in bounded pages when it is genuinely
needed.

The Node gateway adds a second protection layer before giving a result to
Gemini. It strips coordinates, geometries, bounds, latitude/longitude fields,
secret-like values, and overly deep or large structures. Gemini receives useful
identifiers, scalar facts, warnings, and result status, but it does not receive
the raw spatial payload needed to render a map.

This means that the model can answer questions such as “How many features were
returned?” or “Which process output is available?” without becoming a place
where the system tries to perform geospatial computation on a huge coordinate
array.

## From Proxy Memory to a Map

Keeping coordinates out of Gemini's context does not mean that the user loses
the ability to see a map. The rendering path is separate from the reasoning
path.

When Node needs to prepare a visualization, it can privately retrieve a bounded
slice of the stored `mem_*` payload. This retrieval happens outside the model
conversation. Node validates the geometry, coordinate ranges, coordinate
reference system, bounds, and size limits, then produces a browser-safe map
visualization. That visualization is streamed directly to React.

React renders the visualization with MapLibre GL. Supported feature outputs can
be shown as points, lines, polygons, multi-geometries, or geometry collections.
Dense point collections can be represented as heatmaps. The map renderer also
shows layer information, feature properties, warnings, and truncation details.

The system fails closed when the data cannot be mapped safely. For example,
unknown coordinate reference systems, missing coordinate semantics, invalid
coordinate ranges, or ambiguous `x`/`y` columns do not become a misleading map.
Instead, the user receives a table, a download, or a clarification request.

## Process Output Artifacts and Visual Presentations

The second major addition in the final phase was a full output-artifact
pipeline. Process execution and output presentation are not the same thing. A
process can report success while its output is still being published, stored
behind a reference, encoded in an unsupported format, or unavailable for a
browser preview.

The Python server therefore creates an `output_manifest` for process outputs.
For every output, the manifest separately records:

- the execution state;
- whether the output was retrieved;
- whether its format and semantics were understood;
- which presentations are ready for the user interface;
- provenance, warnings, and clarification requirements.

The artifact pipeline preserves the original output behind an opaque `art_*`
handle. When possible, it also creates a canonical representation and a bounded
preview representation. For example, an upstream vector result can be
normalized into GeoJSON for a map preview while the full original file remains
available for download.

This allows the UI to choose the right presentation based on the actual output
rather than guessing from the user's original question.

| Output type | UI presentation |
| --- | --- |
| Valid vector geometry | Interactive map and feature table, plus download |
| Table or time series | Table; time series can also use a chart |
| Scalar value or statistic | Metric card |
| Image | Safe image preview and download |
| Text or document | Bounded text preview and download |
| Raster, coverage, unknown, or binary data | Honest availability status and download when no safe preview exists |

The React `OutputPanel` uses a renderer registry to select components for maps,
tables, charts, metrics, images, text, and downloads. Importantly, the system
does not tell the UI that a map is ready merely because a process succeeded. A
map appears only after a valid drawable layer has been prepared.

## Supporting Asynchronous Jobs

Some OGC API processes return immediately with an asynchronous job instead of a
final result. The interface now supports this workflow as well.

When a confirmed process returns a trackable asynchronous response, Node stores
the job and server identifiers and polls its status in the background. The
original chat response can finish while the job continues. Once the job is
successful, the gateway retrieves the result, passes it through the same
artifact pipeline, and updates the original conversation with progress and a
prepared map when a supported spatial result is available.

The system also handles the realistic case in which a job reports success
before its result endpoint is ready. It uses bounded retries for temporary
result-publication states and reports an explicit unavailable state rather than
leaving the interface permanently loading.

## What I Delivered

Over the course of the project, I delivered the following main pieces of work:

- an experimental OGC API-to-MCP mapping and tool contract;
- a standardized Python FastMCP reference server for Common, Features, Records,
  Processes, and Jobs workflows;
- an operator-owned registry so tools use configured OGC API servers rather
  than arbitrary user-provided URLs;
- bounded HTTP transport, authentication profiles, response limits, and
  security checks;
- discovery-first tools for OGC API capabilities, collections, records, and
  processes;
- a deterministic, human-confirmed plan workflow for OGC API - Processes;
- proxy memory and coordinate-free summaries for large responses;
- in-memory and Redis-backed storage options for plans, memory, and artifacts;
- a React chat interface and a Node.js Gemini gateway;
- safe streamed tool activity, approval cards, and background-job updates;
- process-output manifests, artifact storage, renderer preparation, and secure
  artifact downloads;
- interactive map, table, chart, metric, image, text, and download
  presentations;
- unit tests and documentation covering the tool contract, security boundaries,
  plan lifecycle, memory, artifacts, configuration, deployment, and extension.

## Reflections

The biggest lesson from this project is that connecting a language model to an
API is not mainly a matter of exposing endpoints. The difficult part is
designing the workflow around the endpoint.

For OGC APIs, that means helping the model discover the right server and
capability, preserving exact process schemas, preventing it from guessing
coordinate semantics, keeping large results outside its context, requiring a
human decision for consequential actions, and being honest about what was
actually retrieved, interpreted, and rendered.

I also learned that visual output needs its own safety model. A successful
process does not automatically justify a map. A browser should not load an
arbitrary output URL, and a map should not appear when the CRS is unknown or a
coordinate array is ambiguous. The output manifest and renderer registry made
those decisions explicit instead of hiding them in application code.

The work moved the project from a backend bridge toward a usable research
prototype. A user can focus on a geospatial question, while the system guides
the model through discovery, validation, execution, result handling, and
presentation.

## Future Work

There are several directions that would make this work stronger in a production
environment:

- add authentication and per-user or per-session isolation for plans, memory,
  artifacts, and gateway sessions;
- use durable storage and event delivery for multi-instance deployments;
- add DNS-aware egress controls, stronger audit logging, and rate limiting;
- extend the OGC API coverage to areas such as Coverages, EDR, Tiles, Maps, and
  Styles;
- add more format adapters and preview support, especially for raster and
  coverage outputs;
- strengthen input validation while keeping the planner understandable and
  fail-closed;
- develop interoperability tests and gather feedback from the wider OGC and MCP
  communities.

## Closing

I am grateful to 52°North, my mentors Benjamin Proß and Benedikt Gräler, and
the Google Summer of Code program for this opportunity. This project gave me a
much deeper understanding of geospatial web APIs, MCP tool design, security
boundaries, user-centered workflow design, and the practical challenges of
building AI-assisted systems that remain transparent and controllable.

I am excited to continue improving this work and to explore how a structured
MCP layer can make powerful OGC API capabilities more accessible to a wider
range of users.

LinkedIn: <https://www.linkedin.com/in/pranav-angrish>

GitHub repository: <https://github.com/PranavAngrish/OGC-MCP-Service>

