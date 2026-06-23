"""Proxy memory for full OGC payloads behind opaque, model-safe handles."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from .store import InMemoryStore, KeyValueStore


@dataclass(frozen=True)
class MemoryRecord:
    """Stored full payload with model-safe metadata and summary."""

    handle: str
    operation: str
    server_id: str
    data: Any
    summary: Any
    created_at: float

    def metadata(self) -> dict[str, Any]:
        return {
            "handle": self.handle,
            "operation": self.operation,
            "server_id": self.server_id,
            "created_at": self.created_at,
            "summary": self.summary,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "handle": self.handle,
            "operation": self.operation,
            "server_id": self.server_id,
            "data": self.data,
            "summary": self.summary,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryRecord":
        return cls(
            handle=str(payload["handle"]),
            operation=str(payload.get("operation", "")),
            server_id=str(payload.get("server_id", "")),
            data=payload.get("data"),
            summary=payload.get("summary"),
            created_at=float(payload.get("created_at", 0.0)),
        )


class ProxyMemoryStore:
    """Store full responses behind opaque handles.

    Backed by a pluggable KeyValueStore (see services.store). The default
    in-process backend is correct for a single-worker stdio deployment only;
    multi-worker or multi-replica streamable-http deployments must configure
    an external backend so a handle minted on one worker resolves on another.
    Records expire after ttl_seconds (default 30 minutes) so memory does not
    grow unbounded over a long-running process; pass ttl_seconds=0 to disable
    expiry entirely.
    """

    def __init__(
        self,
        *,
        store: KeyValueStore | None = None,
        ttl_seconds: int | None = 1800,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._now = now or time.time
        self._store = store if store is not None else InMemoryStore(now=self._now)
        self._ttl_seconds = ttl_seconds or None

    def store(
        self,
        *,
        operation: str,
        server_id: str,
        data: Any,
        summary: Any,
    ) -> MemoryRecord:
        handle = f"mem_{uuid.uuid4().hex}"
        record = MemoryRecord(
            handle=handle,
            operation=operation,
            server_id=server_id,
            data=data,
            summary=summary,
            created_at=self._now(),
        )
        self._store.put(handle, record.to_dict(), ttl_seconds=self._ttl_seconds)
        return record

    def get(self, handle: str) -> MemoryRecord | None:
        payload = self._store.get(handle)
        if payload is None:
            return None
        return MemoryRecord.from_dict(payload)

    def require(self, handle: str) -> MemoryRecord:
        record = self.get(handle)
        if not record:
            raise KeyError(handle)
        return record

    def retrieve(
        self,
        handle: str,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return stored data for *handle* with optional paginated slicing.

        For FeatureCollection payloads the caller can walk through the full
        dataset in incremental pages without loading the entire response into
        model context.  Each call returns:

        - ``total_features``: total feature count (None for non-collection data)
        - ``offset``: the requested starting index
        - ``returned``: number of features (or items) in this slice
        - ``has_more``: True when more pages remain
        - ``data``: the sliced payload (or the full payload for non-collections)

        Raises ``KeyError`` when no record exists for the handle (expired or
        unknown).
        """
        record = self.get(handle)
        if record is None:
            raise KeyError(handle)
        data = record.data

        # FeatureCollection — paginate the features list
        if isinstance(data, dict) and isinstance(data.get("features"), list):
            features = data["features"]
            total = len(features)
            end = offset + limit
            sliced = features[offset:end]
            return {
                "handle": handle,
                "operation": record.operation,
                "server_id": record.server_id,
                "total_features": total,
                "offset": offset,
                "returned": len(sliced),
                "has_more": end < total,
                "data": {**data, "features": sliced},
            }

        # Flat list — paginate the list itself
        if isinstance(data, list):
            total = len(data)
            end = offset + limit
            sliced = data[offset:end]
            return {
                "handle": handle,
                "operation": record.operation,
                "server_id": record.server_id,
                "total_features": total,
                "offset": offset,
                "returned": len(sliced),
                "has_more": end < total,
                "data": sliced,
            }

        # Scalar / dict — return as-is; pagination is a no-op
        return {
            "handle": handle,
            "operation": record.operation,
            "server_id": record.server_id,
            "total_features": None,
            "offset": 0,
            "returned": None,
            "has_more": False,
            "data": data,
        }

    def list_metadata(self) -> list[dict[str, Any]]:
        records = sorted(
            (MemoryRecord.from_dict(item) for item in self._store.list_values()),
            key=lambda item: item.created_at,
        )
        return [record.metadata() for record in records]