"""LangGraph-backed orchestration for proxy plan workflows."""

from __future__ import annotations

from typing import Any

from ..errors import OgcMcpError
from ..registry import ServerRegistry
from ..services.capabilities import CapabilityCache
from ..services.fallback import FallbackEngine
from ..services.planner import ProxyPlan, ProxyPlanner
from .state import PlanningWorkflowState


class PlanningWorkflow:
    """Stateful workflow facade around deterministic proxy services.

    LangGraph is used when installed. The local backend runs the same node
    methods directly so tests and constrained environments remain deterministic.
    """

    def __init__(
        self,
        *,
        planner: ProxyPlanner,
        registry: ServerRegistry,
        capabilities: CapabilityCache,
        fallbacks: FallbackEngine,
    ) -> None:
        
        self._planner = planner
        self._registry = registry
        self._capabilities = capabilities
        self._fallbacks = fallbacks
        self._graph = self._build_graph()
        self.backend = "langgraph" if self._graph is not None else "local"

    def create_plan(self, plan_request: dict[str, Any]) -> dict[str, Any]:
        """Create a plan and stop at the resolution/confirmation boundary.

        Accepted input payload:
            {
                "operation": "process_execute",
                "server_id": "geolabs-tb17",
                "process_id": "Delaunay",
                "execute_request": {
                    "inputs": {
                        "InputPoints": {
                            "href": "https://features.example.test/collections/roads/items?f=json"
                        }
                    },
                    "outputs": {
                        "Result": {
                            "transmissionMode": "value"
                        }
                    },
                },
                "sources": [
                    {
                        "server_id": "features-server",
                        "collection_id": "roads",
                        "href": "https://features.example.test/collections/roads/items?f=json",
                        "input_id": "InputPoints",
                    }
                ],
            }

        Output payload when ready for confirmation:
            {
                "ok": True,
                "operation": "workflow.create_plan",
                "workflow": {
                    "backend": "local",
                    "status": "awaiting_human_confirmation",
                    "human_in_the_loop": True,
                },
                "resolution_required": False,
                "confirmation_required": True,
                "plan": {
                    "plan_id": "plan_abc",
                    "status": "ready_for_confirmation",
                    "execute_request": {...},
                    "requires_confirmation": True,
                    ...
                },
                "resolution_prompt": {},
                "confirmation_prompt": {
                    "kind": "human_confirmation",
                    "plan_id": "plan_abc",
                    "execute_request": {...},
                    "steps": [...],
                    "unresolved": [],
                    "instructions": "...",
                },
            }

        Output payload when inputs need correction:
            {
                "ok": True,
                "operation": "workflow.create_plan",
                "workflow": {
                    "backend": "local",
                    "status": "needs_resolution",
                    "human_in_the_loop": True,
                },
                "resolution_required": True,
                "confirmation_required": False,
                "plan": {
                    "plan_id": "plan_abc",
                    "status": "needs_resolution",
                    "unresolved": [
                        {
                            "field": "inputs.InputPoints",
                            "reason": "Required process input is missing...",
                        }
                    ],
                    ...
                },
                "resolution_prompt": {
                    "kind": "human_resolution_required",
                    "plan_id": "plan_abc",
                    "next_tool": "ogc_proxy_update_plan",
                    "per_field_questions": [...],
                },
                "confirmation_prompt": {},
            }

        Errors:
            OgcMcpError can propagate from ProxyPlanner.create_plan when the
            operation or execute_request shape is invalid.
        """
        initial_state: PlanningWorkflowState = {"plan_request": plan_request}
        state = self._invoke_graph(initial_state)
        plan = state.get("plan", {})
        workflow_status = state.get("status", "")
        plan_status = plan.get("status", "")

        # Build a resolution_prompt when the plan still has unresolved inputs so
        # the LLM knows exactly which questions to put to the user, one at a time.
        # Distinguish between a bad process_id (cannot be fixed by update_plan, which
        # only accepts execute_request) vs. bad inputs (update_plan is the right tool).
        resolution_prompt: dict[str, Any] = {}
        if plan_status == "needs_resolution":
            unresolved = plan.get("unresolved", [])
            has_process_id_error = any(
                item.get("field") == "process_id" for item in unresolved
            )
            has_source_metadata_error = any(
                str(item.get("field", "")).startswith("sources")
                for item in unresolved
            )
            if has_process_id_error or has_source_metadata_error:
                _resolution_message = (
                    "The plan contains invalid metadata outside execute_request "
                    "(process_id or sources). Discover the correct process/source "
                    "details, then create a NEW plan (ogc_proxy_create_plan). "
                    "Do NOT call ogc_proxy_update_plan — it can only correct "
                    "execute_request inputs and cannot change process_id or sources "
                    "on an existing plan."
                )
                _next_tool = "ogc_proxy_create_plan"
            else:
                _resolution_message = (
                    "The execution plan cannot proceed because one or more inputs are "
                    "missing or ambiguous. Ask the user to supply each value listed in "
                    "per_field_questions — ONE question at a time — then call "
                    "ogc_proxy_update_plan with the corrected execute_request. "
                    "Do NOT create a brand-new plan; update this one in place."
                )
                _next_tool = "ogc_proxy_update_plan"
            resolution_prompt = {
                "kind": "human_resolution_required",
                "plan_id": plan.get("plan_id", ""),
                "message": _resolution_message,
                "next_tool": _next_tool,
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

        return {
            "ok": True,
            "operation": "workflow.create_plan",
            "workflow": {
                "backend": self.backend,
                "status": workflow_status,
                "human_in_the_loop": workflow_status in (
                    "awaiting_human_confirmation", "needs_resolution"
                ),
            },
            "resolution_required": plan_status == "needs_resolution",
            "confirmation_required": workflow_status == "awaiting_human_confirmation",
            "plan": plan,
            "resolution_prompt": resolution_prompt,
            "confirmation_prompt": state.get("confirmation_prompt", {}),
        }

    def get_plan(self, plan_id: str) -> ProxyPlan | None:
        """Return one stored plan by ID without changing workflow state.

        Accepted input payload:
            plan_id="plan_abc"

        Output payload when found:
            ProxyPlan(
                plan_id="plan_abc",
                operation="process_execute",
                server_id="geolabs-tb17",
                status="ready_for_confirmation",
                steps=(...),
                unresolved=(),
                execute_request={...},
                ...
            )

        Output payload when missing or expired:
            None
        """
        return self._planner.get_plan(plan_id)

    def confirm_plan(
        self,
        plan_id: str,
        *,
        approved: bool,
        actor: str = "",
        comment: str = "",
    ) -> dict[str, Any]:
        """Resume the workflow after explicit human approval or rejection.

        Accepted input payload:
            plan_id="plan_abc"
            approved=True
            actor="user"
            comment="Looks correct"

        Output payload:
            {
                "ok": True,
                "operation": "workflow.confirm_plan",
                "workflow": {
                    "backend": "local",
                    "status": "confirmed",
                    "human_in_the_loop": False,
                },
                "plan": {
                    "plan_id": "plan_abc",
                    "status": "confirmed",
                    "confirmed_at": 1720000000.0,
                    "confirmation": {
                        "approved": True,
                        "actor": "user",
                        "comment": "Looks correct",
                    },
                    ...
                },
            }

        Error payloads:
            Raises OgcMcpError("invalid_argument") for an unknown plan_id.
            Raises OgcMcpError("plan_not_ready") when approving a plan that is
            not ready_for_confirmation.
            Raises OgcMcpError("plan_not_rejectable") when rejecting a plan in
            a terminal or running state.
        """
        plan = self._planner.confirm_plan(
            plan_id,
            approved=approved,
            actor=actor,
            comment=comment,
        )
        return {
            "ok": True,
            "operation": "workflow.confirm_plan",
            "workflow": {
                "backend": self.backend,
                "status": plan.status,
                "human_in_the_loop": False,
            },
            "plan": plan.to_dict(),
        }

    def execute_plan(
        self,
        plan_id: str,
        *,
        execution_mode: str = "auto",
        wait_seconds: int = 10,
    ) -> dict[str, Any]:
        """Execute a confirmed plan with capability-aware fallback selection.

        Accepted input payload:
            plan_id="plan_abc"
            execution_mode="async"  # "auto", "async", or "sync-wait"
            wait_seconds=10

        Output payload:
            {
                "ok": True,
                "operation": "processes.execute",
                "server": {...},
                "request": {"method": "POST", "path": "/processes/Delaunay/execution"},
                "response": {"status_code": 200, "content_type": "application/json"},
                "data": {...},
                "proxy": {
                    "workflow_backend": "local",
                    "requested_execution_mode": "async",
                    "selected_execution_mode": "auto",
                    "active_fallbacks": [
                        {
                            "id": "async_to_sync",
                            "capability": "async",
                            "preferred": "Prefer: respond-async with job polling",
                            "fallback": "Synchronous execution without Prefer: respond-async",
                            "level": "MUST",
                        }
                    ],
                },
            }

        Error payloads:
            Raises OgcMcpError("invalid_argument") for an unknown plan_id.
            Raises OgcMcpError("plan_not_confirmed") when the stored plan has
            not been explicitly confirmed.
            Other OgcMcpError values can propagate from process execution,
            capability loading, security checks, or upstream transport.
        """
        plan = self._planner.get_plan(plan_id)
        if not plan:
            raise OgcMcpError("invalid_argument", "Unknown plan_id.", {"plan_id": plan_id})
        profile_server_id = plan.server_id or self._registry.get(service="processes").id
        profile = self._capabilities.get(profile_server_id)
        selected_mode = self._fallbacks.choose_execution_mode(execution_mode, profile)
        result = self._planner.execute_plan(
            plan_id,
            execution_mode=selected_mode,
            wait_seconds=wait_seconds,
        )
        result["proxy"] = {
            "workflow_backend": self.backend,
            "requested_execution_mode": execution_mode,
            "selected_execution_mode": selected_mode,
            "active_fallbacks": self._fallbacks.active_for(profile),
        }
        return result

    def _invoke_graph(self, initial_state: PlanningWorkflowState) -> PlanningWorkflowState:
        """Run the plan-creation nodes through LangGraph or the local fallback.

        Accepted input payload:
            {
                "plan_request": {
                    "operation": "process_execute",
                    "process_id": "Delaunay",
                    "execute_request": {"inputs": {}},
                }
            }

        Output payload when the plan needs resolution:
            {
                "plan_request": {...},
                "plan_id": "plan_abc",
                "plan": {"status": "needs_resolution", ...},
                "status": "needs_resolution",
            }

        Output payload when the plan is ready for user confirmation:
            {
                "plan_request": {...},
                "plan_id": "plan_abc",
                "plan": {"status": "ready_for_confirmation", ...},
                "status": "awaiting_human_confirmation",
                "confirmation_prompt": {...},
            }

        In LangGraph mode, graph.invoke() returns the final state. In local
        mode, this method manually calls the same node methods in sequence.
        """
        if self._graph is not None:
            return self._graph.invoke(initial_state)
        created = self._create_plan_node(initial_state)
        if self._route_after_create(created) == "await_confirmation":
            return self._await_confirmation_node(created)
        return created

    def _create_plan_node(self, state: PlanningWorkflowState) -> PlanningWorkflowState:
        plan = self._planner.create_plan(state["plan_request"])
        return {
            **state,
            "plan_id": plan.plan_id,
            "plan": plan.to_dict(),
            "status": "needs_resolution"
            if plan.status == "needs_resolution"
            else "plan_created",
        }

    def _await_confirmation_node(self, state: PlanningWorkflowState) -> PlanningWorkflowState:
        plan = state.get("plan", {})
        prompt = {
            "kind": "human_confirmation",
            "plan_id": plan.get("plan_id", ""),
            "message": (
                "All inputs are validated. Show the user the complete execute_request "
                "below — verbatim, not paraphrased — and ask for explicit approval "
                "before calling ogc_proxy_confirm_plan. If any value looks unclear, "
                "vague, or was assumed rather than explicitly supplied by the user, "
                "reject this plan and clarify with the user first."
            ),
            "steps": plan.get("steps", []),
            "execute_request": plan.get("execute_request", {}),
            "unresolved": plan.get("unresolved", []),
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
        return {
            **state,
            "status": "awaiting_human_confirmation",
            "confirmation_prompt": prompt,
        }

    @staticmethod
    def _route_after_create(state: PlanningWorkflowState) -> str:
        plan = state.get("plan", {})
        if plan.get("status") == "ready_for_confirmation":
            return "await_confirmation"
        return "end"

    def _build_graph(self) -> Any | None:
        """Compile the optional LangGraph state graph for plan creation.

        Accepted input payload:
            No arguments. Uses bound methods:
                self._create_plan_node
                self._route_after_create
                self._await_confirmation_node

        Output payload when LangGraph is installed:
            Compiled graph object with this flow:
                START -> create_plan
                create_plan -> await_confirmation when route is
                    "await_confirmation"
                create_plan -> END when route is "end"
                await_confirmation -> END

        Output payload when LangGraph is unavailable:
            None

        Returning None intentionally activates the deterministic local fallback
        in _invoke_graph().
        """
        try:
            from langgraph.graph import END, START, StateGraph
        except ImportError:
            return None

        graph = StateGraph(PlanningWorkflowState)
        graph.add_node("create_plan", self._create_plan_node)
        graph.add_node("await_confirmation", self._await_confirmation_node)
        graph.add_edge(START, "create_plan")
        graph.add_conditional_edges(
            "create_plan",
            self._route_after_create,
            {
                "await_confirmation": "await_confirmation",
                "end": END,
            },
        )
        graph.add_edge("await_confirmation", END)
        return graph.compile()
