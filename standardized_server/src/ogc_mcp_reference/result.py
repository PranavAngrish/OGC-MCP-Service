"""Stable tool-result envelopes shared by all OGC modules."""

from __future__ import annotations

import json
from typing import Any, Callable

from .errors import OgcMcpError
from .models import OgcResponse, ServerProfile


def parse_json_object(value: str, *, label: str, allow_empty: bool = True) -> dict[str, Any]:
    """Parse a JSON object supplied through an MCP string argument."""
    if not value.strip() and allow_empty:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise OgcMcpError(
            "invalid_json_argument",
            f"{label} must be valid JSON: {exc.msg}.",
            {"label": label, "line": exc.lineno, "column": exc.colno},
        ) from exc
    if not isinstance(parsed, dict):
        raise OgcMcpError(
            "invalid_json_argument",
            f"{label} must decode to a JSON object.",
            {"label": label},
        )
    return parsed


def success(
    operation: str,
    server: ServerProfile,
    response: OgcResponse,
    *,
    data: Any | None = None,
    guidance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a stable success envelope."""
    payload: dict[str, Any] = {
        "ok": True,
        "operation": operation,
        "server": {
            "id": server.id,
            "title": server.title,
            "base_url": server.base_url,
        },
        "request": {
            "method": response.method,
            "path": response.path,
        },
        "response": response.metadata(),
        "data": response.data if data is None else data,
    }
    if guidance:
        payload["guidance"] = guidance
    return payload


def failure(operation: str, error: OgcMcpError) -> dict[str, Any]:
    """Build a stable error envelope."""
    return {
        "ok": False,
        "operation": operation,
        "error": error.to_dict(),
    }


def invoke(operation: str, callback: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Convert expected server errors into MCP-friendly structured output."""
    try:
        return callback()
    except OgcMcpError as exc:
        return failure(operation, exc)
