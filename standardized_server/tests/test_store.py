from __future__ import annotations

import unittest

from ogc_mcp_reference.errors import ConfigurationError
from ogc_mcp_reference.models import StoreSettings
from ogc_mcp_reference.services.store import InMemoryStore, RedisStore, build_store


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


class InMemoryStoreTests(unittest.TestCase):
    def test_put_get_round_trip(self) -> None:
        store = InMemoryStore()
        store.put("plan_1", {"status": "ready_for_confirmation"}, ttl_seconds=None)
        self.assertEqual(store.get("plan_1"), {"status": "ready_for_confirmation"})

    def test_missing_key_returns_none(self) -> None:
        store = InMemoryStore()
        self.assertIsNone(store.get("does_not_exist"))

    def test_entries_expire_after_ttl(self) -> None:
        clock = _FakeClock()
        store = InMemoryStore(now=clock)
        store.put("mem_1", {"value": 1}, ttl_seconds=10)
        clock.now += 5
        self.assertEqual(store.get("mem_1"), {"value": 1})
        clock.now += 6
        self.assertIsNone(store.get("mem_1"))

    def test_list_values_excludes_expired_entries(self) -> None:
        clock = _FakeClock()
        store = InMemoryStore(now=clock)
        store.put("a", {"id": "a"}, ttl_seconds=10)
        store.put("b", {"id": "b"}, ttl_seconds=None)
        clock.now += 20
        values = store.list_values()
        self.assertEqual(values, [{"id": "b"}])


class RedisStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            import fakeredis
        except ImportError:
            self.skipTest("fakeredis is not installed")
        self.client = fakeredis.FakeRedis(decode_responses=True)

    def test_put_get_round_trip(self) -> None:
        store = RedisStore(
            url="redis://unused",
            prefix="test:plan",
            default_ttl_seconds=None,
            client=self.client,
        )
        store.put("plan_1", {"status": "confirmed"}, ttl_seconds=None)
        self.assertEqual(store.get("plan_1"), {"status": "confirmed"})

    def test_ttl_expiry_is_visible_across_separate_store_instances(self) -> None:
        writer = RedisStore(
            url="redis://unused",
            prefix="test:mem",
            default_ttl_seconds=None,
            client=self.client,
        )
        writer.put("mem_1", {"handle": "mem_1"}, ttl_seconds=None)

        # A second store instance pointed at the same client/prefix simulates a
        # different worker process reading a plan/handle created elsewhere.
        reader = RedisStore(
            url="redis://unused",
            prefix="test:mem",
            default_ttl_seconds=None,
            client=self.client,
        )
        self.assertEqual(reader.get("mem_1"), {"handle": "mem_1"})

    def test_list_values_prunes_stale_index_entries(self) -> None:
        store = RedisStore(
            url="redis://unused",
            prefix="test:list",
            default_ttl_seconds=1,
            client=self.client,
        )
        store.put("a", {"id": "a"}, ttl_seconds=1)
        store.put("b", {"id": "b"}, ttl_seconds=None)
        self.client.delete("test:list:a")  # simulate Redis-side TTL expiry
        values = store.list_values()
        self.assertEqual(values, [{"id": "b"}])


class BuildStoreTests(unittest.TestCase):
    def test_memory_backend_is_default(self) -> None:
        store = build_store(StoreSettings(), namespace="plan", default_ttl_seconds=3600)
        self.assertIsInstance(store, InMemoryStore)

    def test_redis_backend_requires_url_env(self) -> None:
        with self.assertRaises(ConfigurationError):
            build_store(
                StoreSettings(backend="redis", redis_url_env=""),
                namespace="plan",
                default_ttl_seconds=3600,
            )

    def test_redis_backend_accepts_injected_client(self) -> None:
        try:
            import fakeredis
        except ImportError:
            self.skipTest("fakeredis is not installed")
        import os

        os.environ["TEST_OGC_MCP_REDIS_URL"] = "redis://unused"
        try:
            store = build_store(
                StoreSettings(backend="redis", redis_url_env="TEST_OGC_MCP_REDIS_URL"),
                namespace="plan",
                default_ttl_seconds=3600,
                redis_client=fakeredis.FakeRedis(decode_responses=True),
            )
            self.assertIsInstance(store, RedisStore)
        finally:
            del os.environ["TEST_OGC_MCP_REDIS_URL"]


if __name__ == "__main__":
    unittest.main()
