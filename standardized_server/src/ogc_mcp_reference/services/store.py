"""Pluggable key-value storage for proxy plans and proxy memory records.

The default in-process backend keeps prior single-worker behavior unchanged
and requires no configuration. Operators deploying Streamable HTTP behind more
than one worker process or replica must configure the Redis backend so that a
plan created by one worker is visible to a confirm/execute call routed to a
different worker -- the in-process backend is invisible across processes.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable, Protocol

from ..errors import ConfigurationError
from ..models import StoreSettings


class KeyValueStore(Protocol):
    """Minimal storage contract used by ProxyPlanner and ProxyMemoryStore.

    Values are JSON-serializable dicts. ``ttl_seconds`` is best-effort and
    zero/None mean "no expiry"; callers must not depend on exact expiry
    timing, only on "expired entries eventually stop being returned."
    """

    def put(self, key: str, value: dict[str, Any], *, ttl_seconds: int | None) -> None:
        ...

    def get(self, key: str) -> dict[str, Any] | None:
        ...

    def list_values(self) -> list[dict[str, Any]]:
        ...


class InMemoryStore:
    """Process-local store.

    Safe only for single-worker deployments (typically stdio, one process per
    user). State lives in this Python process's memory and is invisible to
    any other worker, replica, or restart.
    """

    def __init__(self, *, now: Callable[[], float] | None = None) -> None:
        self._now = now or time.time
        self._items: dict[str, tuple[dict[str, Any], float | None]] = {}

    def put(self, key: str, value: dict[str, Any], *, ttl_seconds: int | None) -> None:
        expires_at = self._now() + ttl_seconds if ttl_seconds else None
        self._items[key] = (value, expires_at)

    def get(self, key: str) -> dict[str, Any] | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at is not None and expires_at <= self._now():
            self._items.pop(key, None)
            return None
        return value

    def list_values(self) -> list[dict[str, Any]]:
        now = self._now()
        live: list[dict[str, Any]] = []
        expired_keys: list[str] = []
        for key, (value, expires_at) in self._items.items():
            if expires_at is not None and expires_at <= now:
                expired_keys.append(key)
            else:
                live.append(value)
        for key in expired_keys:
            self._items.pop(key, None)
        return live


class RedisStore:
    """Redis-backed store for multi-worker / multi-replica deployments.

    Requires the optional 'redis' extra:
        pip install ogc-mcp-reference-server[redis]

    Keys are namespaced under ``prefix`` and tracked in a companion Redis SET
    so ``list_values`` can avoid an unbounded KEYS/SCAN call. Expired members
    are pruned from the index lazily on read.
    """

    def __init__(
        self,
        *,
        url: str,
        prefix: str,
        default_ttl_seconds: int | None,
        client: Any | None = None,
    ) -> None:
        if client is not None:
            self._client = client
        else:
            try:
                import redis  # type: ignore[import-not-found]
            except ImportError as exc:
                raise ConfigurationError(
                    "The 'redis' package is required for the redis proxy store backend. "
                    "Install it with: pip install ogc-mcp-reference-server[redis]"
                ) from exc
            self._client = redis.Redis.from_url(url, decode_responses=True)
        self._prefix = prefix
        self._index_key = f"{prefix}:__index__"
        self._default_ttl_seconds = default_ttl_seconds

    def _full_key(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    def put(self, key: str, value: dict[str, Any], *, ttl_seconds: int | None) -> None:
        effective_ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl_seconds
        payload = json.dumps(value)
        pipe = self._client.pipeline()
        if effective_ttl:
            pipe.set(self._full_key(key), payload, ex=effective_ttl)
        else:
            pipe.set(self._full_key(key), payload)
        pipe.sadd(self._index_key, key)
        pipe.execute()

    def get(self, key: str) -> dict[str, Any] | None:
        raw = self._client.get(self._full_key(key))
        if raw is None:
            self._client.srem(self._index_key, key)
            return None
        return json.loads(raw)

    def list_values(self) -> list[dict[str, Any]]:
        keys = self._client.smembers(self._index_key)
        values: list[dict[str, Any]] = []
        stale: list[str] = []
        for key in keys:
            raw = self._client.get(self._full_key(key))
            if raw is None:
                stale.append(key)
                continue
            values.append(json.loads(raw))
        if stale:
            self._client.srem(self._index_key, *stale)
        return values


def _resolve_redis_url(settings: StoreSettings) -> str:
    if not settings.redis_url_env:
        raise ConfigurationError(
            "store.redis_url_env must name an environment variable holding the Redis "
            "connection URL when store.backend is 'redis'."
        )
    value = os.environ.get(settings.redis_url_env)
    if not value:
        raise ConfigurationError(
            f"Required environment variable '{settings.redis_url_env}' for the Redis "
            "proxy store is not set."
        )
    return value


def build_store(
    settings: StoreSettings,
    *,
    namespace: str,
    default_ttl_seconds: int,
    now: Callable[[], float] | None = None,
    redis_client: Any | None = None,
) -> KeyValueStore:
    """Construct the configured backend for one logical namespace (plan/memory).

    ``namespace`` keeps plan and proxy-memory keys (and their TTLs) separate
    even when both are backed by the same Redis instance and key_prefix.
    """
    if settings.backend == "memory":
        return InMemoryStore(now=now)
    if settings.backend == "redis":
        return RedisStore(
            url=_resolve_redis_url(settings),
            prefix=f"{settings.key_prefix}:{namespace}",
            default_ttl_seconds=default_ttl_seconds or None,
            client=redis_client,
        )
    raise ConfigurationError(
        f"Unsupported store.backend '{settings.backend}'.",
        backend=settings.backend,
    )
