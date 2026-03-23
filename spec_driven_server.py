"""
spec_driven_server.py
Reads ogc-mcp-mapping.json and automatically creates MCP tools from it.
This is the real implementation of spec-driven tool registration.
"""

import json
import asyncio
import requests
from mcp.server.fastmcp import FastMCP

# ── Load the spec ─────────────────────────────────────────────────────────────

with open("/Users/pranavangrish/Desktop/GSOC/code/gsoc-mcp/spec/ogc-mcp-mapping.json") as f:
    SPEC = json.load(f)

# ── Config ────────────────────────────────────────────────────────────────────

SERVER_CONFIGS = {
    "processes": {
        "base_url": "http://localhost",
        "auth": {"type": "jwt", "username": "admin", "password": "admin123"}
    },
    "features": {
        "base_url": "https://demo.pygeoapi.io/master",
        "auth": {"type": "none"}
    },
    "records": {
        "base_url": "https://demo.pycsw.org/gisdata",
        "auth": {"type": "none"}
    }
}

mcp = FastMCP("ogc-api-spec-driven")

# ── Auth helper ───────────────────────────────────────────────────────────────

def get_headers(module_id: str) -> dict:
    """Get auth headers for a specific module's server."""
    config = SERVER_CONFIGS.get(module_id, {})
    auth = config.get("auth", {})

    if auth.get("type") == "jwt":
        response = requests.post(
            f"{config['base_url']}/auth/login",
            json={"username": auth["username"], "password": auth["password"]}
        )
        token = response.json()["token"]
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    return {"Content-Type": "application/json"}


def get_base_url(module_id: str) -> str:
    return SERVER_CONFIGS.get(module_id, {}).get("base_url", "")

# ── The core executor ─────────────────────────────────────────────────────────

def execute_tool(tool_spec: dict, arguments: dict) -> str:
    """
    Takes a tool definition from the spec and a set of arguments,
    constructs the correct HTTP request, calls the OGC API,
    and returns a summarised result.

    This is the single function that replaces ALL the individual
    if/elif blocks in our original server.
    """

    module_id   = tool_spec["module"]
    http        = tool_spec["http_mapping"]
    output_spec = tool_spec["output_schema"]

    base_url    = get_base_url(module_id)
    headers     = get_headers(module_id)

    # ── 1. Build the URL path ─────────────────────────────────────────────────
    # Replace {placeholders} in path template with actual argument values
    # e.g. "/collections/{collection_id}/items/{feature_id}"
    # becomes "/collections/lakes/items/ontario"

    path = http["path_template"]
    for param in http.get("path_params", []):
        if param in arguments:
            path = path.replace(f"{{{param}}}", str(arguments[param]))

    url = f"{base_url}{path}"

    # ── 2. Build query parameters ─────────────────────────────────────────────
    # Start with defaults from spec (e.g. f=json)
    # Then add any query params provided in arguments

    params = dict(http.get("default_params", {}))
    for param in http.get("query_params", []):
        if param in arguments and arguments[param] is not None:
            params[param] = arguments[param]

    # ── 3. Build request body (for POST requests) ─────────────────────────────

    body = None
    if http["method"] == "POST":
        body_params = http.get("body_params", [])
        if "inputs" in body_params and "inputs" in arguments:
            body = {"inputs": arguments["inputs"]}

    # ── 4. Make the HTTP request ──────────────────────────────────────────────

    try:
        if http["method"] == "GET":
            response = requests.get(url, headers=headers, params=params)
        elif http["method"] == "POST":
            response = requests.post(url, headers=headers, params=params, json=body)
        elif http["method"] == "DELETE":
            response = requests.delete(url, headers=headers)

        # ── 5. Handle errors using spec's error_handling ──────────────────────
        # Translate HTTP error codes to plain English using the spec

        if not response.ok:
            error_code = str(response.status_code)
            errors = tool_spec.get("error_handling", {}).get("errors", [])
            for err in errors:
                if err["code"] == error_code:
                    return f"Error: {err['plain_english']}\nSuggested action: {err['llm_action']}"
            return f"Error {response.status_code}: {response.text[:200]}"

        data = response.json()

        # ── 6. Summarise response using spec's summary_fields ─────────────────
        # Only extract the fields the spec says to show the LLM
        # This prevents context window overflow from huge GeoJSON responses

        summary_fields = output_spec.get("summary_fields", [])
        followup_tools = output_spec.get("followup_tools", [])

        summary = summarise_response(data, summary_fields)

        followup_hint = ""
        if followup_tools:
            followup_hint = f"\n\nSuggested next tools: {', '.join(followup_tools)}"

        return f"{summary}{followup_hint}"

    except requests.exceptions.ConnectionError:
        return f"Cannot connect to {base_url}. Make sure the server is running."
    except Exception as e:
        return f"Unexpected error: {str(e)}"


def summarise_response(data: dict | list, summary_fields: list) -> str:
    """
    Extracts and formats only the relevant fields from an OGC API response.
    Uses the summary_fields from the spec to decide what to show.
    """

    # Handle FeatureCollection (Features API response)
    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        features = data.get("features", [])
        total = data.get("numberMatched", len(features))
        lines = []
        for f in features[:10]:  # never show more than 10 to LLM
            fid = f.get("id", "unknown")
            props = f.get("properties", {})
            geom_type = f.get("geometry", {}).get("type", "unknown") if f.get("geometry") else "none"
            prop_summary = ", ".join(f"{k}={v}" for k, v in list(props.items())[:3] if v)
            lines.append(f"  [{fid}] ({geom_type}) {prop_summary}")
        return f"Results: {len(features)} of {total} total\n" + "\n".join(lines)

    # Handle single Feature (get feature by ID)
    if isinstance(data, dict) and data.get("type") == "Feature":
        props = data.get("properties", {})
        geom_type = data.get("geometry", {}).get("type", "unknown")
        prop_lines = [f"  {k}: {v}" for k, v in props.items() if v is not None]
        return f"Feature ({geom_type})\nProperties:\n" + "\n".join(prop_lines)

    # Handle collections list
    if isinstance(data, dict) and "collections" in data:
        collections = data["collections"]
        lines = [f"  {c.get('id')}: {c.get('title', c.get('description', ''))[:80]}"
                 for c in collections]
        return f"{len(collections)} collections available:\n" + "\n".join(lines)

    # Handle processes list
    if isinstance(data, dict) and "processes" in data:
        processes = data["processes"]
        lines = [f"  {p.get('id')}: {p.get('description', '')[:80]}"
                 for p in processes]
        return f"{len(processes)} processes available:\n" + "\n".join(lines)

    # Handle jobs list
    if isinstance(data, dict) and "jobs" in data:
        jobs = data["jobs"]
        lines = [f"  {j.get('jobID','')[:8]}... | {j.get('processID')} | {j.get('status')}"
                 for j in jobs]
        return f"{len(jobs)} jobs:\n" + "\n".join(lines)

    # Handle statistics result
    if isinstance(data, dict) and "statistics" in data:
        stats = data["statistics"]
        lines = [f"  {k}: {v}" for k, v in stats.items()]
        return "Statistics:\n" + "\n".join(lines)

    # Default — return formatted JSON but limit size
    text = json.dumps(data, indent=2)
    if len(text) > 2000:
        text = text[:2000] + "\n... (truncated)"
    return text


# ── Spec-driven tool registration ─────────────────────────────────────────────
# THIS is the part that was pseudocode before — here is how it actually works

def register_tools_from_spec(spec: dict):
    """
    Reads every tool from the spec and registers it as an MCP tool.

    The key insight: we use a closure to capture the tool_spec
    for each tool, then create a function dynamically.
    Without the closure, all tools would share the same tool_spec
    reference (the last one in the loop).
    """

    for module_id, module in spec["modules"].items():
        for tool_spec in module["tools"]:

            # Capture tool_spec in closure — critical
            def make_tool_function(captured_spec):

                # Build the function signature dynamically
                # based on the input_schema in the spec
                params = captured_spec["input_schema"].get("parameters", [])
                required_params = [p for p in params if p["required"]]
                optional_params = [p for p in params if not p["required"]]

                if not params:
                    # Tool takes no arguments
                    def tool_fn() -> str:
                        return execute_tool(captured_spec, {})

                elif len(required_params) == 1 and not optional_params:
                    # Tool takes exactly one required argument
                    param = required_params[0]
                    def tool_fn(**kwargs) -> str:
                        return execute_tool(captured_spec, kwargs)

                else:
                    # Tool takes multiple arguments
                    def tool_fn(**kwargs) -> str:
                        return execute_tool(captured_spec, kwargs)

                # Set the function name and docstring from the spec
                tool_fn.__name__ = captured_spec["id"]
                tool_fn.__doc__ = (
                    f"{captured_spec['description']}\n\n"
                    f"Natural language triggers:\n" +
                    "\n".join(f"  - {t}" for t in
                              captured_spec.get("natural_language_triggers", []))
                )

                return tool_fn

            # Register with FastMCP
            tool_function = make_tool_function(tool_spec)
            mcp.tool()(tool_function)

            print(f"Registered tool: {tool_spec['id']}")


# ── Register all tools from spec ──────────────────────────────────────────────

register_tools_from_spec(SPEC)
print(f"\nAll tools registered from spec. Starting server...")

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()


# ## What Just Happened — Step By Step
# ```
# 1. Load spec JSON
#         ↓
# 2. Loop through every module (processes, features, records)
#         ↓
# 3. For each tool in each module:
#    - Read its description → becomes the docstring
#    - Read its http_mapping → used to build HTTP calls
#    - Read its input_schema → defines what arguments to accept
#    - Read its output_schema → defines how to summarise response
#    - Create a function dynamically
#    - Register it with FastMCP
#         ↓
# 4. When Claude calls a tool:
#    - execute_tool() is called with the tool's spec + arguments
#    - Builds URL from path_template
#    - Adds query params and body
#    - Makes HTTP request
#    - Translates errors using spec's error_handling
#    - Summarises response using spec's summary_fields
#    - Returns clean result to Claude