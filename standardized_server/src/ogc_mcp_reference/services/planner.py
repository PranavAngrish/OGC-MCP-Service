"""Validated proxy plans for deterministic multi-step execution."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from ..errors import OgcMcpError
from ..modules import FeaturesService, ProcessesService
from .input_schema import validate_execute_inputs
from .process_descriptions import ProcessDescriptionCache
from .store import InMemoryStore, KeyValueStore


@dataclass(frozen=True)
class PlanSource:
    """One declared data source used by a process execution request."""

    server_id: str
    collection_id: str
    href: str = ""
    role: str = ""
    input_id: str = ""
    strict: bool = True
    legacy: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "server_id": self.server_id,
            "collection_id": self.collection_id,
        }
        if self.href:
            payload["href"] = self.href
        if self.role:
            payload["role"] = self.role
        if self.input_id:
            payload["input_id"] = self.input_id
        if self.legacy:
            payload["legacy"] = True
        return payload


@dataclass(frozen=True)
class ProxyPlan:
    """A validated, user-confirmable execution plan."""

    plan_id: str
    operation: str
    server_id: str
    status: str
    steps: tuple[dict[str, Any], ...]
    unresolved: tuple[dict[str, Any], ...] = ()
    execute_request: dict[str, Any] = field(default_factory=dict)
    input_context: dict[str, Any] = field(default_factory=dict)
    sources: tuple[dict[str, Any], ...] = ()
    created_at: float = 0.0
    confirmed_at: float | None = None
    confirmation: dict[str, Any] = field(default_factory=dict)
    execution: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "operation": self.operation,
            "server_id": self.server_id,
            "status": self.status,
            "steps": list(self.steps),
            "unresolved": list(self.unresolved),
            "execute_request": self.execute_request,
            "input_context": self.input_context,
            "sources": list(self.sources),
            "created_at": self.created_at,
            "confirmed_at": self.confirmed_at,
            "confirmation": self.confirmation,
            "execution": self.execution,
            "requires_confirmation": self.status == "ready_for_confirmation",
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProxyPlan":
        return cls(
            plan_id=str(payload["plan_id"]),
            operation=str(payload.get("operation", "")),
            server_id=str(payload.get("server_id", "")),
            status=str(payload.get("status", "")),
            steps=tuple(payload.get("steps", [])),
            unresolved=tuple(payload.get("unresolved", [])),
            execute_request=dict(payload.get("execute_request", {})),
            input_context=dict(payload.get("input_context", {})),
            sources=tuple(payload.get("sources", [])),
            created_at=float(payload.get("created_at", 0.0)),
            confirmed_at=payload.get("confirmed_at"),
            confirmation=dict(payload.get("confirmation", {})),
            execution=dict(payload.get("execution", {})),
        )


class ProxyPlanner:
    """Create and execute plans from validated server discovery.

    Plans are persisted through a pluggable KeyValueStore (see
    services.store). The default in-process backend is correct for a
    single-worker stdio deployment only; multi-worker or multi-replica
    streamable-http deployments must configure an external backend so a plan
    created on one worker is visible to a confirm/execute call routed to
    another. Plans expire after ttl_seconds (default 1 hour) so abandoned,
    never-confirmed plans do not accumulate forever; pass ttl_seconds=0 to
    disable expiry entirely.
    """

    def __init__(
        self,
        *,
        features: FeaturesService,
        processes: ProcessesService,
        process_descriptions: ProcessDescriptionCache | None = None,
        store: KeyValueStore | None = None,
        ttl_seconds: int | None = 3600,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._features = features
        self._processes = processes
        self._process_descriptions = process_descriptions or ProcessDescriptionCache(processes)
        self._now = now or time.time
        self._store = store if store is not None else InMemoryStore(now=self._now)
        self._ttl_seconds = ttl_seconds or None

    def create_plan(self, request: dict[str, Any]) -> ProxyPlan:
        operation = str(request.get("operation", "")).strip()
        if operation != "process_execute":
            raise OgcMcpError(
                "invalid_argument",
                "operation must be 'process_execute'.",
                {"operation": operation},
            )
        server_id = str(request.get("server_id", ""))
        process_id = str(request.get("process_id", "")).strip()
        execute_request = request.get("execute_request", {})
        if not isinstance(execute_request, dict):
            raise OgcMcpError(
                "invalid_argument",
                "execute_request must be a JSON object.",
            )

        unresolved: list[dict[str, Any]] = []
        steps: list[dict[str, Any]] = []
        input_context, input_context_errors = _normalize_input_context(
            request.get("input_context", {})
        )
        unresolved.extend(input_context_errors)
        sources, source_shape_errors = _plan_sources_from_request(request, server_id)
        unresolved.extend(source_shape_errors)

        process_description: dict[str, Any] | None = None
        if process_id:
            process_description = self._load_process_description(server_id, process_id)
        if not process_id or process_description is None:
            available_processes = self._available_process_ids(server_id)
            unresolved.append(
                {
                    "field": "process_id",
                    "reason": "Process is not advertised by the selected server.",
                    "available": sorted(available_processes),
                }
            )
        else:
            steps.append(
                {
                    "kind": "process_execute",
                    "process_id": process_id,
                    "validated": True,
                }
            )
            unresolved.extend(
                validate_execute_inputs(
                    process_description,
                    execute_request,
                    input_context=input_context,
                )
            )

        source_steps, source_unresolved = self._validate_sources(sources, execute_request)
        steps = source_steps + steps
        unresolved.extend(source_unresolved)

        status = "ready_for_confirmation" if not unresolved else "needs_resolution"
        plan = ProxyPlan(
            plan_id=f"plan_{uuid.uuid4().hex}",
            operation=operation,
            server_id=server_id,
            status=status,
            steps=tuple(steps),
            unresolved=tuple(unresolved),
            execute_request=execute_request,
            input_context=input_context,
            sources=tuple(source.to_dict() for source in sources),
            created_at=self._now(),
        )
        return self._save(plan)

    def get_plan(self, plan_id: str) -> ProxyPlan | None:
        payload = self._store.get(plan_id)
        if payload is None:
            return None
        return ProxyPlan.from_dict(payload)

    def confirm_plan(
        self,
        plan_id: str,
        *,
        approved: bool,
        actor: str = "",
        comment: str = "",
    ) -> ProxyPlan:
        """Record explicit human approval or rejection for a validated plan."""
        plan = self.get_plan(plan_id)
        if not plan:
            raise OgcMcpError("invalid_argument", "Unknown plan_id.", {"plan_id": plan_id})
        # Approval requires the plan to be fully resolved (ready_for_confirmation).
        # Rejection is valid from either resolvable state so the user can abandon
        # a plan that is stuck at needs_resolution without waiting for TTL expiry.
        if approved and plan.status != "ready_for_confirmation":
            raise OgcMcpError(
                "plan_not_ready",
                "Only plans with status 'ready_for_confirmation' can be approved. "
                "Resolve all missing inputs first (ogc_proxy_update_plan), "
                "or reject the plan to abandon it (approved=False).",
                {"plan_id": plan_id, "status": plan.status},
            )
        if not approved and plan.status not in ("ready_for_confirmation", "needs_resolution"):
            raise OgcMcpError(
                "plan_not_rejectable",
                "Only plans with status 'needs_resolution' or 'ready_for_confirmation' can be rejected.",
                {"plan_id": plan_id, "status": plan.status},
            )
        confirmation = {
            "approved": approved,
            "actor": actor or "user",
            "comment": comment,
        }
        updated = replace(
            plan,
            status="confirmed" if approved else "rejected",
            confirmed_at=self._now(),
            confirmation=confirmation,
        )
        return self._save(updated)

    def execute_plan(
        self,
        plan_id: str,
        *,
        execution_mode: str = "auto",
        wait_seconds: int = 10,
    ) -> dict[str, Any]:
        plan = self.get_plan(plan_id)
        if not plan:
            raise OgcMcpError("invalid_argument", "Unknown plan_id.", {"plan_id": plan_id})
        if plan.status != "confirmed":
            raise OgcMcpError(
                "plan_not_confirmed",
                "Plan cannot be executed until it has explicit human confirmation.",
                {
                    "plan_id": plan_id,
                    "status": plan.status,
                    "unresolved": list(plan.unresolved),
                },
            )
        process_step = next(
            (step for step in plan.steps if step.get("kind") == "process_execute"),
            None,
        )
        if not process_step:
            raise OgcMcpError(
                "plan_not_ready",
                "Plan does not contain an executable process step.",
                {"plan_id": plan_id},
            )
        self._save(replace(plan, status="running"))
        try:
            result = self._processes.execute(
                str(process_step["process_id"]),
                plan.execute_request,
                server_id=plan.server_id,
                execution_mode=execution_mode,
                wait_seconds=wait_seconds,
            )
        except OgcMcpError:
            self._save(replace(plan, status="failed"))
            raise
        execution = _execution_record(result, plan.server_id, now=self._now())
        if execution.get("asynchronous"):
            next_status = (
                "submitted"
                if execution.get("tracking_state") == "available"
                else "failed"
            )
        else:
            next_status = "completed"
        self._save(
            replace(
                plan,
                status=next_status,
                execution=execution,
            )
        )
        return result

    def reconcile_job_status(
        self,
        job_id: str,
        *,
        server_id: str = "",
        result: dict[str, Any],
    ) -> list[str]:
        """Reconcile stored async plans from a trusted OGC job-status response."""
        clean_job_id = str(job_id).strip()
        if not clean_job_id:
            return []
        reported_status = str(
            _find_named_value(result.get("data"), {"status", "state"}) or "unknown"
        ).strip()[:200]
        normalized = reported_status.casefold()
        if normalized in {"successful", "succeeded", "success", "finished", "complete", "completed"}:
            plan_status = "completed"
        elif normalized in {"failed", "error"}:
            plan_status = "failed"
        elif normalized in {"dismissed", "cancelled", "canceled"}:
            plan_status = "cancelled"
        else:
            plan_status = "running"
        return self._reconcile_job(
            clean_job_id,
            server_id=server_id,
            plan_status=plan_status,
            reported_status=reported_status,
        )

    def reconcile_job_results(
        self,
        job_id: str,
        *,
        server_id: str = "",
    ) -> list[str]:
        """Mark matching submitted plans completed after results are retrieved."""
        return self._reconcile_job(
            str(job_id).strip(),
            server_id=server_id,
            plan_status="completed",
            reported_status="results_retrieved",
        )

    def _reconcile_job(
        self,
        job_id: str,
        *,
        server_id: str,
        plan_status: str,
        reported_status: str,
    ) -> list[str]:
        if not job_id:
            return []
        updated_ids: list[str] = []
        for payload in self._store.list_values():
            try:
                plan = ProxyPlan.from_dict(payload)
            except (KeyError, TypeError, ValueError):
                continue
            execution = plan.execution
            if str(execution.get("job_id", "")) != job_id:
                continue
            execution_server = str(execution.get("server_id") or plan.server_id)
            if server_id and execution_server != server_id:
                continue
            if plan.status not in {"submitted", "running"}:
                continue
            updated_execution = {
                **execution,
                "reported_status": reported_status,
                "last_reconciled_at": self._now(),
            }
            if plan_status in {"completed", "failed", "cancelled"}:
                updated_execution["completed_at"] = self._now()
            self._save(
                replace(
                    plan,
                    status=plan_status,
                    execution=updated_execution,
                )
            )
            updated_ids.append(plan.plan_id)
        return updated_ids

    def update_plan(
        self,
        plan_id: str,
        execute_request: dict[str, Any],
        input_context: dict[str, Any] | None = None,
    ) -> ProxyPlan:
        """Update the execute_request of a needs_resolution or ready_for_confirmation plan.

        This lets callers correct missing or incorrectly-typed inputs without
        discarding the plan and starting over. The plan is re-validated against
        the same process description used by ``create_plan``; if all issues are
        resolved the plan advances to ``ready_for_confirmation``, otherwise it
        stays at ``needs_resolution`` with an updated ``unresolved`` list.

        Plans in ``needs_resolution`` or ``ready_for_confirmation`` state can be
        updated. This allows a user who sees the confirmation prompt to revise
        inputs without having to reject and restart from a brand-new plan.
        Plans that are ``confirmed``, ``rejected``, ``running``, ``completed``,
        or ``failed`` are immutable.
        """
        plan = self.get_plan(plan_id)
        if not plan:
            raise OgcMcpError("invalid_argument", "Unknown plan_id.", {"plan_id": plan_id})
        if plan.status not in ("needs_resolution", "ready_for_confirmation"):
            raise OgcMcpError(
                "plan_not_updatable",
                "Only plans with status 'needs_resolution' or 'ready_for_confirmation' can have their inputs updated.",
                {"plan_id": plan_id, "status": plan.status},
            )

        process_step = next(
            (step for step in plan.steps if step.get("kind") == "process_execute"),
            None,
        )
        process_id = str(process_step["process_id"]) if process_step else ""
        normalized_input_context, input_context_errors = _normalize_input_context(
            plan.input_context if input_context is None else input_context
        )

        unresolved: list[dict[str, Any]] = _non_updatable_unresolved(plan.unresolved)
        unresolved.extend(input_context_errors)
        if process_id:
            unresolved.extend(
                self._validate_process_inputs(
                    plan.server_id,
                    process_id,
                    execute_request,
                    normalized_input_context,
                )
            )
        elif not any(item.get("field") == "process_id" for item in unresolved):
            unresolved.append(
                {
                    "field": "process_id",
                    "reason": (
                        "This plan has no validated process step. Create a new "
                        "plan with a valid process_id."
                    ),
                }
            )
        sources = tuple(_plan_source_from_payload(source) for source in plan.sources)
        source_steps, source_unresolved = self._validate_sources(sources, execute_request)
        unresolved.extend(source_unresolved)
        unresolved = _dedupe_unresolved(unresolved)

        steps = list(source_steps)
        if process_step:
            steps.append(dict(process_step))

        status = "ready_for_confirmation" if not unresolved else "needs_resolution"
        updated = replace(
            plan,
            execute_request=execute_request,
            input_context=normalized_input_context,
            steps=tuple(steps),
            unresolved=tuple(unresolved),
            status=status,
        )
        return self._save(updated)

    def list_plans(self) -> list[dict[str, Any]]:
        """Return model-safe metadata for all non-expired plans in the store.

        Useful for recovering a plan_id that was lost in a multi-turn
        conversation, or for checking whether any plans are pending
        confirmation. Only summary metadata is returned; full
        execute_request bodies and step details are omitted.
        """
        summaries: list[dict[str, Any]] = []
        for payload in self._store.list_values():
            try:
                plan = ProxyPlan.from_dict(payload)
                summaries.append(
                    {
                        "plan_id": plan.plan_id,
                        "operation": plan.operation,
                        "server_id": plan.server_id,
                        "status": plan.status,
                        "created_at": plan.created_at,
                        "unresolved_count": len(plan.unresolved),
                    }
                )
            except (KeyError, TypeError, ValueError):
                pass
        return sorted(summaries, key=lambda item: item.get("created_at", 0.0))

    def _save(self, plan: ProxyPlan) -> ProxyPlan:
        self._store.put(plan.plan_id, plan.to_dict(), ttl_seconds=self._ttl_seconds)
        return plan

    def _validate_process_inputs(
        self,
        server_id: str,
        process_id: str,
        execute_request: dict[str, Any],
        input_context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Validate against a fresh/cached schema and fail closed if unavailable."""
        process_description = self._load_process_description(server_id, process_id)
        if process_description is None:
            return [
                {
                    "id": "process-schema-unavailable",
                    "field": "process_schema",
                    "kind": "input",
                    "reason": (
                        "The process description is temporarily unavailable, so "
                        "the edited request cannot be validated safely."
                    ),
                    "question": (
                        "Would you like me to retry validation of this process "
                        "before asking for execution approval?"
                    ),
                    "why_it_matters": (
                        "An edited request must be checked against the authoritative "
                        "input schema before it can be approved."
                    ),
                    "allow_free_text": False,
                    "retryable": True,
                }
            ]
        return validate_execute_inputs(
            process_description,
            execute_request,
            input_context=input_context,
        )

    def _load_process_description(
        self,
        server_id: str,
        process_id: str,
    ) -> dict[str, Any] | None:
        """Return a cached/fresh process description body, or None on lookup failure."""
        try:
            description = self._process_descriptions.describe(process_id, server_id)
        except OgcMcpError:
            return None
        data = description.get("data")
        return data if isinstance(data, dict) else {}

    def _available_process_ids(self, server_id: str) -> set[str]:
        try:
            result = self._processes.list_processes(server_id)
        except OgcMcpError:
            return set()
        data = result.get("data", {})
        if not isinstance(data, dict):
            return set()
        processes = data.get("processes", [])
        if not isinstance(processes, list):
            return set()
        return {
            str(item.get("id", ""))
            for item in processes
            if isinstance(item, dict) and item.get("id")
        }

    def _validate_sources(
        self,
        sources: tuple[PlanSource, ...] | list[PlanSource],
        execute_request: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        steps: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        execute_hrefs = _href_values(execute_request)

        for index, source in enumerate(sources):
            field_prefix = "collection_id" if source.legacy else f"sources[{index}]"
            source_unresolved: list[dict[str, Any]] = []

            if source.href:
                matching_hrefs = [source.href] if source.href in execute_hrefs else []
                if not matching_hrefs:
                    source_unresolved.append(
                        {
                            "field": "execute_request.href",
                            "reason": (
                                "A declared source href is not present anywhere in "
                                "execute_request."
                            ),
                            "source_index": index,
                            "expected_href": source.href,
                        }
                    )
                if not _href_matches_collection(source.href, source.collection_id):
                    source_unresolved.append(
                        {
                            "field": _source_field(field_prefix, "href", legacy=source.legacy),
                            "reason": (
                                "The declared source href does not reference the "
                                "declared collection_id."
                            ),
                            "source_index": index,
                            "expected_path": f"/collections/{source.collection_id}",
                            "href": source.href,
                        }
                    )
            else:
                matching_hrefs = _collection_hrefs(execute_request, source.collection_id)
                if not matching_hrefs:
                    source_unresolved.append(
                        {
                            "field": field_prefix,
                            "reason": (
                                "collection_id was supplied, but no execute_request href "
                                "references that collection."
                            ),
                            "source_index": index,
                            "expected_path": f"/collections/{source.collection_id}",
                        }
                    )

            collection_result = self._describe_collection(
                source.server_id,
                source.collection_id,
            )
            if collection_result is None:
                if source.strict:
                    source_unresolved.append(
                        {
                            "field": _source_field(
                                field_prefix,
                                "collection_id",
                                legacy=source.legacy,
                            ),
                            "reason": (
                                "Collection is not advertised by the declared "
                                "Features server."
                            ),
                            "source_index": index,
                            "server_id": source.server_id,
                            "collection_id": source.collection_id,
                        }
                    )
            else:
                base_url = str(collection_result.get("server", {}).get("base_url", ""))
                outside_base = [
                    href
                    for href in matching_hrefs
                    if not _href_matches_server_base(href, base_url)
                ]
                if outside_base:
                    source_unresolved.append(
                        {
                            "field": _source_field(field_prefix, "href", legacy=source.legacy),
                            "reason": (
                                "The source href is not under the declared Features "
                                "server base_url."
                            ),
                            "source_index": index,
                            "server_id": source.server_id,
                            "base_url": base_url,
                            "hrefs": outside_base,
                        }
                    )

            if not source_unresolved:
                step: dict[str, Any] = {
                    "kind": "collection_reference",
                    "server_id": source.server_id,
                    "collection_id": source.collection_id,
                    "hrefs": matching_hrefs,
                    "validated": True,
                }
                if source.href:
                    step["href"] = source.href
                if source.role:
                    step["role"] = source.role
                if source.input_id:
                    step["input_id"] = source.input_id
                if source.legacy:
                    step["legacy"] = True
                steps.append(step)

            unresolved.extend(source_unresolved)

        return steps, unresolved

    def _describe_collection(
        self,
        server_id: str,
        collection_id: str,
    ) -> dict[str, Any] | None:
        try:
            return self._features.describe_collection(collection_id, server_id)
        except OgcMcpError:
            return None


def _href_values(value: Any, *, depth: int = 0) -> list[str]:
    if depth > 40:
        return []
    if isinstance(value, dict):
        hrefs: list[str] = []
        href = value.get("href")
        if isinstance(href, str):
            hrefs.append(href)
        for item in value.values():
            hrefs.extend(_href_values(item, depth=depth + 1))
        return hrefs
    if isinstance(value, list):
        hrefs = []
        for item in value:
            hrefs.extend(_href_values(item, depth=depth + 1))
        return hrefs
    return []


def _collection_hrefs(execute_request: dict[str, Any], collection_id: str) -> list[str]:
    return [
        href
        for href in _href_values(execute_request)
        if _href_matches_collection(href, collection_id)
    ]


def _href_matches_collection(href: str, collection_id: str) -> bool:
    """Match an exact OGC collection path segment below any server base path."""
    path_segments = [
        unquote(segment)
        for segment in urlparse(href).path.split("/")
        if segment
    ]
    return any(
        segment == "collections" and path_segments[index + 1] == collection_id
        for index, segment in enumerate(path_segments[:-1])
    )


def _href_matches_server_base(href: str, base_url: str) -> bool:
    href_parts = urlparse(href)
    base_parts = urlparse(base_url)
    if not href_parts.scheme or not href_parts.netloc:
        return False
    if href_parts.scheme.lower() != base_parts.scheme.lower():
        return False
    if (href_parts.hostname or "").lower() != (base_parts.hostname or "").lower():
        return False
    if _effective_port(href_parts.scheme, href_parts.port) != _effective_port(
        base_parts.scheme,
        base_parts.port,
    ):
        return False
    base_path = unquote(base_parts.path).rstrip("/")
    href_path = unquote(href_parts.path).rstrip("/")
    return not base_path or href_path == base_path or href_path.startswith(f"{base_path}/")


def _effective_port(scheme: str, port: int | None) -> int | None:
    if port is not None:
        return port
    if scheme.lower() == "http":
        return 80
    if scheme.lower() == "https":
        return 443
    return None


_INPUT_CONTEXT_ORIGINS = {
    "user",
    "service",
    "operator",
    "assumed",
    "inferred",
    "default",
    "unknown",
}


def _normalize_input_context(
    value: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Bound and normalize auditable input provenance supplied by the client."""
    if value is None:
        return {}, []
    if not isinstance(value, dict):
        return {}, [
            {
                "id": "input-context-shape",
                "field": "input_context",
                "kind": "input",
                "reason": "input_context must be a JSON object keyed by process input ID.",
                "question": "What provenance should be recorded for the process inputs?",
                "why_it_matters": (
                    "Input origin, units, and explicit acknowledgement must use a "
                    "structured form so they can be audited before execution."
                ),
                "allow_free_text": True,
            }
        ]

    normalized: dict[str, Any] = {}
    issues: list[dict[str, Any]] = []
    entries = list(value.items())
    if len(entries) > 100:
        issues.append(
            {
                "id": "input-context-count",
                "field": "input_context",
                "kind": "input",
                "reason": "input_context contains more than 100 entries.",
                "question": "Which input-context entries are required for this execution?",
                "why_it_matters": "The plan context is intentionally bounded for safe review.",
                "allow_free_text": True,
            }
        )

    for raw_key, raw_context in entries[:100]:
        key = str(raw_key).strip()[:300]
        field = key if key.startswith("inputs.") else f"inputs.{key}"
        if not key or not isinstance(raw_context, dict):
            issues.append(
                {
                    "id": f"input-context-{len(issues) + 1}",
                    "field": field if key else "input_context",
                    "kind": "input",
                    "reason": "Each input_context entry must be a JSON object.",
                    "question": f"What provenance should be recorded for '{key or 'this input'}'?",
                    "why_it_matters": (
                        "The human-in-the-loop gate cannot audit an unstructured "
                        "assumption record."
                    ),
                    "allow_free_text": True,
                }
            )
            continue

        origin = str(raw_context.get("origin") or "unknown").strip().casefold()
        if origin not in _INPUT_CONTEXT_ORIGINS:
            issues.append(
                {
                    "id": f"input-context-origin-{key}",
                    "field": field,
                    "kind": "input",
                    "reason": (
                        "input_context.origin must be one of: user, service, "
                        "operator, assumed, inferred, default, or unknown."
                    ),
                    "question": f"Where did the proposed value for '{key}' come from?",
                    "why_it_matters": (
                        "The confirmation gate must distinguish user-supplied "
                        "values from assumptions and service defaults."
                    ),
                    "allow_free_text": False,
                    "options": [
                        {"value": item, "label": item.replace("_", " ").title()}
                        for item in sorted(_INPUT_CONTEXT_ORIGINS)
                    ],
                }
            )
            origin = "unknown"

        context: dict[str, Any] = {
            "origin": origin,
            "confirmed": raw_context.get("confirmed") is True,
        }
        for context_key in ("unit", "crs", "note"):
            candidate = raw_context.get(context_key)
            if isinstance(candidate, str) and candidate.strip():
                context[context_key] = candidate.strip()[:1000]
        normalized[key.removeprefix("inputs.")] = context

    return normalized, issues


def _plan_sources_from_request(
    request: dict[str, Any],
    process_server_id: str,
) -> tuple[tuple[PlanSource, ...], list[dict[str, Any]]]:
    raw_sources = request.get("sources")
    if raw_sources is not None:
        return _explicit_sources(raw_sources)

    collection_id = _text(request.get("collection_id"))
    if not collection_id:
        return (), []

    collection_server_id = _text(
        request.get("collection_server_id", request.get("source_server_id"))
    )
    strict = bool(collection_server_id)
    source = PlanSource(
        server_id=collection_server_id or process_server_id,
        collection_id=collection_id,
        href=_text(request.get("collection_href")),
        strict=strict,
        legacy=True,
    )
    return (source,), []


def _explicit_sources(raw_sources: Any) -> tuple[tuple[PlanSource, ...], list[dict[str, Any]]]:
    if not isinstance(raw_sources, list):
        return (), [
            {
                "field": "sources",
                "reason": "sources must be a JSON array of source objects.",
            }
        ]

    sources: list[PlanSource] = []
    unresolved: list[dict[str, Any]] = []
    for index, raw_source in enumerate(raw_sources):
        field_prefix = f"sources[{index}]"
        if not isinstance(raw_source, dict):
            unresolved.append(
                {
                    "field": field_prefix,
                    "reason": "Each source must be a JSON object.",
                }
            )
            continue

        server_id = _text(raw_source.get("server_id"))
        collection_id = _text(raw_source.get("collection_id"))
        href = _text(raw_source.get("href"))
        if not server_id:
            unresolved.append(
                {
                    "field": f"{field_prefix}.server_id",
                    "reason": "Each source must name the registered Features server_id.",
                }
            )
        if not collection_id:
            unresolved.append(
                {
                    "field": f"{field_prefix}.collection_id",
                    "reason": "Each source must name the source collection_id.",
                }
            )
        if not href:
            unresolved.append(
                {
                    "field": f"{field_prefix}.href",
                    "reason": (
                        "Each source must include the exact href placed in "
                        "execute_request."
                    ),
                }
            )
        if not server_id or not collection_id or not href:
            continue

        sources.append(
            PlanSource(
                server_id=server_id,
                collection_id=collection_id,
                href=href,
                role=_text(raw_source.get("role")),
                input_id=_text(raw_source.get("input_id")),
                strict=True,
            )
        )

    return tuple(sources), unresolved


def _plan_source_from_payload(payload: dict[str, Any]) -> PlanSource:
    return PlanSource(
        server_id=_text(payload.get("server_id")),
        collection_id=_text(payload.get("collection_id")),
        href=_text(payload.get("href")),
        role=_text(payload.get("role")),
        input_id=_text(payload.get("input_id")),
        strict=not bool(payload.get("legacy")),
        legacy=bool(payload.get("legacy")),
    )


def _source_field(prefix: str, suffix: str, *, legacy: bool) -> str:
    if legacy:
        return prefix
    return f"{prefix}.{suffix}"


def _non_updatable_unresolved(unresolved: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in unresolved
        if item.get("field") == "process_id"
        or str(item.get("field", "")).startswith("sources")
    ]


def _dedupe_unresolved(unresolved: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for item in unresolved:
        key = (str(item.get("field", "")), str(item.get("reason", "")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _find_named_value(
    value: Any,
    names: set[str],
    *,
    depth: int = 0,
) -> Any:
    if depth > 5:
        return None
    if isinstance(value, list):
        for item in value[:100]:
            found = _find_named_value(item, names, depth=depth + 1)
            if found is not None:
                return found
        return None
    if not isinstance(value, dict):
        return None
    for key, item in list(value.items())[:100]:
        if str(key).casefold() in names:
            return item
    for item in list(value.values())[:100]:
        found = _find_named_value(item, names, depth=depth + 1)
        if found is not None:
            return found
    return None


def _job_id_from_location(location: str) -> str:
    if not location:
        return ""
    path = urlparse(location).path
    segments = [unquote(item) for item in path.split("/") if item]
    for index, segment in enumerate(segments):
        if segment.casefold() == "jobs" and index + 1 < len(segments):
            return segments[index + 1][:300]
    return segments[-1][:300] if segments else ""


def _execution_record(
    result: dict[str, Any],
    server_id: str,
    *,
    now: float,
) -> dict[str, Any]:
    response = result.get("response") if isinstance(result.get("response"), dict) else {}
    guidance = result.get("guidance") if isinstance(result.get("guidance"), dict) else {}
    manifest = (
        result.get("output_manifest")
        if isinstance(result.get("output_manifest"), dict)
        else {}
    )
    manifest_execution = (
        manifest.get("execution")
        if isinstance(manifest.get("execution"), dict)
        else {}
    )
    try:
        status_code = int(response.get("status_code", 0))
    except (TypeError, ValueError):
        status_code = 0
    location = str(guidance.get("location") or response.get("location") or "")[:2000]
    reported_status = str(
        _find_named_value(result.get("data"), {"status", "state"}) or ""
    ).strip()[:200]
    normalized_status = reported_status.casefold()
    asynchronous = (
        status_code in {201, 202}
        or bool(location)
        or manifest_execution.get("state") in {"submitted", "running"}
        or normalized_status in {"accepted", "queued", "pending", "submitted", "running"}
    )
    job_id = str(
        _find_named_value(result.get("data"), {"jobid", "job_id"})
        or manifest_execution.get("jobId")
        or manifest_execution.get("job_id")
        or _job_id_from_location(location)
        or ""
    ).strip()[:300]
    raw_tracking_state = str(manifest_execution.get("trackingState") or "").strip()
    tracking_state = (
        raw_tracking_state
        if raw_tracking_state in {"available", "unavailable"}
        else "available"
        if asynchronous and (job_id or location)
        else "unavailable"
        if asynchronous
        else ""
    )
    raw_tracking_error = manifest_execution.get("trackingError")
    tracking_error = (
        {
            "code": str(raw_tracking_error.get("code") or "async_job_untrackable")[:200],
            "message": str(
                raw_tracking_error.get("message")
                or "The asynchronous execution cannot be monitored."
            )[:2000],
        }
        if isinstance(raw_tracking_error, dict)
        else {
            "code": "async_job_untrackable",
            "message": (
                "The upstream server accepted asynchronous execution without "
                "returning a usable job identifier or Location."
            ),
        }
        if asynchronous and tracking_state == "unavailable"
        else {}
    )
    return {
        "asynchronous": asynchronous,
        "server_id": server_id,
        "submitted_at": now,
        **({"job_id": job_id} if job_id else {}),
        **({"location": location} if location else {}),
        **({"http_status": status_code} if status_code else {}),
        **({"reported_status": reported_status} if reported_status else {}),
        **({"tracking_state": tracking_state} if tracking_state else {}),
        **({"tracking_error": tracking_error} if tracking_error else {}),
        **(
            {"completed_at": now}
            if not asynchronous or tracking_state == "unavailable"
            else {}
        ),
    }


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
