"""FastMCP application exposing a stable OGC API tool contract."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from .errors import OgcMcpError
from .result import invoke, parse_json_object
from .runtime import ProxyRuntime, create_runtime
from .services.sanitization import DEFAULT_SUMMARY_FIELDS


SERVER_INSTRUCTIONS = """
This MCP server is a reference bridge for OGC APIs. It gives non-GIS users
access to geospatial data and processes through plain language — but only when
each step is validated and explicitly approved by the human.

━━━ HUMAN-IN-THE-LOOP RULES — ALWAYS FOLLOW, NO EXCEPTIONS ━━━

RULE 1 — NEVER ASSUME VAGUE INPUTS.
If the user says "near XYZ", "around the city", "close to", "draw a circle",
or uses any spatial language without exact coordinates or a numeric distance,
STOP and ask for clarification. Do not guess coordinates, buffer sizes, or
area boundaries on behalf of the user.

RULE 2 — ONE QUESTION AT A TIME FOR MISSING INPUTS.
When ogc_proxy_create_plan or ogc_proxy_update_plan returns resolution_required=true,
read resolution_prompt.per_field_questions and ask the user each question ONE
AT A TIME. Wait for a concrete answer before moving to the next question.
After collecting all answers, call ogc_proxy_update_plan (not ogc_proxy_create_plan
again) with the corrected execute_request. Repeat until resolution_required=false.

RULE 3 — ALWAYS SHOW execute_request VERBATIM BEFORE CONFIRMING.
After ogc_proxy_create_plan or ogc_proxy_update_plan returns confirmation_required=true,
read confirmation_prompt.execute_request and display it to the user exactly as-is —
do NOT paraphrase or summarize the inputs. Ask: "These are the exact parameters
that will be sent. Do you approve?" Only call ogc_proxy_confirm_plan(approved=True)
after the user explicitly says yes.

RULE 4 — REJECT RATHER THAN GUESS.
If any value in execute_request was assumed (not explicitly stated by the user),
call ogc_proxy_confirm_plan(approved=False) and ask for the missing value.

RULE 5 — UPDATE, DON'T RECREATE.
Once a plan_id exists (even at needs_resolution), always use ogc_proxy_update_plan
to correct its inputs. Creating a new plan wastes the validated steps already stored.
To abandon a plan the user no longer wants, call ogc_proxy_confirm_plan(approved=False)
— this is valid from both needs_resolution and ready_for_confirmation states.

━━━ STANDARD WORKFLOW SEQUENCE ━━━

For unfamiliar servers, start with ogc_common_get_landing_page and ogc_proxy_get_capabilities.

For human-confirmed process execution:
1.  ogc_servers_list
2.  ogc_processes_list
3.  ogc_processes_describe  ← read EXACT input names, never invent them
4.  [If any parameter is unclear → ask user NOW, before creating a plan]
5.  ogc_proxy_create_plan
6.  If resolution_required=true → follow RULE 2 (update_plan loop)
7.  When confirmation_required=true → follow RULE 3 (show execute_request verbatim)
8.  ogc_proxy_confirm_plan  ← only after explicit user yes
9.  ogc_proxy_execute_plan
10. For async results: ogc_jobs_get_status → ogc_jobs_get_results

If a plan_id from a prior turn is unavailable, call ogc_proxy_list_plans first.
Use ogc_proxy_get_plan to inspect the current lifecycle state of any stored plan.

For dataset discovery: ogc_records_search → ogc_records_get_record
For vector data inspection: ogc_features_list_collections → ogc_features_get_items

━━━ LARGE DATA & MEMORY HANDLES ━━━

Tools that can return large or unbounded payloads (ogc_common_get_resource,
ogc_features_list_collections, ogc_features_get_items,
ogc_records_list_collections, ogc_records_search, ogc_processes_list,
ogc_jobs_get_results, ogc_proxy_execute_plan) default to
response_mode="summary": the full payload is stored behind an opaque proxy
memory handle and only a sanitized summary is returned to model context.

When a tool returns a memory handle, use ogc_proxy_memory_retrieve with that
handle and an offset/limit to page through the full dataset incrementally
without copying everything into context at once.

Use response_mode="raw" only for intentionally small responses or
low-level interoperability testing.

Prefer referenced data URLs (href) over large inline payloads whenever the
upstream process description says it accepts references.

━━━ PROCESS INPUT DISCIPLINE ━━━

Never invent process input names. Read ogc_processes_describe and preserve the
exact input/output identifiers advertised by the upstream server.

ogc_processes_execute (direct, no-confirmation execution) is absent by default.
It only appears when the operator sets policy.expose_direct_execution_tools=true.
Always prefer the create_plan / confirm_plan / execute_plan sequence.
""".strip()


def _summary_fields(value: str) -> tuple[str, ...]:
    config = parse_json_object(value, label="summary_fields_json")
    fields = config.get("fields", DEFAULT_SUMMARY_FIELDS)
    if not isinstance(fields, (list, tuple)) or not all(
        isinstance(item, str) for item in fields
    ):
        raise OgcMcpError(
            "invalid_json_argument",
            "summary_fields_json.fields must be a JSON array of strings.",
            {"label": "summary_fields_json"},
        )
    return tuple(fields)


def _apply_response_mode(
    result: dict[str, Any],
    *,
    response_mode: str,
    summary_fields_json: str,
    operation: str,
    runtime: ProxyRuntime,
) -> dict[str, Any]:
    """Summarize a result envelope's data behind a proxy memory handle, or pass it through.

    Shared by every tool that can return a large or unbounded upstream
    payload: list/search/get-many operations, ogc_common_get_resource,
    ogc_jobs_get_results, ogc_proxy_execute_plan, and (only when the
    operator has enabled it) ogc_processes_execute. response_mode="summary"
    is the default everywhere it appears: the full payload is stored behind
    an opaque proxy memory handle and only a sanitized summary is returned in
    model context. response_mode="raw" returns the original upstream payload
    unchanged, for low-level interoperability testing or intentionally small
    responses.
    """
    if response_mode == "raw":
        return result
    if response_mode != "summary":
        raise OgcMcpError(
            "invalid_argument",
            "response_mode must be 'summary' or 'raw'.",
            {"response_mode": response_mode},
        )
    fields = _summary_fields(summary_fields_json)
    summary = runtime.sanitizer.summarize(
        result["data"],
        operation=operation,
        summary_fields=fields,
    )
    record = runtime.memory.store(
        operation=operation,
        server_id=str(result.get("server", {}).get("id", "")),
        data=result["data"],
        summary=summary,
    )
    result["data"] = summary
    result["memory"] = {
        "handle": record.handle,
        "usage": "Pass this handle to future steps instead of copying full output into model context.",
    }
    return result


def create_mcp_server(
    config_path: str | Path | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
) -> FastMCP:
    """Create a configured FastMCP server.

    The optional HTTP transport exists for deterministic tests. Production
    callers normally provide only config_path or set OGC_MCP_CONFIG.
    """
    runtime = create_runtime(
        config_path,
        transport=transport,
        bootstrap_capabilities=os.environ.get("OGC_MCP_BOOTSTRAP_CAPABILITIES", "") == "1",
    )
    registry = runtime.registry
    common = runtime.common
    features = runtime.features
    records = runtime.records
    processes = runtime.processes

    mcp = FastMCP(
        "OGC API MCP Reference Server",
        instructions=SERVER_INSTRUCTIONS,
        host=os.environ.get("OGC_MCP_HOST", "127.0.0.1"),
        port=int(os.environ.get("OGC_MCP_PORT", "8000")),
        json_response=True,
        stateless_http=True,
    )

    @mcp.resource("ogc-mcp://guide/workflow")
    def workflow_guide() -> str:
        """Provide the recommended cross-API workflow for MCP clients."""
        return SERVER_INSTRUCTIONS

    @mcp.resource("ogc-mcp://registry/servers")
    def registered_servers_resource() -> str:
        """Provide non-secret metadata for registered OGC API deployments."""
        return json.dumps({"servers": registry.list()}, indent=2)

    @mcp.tool()
    def ogc_servers_list() -> dict[str, Any]:
        """List operator-approved OGC API deployments available to this MCP server.

        Call this first when the user has not selected a backend, when you need
        to know which OGC API modules are available, or when choosing a server
        for Features, Records, or Processes operations.

        Each result contains a stable server ID, display title, base URL,
        supported OGC API modules, and any module for which the server is the
        configured default. Credentials are intentionally never exposed.

        Returns:
            A structured list of configured OGC API deployments.
        """
        return {"ok": True, "operation": "servers.list", "servers": registry.list()}

    @mcp.tool()
    def ogc_proxy_get_capabilities(
        server_id: str = "",
        refresh: bool = False,
    ) -> dict[str, Any]:
        """Retrieve cached server capabilities and active deterministic fallbacks.

        Use this before choosing optional behavior such as async execution,
        CQL2 filtering, CRS negotiation, temporal filtering, or property
        selection. The proxy derives these flags from /conformance and maps
        missing capabilities to concrete fallback rules.

        Args:
            server_id: Registered server ID. If omitted, a default server must
                be configured.
            refresh: If true, reload /conformance instead of using the cache.

        Returns:
            A capability profile plus active fallback rules for the server.
        """
        def callback() -> dict[str, Any]:
            profile = runtime.capabilities.get(server_id, refresh=refresh)
            return {
                "ok": True,
                "operation": "proxy.capabilities",
                "capabilities": profile.to_dict(),
                "active_fallbacks": runtime.fallbacks.active_for(profile),
            }

        return invoke("proxy.capabilities", callback)

    @mcp.tool()
    def ogc_proxy_memory_list() -> dict[str, Any]:
        """List model-safe metadata for full payloads stored in proxy memory."""
        return {
            "ok": True,
            "operation": "proxy.memory.list",
            "records": runtime.memory.list_metadata(),
        }

    @mcp.tool()
    def ogc_proxy_memory_retrieve(
        handle: str,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Retrieve stored data from a proxy memory handle with optional pagination.

        Use this after any tool that returns a memory handle (ogc_features_get_items,
        ogc_records_search, ogc_jobs_get_results, ogc_proxy_execute_plan) when the
        user needs to inspect the actual features or records in the stored payload.

        For large FeatureCollections, page through the data incrementally by
        increasing the offset in steps of limit until has_more is false. Never
        load all features at once when a summary is sufficient.

        Args:
            handle: Opaque memory handle returned by a prior tool call.
            offset: Zero-based start index for paginated slicing (default 0).
            limit: Maximum number of items to return per call (default 50).

        Returns:
            The stored data slice plus pagination metadata (total_features,
            offset, returned, has_more).
        """
        def callback() -> dict[str, Any]:
            try:
                result = runtime.memory.retrieve(handle, offset=offset, limit=limit)
            except KeyError:
                raise OgcMcpError(
                    "not_found",
                    "No stored payload found for this handle. "
                    "It may have expired (default TTL: 30 min) or the handle is incorrect.",
                    {"handle": handle},
                )
            return {
                "ok": True,
                "operation": "proxy.memory.retrieve",
                "handle": handle,
                "total_features": result.get("total_features"),
                "offset": result.get("offset", 0),
                "returned": result.get("returned"),
                "has_more": result.get("has_more", False),
                "data": result.get("data"),
            }

        return invoke("proxy.memory.retrieve", callback)

    @mcp.tool()
    def ogc_proxy_create_plan(plan_request_json: str) -> dict[str, Any]:
        """Create a validated, user-confirmable proxy execution plan.

        The first supported operation is "process_execute". The proxy validates
        the requested process ID against ogc_processes_list and optionally
        validates collection_id against ogc_features_list_collections. Plans
        that still contain unresolved inputs are stored but cannot execute.

        Args:
            plan_request_json: JSON object with operation, server_id,
                process_id, execute_request, and optional collection_id.

        Returns:
            A stored plan with status "ready_for_confirmation" or
            "needs_resolution".
        """
        return invoke(
            "proxy.create_plan",
            lambda: runtime.workflow.create_plan(
                parse_json_object(
                    plan_request_json,
                    label="plan_request_json",
                    allow_empty=False,
                )
            ),
        )

    @mcp.tool()
    def ogc_proxy_get_plan(plan_id: str) -> dict[str, Any]:
        """Retrieve one stored proxy plan and its current lifecycle state.

        Use this before confirming or executing a plan when you need to inspect
        whether it is awaiting confirmation, confirmed, running, completed, or
        blocked by unresolved inputs.

        Args:
            plan_id: Plan ID returned by ogc_proxy_create_plan.

        Returns:
            The stored plan state.
        """
        def callback() -> dict[str, Any]:
            plan = runtime.workflow.get_plan(plan_id)
            if not plan:
                raise OgcMcpError("invalid_argument", "Unknown plan_id.", {"plan_id": plan_id})
            return {
                "ok": True,
                "operation": "proxy.get_plan",
                "workflow": {"backend": runtime.workflow.backend, "status": plan.status},
                "plan": plan.to_dict(),
            }

        return invoke("proxy.get_plan", callback)

    @mcp.tool()
    def ogc_proxy_list_plans() -> dict[str, Any]:
        """List summary metadata for all non-expired proxy plans in the store.

        Use this at the start of a new turn when a plan_id from a previous
        conversation turn is unavailable, or to check which plans are currently
        pending resolution or confirmation. Returns only compact summary fields
        (plan_id, operation, server_id, status, created_at, unresolved_count)
        ordered by creation time. Full execute_request bodies and step details
        are available via ogc_proxy_get_plan.

        Returns:
            A structured list of plan summaries.
        """
        def callback() -> dict[str, Any]:
            return {
                "ok": True,
                "operation": "proxy.list_plans",
                "plans": runtime.planner.list_plans(),
            }

        return invoke("proxy.list_plans", callback)

    @mcp.tool()
    def ogc_proxy_update_plan(
        plan_id: str,
        execute_request_json: str,
    ) -> dict[str, Any]:
        """Update the inputs of a needs_resolution plan and revalidate in place.

        Use this — not ogc_proxy_create_plan — when ogc_proxy_create_plan
        returned resolution_required=true and the user has now supplied the
        missing or corrected values. The plan is revalidated against the same
        process description; if all inputs are now valid the plan advances to
        ready_for_confirmation and a confirmation_prompt is returned for the
        user to review.

        If inputs are still incomplete, a new resolution_prompt is returned with
        the remaining per_field_questions. Continue the update_plan loop until
        resolution_required is false and confirmation_required is true.

        This tool preserves the plan_id so the full lifecycle (create → resolve
        → confirm → execute) stays traceable under a single identifier.

        Args:
            plan_id: Plan ID returned by ogc_proxy_create_plan.
            execute_request_json: Corrected execute request body as a JSON object.

        Returns:
            Updated plan state plus either resolution_prompt (if still unresolved)
            or confirmation_prompt (if ready — show execute_request to user before
            calling ogc_proxy_confirm_plan).
        """
        def callback() -> dict[str, Any]:
            updated_plan = runtime.planner.update_plan(
                plan_id,
                parse_json_object(
                    execute_request_json,
                    label="execute_request_json",
                    allow_empty=False,
                ),
            )
            plan_dict = updated_plan.to_dict()
            result: dict[str, Any] = {
                "ok": True,
                "operation": "proxy.update_plan",
                "workflow": {
                    "backend": runtime.workflow.backend,
                    "status": updated_plan.status,
                    "human_in_the_loop": updated_plan.status in (
                        "needs_resolution", "ready_for_confirmation"
                    ),
                },
                "resolution_required": updated_plan.status == "needs_resolution",
                "confirmation_required": updated_plan.status == "ready_for_confirmation",
                "plan": plan_dict,
                "resolution_prompt": {},
                "confirmation_prompt": {},
            }
            if updated_plan.status == "needs_resolution":
                unresolved = list(updated_plan.unresolved)
                result["resolution_prompt"] = {
                    "kind": "human_resolution_required",
                    "plan_id": plan_id,
                    "message": (
                        "Some inputs are still missing or have type mismatches. "
                        "Ask the user the questions in per_field_questions ONE AT A TIME, "
                        "then call ogc_proxy_update_plan again with the corrected inputs."
                    ),
                    "unresolved": unresolved,
                    "per_field_questions": [
                        {
                            "field": item.get("field", ""),
                            "title": item.get("title", item.get("field", "")),
                            "reason": item.get("reason", ""),
                            "question": (
                                f"What value should be used for "
                                f"'{item.get('title', item.get('field', ''))}'? "
                                f"({item.get('reason', '')})"
                            ),
                        }
                        for item in unresolved
                    ],
                }
            elif updated_plan.status == "ready_for_confirmation":
                result["confirmation_prompt"] = {
                    "kind": "human_confirmation",
                    "plan_id": plan_id,
                    "message": (
                        "All inputs are validated. Show the user the complete execute_request "
                        "below — verbatim, not paraphrased — and ask for explicit approval "
                        "before calling ogc_proxy_confirm_plan. If any value looks unclear, "
                        "vague, or was assumed rather than explicitly supplied by the user, "
                        "call ogc_proxy_update_plan with corrections instead."
                    ),
                    "execute_request": plan_dict.get("execute_request", {}),
                    "steps": plan_dict.get("steps", []),
                    "unresolved": plan_dict.get("unresolved", []),
                    "instructions": (
                        "1. Display execute_request to the user verbatim.\n"
                        "2. Ask: 'Are these the correct inputs you want to send?'\n"
                        "3. Only call ogc_proxy_confirm_plan(approved=True) after the user "
                        "explicitly says yes.\n"
                        "4. If they want to change a value, call ogc_proxy_update_plan with the "
                        "revised execute_request — you do NOT need to reject and restart.\n"
                        "5. Only call ogc_proxy_confirm_plan(approved=False) if the user "
                        "explicitly cancels execution entirely."
                    ),
                }
            return result

        return invoke("proxy.update_plan", callback)

    @mcp.tool()
    def ogc_proxy_confirm_plan(
        plan_id: str,
        approved: bool,
        actor: str = "user",
        comment: str = "",
    ) -> dict[str, Any]:
        """Record explicit human approval or rejection for a proxy plan.

        This is the human-in-the-loop gate. ogc_proxy_execute_plan refuses to
        run until this tool records approval for a plan that is ready for
        confirmation. A rejection stores the plan as rejected and execution
        remains blocked.

        Args:
            plan_id: Plan ID returned by ogc_proxy_create_plan.
            approved: True to approve execution; false to reject it.
            actor: Human or client identity recording the decision.
            comment: Optional confirmation note.

        Returns:
            The updated plan lifecycle state.
        """
        return invoke(
            "proxy.confirm_plan",
            lambda: runtime.workflow.confirm_plan(
                plan_id,
                approved=approved,
                actor=actor,
                comment=comment,
            ),
        )

    @mcp.tool()
    def ogc_proxy_execute_plan(
        plan_id: str,
        execution_mode: str = "auto",
        wait_seconds: int = 10,
        response_mode: str = "summary",
        summary_fields_json: str = "{}",
    ) -> dict[str, Any]:
        """Execute a previously validated proxy plan after user confirmation.

        This tool accepts only a plan_id, not arbitrary process inputs. The
        proxy can therefore validate process and collection identifiers before
        execution, choose capability-aware fallbacks, and preserve the original
        execute payload from the stored plan.

        A synchronous process result can itself be large (for example, a
        returned geometry or coverage). By default the proxy stores the full
        result behind a memory handle and returns only a sanitized summary.
        Use response_mode="raw" only for low-level interoperability testing
        or intentionally small results.

        Args:
            plan_id: Plan ID returned by ogc_proxy_create_plan.
            execution_mode: "auto", "async", or "sync-wait".
            wait_seconds: Positive wait preference used by sync-wait.
            response_mode: "summary" for proxy memory + sanitized summary, or
                "raw" for the original full result envelope.
            summary_fields_json: Optional object like
                {"fields":["id","geometry.type","properties.name"]}.

        Returns:
            The process execution result plus any fallback applied by the proxy.
        """
        def callback() -> dict[str, Any]:
            result = runtime.workflow.execute_plan(
                plan_id,
                execution_mode=execution_mode,
                wait_seconds=wait_seconds,
            )
            return _apply_response_mode(
                result,
                response_mode=response_mode,
                summary_fields_json=summary_fields_json,
                operation="proxy.execute_plan",
                runtime=runtime,
            )

        return invoke("proxy.execute_plan", callback)

    @mcp.tool()
    def ogc_common_get_landing_page(server_id: str = "") -> dict[str, Any]:
        """Retrieve an OGC API landing page from a registered deployment.

        Use this as the first discovery call for an unfamiliar server. Landing
        pages usually advertise links to /conformance, API definitions,
        collections, processes, and related resources. This tool performs a
        read-only GET request and does not execute a process.

        Args:
            server_id: Registered server ID from ogc_servers_list. If omitted,
                the configured default Common server is used.

        Returns:
            A standard result envelope containing the upstream landing page.
        """
        return invoke("common.landing_page", lambda: common.landing_page(server_id))

    @mcp.tool()
    def ogc_common_get_conformance(server_id: str = "") -> dict[str, Any]:
        """Retrieve standards-conformance URIs advertised by an OGC API server.

        Use this before relying on optional capabilities. The returned
        conformsTo values indicate which OGC API standards and extensions the
        deployment claims to implement, such as Processes Core, job lists,
        Features encodings, Records capabilities, or filtering extensions.

        Args:
            server_id: Registered server ID from ogc_servers_list. If omitted,
                the configured default Common server is used.

        Returns:
            A standard result envelope containing the conformance document.
        """
        return invoke("common.conformance", lambda: common.conformance(server_id))

    @mcp.tool()
    def ogc_common_get_resource(
        server_id: str,
        path: str,
        query_json: str = "{}",
        response_mode: str = "summary",
        summary_fields_json: str = "{}",
    ) -> dict[str, Any]:
        """Read a relative resource path from a registered OGC API deployment.

        Use this read-only escape hatch for OGC API modules that do not yet have
        dedicated MCP tools, such as Tiles, Coverages, EDR, Maps, Styles, or
        implementation-specific discovery resources. Prefer dedicated tools
        whenever one exists.

        Security boundary:
        The path must be relative to the registered server and start with one
        slash. Absolute URLs are rejected. The AI model cannot redirect this
        tool to an unregistered host.

        Args:
            server_id: Registered server ID from ogc_servers_list.
            path: Relative upstream path, for example "/collections" or "/api".
            query_json: JSON object encoded as a string for query parameters.
            response_mode: "summary" for proxy memory + sanitized summary, or
                "raw" for the original upstream resource.
            summary_fields_json: Optional object like
                {"fields":["id","title","description"]}.

        Returns:
            A standard result envelope containing either a model-safe summary
            plus memory handle, or the raw upstream resource.
        """
        def callback() -> dict[str, Any]:
            result = common.get_resource(
                server_id,
                path,
                parse_json_object(query_json, label="query_json"),
            )
            return _apply_response_mode(
                result,
                response_mode=response_mode,
                summary_fields_json=summary_fields_json,
                operation="common.get_resource",
                runtime=runtime,
            )

        return invoke("common.get_resource", callback)

    @mcp.tool()
    def ogc_features_list_collections(
        server_id: str = "",
        response_mode: str = "summary",
        summary_fields_json: str = "{}",
    ) -> dict[str, Any]:
        """List vector-data collections from an OGC API - Features deployment.

        Use this to discover available feature datasets such as roads,
        buildings, administrative boundaries, lakes, or observation locations.
        Call it before fetching feature items when the user has not already
        supplied a collection ID.

        Args:
            server_id: Registered Features server ID. If omitted, the configured
                default Features server is used.
            response_mode: "summary" for proxy memory + sanitized summary, or
                "raw" for the original collections envelope.
            summary_fields_json: Optional object like
                {"fields":["id","title","description"]}.

        Returns:
            A standard result envelope containing either a model-safe summary
            plus memory handle, or the raw /collections response.
        """
        def callback() -> dict[str, Any]:
            result = features.list_collections(server_id)
            return _apply_response_mode(
                result,
                response_mode=response_mode,
                summary_fields_json=summary_fields_json,
                operation="features.list_collections",
                runtime=runtime,
            )

        return invoke("features.list_collections", callback)

    @mcp.tool()
    def ogc_features_describe_collection(
        collection_id: str,
        server_id: str = "",
    ) -> dict[str, Any]:
        """Retrieve metadata for one OGC API - Features collection.

        Use this after ogc_features_list_collections when you need to inspect a
        collection's title, description, extent, CRS declarations, or links
        before fetching data or using the collection as process input.

        Args:
            collection_id: Exact collection ID advertised by the server.
            server_id: Registered Features server ID. If omitted, the default is used.

        Returns:
            A standard result envelope containing collection metadata.
        """
        return invoke(
            "features.describe_collection",
            lambda: features.describe_collection(collection_id, server_id),
        )

    @mcp.tool()
    def ogc_features_get_items(
        collection_id: str,
        server_id: str = "",
        query_json: str = "{}",
        response_mode: str = "summary",
        summary_fields_json: str = "{}",
    ) -> dict[str, Any]:
        """Retrieve feature items from an OGC API - Features collection.

        Use this for actual GeoJSON features and properties. Pass standard query
        parameters such as bbox, datetime, limit, offset, filter, or
        implementation-supported extensions through query_json.

        By default, the proxy stores the full FeatureCollection behind a memory
        handle and returns only sanitized summary fields. Use response_mode="raw"
        only for low-level interoperability testing or intentionally small
        responses where the full upstream payload is needed in model context.

        Args:
            collection_id: Exact collection ID advertised by the server.
            server_id: Registered Features server ID. If omitted, the default is used.
            query_json: JSON object encoded as a string, for example
                '{"bbox":"5.0,50.0,8.0,53.0","limit":10}'.
            response_mode: "summary" for proxy memory + sanitized summary, or
                "raw" for the original full FeatureCollection envelope.
            summary_fields_json: Optional object like
                {"fields":["id","geometry.type","properties.name"]}.

        Returns:
            A standard result envelope containing either a model-safe summary
            plus memory handle, or the raw upstream FeatureCollection.
        """
        def callback() -> dict[str, Any]:
            result = features.get_items(
                collection_id,
                server_id=server_id,
                query=parse_json_object(query_json, label="query_json"),
            )
            return _apply_response_mode(
                result,
                response_mode=response_mode,
                summary_fields_json=summary_fields_json,
                operation="features.get_items",
                runtime=runtime,
            )

        return invoke("features.get_items", callback)

    @mcp.tool()
    def ogc_features_get_item(
        collection_id: str,
        item_id: str,
        server_id: str = "",
    ) -> dict[str, Any]:
        """Retrieve one complete GeoJSON feature by collection and item ID.

        Use this when a user selects a specific feature or when a downstream
        process expects one inline geometry. For whole collections or large
        datasets, pass a referenced items URL to the process instead.

        Args:
            collection_id: Exact collection ID advertised by the server.
            item_id: Exact feature ID from ogc_features_get_items.
            server_id: Registered Features server ID. If omitted, the default is used.

        Returns:
            A standard result envelope containing one GeoJSON Feature.
        """
        return invoke(
            "features.get_item",
            lambda: features.get_item(collection_id, item_id, server_id=server_id),
        )

    @mcp.tool()
    def ogc_records_list_collections(
        server_id: str = "",
        response_mode: str = "summary",
        summary_fields_json: str = "{}",
    ) -> dict[str, Any]:
        """List metadata collections from an OGC API - Records deployment.

        Use this to discover which catalogues can be searched. Most workflows
        can proceed directly to ogc_records_search when a default catalogue is
        configured, but this tool is valuable for unfamiliar deployments.

        Args:
            server_id: Registered Records server ID. If omitted, the configured
                default Records server is used.
            response_mode: "summary" for proxy memory + sanitized summary, or
                "raw" for the original catalogue collections envelope.
            summary_fields_json: Optional object like
                {"fields":["id","title","description"]}.

        Returns:
            A standard result envelope containing either a model-safe summary
            plus memory handle, or the raw catalogue collections response.
        """
        def callback() -> dict[str, Any]:
            result = records.list_collections(server_id)
            return _apply_response_mode(
                result,
                response_mode=response_mode,
                summary_fields_json=summary_fields_json,
                operation="records.list_collections",
                runtime=runtime,
            )

        return invoke("records.list_collections", callback)

    @mcp.tool()
    def ogc_records_search(
        query_text: str = "",
        bbox: str = "",
        limit: int = 10,
        server_id: str = "",
        collection_id: str = "",
        query_json: str = "{}",
        response_mode: str = "summary",
        summary_fields_json: str = "{}",
    ) -> dict[str, Any]:
        """Search an OGC API - Records catalogue for geospatial resources.

        Use this when the user needs to find datasets, services, maps, imagery,
        or other geospatial resources before analysis. Search by free text,
        optional bbox, and optional extension query parameters. After choosing a
        record, call ogc_records_get_record to inspect links and metadata.

        Catalogues can return thousands of records. By default the full response
        is stored behind a proxy memory handle and only a sanitized summary is
        returned to model context. Use ogc_proxy_memory_retrieve with the
        returned handle to page through the full record list if needed.

        Args:
            query_text: Free-text search term such as "temperature" or "windmills".
            bbox: Optional bounding box string "minLon,minLat,maxLon,maxLat".
            limit: Maximum number of records requested.
            server_id: Registered Records server ID. If omitted, the default is used.
            collection_id: Catalogue collection ID. If omitted, the profile default is used.
            query_json: Additional query parameters encoded as a JSON object string.
            response_mode: "summary" for proxy memory + sanitized summary, or
                "raw" for the original full records envelope.
            summary_fields_json: Optional object like
                {"fields":["id","properties.title","properties.type"]}.

        Returns:
            A standard result envelope containing either a model-safe summary
            plus memory handle, or the raw upstream record collection.
        """
        def callback() -> dict[str, Any]:
            result = records.search(
                server_id=server_id,
                collection_id=collection_id,
                query_text=query_text,
                bbox=bbox,
                limit=limit,
                query=parse_json_object(query_json, label="query_json"),
            )
            return _apply_response_mode(
                result,
                response_mode=response_mode,
                summary_fields_json=summary_fields_json,
                operation="records.search",
                runtime=runtime,
            )

        return invoke("records.search", callback)

    @mcp.tool()
    def ogc_records_get_record(
        record_id: str,
        server_id: str = "",
        collection_id: str = "",
    ) -> dict[str, Any]:
        """Retrieve complete metadata for one OGC API - Records result.

        Use this after ogc_records_search. Inspect the returned links for data
        downloads or service URLs that may be suitable as referenced inputs to
        an OGC process.

        Args:
            record_id: Exact record ID returned by ogc_records_search.
            server_id: Registered Records server ID. If omitted, the default is used.
            collection_id: Catalogue collection ID. If omitted, the profile default is used.

        Returns:
            A standard result envelope containing the full record.
        """
        return invoke(
            "records.get_record",
            lambda: records.get_record(
                record_id,
                server_id=server_id,
                collection_id=collection_id,
            ),
        )

    @mcp.tool()
    def ogc_processes_list(
        server_id: str = "",
        response_mode: str = "summary",
        summary_fields_json: str = "{}",
    ) -> dict[str, Any]:
        """List executable processes advertised by an OGC API - Processes server.

        Always call this before choosing a process on an unfamiliar backend. It
        calls GET /processes and returns process IDs, summaries, links, and any
        advertised job-control metadata. Never guess a process ID.

        Args:
            server_id: Registered Processes server ID. If omitted, the configured
                default Processes server is used.
            response_mode: "summary" for proxy memory + sanitized summary, or
                "raw" for the original process list envelope.
            summary_fields_json: Optional object like
                {"fields":["id","title","description","version"]}.

        Returns:
            A standard result envelope containing either a model-safe summary
            plus memory handle, or the raw process list.
        """
        def callback() -> dict[str, Any]:
            result = processes.list_processes(server_id)
            return _apply_response_mode(
                result,
                response_mode=response_mode,
                summary_fields_json=summary_fields_json,
                operation="processes.list",
                runtime=runtime,
            )

        return invoke("processes.list", callback)

    @mcp.tool()
    def ogc_processes_describe(process_id: str, server_id: str = "") -> dict[str, Any]:
        """Retrieve the full description of one advertised OGC process.

        Call this after ogc_processes_list and before execution. Read the exact
        input names, schemas, media types, occurrence constraints, output names,
        and job-control options. Process interfaces vary by server; do not
        invent or normalize identifiers such as "InputPoints", "product", or
        "Result".

        Args:
            process_id: Exact process ID returned by ogc_processes_list.
            server_id: Registered Processes server ID. If omitted, the default is used.

        Returns:
            A standard result envelope containing the process description.
        """
        return invoke("processes.describe", lambda: processes.describe(process_id, server_id))

    if runtime.policy.expose_direct_execution_tools:

        @mcp.tool()
        def ogc_processes_execute(
            process_id: str,
            execute_request_json: str,
            server_id: str = "",
            execution_mode: str = "auto",
            wait_seconds: int = 10,
            response_mode: str = "summary",
            summary_fields_json: str = "{}",
        ) -> dict[str, Any]:
            """Execute any advertised OGC API - Processes process directly.

            This tool is only available because the operator has set
            policy.expose_direct_execution_tools=true in the server
            configuration. Unlike ogc_proxy_create_plan /
            ogc_proxy_confirm_plan / ogc_proxy_execute_plan, this tool has no
            built-in human-confirmation gate: any arbitrary execute_request_json
            you build is sent immediately. It exists for low-level
            interoperability testing. For user-facing workflows, prefer the
            proxy plan tools instead.

            This is the generic execution tool. It sends the complete JSON
            object supplied in execute_request_json to
            POST /processes/{process_id}/execution without rewriting
            process-specific fields. Build the body from ogc_processes_describe.

            The body normally contains an "inputs" object and may include
            "outputs", "response", "subscriber", or extension fields advertised
            by the server. External HTTP(S) references inside the payload are
            validated against the operator-approved allowlist before the
            request leaves this MCP server.

            For the GeoLabs Delaunay example, execute_request_json can contain:
            {"inputs":{"InputPoints":{"type":"text/xml","href":"https://demo.pygeoapi.io/master/collections/dutch_windmills/items?f=json"}},"outputs":{"Result":{"format":{"mediaType":"application/json"},"transmissionMode":"value"}}}

            Async workflow:
            Use execution_mode="async" for long-running work. If the response
            includes a job ID or Location header, call ogc_jobs_get_status and
            then ogc_jobs_get_results.

            A synchronous result can be large. By default the proxy stores the
            full result behind a memory handle and returns only a sanitized
            summary. Use response_mode="raw" for the original full payload.

            Args:
                process_id: Exact process ID returned by ogc_processes_list.
                execute_request_json: Complete execute request body encoded as JSON.
                server_id: Registered Processes server ID. If omitted, the default is used.
                execution_mode: "auto", "async", or "sync-wait".
                wait_seconds: Positive wait preference used only by "sync-wait".
                response_mode: "summary" for proxy memory + sanitized summary, or
                    "raw" for the original full result envelope.
                summary_fields_json: Optional object like
                    {"fields":["id","geometry.type","properties.name"]}.

            Returns:
                A standard result envelope containing status, headers, and process output or job metadata.
            """
            def callback() -> dict[str, Any]:
                result = processes.execute(
                    process_id,
                    parse_json_object(
                        execute_request_json,
                        label="execute_request_json",
                        allow_empty=False,
                    ),
                    server_id=server_id,
                    execution_mode=execution_mode,
                    wait_seconds=wait_seconds,
                )
                return _apply_response_mode(
                    result,
                    response_mode=response_mode,
                    summary_fields_json=summary_fields_json,
                    operation="processes.execute",
                    runtime=runtime,
                )

            return invoke("processes.execute", callback)

    @mcp.tool()
    def ogc_jobs_list(server_id: str = "", query_json: str = "{}") -> dict[str, Any]:
        """List jobs advertised by an OGC API - Processes deployment.

        Use this after asynchronous execution, when a user asks about prior
        jobs, or when locating a job ID. Common filters such as processID,
        status, datetime, minDuration, maxDuration, type, and limit can be
        supplied through query_json if the upstream implementation supports
        them.

        Args:
            server_id: Registered Processes server ID. If omitted, the default is used.
            query_json: Optional job-list query parameters encoded as a JSON object string.

        Returns:
            A standard result envelope containing the job list.
        """
        return invoke(
            "jobs.list",
            lambda: processes.list_jobs(
                server_id=server_id,
                query=parse_json_object(query_json, label="query_json"),
            ),
        )

    @mcp.tool()
    def ogc_jobs_get_status(job_id: str, server_id: str = "") -> dict[str, Any]:
        """Retrieve the current status of one asynchronous OGC job.

        Poll this after ogc_processes_execute with execution_mode="async" until
        the status indicates success, failure, or dismissal. Then call
        ogc_jobs_get_results for successful jobs.

        Args:
            job_id: Exact job ID from the execute response or ogc_jobs_list.
            server_id: Registered Processes server ID. If omitted, the default is used.

        Returns:
            A standard result envelope containing job status metadata.
        """
        return invoke("jobs.get_status", lambda: processes.get_job_status(job_id, server_id))

    @mcp.tool()
    def ogc_jobs_get_results(
        job_id: str,
        server_id: str = "",
        response_mode: str = "summary",
        summary_fields_json: str = "{}",
    ) -> dict[str, Any]:
        """Retrieve results for a completed asynchronous OGC job.

        Call this only after ogc_jobs_get_status reports successful completion.
        Results follow the output structure declared by the process description
        and can be large (for example, a returned geometry or coverage).

        By default, the proxy stores the full result behind a memory handle
        and returns only a sanitized summary. Use response_mode="raw" only for
        low-level interoperability testing or intentionally small results.

        Args:
            job_id: Exact job ID from the execute response or ogc_jobs_list.
            server_id: Registered Processes server ID. If omitted, the default is used.
            response_mode: "summary" for proxy memory + sanitized summary, or
                "raw" for the original full job-results envelope.
            summary_fields_json: Optional object like
                {"fields":["id","geometry.type","properties.name"]}.

        Returns:
            A standard result envelope containing job results.
        """
        def callback() -> dict[str, Any]:
            result = processes.get_job_results(job_id, server_id)
            return _apply_response_mode(
                result,
                response_mode=response_mode,
                summary_fields_json=summary_fields_json,
                operation="jobs.get_results",
                runtime=runtime,
            )

        return invoke("jobs.get_results", callback)

    @mcp.tool()
    def ogc_jobs_dismiss(job_id: str, server_id: str = "") -> dict[str, Any]:
        """Cancel or delete an asynchronous OGC job.

        Use this when a user wants to cancel a running job or clean up job
        history, where supported by the server.

        Args:
            job_id: Exact job ID from the execute response or ogc_jobs_list.
            server_id: Registered Processes server ID. If omitted, the default is used.

        Returns:
            A standard result envelope confirming dismissal.
        """
        return invoke("jobs.dismiss", lambda: processes.dismiss_job(job_id, server_id))

    return mcp
