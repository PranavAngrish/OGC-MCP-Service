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
        """Return the model-safe metadata shape for list views.

        Accepted input payload:
            No arguments. Uses the current MemoryRecord instance:
                MemoryRecord(
                    handle="mem_abc",
                    operation="features.get_items",
                    server_id="pygeoapi-demo",
                    data={...},          # omitted from metadata output
                    summary={...},
                    created_at=1720000000.0,
                )

        Output payload:
            {
                "handle": "mem_abc",
                "operation": "features.get_items",
                "server_id": "pygeoapi-demo",
                "created_at": 1720000000.0,
                "summary": {...},
            }

        The full stored data is intentionally excluded so memory-list calls do
        not copy large upstream payloads into model context.
        """
        return {
            "handle": self.handle,
            "operation": self.operation,
            "server_id": self.server_id,
            "created_at": self.created_at,
            "summary": self.summary,
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full record for the configured KeyValueStore backend.

        Accepted input payload:
            No arguments. Uses the current MemoryRecord instance.

        Output payload:
            {
                "handle": "mem_abc",
                "operation": "features.get_items",
                "server_id": "pygeoapi-demo",
                "data": {...},      # full original payload, any JSON-like value
                "summary": {...},   # sanitized summary returned to the model
                "created_at": 1720000000.0,
            }

        This is the persistence payload; unlike metadata(), it includes the
        full upstream data so the handle can be retrieved later.
        """
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
        """Rehydrate a MemoryRecord from a store payload.

        Accepted input payload:
            {
                "handle": "mem_abc",      # required; KeyError if missing
                "operation": "features.get_items",
                "server_id": "pygeoapi-demo",
                "data": {...},
                "summary": {...},
                "created_at": 1720000000.0,
            }

        Output payload:
            MemoryRecord(
                handle="mem_abc",
                operation="features.get_items",
                server_id="pygeoapi-demo",
                data={...},
                summary={...},
                created_at=1720000000.0,
            )

        Missing optional fields default to empty strings, None, or 0.0. The
        handle is required because it is the stable identifier for retrieval.
        """
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
        """Create a proxy-memory facade over a pluggable key-value store.

        Accepted input payload:
            store=None
            ttl_seconds=1800
            now=None

        Alternative input payload:
            store=RedisStore(...)
            ttl_seconds=0
            now=time.time

        Output payload:
            No returned payload. The instance stores:
                _store       -> supplied store or a new InMemoryStore
                _ttl_seconds -> None when ttl_seconds is 0/None, otherwise int
                _now         -> supplied clock or time.time

        A ttl_seconds value of 0 or None disables expiry when records are put
        into the underlying store.
        """
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
        """Store one full payload and return its opaque memory record.

        Accepted input payload:
            operation="features.get_items"
            server_id="pygeoapi-demo"
            data={
                "type": "FeatureCollection",
                "features": [{...}, {...}],
            }
            summary={
                "boundary": "tool_result_data_only",
                "operation": "features.get_items",
                "summary": {"count": 2, "items": [...]},
            }

        Output payload:
            MemoryRecord(
                handle="mem_<uuid>",
                operation="features.get_items",
                server_id="pygeoapi-demo",
                data={...},
                summary={...},
                created_at=<current timestamp>,
            )

        Side effect:
            Persists record.to_dict() under the generated handle in the
            configured KeyValueStore, using this store's TTL setting.
        """
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
        """Look up one memory handle without raising when it is absent.

        Accepted input payload:
            handle="mem_abc"

        Output payload when found:
            MemoryRecord(
                handle="mem_abc",
                operation="features.get_items",
                server_id="pygeoapi-demo",
                data={...},
                summary={...},
                created_at=1720000000.0,
            )

        Output payload when missing or expired:
            None
        """
        payload = self._store.get(handle)
        if payload is None:
            return None
        return MemoryRecord.from_dict(payload)

    def require(self, handle: str) -> MemoryRecord:
        """Look up one memory handle and fail loudly when it is absent.

        Accepted input payload:
            handle="mem_abc"

        Output payload when found:
            MemoryRecord(...)

        Error payload when missing or expired:
            Raises KeyError("mem_abc")

        Use this when a caller cannot proceed without the full stored payload.
        """
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
        """Return stored data for a handle with optional paginated slicing.

        Accepted input payload:
            handle="mem_abc"
            offset=0
            limit=50

        FeatureCollection record.data input shape:
            {
                "type": "FeatureCollection",
                "features": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
                "links": [...],
            }

        FeatureCollection output payload:
            {
                "handle": "mem_abc",
                "operation": "features.get_items",
                "server_id": "pygeoapi-demo",
                "total_features": 3,
                "offset": 0,
                "returned": 2,
                "has_more": True,
                "data": {
                    "type": "FeatureCollection",
                    "features": [{"id": "a"}, {"id": "b"}],
                    "links": [...],
                },
            }

        Flat-list record.data input shape:
            [{"id": "a"}, {"id": "b"}, {"id": "c"}]

        Flat-list output payload:
            {
                "handle": "mem_abc",
                "operation": "records.search",
                "server_id": "pygeoapi-demo",
                "total_features": 3,
                "offset": 0,
                "returned": 2,
                "has_more": True,
                "data": [{"id": "a"}, {"id": "b"}],
            }

        Scalar/object record.data output payload:
            {
                "handle": "mem_abc",
                "operation": "jobs.get_results",
                "server_id": "geolabs-tb17",
                "total_features": None,
                "offset": 0,
                "returned": None,
                "has_more": False,
                "data": {...},  # original payload, unsliced
            }

        Error payload when missing or expired:
            Raises KeyError("mem_abc")

        offset and limit are passed directly to Python slicing. Callers should
        pass non-negative offsets and positive limits; this method does not
        clamp or validate them.
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
                "stored_features": total,
                "upstream_matched": data.get("numberMatched"),
                "upstream_complete": data.get("queryCompleteness", {}).get("complete")
                if isinstance(data.get("queryCompleteness"), dict)
                else None,
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
        """Return metadata for all non-expired memory records.

        Accepted input payload:
            No arguments. Reads all values currently visible from the
            configured KeyValueStore.

        Output payload:
            [
                {
                    "handle": "mem_abc",
                    "operation": "features.get_items",
                    "server_id": "pygeoapi-demo",
                    "created_at": 1720000000.0,
                    "summary": {...},
                },
                {
                    "handle": "mem_def",
                    "operation": "jobs.get_results",
                    "server_id": "geolabs-tb17",
                    "created_at": 1720000060.0,
                    "summary": {...},
                },
            ]

        The list is sorted by created_at ascending. Full stored data is not
        included; callers must use retrieve() with a handle to access it.
        """
        records = sorted(
            (MemoryRecord.from_dict(item) for item in self._store.list_values()),
            key=lambda item: item.created_at,
        )
        return [record.metadata() for record in records]
