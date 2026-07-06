"""Short-lived cache for OGC process descriptions."""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass
from typing import Any, Callable

from ..modules import ProcessesService


@dataclass(frozen=True)
class CachedProcessDescription:
    """One cached ogc_processes_describe result envelope."""

    result: dict[str, Any]
    expires_at: float | None

    def is_expired(self, now: float) -> bool:
        return self.expires_at is not None and self.expires_at <= now


class ProcessDescriptionCache:
    """Cache process descriptions discovered through ogc_processes_describe.

    This keeps the normal create-plan path from fetching /processes and then
    /processes/{process_id} when a caller has already described the process.
    Cache misses still fetch the live description, so the planner keeps its
    server-side validation boundary even when the LLM skipped discovery.
    """

    def __init__(
        self,
        processes: ProcessesService,
        *,
        ttl_seconds: int | None = 300,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._processes = processes
        self._ttl_seconds = ttl_seconds or None
        self._now = now or time.time
        self._items: dict[tuple[str, str], CachedProcessDescription] = {}

    def describe(self, process_id: str, server_id: str = "") -> dict[str, Any]:
        """Return a cached or freshly-fetched process description envelope."""
        requested_key = (server_id, process_id)
        cached = self._get(requested_key)
        if cached is not None:
            return cached

        result = self._processes.describe(process_id, server_id)
        actual_server_id = str(result.get("server", {}).get("id", server_id))
        self._put((actual_server_id, process_id), result)
        if requested_key != (actual_server_id, process_id):
            self._put(requested_key, result)
        return copy.deepcopy(result)

    def _get(self, key: tuple[str, str]) -> dict[str, Any] | None:
        cached = self._items.get(key)
        if cached is None:
            return None
        if cached.is_expired(self._now()):
            self._items.pop(key, None)
            return None
        return copy.deepcopy(cached.result)

    def _put(self, key: tuple[str, str], result: dict[str, Any]) -> None:
        expires_at = self._now() + self._ttl_seconds if self._ttl_seconds else None
        self._items[key] = CachedProcessDescription(
            result=copy.deepcopy(result),
            expires_at=expires_at,
        )
