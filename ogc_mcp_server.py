# """
# OGC API – MCP Server (FastMCP version)
# Exposes OGC API operations as MCP tools for LLM consumption.
# """

# import json
# import os
# from typing import Any

# import requests
# from mcp.server.fastmcp import FastMCP

# # ─── Configuration ────────────────────────────────────────────────────────────

# KNOWN_PROCESS_SERVERS = {
#     "geolabs": "http://tb17.geolabs.fr:8119/ogc-api",
#     "cubewerx": "https://www.pvretano.com/cubewerx/cubeserv/default/ogcapi/processing",
#     "local": "http://localhost",
# }

# DEFAULT_PROCESS_SERVER = os.environ.get("OGC_PROCESSES_BASE_URL", "geolabs")
# DEFAULT_TIMEOUT_SECONDS = int(os.environ.get("OGC_REQUEST_TIMEOUT_SECONDS", "120"))

# LOCAL_OGC_USERNAME = os.environ.get("OGC_LOCAL_USERNAME", "admin")
# LOCAL_OGC_PASSWORD = os.environ.get("OGC_LOCAL_PASSWORD", "admin123")
# _LOCAL_TOKEN_CACHE: dict[str, str] = {}

# # ─── FastMCP instance ─────────────────────────────────────────────────────────

# mcp = FastMCP("ogc-api-mcp")

# # ─── Generic OGC API - Processes helpers ──────────────────────────────────────

# def resolve_process_server(server_url: str = "") -> str:
#     """Resolve a server alias or full URL into a normalized base URL."""
#     selected = (server_url or DEFAULT_PROCESS_SERVER).strip()
#     selected = KNOWN_PROCESS_SERVERS.get(selected, selected)

#     if not selected.startswith(("http://", "https://")):
#         raise ValueError(
#             f"Unknown process server '{selected}'. Use a full URL or one of: "
#             f"{', '.join(KNOWN_PROCESS_SERVERS)}"
#         )

#     selected = selected.rstrip("/")
#     if selected.endswith("/processes"):
#         selected = selected[: -len("/processes")]

#     return selected


# def _is_local_server(base_url: str) -> bool:
#     return base_url.startswith("http://localhost") or base_url.startswith("http://127.0.0.1")


# def _get_local_token(base_url: str) -> str | None:
#     """Try the local demo auth service. Real public servers usually do not need this."""
#     if base_url in _LOCAL_TOKEN_CACHE:
#         return _LOCAL_TOKEN_CACHE[base_url]

#     try:
#         response = requests.post(
#             f"{base_url}/auth/login",
#             json={"username": LOCAL_OGC_USERNAME, "password": LOCAL_OGC_PASSWORD},
#             timeout=10,
#         )
#         if response.ok:
#             token = response.json().get("token")
#             if token:
#                 _LOCAL_TOKEN_CACHE[base_url] = token
#                 return token
#     except requests.RequestException:
#         return None

#     return None


# def _process_headers(base_url: str, has_body: bool = False, prefer_async: bool = False) -> dict:
#     headers = {"Accept": "application/json"}

#     if has_body:
#         headers["Content-Type"] = "application/json"

#     bearer_token = os.environ.get("OGC_PROCESSES_BEARER_TOKEN")
#     api_key = os.environ.get("OGC_PROCESSES_API_KEY")

#     if bearer_token:
#         headers["Authorization"] = f"Bearer {bearer_token}"
#     elif api_key:
#         headers["X-API-Key"] = api_key
#     elif _is_local_server(base_url):
#         token = _get_local_token(base_url)
#         if token:
#             headers["Authorization"] = f"Bearer {token}"

#     if prefer_async:
#         headers["Prefer"] = "respond-async"

#     return headers


# def _coerce_json(value: Any, label: str) -> Any:
#     """Accept JSON objects directly, or JSON encoded strings from MCP clients."""
#     if value is None or value == "":
#         return None
#     if isinstance(value, str):
#         try:
#             return json.loads(value)
#         except json.JSONDecodeError as exc:
#             raise ValueError(f"{label} must be valid JSON: {exc}") from exc
#     return value


# def _read_response(response: requests.Response) -> Any:
#     if not response.content:
#         return None

#     text = response.text
#     content_type = response.headers.get("Content-Type", "")

#     if "json" in content_type or text.lstrip().startswith(("{", "[")):
#         try:
#             return response.json()
#         except ValueError:
#             return text

#     return text


# def _dump_limited(data: Any, max_chars: int = 12000) -> str:
#     if data is None:
#         return ""
#     if isinstance(data, str):
#         text = data
#     else:
#         text = json.dumps(data, indent=2, ensure_ascii=False)
#     if len(text) > max_chars:
#         return text[:max_chars] + "\n... (truncated)"
#     return text


# def _request_process_server(
#     method: str,
#     server_url: str,
#     path: str,
#     *,
#     params: dict | None = None,
#     body: dict | None = None,
#     prefer_async: bool = False,
#     timeout_seconds: int | None = None,
# ) -> tuple[requests.Response | None, Any, str]:
#     base_url = resolve_process_server(server_url)
#     url = f"{base_url}{path}"
#     headers = _process_headers(base_url, has_body=body is not None, prefer_async=prefer_async)
#     timeout = timeout_seconds or DEFAULT_TIMEOUT_SECONDS

#     try:
#         response = requests.request(
#             method,
#             url,
#             headers=headers,
#             params=params,
#             json=body,
#             timeout=timeout,
#         )
#     except requests.RequestException as exc:
#         return None, None, f"Cannot connect to {base_url}: {exc}"

#     data = _read_response(response)
#     if not response.ok:
#         detail = _dump_limited(data, max_chars=2000) or response.text[:2000]
#         return response, data, (
#             f"Request failed.\n"
#             f"Server: {base_url}\n"
#             f"Operation: {method} {path}\n"
#             f"Status: {response.status_code}\n"
#             f"Response:\n{detail}"
#         )

#     return response, data, ""


# def _extract_processes(data: Any) -> list[dict]:
#     if isinstance(data, dict):
#         processes = data.get("processes", [])
#         if isinstance(processes, list):
#             return [p for p in processes if isinstance(p, dict)]
#     return []


# def _format_process_list(data: Any, base_url: str) -> str:
#     processes = _extract_processes(data)
#     if not processes:
#         return f"No processes found at {base_url}.\n\nRaw response:\n{_dump_limited(data, 4000)}"

#     lines = []
#     for process in processes:
#         pid = process.get("id") or process.get("identifier") or process.get("processID") or "unknown"
#         title = process.get("title") or ""
#         description = process.get("description") or process.get("abstract") or "No description"
#         controls = process.get("jobControlOptions") or []
#         controls_text = f" | jobControlOptions={controls}" if controls else ""
#         if title and title != pid:
#             lines.append(f"- {pid}: {title} — {description[:180]}{controls_text}")
#         else:
#             lines.append(f"- {pid}: {description[:220]}{controls_text}")

#     return f"Processes at {base_url} ({len(processes)} total):\n" + "\n".join(lines)


# def _format_schema(schema: Any) -> str:
#     if not schema:
#         return "schema unspecified"
#     if isinstance(schema, dict):
#         schema_type = schema.get("type")
#         media_type = schema.get("contentMediaType")
#         ref = schema.get("$ref")
#         parts = [p for p in [schema_type, media_type, ref] if p]
#         if parts:
#             return ", ".join(parts)
#         return json.dumps(schema, ensure_ascii=False)[:300]
#     return str(schema)


# def _format_io_block(title: str, definitions: Any) -> str:
#     if not definitions:
#         return f"{title}: none advertised"

#     lines = [f"{title}:"]
#     if isinstance(definitions, dict):
#         iterable = definitions.items()
#     elif isinstance(definitions, list):
#         iterable = ((item.get("id", f"item-{idx}"), item) for idx, item in enumerate(definitions) if isinstance(item, dict))
#     else:
#         return f"{title}: {_dump_limited(definitions, 1000)}"

#     for name, definition in iterable:
#         if not isinstance(definition, dict):
#             lines.append(f"  - {name}: {definition}")
#             continue
#         description = definition.get("description") or definition.get("title") or "No description"
#         schema = _format_schema(definition.get("schema"))
#         min_occurs = definition.get("minOccurs")
#         max_occurs = definition.get("maxOccurs")
#         occurs = ""
#         if min_occurs is not None or max_occurs is not None:
#             occurs = f" | occurs={min_occurs or 0}..{max_occurs or 'unbounded'}"
#         lines.append(f"  - {name}: {description} | {schema}{occurs}")

#     return "\n".join(lines)


# def _format_process_description(data: Any, base_url: str) -> str:
#     if not isinstance(data, dict):
#         return f"Process description from {base_url}:\n{_dump_limited(data, 8000)}"

#     pid = data.get("id") or data.get("identifier") or data.get("processID") or "unknown"
#     title = data.get("title") or pid
#     description = data.get("description") or data.get("abstract") or "No description"
#     job_controls = data.get("jobControlOptions") or []
#     transmissions = data.get("outputTransmission") or []

#     summary = [
#         f"Process: {pid}",
#         f"Server: {base_url}",
#         f"Title: {title}",
#         f"Description: {description}",
#         f"Job control options: {job_controls or 'not advertised'}",
#         f"Output transmission: {transmissions or 'not advertised'}",
#         "",
#         _format_io_block("Inputs", data.get("inputs")),
#         "",
#         _format_io_block("Outputs", data.get("outputs")),
#         "",
#         "Raw process description:",
#         _dump_limited(data, 12000),
#     ]
#     return "\n".join(summary)


# def _extract_job_id(data: Any, location: str = "") -> str:
#     if isinstance(data, dict):
#         for key in ("jobID", "jobId", "id"):
#             value = data.get(key)
#             if isinstance(value, str) and value:
#                 return value

#     if location:
#         return location.rstrip("/").split("/")[-1]

#     return ""


# def _format_execute_response(response: requests.Response, data: Any, base_url: str) -> str:
#     location = response.headers.get("Location", "")
#     preference_applied = response.headers.get("Preference-Applied", "")
#     content_type = response.headers.get("Content-Type", "")

#     lines = [
#         "Process execution request accepted.",
#         f"Server: {base_url}",
#         f"HTTP status: {response.status_code}",
#     ]
#     if content_type:
#         lines.append(f"Content-Type: {content_type}")
#     if preference_applied:
#         lines.append(f"Preference-Applied: {preference_applied}")
#     if location:
#         lines.append(f"Location: {location}")

#     job_id = _extract_job_id(data, location)
#     if job_id and response.status_code in (201, 202):
#         lines.extend([
#             f"Job ID: {job_id}",
#             "",
#             "Suggested next step: call jobs_get_status, then jobs_get_results when the job is successful.",
#         ])

#     lines.extend(["", "Response body:", _dump_limited(data, 12000) or "(empty response body)"])
#     return "\n".join(lines)


# # ─── Generic OGC API - Processes tools ────────────────────────────────────────

# @mcp.tool()
# def processes_known_servers() -> str:
#     """Show the OGC API - Processes servers configured in this MCP bridge.

#     Use this when the user asks which processing backends are available, when a
#     request mentions a server by name, or before using the generic process tools
#     without a specific base URL. The returned aliases can be passed as
#     server_url to any processes_* or jobs_* tool.

#     Known aliases currently include geolabs, cubewerx, and local. A caller may
#     also skip aliases and pass a full OGC API - Processes deployment URL such as
#     "https://example.org/ogcapi/processing" to the other tools.

#     Returns:
#         A readable list of aliases, base URLs, and the default process server.
#     """

#     lines = [f"- {alias}: {url}" for alias, url in KNOWN_PROCESS_SERVERS.items()]
#     return (
#         "Known OGC API - Processes servers:\n"
#         + "\n".join(lines)
#         + f"\n\nDefault server: {DEFAULT_PROCESS_SERVER}"
#     )


# @mcp.tool()
# def processes_get_landing_page(server_url: str = "") -> str:
#     """Retrieve the landing page for an OGC API deployment.

#     Use this as a lightweight capability/discovery check when connecting to an
#     unfamiliar OGC API server. The landing page usually contains links to key
#     resources such as /api, /conformance, /processes, collections, and service
#     metadata. This tool does not execute any process.

#     Typical workflow:
#     1. Call processes_get_landing_page to verify the server is reachable.
#     2. Call processes_get_conformance to inspect advertised standards support.
#     3. Call processes_list to discover available processes.

#     Args:
#         server_url: Server alias or base URL. Known aliases: geolabs, cubewerx, local.

#     Returns:
#         The landing page JSON, truncated if it is too large.
#     """

#     base_url = resolve_process_server(server_url)
#     _, data, error = _request_process_server(
#         "GET",
#         base_url,
#         "/",
#         params={"f": "json"},
#     )
#     if error:
#         return error
#     return f"Landing page for {base_url}:\n{_dump_limited(data, 8000)}"


# @mcp.tool()
# def processes_get_conformance(server_url: str = "") -> str:
#     """Retrieve conformance classes advertised by an OGC API server.

#     Use this to check whether a server claims support for OGC API - Processes
#     Core, JSON encodings, job list, async execution, or related OGC API
#     building blocks. This is especially useful before attempting generic
#     execution against a server you have not used before.

#     This tool only reads /conformance. It does not list process IDs; call
#     processes_list for that.

#     Args:
#         server_url: Server alias or base URL. Known aliases: geolabs, cubewerx, local.

#     Returns:
#         A readable list of conformance class URIs, or the raw conformance body.
#     """

#     base_url = resolve_process_server(server_url)
#     _, data, error = _request_process_server(
#         "GET",
#         base_url,
#         "/conformance",
#         params={"f": "json"},
#     )
#     if error:
#         return error

#     classes = data.get("conformsTo", []) if isinstance(data, dict) else []
#     if classes:
#         return f"Conformance classes at {base_url}:\n" + "\n".join(f"- {c}" for c in classes)

#     return f"Conformance response from {base_url}:\n{_dump_limited(data, 8000)}"


# @mcp.tool()
# def processes_list(server_url: str = "") -> str:
#     """List all processes advertised by an OGC API - Processes server.

#     Use this before executing anything. It calls GET /processes and returns the
#     process identifiers, titles, descriptions, and advertised job control
#     options when present. The process ID returned by this tool is the value to
#     pass into processes_describe, processes_execute, or
#     processes_execute_from_json.

#     Use this when the user asks "what analyses are available?", "what can this
#     processing server do?", "does this server have a Delaunay process?", or
#     similar capability-discovery questions.

#     Typical workflow:
#     1. processes_list(server_url)
#     2. processes_describe(process_id, server_url)
#     3. processes_execute(...) or processes_execute_from_json(...)

#     Args:
#         server_url: Server alias or base URL. Known aliases: geolabs, cubewerx, local.

#     Returns:
#         A concise, human-readable summary of all advertised processes.
#     """

#     base_url = resolve_process_server(server_url)
#     _, data, error = _request_process_server(
#         "GET",
#         base_url,
#         "/processes",
#         params={"f": "json"},
#     )
#     if error:
#         return error

#     return _format_process_list(data, base_url)


# @mcp.tool()
# def processes_describe(process_id: str, server_url: str = "") -> str:
#     """Describe one OGC API - Processes process in detail.

#     Use this after processes_list and before execution. It calls
#     GET /processes/{process_id} and returns the advertised title, description,
#     job control options, input definitions, output definitions, and raw process
#     description. This helps the LLM build a valid execute request body using
#     the exact input and output names expected by the server.

#     This tool is especially important because process input names are not
#     standardized across servers. For example, GeoLabs Delaunay expects
#     "InputPoints", while another process may expect "product" or "geometry".

#     Args:
#         process_id: Process identifier from processes_list, for example Delaunay.
#         server_url: Server alias or base URL. Known aliases: geolabs, cubewerx, local.

#     Returns:
#         A readable process description plus the raw JSON description.
#     """

#     base_url = resolve_process_server(server_url)
#     _, data, error = _request_process_server(
#         "GET",
#         base_url,
#         f"/processes/{process_id}",
#         params={"f": "json"},
#     )
#     if error:
#         return error

#     return _format_process_description(data, base_url)


# @mcp.tool()
# def processes_execute(
#     process_id: str,
#     inputs: dict,
#     outputs: dict | None = None,
#     server_url: str = "",
#     prefer_async: bool = False,
#     timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
# ) -> str:
#     """Execute any OGC API - Processes process with structured inputs/outputs.

#     Use this when you know the process_id and can provide the execute request as
#     Python/JSON objects. The tool builds this standard OGC execute body:
#     {"inputs": <inputs>, "outputs": <outputs if provided>}

#     This is the main generic execution tool for real OGC API - Processes
#     servers. It is not tied to local demo processes such as buffer or
#     zonal-stats. It can execute any process advertised by the target server as
#     long as the inputs match that server's process description.

#     Prefer this tool when the LLM has already parsed the user's request into an
#     inputs object. Prefer processes_execute_from_json when the user or
#     documentation provides a complete execute request body that should be sent
#     exactly as written. Prefer processes_execute_reference_input for the common
#     pattern "take this OGC API Features/Records URL and pass it to a process".

#     Async behavior:
#     Set prefer_async=True for long-running jobs. If the server returns a job ID
#     or Location header, follow up with jobs_get_status and jobs_get_results.

#     Args:
#         process_id: Process identifier from processes_list.
#         inputs: JSON object for the execute request's "inputs" member. This may
#             also be a JSON string if the MCP client cannot pass objects directly.
#         outputs: Optional JSON object for the execute request's "outputs" member.
#         server_url: Server alias or base URL. Known aliases: geolabs, cubewerx, local.
#         prefer_async: If true, sends Prefer: respond-async for long-running jobs.
#         timeout_seconds: HTTP request timeout.

#     Returns:
#         HTTP status, key response headers, possible job ID, and response body.
#     """

#     base_url = resolve_process_server(server_url)
#     try:
#         coerced_inputs = _coerce_json(inputs, "inputs")
#         coerced_outputs = _coerce_json(outputs, "outputs")
#     except ValueError as exc:
#         return str(exc)

#     payload = {"inputs": coerced_inputs}
#     if coerced_outputs:
#         payload["outputs"] = coerced_outputs

#     response, data, error = _request_process_server(
#         "POST",
#         base_url,
#         f"/processes/{process_id}/execution",
#         body=payload,
#         prefer_async=prefer_async,
#         timeout_seconds=timeout_seconds,
#     )
#     if error:
#         return error

#     return _format_execute_response(response, data, base_url)


# @mcp.tool()
# def processes_execute_from_json(
#     process_id: str,
#     execute_request_json: str,
#     server_url: str = "",
#     prefer_async: bool = False,
#     timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
# ) -> str:
#     """Execute an OGC process using a complete JSON execute request body.

#     Use this when the user, mentor, API documentation, or process description
#     provides an exact request body and it should be sent with minimal
#     transformation. This is the safest choice for real-world examples because
#     some OGC API - Processes servers use process-specific input structures,
#     media type hints, or output objects that should not be simplified.

#     Example use case:
#     GeoLabs Delaunay expects a body containing:
#     {
#       "inputs": {
#         "InputPoints": {
#           "type": "text/xml",
#           "href": "https://demo.pygeoapi.io/master/collections/dutch_windmills/items?f=json"
#         }
#       },
#       "outputs": {
#         "Result": {
#           "format": {"mediaType": "application/json"},
#           "transmissionMode": "value"
#         }
#       }
#     }

#     Async behavior:
#     Set prefer_async=True for long-running processes. If the server creates a
#     job, use jobs_get_status and jobs_get_results afterward.

#     Args:
#         process_id: Process identifier from processes_list.
#         execute_request_json: Complete JSON body, including inputs and optional outputs.
#         server_url: Server alias or base URL. Known aliases: geolabs, cubewerx, local.
#         prefer_async: If true, sends Prefer: respond-async for long-running jobs.
#         timeout_seconds: HTTP request timeout.

#     Returns:
#         HTTP status, key response headers, possible job ID, and response body.
#     """

#     base_url = resolve_process_server(server_url)
#     try:
#         payload = _coerce_json(execute_request_json, "execute_request_json")
#     except ValueError as exc:
#         return str(exc)

#     if not isinstance(payload, dict):
#         return "execute_request_json must decode to a JSON object."

#     response, data, error = _request_process_server(
#         "POST",
#         base_url,
#         f"/processes/{process_id}/execution",
#         body=payload,
#         prefer_async=prefer_async,
#         timeout_seconds=timeout_seconds,
#     )
#     if error:
#         return error

#     return _format_execute_response(response, data, base_url)


# @mcp.tool()
# def processes_execute_reference_input(
#     process_id: str,
#     input_name: str,
#     href: str,
#     input_type: str = "text/xml",
#     output_name: str = "Result",
#     output_media_type: str = "application/json",
#     server_url: str = "",
#     prefer_async: bool = False,
#     timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
# ) -> str:
#     """Execute a process by passing one external dataset URL as a referenced input.

#     Use this for the important OGC chaining pattern where one OGC API provides
#     data and another OGC API - Processes server consumes that data by reference.
#     For example, pass an OGC API - Features items URL from demo.pygeoapi into
#     the GeoLabs Delaunay process.

#     This tool constructs a body like:
#     {
#       "inputs": {
#         "<input_name>": {
#           "type": "<input_type>",
#           "href": "<href>"
#         }
#       },
#       "outputs": {
#         "<output_name>": {
#           "format": {"mediaType": "<output_media_type>"},
#           "transmissionMode": "value"
#         }
#       }
#     }

#     For the mentor-provided GeoLabs test, use:
#     server_url="geolabs", process_id="Delaunay", input_name="InputPoints",
#     href="https://demo.pygeoapi.io/master/collections/dutch_windmills/items?f=json",
#     input_type="text/xml", output_name="Result",
#     output_media_type="application/json".

#     Args:
#         process_id: Process identifier from processes_list.
#         input_name: Name of the process input that accepts the reference.
#         href: URL to the dataset or collection items endpoint.
#         input_type: Media type/value expected by the process description.
#         output_name: Output identifier to request as a returned value.
#         output_media_type: Requested output media type.
#         server_url: Server alias or base URL. Known aliases: geolabs, cubewerx, local.
#         prefer_async: If true, sends Prefer: respond-async for long-running jobs.
#         timeout_seconds: HTTP request timeout.

#     Returns:
#         HTTP status, key response headers, possible job ID, and response body.
#     """

#     reference = {"href": href}
#     if input_type:
#         reference["type"] = input_type

#     outputs = {}
#     if output_name:
#         outputs[output_name] = {
#             "format": {"mediaType": output_media_type},
#             "transmissionMode": "value",
#         }

#     return processes_execute(
#         process_id=process_id,
#         inputs={input_name: reference},
#         outputs=outputs or None,
#         server_url=server_url,
#         prefer_async=prefer_async,
#         timeout_seconds=timeout_seconds,
#     )


# @mcp.tool()
# def jobs_list(
#     server_url: str = "",
#     process_id: str = "",
#     status: str = "",
#     limit: int = 20,
# ) -> str:
#     """List jobs known to an OGC API - Processes server.

#     Use this when the user asks what processing jobs exist, wants to monitor
#     submitted work, or needs to find a job ID before checking status/results.
#     This calls GET /jobs and supports common filters when the target server
#     implements them.

#     This is mainly useful after async execution. For synchronous executions,
#     results are usually returned directly by processes_execute or
#     processes_execute_from_json.

#     Args:
#         server_url: Server alias or base URL. Known aliases: geolabs, cubewerx, local.
#         process_id: Optional processID filter.
#         status: Optional status filter, for example accepted, running, successful, failed.
#         limit: Maximum number of jobs to request.

#     Returns:
#         A readable list of job IDs, process IDs, status values, and timestamps.
#     """

#     base_url = resolve_process_server(server_url)
#     params = {"f": "json", "limit": limit}
#     if process_id:
#         params["processID"] = process_id
#     if status:
#         params["status"] = status

#     _, data, error = _request_process_server(
#         "GET",
#         base_url,
#         "/jobs",
#         params=params,
#     )
#     if error:
#         return error

#     jobs = data.get("jobs", []) if isinstance(data, dict) else []
#     if not jobs:
#         return f"No jobs found at {base_url}.\n\nRaw response:\n{_dump_limited(data, 4000)}"

#     lines = []
#     for job in jobs:
#         job_id = job.get("jobID") or job.get("jobId") or job.get("id") or ""
#         lines.append(
#             f"- {job_id[:12]}... | "
#             f"{job.get('processID') or job.get('processId') or ''} | "
#             f"{job.get('status', '')} | "
#             f"{job.get('created', '') or job.get('started', '')}"
#         )

#     return f"Jobs at {base_url} ({len(jobs)} shown):\n" + "\n".join(lines)


# @mcp.tool()
# def jobs_get_status(job_id: str, server_url: str = "") -> str:
#     """Get status/progress metadata for a single OGC API - Processes job.

#     Use this after an async execution returns a job ID or Location header.
#     Poll this tool until the job status is successful or failed. Typical status
#     values include accepted, running, successful, failed, and dismissed, but
#     exact values depend on the server.

#     Do not call jobs_get_results until this tool indicates the job is complete
#     or the server documentation says results are already available.

#     Args:
#         job_id: Job ID returned by a previous async execution.
#         server_url: Server alias or base URL. Known aliases: geolabs, cubewerx, local.

#     Returns:
#         The job status document from GET /jobs/{job_id}.
#     """

#     base_url = resolve_process_server(server_url)
#     _, data, error = _request_process_server(
#         "GET",
#         base_url,
#         f"/jobs/{job_id}",
#         params={"f": "json"},
#     )
#     if error:
#         return error

#     return f"Status for job {job_id} at {base_url}:\n{_dump_limited(data, 8000)}"


# @mcp.tool()
# def jobs_get_results(job_id: str, server_url: str = "") -> str:
#     """Retrieve results for a completed OGC API - Processes job.

#     Use this after jobs_get_status reports a successful/completed job. It calls
#     GET /jobs/{job_id}/results and returns the result payload. The result format
#     is process-specific: it may be GeoJSON, statistics JSON, links to output
#     files, or another media type represented by the server.

#     If this returns a "results not ready" or 404-style response, call
#     jobs_get_status again and wait until the server reports completion.

#     Args:
#         job_id: Job ID returned by a previous async execution.
#         server_url: Server alias or base URL. Known aliases: geolabs, cubewerx, local.

#     Returns:
#         The job result document, truncated if it is too large.
#     """

#     base_url = resolve_process_server(server_url)
#     _, data, error = _request_process_server(
#         "GET",
#         base_url,
#         f"/jobs/{job_id}/results",
#         params={"f": "json"},
#     )
#     if error:
#         return error

#     return f"Results for job {job_id} at {base_url}:\n{_dump_limited(data, 12000)}"


# @mcp.tool()
# def jobs_delete(job_id: str, server_url: str = "") -> str:
#     """Dismiss, cancel, or delete a job if the server supports DELETE /jobs/{job_id}.

#     Use this only when the user asks to cancel/clean up a job, or after results
#     have been retrieved and it is appropriate to remove server-side job state.
#     Some servers may reject deletion for completed jobs, protected jobs, or jobs
#     owned by another user.

#     This is a state-changing operation. Prefer jobs_get_status or
#     jobs_get_results for read-only inspection.

#     Args:
#         job_id: Job ID to dismiss.
#         server_url: Server alias or base URL. Known aliases: geolabs, cubewerx, local.

#     Returns:
#         The server response from DELETE /jobs/{job_id}.
#     """

#     base_url = resolve_process_server(server_url)
#     _, data, error = _request_process_server(
#         "DELETE",
#         base_url,
#         f"/jobs/{job_id}",
#     )
#     if error:
#         return error

#     return f"Delete/dismiss response for job {job_id} at {base_url}:\n{_dump_limited(data, 4000) or '(empty response body)'}"


# # Backward-compatible names for earlier Claude Desktop configs/prompts.

# @mcp.tool()
# def list_processes(server_url: str = "") -> str:
#     """Backward-compatible alias for processes_list.

#     Use this exactly like processes_list when an older prompt or Claude Desktop
#     configuration expects the previous tool name. It lists process IDs,
#     descriptions, and job control hints from GET /processes.

#     Args:
#         server_url: Server alias or base URL. Known aliases: geolabs, cubewerx, local.
#     """
#     return processes_list(server_url=server_url)


# @mcp.tool()
# def get_process_details(process_id: str, server_url: str = "") -> str:
#     """Backward-compatible alias for processes_describe.

#     Use this exactly like processes_describe when an older prompt or MCP client
#     expects the previous tool name. It fetches GET /processes/{process_id} and
#     returns input/output details needed to build a valid execute request.

#     Args:
#         process_id: Process identifier from list_processes/processes_list.
#         server_url: Server alias or base URL. Known aliases: geolabs, cubewerx, local.
#     """
#     return processes_describe(process_id=process_id, server_url=server_url)


# @mcp.tool()
# def list_jobs(server_url: str = "") -> str:
#     """Backward-compatible alias for jobs_list.

#     Use this exactly like jobs_list when an older prompt or MCP client expects
#     the previous tool name. It lists jobs from GET /jobs on the selected
#     process server.

#     Args:
#         server_url: Server alias or base URL. Known aliases: geolabs, cubewerx, local.
#     """
#     return jobs_list(server_url=server_url)


# @mcp.tool()
# def get_job_results(job_id: str, server_url: str = "") -> str:
#     """Backward-compatible alias for jobs_get_results.

#     Use this exactly like jobs_get_results when an older prompt or MCP client
#     expects the previous tool name. It retrieves output from
#     GET /jobs/{job_id}/results after async execution completes.

#     Args:
#         job_id: Job ID returned by a previous async execution.
#         server_url: Server alias or base URL. Known aliases: geolabs, cubewerx, local.
#     """
#     return jobs_get_results(job_id=job_id, server_url=server_url)

# # ─── OGC API – Features Tools ─────────────────────────────────────────────────

# FEATURES_BASE_URL = "https://demo.pygeoapi.io/master"


# @mcp.tool()
# def features_list_collections() -> str:
#     """List available collections from the configured OGC API - Features server.

#     Use this when the user asks what feature datasets, layers, or collections
#     are available. It calls GET /collections on the demo pygeoapi Features
#     server and returns collection IDs, titles, and short descriptions.

#     This is usually the first step for data discovery before fetching actual
#     features. For process chaining, use this to identify candidate input data,
#     then call features_get_collection_info or features_get_items. A collection
#     items URL can later be passed by reference to processes_execute_reference_input.

#     Returns:
#         A readable list of feature collection IDs and descriptions.
#     """

#     response = requests.get(
#         f"{FEATURES_BASE_URL}/collections",
#         params={"f": "json"}
#     )
#     response.raise_for_status()
#     collections = response.json().get("collections", [])

#     lines = []
#     for c in collections:
#         title = c.get("title", c.get("id", "unknown"))
#         cid = c.get("id", "unknown")
#         desc = c.get("description", "No description")[:100]
#         lines.append(f"- {cid}: {title} — {desc}")

#     return f"""Available feature collections ({len(collections)} total):

# {chr(10).join(lines)}

# Use features_get_items with a collection_id to fetch actual features."""


# @mcp.tool()
# def features_get_collection_info(collection_id: str) -> str:
#     """Describe one OGC API - Features collection.

#     Use this after features_list_collections and before fetching items when the
#     model needs more context about a dataset. It calls
#     GET /collections/{collection_id} and summarizes title, description, and
#     spatial extent. This helps decide whether a collection is suitable as input
#     to a processing workflow.

#     Use this for questions such as "what area does this dataset cover?",
#     "what is the lakes collection?", or "is this collection likely to contain
#     the data I need?".

#     Args:
#         collection_id: The ID of the collection (e.g. 'lakes', 'airports', 'roads')

#     Returns:
#         Collection metadata including title, description, and bounding box.
#     """

#     response = requests.get(
#         f"{FEATURES_BASE_URL}/collections/{collection_id}",
#         params={"f": "json"}
#     )
#     response.raise_for_status()
#     c = response.json()

#     bbox = c.get("extent", {}).get("spatial", {}).get("bbox", [[]])[0]
#     bbox_str = f"{bbox}" if bbox else "Not specified"

#     return f"""Collection: {c.get('id')}
# Title: {c.get('title', 'No title')}
# Description: {c.get('description', 'No description')}
# Bounding box: {bbox_str}

# Use features_get_items to fetch actual features from this collection."""


# @mcp.tool()
# def features_get_items(
#     collection_id: str,
#     bbox: str = None,
#     limit: int = 10,
#     property_filter: str = None
# ) -> str:
#     """Fetch feature items from an OGC API - Features collection.

#     Use this when the user wants actual geospatial features: points, lines,
#     polygons, properties, or sample records from a collection. It calls
#     GET /collections/{collection_id}/items and supports bbox, limit, and a
#     simple property=value filter.

#     This tool returns summarized features rather than the full geometry for
#     every item, which keeps model context small. If you need the complete
#     geometry of one specific feature, call features_get_feature_by_id afterward.

#     For process chaining, this tool is useful to inspect data, but many OGC
#     processes should receive a collection/items URL by reference instead of a
#     large inline FeatureCollection. For that pattern, pass an href such as
#     "https://demo.pygeoapi.io/master/collections/dutch_windmills/items?f=json"
#     to processes_execute_reference_input.

#     Args:
#         collection_id: The collection to query (e.g. 'lakes', 'airports')
#         bbox: Optional bounding box as 'minLon,minLat,maxLon,maxLat'
#               Example: '77.4,12.8,77.8,13.1' for Bangalore area
#               Leave empty to get features from anywhere
#         limit: Maximum number of features to return (default 10, max 50)
#         property_filter: Optional property name and value to filter by
#                         Example: 'name=Bangalore' or 'type=airport'

#     Returns:
#         A concise list of matching feature IDs, geometry types, and key properties.
#     """

#     params = {"f": "json", "limit": min(limit, 50)}

#     if bbox:
#         params["bbox"] = bbox

#     if property_filter and "=" in property_filter:
#         key, value = property_filter.split("=", 1)
#         params[key.strip()] = value.strip()

#     response = requests.get(
#         f"{FEATURES_BASE_URL}/collections/{collection_id}/items",
#         params=params
#     )
#     response.raise_for_status()
#     data = response.json()

#     features = data.get("features", [])
#     total = data.get("numberMatched", "unknown")

#     if not features:
#         return f"No features found in collection '{collection_id}' with the given filters."

#     lines = []
#     for f in features:
#         fid = f.get("id", "unknown")
#         props = f.get("properties", {})
#         geom_type = f.get("geometry", {}).get("type", "unknown") if f.get("geometry") else "no geometry"

#         prop_summary = ", ".join(
#             f"{k}={v}" for k, v in list(props.items())[:4] if v is not None
#         )
#         lines.append(f"- [{fid}] ({geom_type}) {prop_summary}")

#     return f"""Features from '{collection_id}' (showing {len(features)} of {total} total):

# {chr(10).join(lines)}

# Use features_get_feature_by_id to get full details of a specific feature."""


# @mcp.tool()
# def features_get_feature_by_id(collection_id: str, feature_id: str) -> str:
#     """Retrieve one complete GeoJSON feature by collection ID and feature ID.

#     Use this after features_get_items when the user asks for a specific feature
#     or when a downstream process needs the exact geometry/properties of one
#     feature. It calls GET /collections/{collection_id}/items/{feature_id} and
#     returns the full GeoJSON feature.

#     This is best for single-feature workflows. For large datasets or whole
#     collections, avoid dumping full GeoJSON into the model; pass a referenced
#     collection/items URL into processes_execute_reference_input instead.

#     Args:
#         collection_id: The collection the feature belongs to
#         feature_id: The ID of the specific feature to retrieve

#     Returns:
#         Full GeoJSON for the requested feature.
#     """

#     response = requests.get(
#         f"{FEATURES_BASE_URL}/collections/{collection_id}/items/{feature_id}",
#         params={"f": "json"}
#     )
#     response.raise_for_status()
#     feature = response.json()

#     props = feature.get("properties", {})
#     geom = feature.get("geometry", {})
#     geom_type = geom.get("type", "unknown")

#     props_lines = [f"  {k}: {v}" for k, v in props.items() if v is not None]

#     return f"""Feature {feature_id} from '{collection_id}':

# Geometry type: {geom_type}
# Properties:
# {chr(10).join(props_lines)}

# Full GeoJSON:
# {json.dumps(feature, indent=2)}"""



# # ─── OGC API – Records Tools ──────────────────────────────────────────────────

# RECORDS_BASE_URL = "https://demo.pycsw.org/gisdata"
# RECORDS_COLLECTION = "metadata:main"


# @mcp.tool()
# def records_search(
#     keyword: str = None,
#     bbox: str = None,
#     limit: int = 10
# ) -> str:
#     """Search an OGC API - Records catalogue for geospatial datasets.

#     Use this when the user needs to discover data by topic, keyword, or area
#     before querying features or running a process. It calls the configured
#     Records collection with q, bbox, and limit parameters and returns concise
#     metadata records.

#     This should usually come before process execution when the user has not
#     already provided an input dataset. For example, use this for requests like
#     "find temperature datasets", "is there flood data near this area?", or
#     "search the catalogue for windmill data".

#     After finding a relevant record, call records_get_record to inspect full
#     metadata and links. Any suitable download/service URL discovered there can
#     be used as an href for a process input if the process accepts references.

#     Args:
#         keyword: Search term to find relevant datasets
#                  Example: 'temperature', 'roads', 'flood', 'land use'
#         bbox: Optional area filter as 'minLon,minLat,maxLon,maxLat'
#               Example: '77.4,12.8,77.8,13.1' to find data near Bangalore
#         limit: Maximum number of records to return (default 10)

#     Returns:
#         A concise list of matching catalogue records with IDs and descriptions.
#     """

#     params = {"f": "json", "limit": min(limit, 20)}

#     if keyword:
#         params["q"] = keyword

#     if bbox:
#         params["bbox"] = bbox

#     response = requests.get(
#         f"{RECORDS_BASE_URL}/collections/{RECORDS_COLLECTION}/items",
#         params=params
#     )
#     response.raise_for_status()
#     data = response.json()

#     features = data.get("features", [])
#     total = data.get("numberMatched", "unknown")

#     if not features:
#         return f"No records found matching '{keyword}'. Try a different search term."

#     lines = []
#     for f in features:
#         props = f.get("properties", {})
#         record_id = f.get("id", "unknown")
#         title = props.get("title", "No title")
#         description = props.get("description", props.get("abstract", "No description"))
#         if description and len(description) > 120:
#             description = description[:120] + "..."
#         record_type = props.get("type", props.get("recordtype", "dataset"))
#         lines.append(f"- [{record_id}]\n  Title: {title}\n  Type: {record_type}\n  Description: {description}")

#     return f"""Catalogue search results for '{keyword}' ({len(features)} of {total} total):

# {chr(10).join(lines)}

# Use records_get_record with a record ID to get full metadata including download links."""


# @mcp.tool()
# def records_get_record(record_id: str) -> str:
#     """Retrieve complete metadata for one OGC API - Records catalogue record.

#     Use this after records_search when the model needs full dataset metadata,
#     provider details, temporal/spatial extent, keywords, and links. This is the
#     tool to call before deciding whether a catalogue result can be used as
#     input to an OGC process.

#     Look carefully at returned links. If a link points to downloadable data or
#     an OGC API endpoint, it may be usable as an href in
#     processes_execute_reference_input or inside a custom execute JSON body.

#     Args:
#         record_id: The ID of the record from records_search results

#     Returns:
#         Full metadata summary for the requested record, including available links.
#     """

#     response = requests.get(
#         f"{RECORDS_BASE_URL}/collections/{RECORDS_COLLECTION}/items/{record_id}",
#         params={"f": "json"}
#     )
#     response.raise_for_status()
#     feature = response.json()
#     props = feature.get("properties", {})

#     # Extract links
#     links = feature.get("links", [])
#     link_lines = []
#     for link in links:
#         rel = link.get("rel", "link")
#         href = link.get("href", "")
#         title = link.get("title", rel)
#         if href:
#             link_lines.append(f"  - {title}: {href}")

#     # Extract key metadata
#     title = props.get("title", "No title")
#     description = props.get("description", props.get("abstract", "No description"))
#     record_type = props.get("type", props.get("recordtype", "unknown"))
#     created = props.get("created", props.get("date", "unknown"))
#     updated = props.get("updated", props.get("modified", "unknown"))
#     language = props.get("language", "unknown")
#     keywords = props.get("keywords", props.get("subject", []))

#     if isinstance(keywords, list):
#         keywords_str = ", ".join(keywords[:8])
#     else:
#         keywords_str = str(keywords)

#     # Spatial extent
#     bbox = feature.get("bbox", [])
#     bbox_str = f"{bbox}" if bbox else "Not specified"

#     return f"""Record: {record_id}
# Title: {title}
# Type: {record_type}
# Description: {description}

# Spatial extent: {bbox_str}
# Created: {created}
# Updated: {updated}
# Language: {language}
# Keywords: {keywords_str}

# Links:
# {chr(10).join(link_lines) if link_lines else '  No links available'}"""


# @mcp.tool()
# def records_list_collections() -> str:
#     """List available catalogue collections from the OGC API - Records server.

#     Use this when the user asks what catalogues or metadata collections are
#     available, or before searching an unfamiliar Records server. The current MCP
#     bridge searches a default collection, but this tool exposes the catalogue
#     collection IDs so the model can understand what metadata sources exist.

#     For normal topic search, call records_search after this. For full metadata
#     on one search result, call records_get_record.

#     Returns:
#         A readable list of catalogue collection IDs, titles, and descriptions.
#     """

#     response = requests.get(
#         f"{RECORDS_BASE_URL}/collections",
#         params={"f": "json"}
#     )
#     response.raise_for_status()
#     collections = response.json().get("collections", [])

#     lines = []
#     for c in collections:
#         cid = c.get("id", "unknown")
#         title = c.get("title", "No title")
#         desc = c.get("description", "No description")[:100]
#         lines.append(f"- {cid}: {title} — {desc}")

#     return f"""Available catalogue collections ({len(collections)} total):

# {chr(10).join(lines)}

# Use records_search with a keyword to find specific datasets."""


# # ─── Entry point ──────────────────────────────────────────────────────────────

# if __name__ == "__main__":
#     mcp.run()
