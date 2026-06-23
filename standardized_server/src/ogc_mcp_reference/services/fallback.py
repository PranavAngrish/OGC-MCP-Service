"""Deterministic capability fallback selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .capabilities import CapabilityProfile


@dataclass(frozen=True)
class FallbackRule:
    """One deterministic fallback rule tied to a normalized capability flag."""

    id: str
    capability: str
    preferred: str
    fallback: str
    level: str = "MUST"

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "capability": self.capability,
            "preferred": self.preferred,
            "fallback": self.fallback,
            "level": self.level,
        }


DEFAULT_FALLBACK_RULES: tuple[FallbackRule, ...] = (
    FallbackRule(
        id="async_to_sync",
        capability="async",
        preferred="Prefer: respond-async with job polling",
        fallback="Synchronous execution without Prefer: respond-async",
    ),
    FallbackRule(
        id="cql2_to_client_filter",
        capability="cql2",
        preferred="Server-side CQL2 filter query",
        fallback="Fetch constrained data and apply the filter in the proxy",
    ),
    FallbackRule(
        id="crs_to_client_reproject",
        capability="crs_negotiation",
        preferred="Request data in EPSG:4326 from the server",
        fallback="Fetch server-default CRS and reproject in the proxy",
    ),
)


class FallbackEngine:
    """Map missing server capabilities to active fallback rules."""

    def __init__(self, rules: tuple[FallbackRule, ...] = DEFAULT_FALLBACK_RULES) -> None:
        self._rules = rules

    def active_for(self, profile: CapabilityProfile) -> list[dict[str, Any]]:
        active: list[dict[str, Any]] = []
        for rule in self._rules:
            if not profile.flags.get(rule.capability, False):
                active.append(rule.to_dict())
        return active

    def choose_execution_mode(self, requested_mode: str, profile: CapabilityProfile) -> str:
        """Avoid async execution when the server lacks async/job capabilities."""
        if requested_mode == "async" and not profile.flags.get("async", False):
            return "auto"
        return requested_mode
