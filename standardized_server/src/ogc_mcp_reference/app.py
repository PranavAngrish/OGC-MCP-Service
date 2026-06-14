"""FastMCP application exposing a stable OGC API tool contract."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from .config import load_settings
from .modules import CommonService, FeaturesService, ProcessesService, RecordsService
from .registry import ServerRegistry
from .result import invoke, parse_json_object
from .transport import OgcHttpClient


SERVER_INSTRUCTIONS = """
This MCP server is a reference bridge for OGC APIs.

Use registered server IDs from ogc_servers_list. Start with OGC Common discovery
for unfamiliar deployments. For processing, use this sequence:
1. ogc_processes_list
2. ogc_processes_describe
3. ogc_processes_execute
4. ogc_jobs_get_status and ogc_jobs_get_results for asynchronous jobs

Use OGC API - Records to discover datasets and OGC API - Features to inspect
vector data. Prefer referenced data URLs over large inline payloads when an
advertised process accepts references.

Never invent process input names. Read the process description and preserve the
input/output structure expected by the upstream server.
""".strip()


def create_mcp_server(
    config_path: str | Path | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
) -> FastMCP:
    """Create a configured FastMCP server.

    The optional HTTP transport exists for deterministic tests. Production
    callers normally provide only config_path or set OGC_MCP_CONFIG.
    """
    registry = ServerRegistry(load_settings(config_path))
    client = OgcHttpClient(transport=transport)
    common = CommonService(registry, client)
    features = FeaturesService(registry, client)
    records = RecordsService(registry, client)
    processes = ProcessesService(registry, client)

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

        Returns:
            A standard result envelope containing the upstream resource.
        """
        return invoke(
            "common.get_resource",
            lambda: common.get_resource(
                server_id,
                path,
                parse_json_object(query_json, label="query_json"),
            ),
        )

    @mcp.tool()
    def ogc_features_list_collections(server_id: str = "") -> dict[str, Any]:
        """List vector-data collections from an OGC API - Features deployment.

        Use this to discover available feature datasets such as roads,
        buildings, administrative boundaries, lakes, or observation locations.
        Call it before fetching feature items when the user has not already
        supplied a collection ID.

        Args:
            server_id: Registered Features server ID. If omitted, the configured
                default Features server is used.

        Returns:
            A standard result envelope containing the /collections response.
        """
        return invoke("features.list_collections", lambda: features.list_collections(server_id))

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
    ) -> dict[str, Any]:
        """Retrieve feature items from an OGC API - Features collection.

        Use this for actual GeoJSON features and properties. Pass standard query
        parameters such as bbox, datetime, limit, offset, filter, or
        implementation-supported extensions through query_json.

        For large datasets used as process inputs, prefer the collection-items
        URL provided in guidance.reference_href over copying a large
        FeatureCollection inline into an execution request.

        Args:
            collection_id: Exact collection ID advertised by the server.
            server_id: Registered Features server ID. If omitted, the default is used.
            query_json: JSON object encoded as a string, for example
                '{"bbox":"5.0,50.0,8.0,53.0","limit":10}'.

        Returns:
            A standard result envelope containing a FeatureCollection.
        """
        return invoke(
            "features.get_items",
            lambda: features.get_items(
                collection_id,
                server_id=server_id,
                query=parse_json_object(query_json, label="query_json"),
            ),
        )

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
    def ogc_records_list_collections(server_id: str = "") -> dict[str, Any]:
        """List metadata collections from an OGC API - Records deployment.

        Use this to discover which catalogues can be searched. Most workflows
        can proceed directly to ogc_records_search when a default catalogue is
        configured, but this tool is valuable for unfamiliar deployments.

        Args:
            server_id: Registered Records server ID. If omitted, the configured
                default Records server is used.

        Returns:
            A standard result envelope containing catalogue collections.
        """
        return invoke("records.list_collections", lambda: records.list_collections(server_id))

    @mcp.tool()
    def ogc_records_search(
        query_text: str = "",
        bbox: str = "",
        limit: int = 10,
        server_id: str = "",
        collection_id: str = "",
        query_json: str = "{}",
    ) -> dict[str, Any]:
        """Search an OGC API - Records catalogue for geospatial resources.

        Use this when the user needs to find datasets, services, maps, imagery,
        or other geospatial resources before analysis. Search by free text,
        optional bbox, and optional extension query parameters. After choosing a
        record, call ogc_records_get_record to inspect links and metadata.

        Args:
            query_text: Free-text search term such as "temperature" or "windmills".
            bbox: Optional bounding box string "minLon,minLat,maxLon,maxLat".
            limit: Maximum number of records requested.
            server_id: Registered Records server ID. If omitted, the default is used.
            collection_id: Catalogue collection ID. If omitted, the profile default is used.
            query_json: Additional query parameters encoded as a JSON object string.

        Returns:
            A standard result envelope containing matching records.
        """
        return invoke(
            "records.search",
            lambda: records.search(
                server_id=server_id,
                collection_id=collection_id,
                query_text=query_text,
                bbox=bbox,
                limit=limit,
                query=parse_json_object(query_json, label="query_json"),
            ),
        )

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
    def ogc_processes_list(server_id: str = "") -> dict[str, Any]:
        """List executable processes advertised by an OGC API - Processes server.

        Always call this before choosing a process on an unfamiliar backend. It
        calls GET /processes and returns process IDs, summaries, links, and any
        advertised job-control metadata. Never guess a process ID.

        Args:
            server_id: Registered Processes server ID. If omitted, the configured
                default Processes server is used.

        Returns:
            A standard result envelope containing the process list.
        """
        return invoke("processes.list", lambda: processes.list_processes(server_id))

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

    @mcp.tool()
    def ogc_processes_execute(
        process_id: str,
        execute_request_json: str,
        server_id: str = "",
        execution_mode: str = "auto",
        wait_seconds: int = 10,
    ) -> dict[str, Any]:
        """Execute any advertised OGC API - Processes process.

        This is the generic execution tool. It sends the complete JSON object
        supplied in execute_request_json to
        POST /processes/{process_id}/execution without rewriting
        process-specific fields. Build the body from ogc_processes_describe.

        The body normally contains an "inputs" object and may include "outputs",
        "response", "subscriber", or extension fields advertised by the server.
        External HTTP(S) references inside the payload are validated against the
        operator-approved allowlist before the request leaves this MCP server.

        For the GeoLabs Delaunay example, execute_request_json can contain:
        {"inputs":{"InputPoints":{"type":"text/xml","href":"https://demo.pygeoapi.io/master/collections/dutch_windmills/items?f=json"}},"outputs":{"Result":{"format":{"mediaType":"application/json"},"transmissionMode":"value"}}}

        Async workflow:
        Use execution_mode="async" for long-running work. If the response
        includes a job ID or Location header, call ogc_jobs_get_status and then
        ogc_jobs_get_results.

        Args:
            process_id: Exact process ID returned by ogc_processes_list.
            execute_request_json: Complete execute request body encoded as JSON.
            server_id: Registered Processes server ID. If omitted, the default is used.
            execution_mode: "auto", "async", or "sync-wait".
            wait_seconds: Positive wait preference used only by "sync-wait".

        Returns:
            A standard result envelope containing status, headers, and process output or job metadata.
        """
        return invoke(
            "processes.execute",
            lambda: processes.execute(
                process_id,
                parse_json_object(
                    execute_request_json,
                    label="execute_request_json",
                    allow_empty=False,
                ),
                server_id=server_id,
                execution_mode=execution_mode,
                wait_seconds=wait_seconds,
            ),
        )

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
            A standard result envelope containing jobs and status metadata.
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
        """Retrieve status and progress metadata for one asynchronous job.

        Poll this after ogc_processes_execute creates a job. Wait until the
        returned status indicates successful completion before calling
        ogc_jobs_get_results. Servers may use statuses such as accepted,
        running, successful, failed, or dismissed.

        Args:
            job_id: Exact job identifier returned by the process server.
            server_id: Registered Processes server ID. If omitted, the default is used.

        Returns:
            A standard result envelope containing the job status document.
        """
        return invoke("jobs.get_status", lambda: processes.get_job_status(job_id, server_id))

    @mcp.tool()
    def ogc_jobs_get_results(job_id: str, server_id: str = "") -> dict[str, Any]:
        """Retrieve outputs for a successfully completed asynchronous job.

        Call this after ogc_jobs_get_status reports successful completion. The
        result is process-specific and may contain inline JSON, GeoJSON, output
        descriptors, or links to generated artifacts.

        Args:
            job_id: Exact job identifier returned by the process server.
            server_id: Registered Processes server ID. If omitted, the default is used.

        Returns:
            A standard result envelope containing the process results.
        """
        return invoke("jobs.get_results", lambda: processes.get_job_results(job_id, server_id))

    @mcp.tool()
    def ogc_jobs_dismiss(job_id: str, server_id: str = "") -> dict[str, Any]:
        """Dismiss, cancel, or delete a process job using DELETE /jobs/{job_id}.

        This is a state-changing operation. Use it only when the user explicitly
        asks to cancel or clean up a job. Some servers may reject dismissal
        depending on job state, authorization, or supported conformance classes.

        Args:
            job_id: Exact job identifier returned by the process server.
            server_id: Registered Processes server ID. If omitted, the default is used.

        Returns:
            A standard result envelope containing the upstream dismissal response.
        """
        return invoke("jobs.dismiss", lambda: processes.dismiss_job(job_id, server_id))

    return mcp
