"""Validated proxy plans for deterministic multi-step execution."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from ..errors import OgcMcpError
from ..modules import FeaturesService, ProcessesService
from .input_schema import validate_execute_inputs
from .store import InMemoryStore, KeyValueStore


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
    created_at: float = 0.0
    confirmed_at: float | None = None
    confirmation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "operation": self.operation,
            "server_id": self.server_id,
            "status": self.status,
            "steps": list(self.steps),
            "unresolved": list(self.unresolved),
            "execute_request": self.execute_request,
            "created_at": self.created_at,
            "confirmed_at": self.confirmed_at,
            "confirmation": self.confirmation,
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
            created_at=float(payload.get("created_at", 0.0)),
            confirmed_at=payload.get("confirmed_at"),
            confirmation=dict(payload.get("confirmation", {})),
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
        store: KeyValueStore | None = None,
        ttl_seconds: int | None = 3600,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._features = features
        self._processes = processes
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
        available_processes = self._available_process_ids(server_id)
        if not process_id or process_id not in available_processes:
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
                self._validate_process_inputs(server_id, process_id, execute_request)
            )

        collection_id = str(request.get("collection_id", "")).strip()
        if collection_id:
            available_collections = self._available_collection_ids(server_id)
            if collection_id not in available_collections:
                unresolved.append(
                    {
                        "field": "collection_id",
                        "reason": "Collection is not advertised by the selected server.",
                        "available": sorted(available_collections),
                    }
                )
            else:
                steps.insert(
                    0,
                    {
                        "kind": "collection_reference",
                        "collection_id": collection_id,
                        "validated": True,
                    },
                )

        status = "ready_for_confirmation" if not unresolved else "needs_resolution"
        plan = ProxyPlan(
            plan_id=f"plan_{uuid.uuid4().hex}",
            operation=operation,
            server_id=server_id,
            status=status,
            steps=tuple(steps),
            unresolved=tuple(unresolved),
            execute_request=execute_request,
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
        self._save(replace(plan, status="completed"))
        return result

    def update_plan(
        self,
        plan_id: str,
        execute_request: dict[str, Any],
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

        unresolved: list[dict[str, Any]] = []
        if process_id:
            unresolved = self._validate_process_inputs(
                plan.server_id, process_id, execute_request
            )

        status = "ready_for_confirmation" if not unresolved else "needs_resolution"
        updated = replace(
            plan,
            execute_request=execute_request,
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
    ) -> list[dict[str, Any]]:
        """Best-effort schema check; fails open if the description can't be fetched.

        process_id has already been confirmed to exist in /processes at this
        point, so a transient describe() failure here should not block
        plan creation outright -- it just means this extra layer of input
        validation is skipped for this plan.
        """
        try:
            description = self._processes.describe(process_id, server_id)
        except OgcMcpError:
            return []
        data = description.get("data")
        if not isinstance(data, dict):
            return []
        return validate_execute_inputs(data, execute_request)

    def _available_process_ids(self, server_id: str) -> set[str]:
        result = self._processes.list_processes(server_id)
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

    def _available_collection_ids(self, server_id: str) -> set[str]:
        result = self._features.list_collections(server_id)
        data = result.get("data", {})
        if not isinstance(data, dict):
            return set()
        collections = data.get("collections", [])
        if not isinstance(collections, list):
            return set()
        return {
            str(item.get("id", ""))
            for item in collections
            if isinstance(item, dict) and item.get("id")
        }