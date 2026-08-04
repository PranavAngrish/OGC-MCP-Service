"""Opaque storage for original and canonical output representations."""

from __future__ import annotations

import base64
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from ..services.store import KeyValueStore


@dataclass(frozen=True)
class StoredArtifact:
    handle: str
    media_type: str
    role: str
    size_bytes: int
    created_at: float

    def metadata(self) -> dict[str, Any]:
        return {
            "handle": self.handle,
            "mediaType": self.media_type,
            "role": self.role,
            "sizeBytes": self.size_bytes,
            "createdAt": self.created_at,
        }


def _serialized_size(value: Any) -> int:
    if isinstance(value, bytes):
        return len(value)
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    # Avoid importing a custom encoder: artifact pipeline values are expected
    # to be ordinary JSON-compatible structures.
    import json

    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


class ArtifactStore:
    """Store representations behind unguessable handles.

    Bytes are base64 encoded before reaching the generic JSON key-value store.
    Other values remain JSON-native so callers can retrieve canonical GeoJSON
    without decoding an additional serialization layer.
    """

    def __init__(
        self,
        *,
        store: KeyValueStore,
        ttl_seconds: int | None = 1800,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._store = store
        self._ttl_seconds = ttl_seconds or None
        self._now = now or time.time

    def put(self, data: Any, *, media_type: str, role: str) -> StoredArtifact:
        handle = f"art_{uuid.uuid4().hex}"
        created_at = self._now()
        size_bytes = _serialized_size(data)
        if isinstance(data, bytes):
            stored_data: Any = base64.b64encode(data).decode("ascii")
            encoding = "base64"
        else:
            stored_data = data
            encoding = "identity"
        record = {
            "handle": handle,
            "mediaType": media_type or "application/octet-stream",
            "role": role,
            "sizeBytes": size_bytes,
            "createdAt": created_at,
            "encoding": encoding,
            "data": stored_data,
        }
        self._store.put(handle, record, ttl_seconds=self._ttl_seconds)
        return StoredArtifact(
            handle=handle,
            media_type=record["mediaType"],
            role=role,
            size_bytes=size_bytes,
            created_at=created_at,
        )

    def retrieve(self, handle: str) -> dict[str, Any] | None:
        record = self._store.get(handle)
        if record is None:
            return None
        # Keep binary payloads JSON-safe at the MCP boundary.  The explicit
        # encoding tells a trusted client how to reconstruct the original.
        return {
            "handle": record["handle"],
            "mediaType": record["mediaType"],
            "role": record["role"],
            "sizeBytes": record["sizeBytes"],
            "createdAt": record["createdAt"],
            "encoding": record["encoding"],
            "data": record["data"],
        }

    def list_metadata(self) -> list[dict[str, Any]]:
        return [
            {
                key: record[key]
                for key in ("handle", "mediaType", "role", "sizeBytes", "createdAt")
            }
            for record in self._store.list_values()
        ]
