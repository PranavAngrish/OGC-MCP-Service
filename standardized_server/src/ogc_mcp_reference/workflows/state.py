"""Typed state used by proxy planning workflows."""

from __future__ import annotations

from typing import Any, TypedDict


class PlanningWorkflowState(TypedDict, total=False):
    """LangGraph-compatible state for plan creation and confirmation."""

    plan_request: dict[str, Any]
    plan: dict[str, Any]
    plan_id: str
    status: str
    confirmation_prompt: dict[str, Any]
    confirmation: dict[str, Any]
    result: dict[str, Any]
    error: dict[str, Any]
