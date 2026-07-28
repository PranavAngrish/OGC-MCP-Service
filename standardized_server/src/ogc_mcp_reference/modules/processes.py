"""OGC API - Processes Core operations."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, quote, urlsplit

from ..errors import OgcMcpError, UpstreamResponseError
from ..models import OgcResponse, ServerProfile
from ..registry import ServerRegistry
from ..result import success
from ..security import validate_execute_references
from ..transport import OgcHttpClient


_PROCESS_PAGE_SIZE = 100
_MAX_PROCESS_PAGES = 12


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

    @staticmethod
    def _next_page_query(data: Any) -> dict[str, str] | None:
        if not isinstance(data, dict) or not isinstance(data.get("links"), list):
            return None
        for link in data["links"]:
            if not isinstance(link, dict) or link.get("rel") != "next":
                continue
            href = link.get("href")
            if not isinstance(href, str):
                continue
            query = dict(parse_qsl(urlsplit(href).query, keep_blank_values=True))
            return query or None
        return None

    @staticmethod
    def _matches_process(process: Any, search_text: str) -> bool:
        if not isinstance(process, dict):
            return False
        term = search_text.casefold()
        return any(
            term in str(process.get(field, "")).casefold()
            for field in ("id", "title", "description", "summary")
        )

    def _exact_process_lookup(
        self,
        server: ServerProfile,
        path: str,
        search_text: str,
    ) -> OgcResponse | None:
        """Return a process description when a one-token search is its exact ID."""
        if len(search_text) > 256 or any(character.isspace() for character in search_text):
            return None
        try:
            response = self._client.request(
                server,
                "GET",
                f"{path}/{_segment(search_text)}",
                query={"f": "json"},
            )
        except UpstreamResponseError as exc:
            # A keyword need not be a process ID. These responses simply mean
            # that the bounded catalogue scan below is still required.
            if exc.details.get("status_code") in {400, 404, 405, 501}:
                return None
            raise

        data = response.data
        if not isinstance(data, dict):
            return None
        process_id = data.get("id")
        if not isinstance(process_id, str) or process_id.casefold() != search_text.casefold():
            return None
        return response

    def list_processes(
        self,
        server_id: str = "",
        *,
        search_text: str = "",
    ) -> dict[str, Any]:
        server = self._registry.get(server_id, service="processes")
        path = server.path("processes", "/processes")
        search_text = search_text.strip()

        # OGC API - Processes exposes an individual process at
        # /processes/{processID}. Most targeted searches use the exact process
        # ID (with case-insensitive implementations accepting e.g. "buffer"
        # for "Buffer"), so try that constant-time lookup before walking a
        # potentially very large and slow catalogue page by page.
        if search_text:
            exact_response = self._exact_process_lookup(server, path, search_text)
            if exact_response is not None:
                process = exact_response.data
                return success(
                    "processes.list",
                    server,
                    exact_response,
                    data={
                        "processes": [process],
                        "numberMatched": 1,
                        "numberReturned": 1,
                    },
                    guidance={
                        "next_tools": ["ogc_processes_describe"],
                        "pages_scanned": 0,
                        "lookup_strategy": "exact_process_id",
                        "matched_process_id": process["id"],
                        "search_hint": (
                            "The search matched an exact advertised process ID. "
                            "Use ogc_processes_describe with matched_process_id "
                            "before configuring an execution plan."
                        ),
                    },
                )

        query: dict[str, Any] = {"f": "json", "limit": _PROCESS_PAGE_SIZE}
        response = self._client.request(server, "GET", path, query=query)
        first_data = response.data
        pages = 1
        page_data = first_data
        matches: list[dict[str, Any]] = []
        seen_queries: set[tuple[tuple[str, str], ...]] = set()

        if search_text:
            while True:
                processes = page_data.get("processes", []) if isinstance(page_data, dict) else []
                if isinstance(processes, list):
                    matches.extend(
                        process for process in processes
                        if self._matches_process(process, search_text)
                    )
                    if any(
                        isinstance(process, dict)
                        and str(process.get("id", "")).casefold() == search_text.casefold()
                        for process in processes
                    ):
                        break

                next_query = self._next_page_query(page_data)
                if not next_query or pages >= _MAX_PROCESS_PAGES:
                    break
                signature = tuple(sorted(next_query.items()))
                if signature in seen_queries:
                    break
                seen_queries.add(signature)
                next_query.setdefault("f", "json")
                next_query.setdefault("limit", str(_PROCESS_PAGE_SIZE))
                page_data = self._client.request(
                    server,
                    "GET",
                    path,
                    query=next_query,
                ).data
                pages += 1

            if isinstance(first_data, dict):
                data = {
                    **first_data,
                    "processes": matches,
                    "numberReturned": len(matches),
                }
            else:
                data = {"processes": matches, "numberReturned": len(matches)}
        else:
            # A number of public deployments return thousands of process
            # descriptions from an unbounded GET /processes request. Keep the
            # initial discovery call responsive; callers can use search_text
            # for a bounded paginated scan of the catalogue.
            data = first_data

        return success(
            "processes.list",
            server,
            response,
            data=data,
            guidance={
                "next_tools": ["ogc_processes_describe"],
                "pages_scanned": pages,
                "search_hint": (
                    "Use search_text=\"<keyword>\" (for example, \"delaunay\") "
                    "to scan the advertised catalogue in bounded pages before "
                    "choosing a process."
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
