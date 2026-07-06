"""OGC API - Processes Core operations."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ..errors import OgcMcpError
from ..registry import ServerRegistry
from ..result import success
from ..security import validate_execute_references
from ..transport import OgcHttpClient


def _segment(value: str) -> str:
    return quote(value, safe="")


def _execution_prefer(execution_mode: str, wait_seconds: int) -> str:
    if execution_mode == "auto":
        return ""
    if execution_mode == "async":
        return "respond-async"
    if execution_mode == "sync-wait":
        if wait_seconds <= 0:
            raise OgcMcpError(
                "invalid_argument",
                "wait_seconds must be positive when execution_mode is 'sync-wait'.",
            )
        return f"wait={wait_seconds}"
    raise OgcMcpError(
        "invalid_argument",
        "execution_mode must be one of: auto, async, sync-wait.",
        {"execution_mode": execution_mode},
    )


class ProcessesService:
    """Execute advertised processes and follow asynchronous jobs."""

    def __init__(self, registry: ServerRegistry, client: OgcHttpClient) -> None:
        self._registry = registry
        self._client = client

    def list_processes(self, server_id: str = "") -> dict[str, Any]:
        server = self._registry.get(server_id, service="processes")
        path = server.path("processes", "/processes")
        response = self._client.request(server, "GET", path, query={"f": "json"})
        return success(
            "processes.list",
            server,
            response,
            guidance={
                "next_tools": ["ogc_processes_describe"],
                "search_hint": (
                    "If this list is truncated and you need a specific process, "
                    "retry ogc_processes_list with search_text=\"<keyword>\" "
                    "(e.g. search_text=\"delaunay\") to filter the full list "
                    "client-side before the item limit is applied."
                ),
            },
        )

    def describe(self, process_id: str, server_id: str = "") -> dict[str, Any]:
        server = self._registry.get(server_id, service="processes")
        path = f"{server.path('processes', '/processes')}/{_segment(process_id)}"
        response = self._client.request(server, "GET", path, query={"f": "json"})
        return success(
            "processes.describe",
            server,
            response,
            guidance={
                "next_tools": ["ogc_proxy_create_plan"],
                "usage": (
                    "Use the exact advertised input/output identifiers when building the execute_request. "
                    "Never invent or normalize field names. "
                    "Create a proxy plan with ogc_proxy_create_plan — "
                    "do NOT run local computation instead."
                ),
            },
        )

    def execute(
        self,
        process_id: str,
        execute_request: dict[str, Any],
        *,
        server_id: str = "",
        execution_mode: str = "auto",
        wait_seconds: int = 10,
    ) -> dict[str, Any]:
        server = self._registry.get(server_id, service="processes")
        validate_execute_references(execute_request, server.security)
        path = f"{server.path('processes', '/processes')}/{_segment(process_id)}/execution"
        response = self._client.request(
            server,
            "POST",
            path,
            json_body=execute_request,
            prefer=_execution_prefer(execution_mode, wait_seconds),
        )
        guidance: dict[str, Any] = {}
        if response.location or response.status_code in {201, 202}:
            guidance = {
                "next_tools": ["ogc_jobs_get_status", "ogc_jobs_get_results"],
                "location": response.location,
                "usage": "Extract the job ID from the response body or Location header for async follow-up.",
            }
        return success("processes.execute", server, response, guidance=guidance)

    def list_jobs(
        self,
        *,
        server_id: str = "",
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        server = self._registry.get(server_id, service="processes")
        path = server.path("jobs", "/jobs")
        response = self._client.request(server, "GET", path, query={"f": "json", **(query or {})})
        return success(
            "jobs.list",
            server,
            response,
            guidance={"next_tools": ["ogc_jobs_get_status", "ogc_jobs_get_results"]},
        )

    def get_job_status(self, job_id: str, server_id: str = "") -> dict[str, Any]:
        server = self._registry.get(server_id, service="processes")
        path = f"{server.path('jobs', '/jobs')}/{_segment(job_id)}"
        response = self._client.request(server, "GET", path, query={"f": "json"})
        return success(
            "jobs.get_status",
            server,
            response,
            guidance={
                "next_tools": ["ogc_jobs_get_results"],
                "usage": "Retrieve results after the status indicates successful completion.",
            },
        )

    def get_job_results(self, job_id: str, server_id: str = "") -> dict[str, Any]:
        server = self._registry.get(server_id, service="processes")
        path = f"{server.path('jobs', '/jobs')}/{_segment(job_id)}/results"
        response = self._client.request(server, "GET", path, query={"f": "json"})
        return success("jobs.get_results", server, response)

    def dismiss_job(self, job_id: str, server_id: str = "") -> dict[str, Any]:
        server = self._registry.get(server_id, service="processes")
        path = f"{server.path('jobs', '/jobs')}/{_segment(job_id)}"
        response = self._client.request(server, "DELETE", path)
        return success("jobs.dismiss", server, response)
