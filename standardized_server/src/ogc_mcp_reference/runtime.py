"""Runtime composition for the OGC MCP proxy."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

from .config import load_settings
from .models import RegistrySettings, ServerPolicy
from .modules import CommonService, FeaturesService, ProcessesService, RecordsService
from .registry import ServerRegistry
from .services.auth import TokenManager
from .services.capabilities import CapabilityCache
from .services.fallback import FallbackEngine
from .services.memory import ProxyMemoryStore
from .services.planner import ProxyPlanner
from .services.sanitization import ResponseSanitizer
from .services.store import build_store
from .transport import OgcHttpClient
from .workflows import PlanningWorkflow


@dataclass
class ProxyRuntime:
    """All long-lived services for one MCP server instance."""

    registry: ServerRegistry
    client: OgcHttpClient
    common: CommonService
    features: FeaturesService
    records: RecordsService
    processes: ProcessesService
    capabilities: CapabilityCache
    fallbacks: FallbackEngine
    memory: ProxyMemoryStore
    sanitizer: ResponseSanitizer
    planner: ProxyPlanner
    workflow: PlanningWorkflow
    policy: ServerPolicy


def create_runtime(
    config_path: str | Path | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
    bootstrap_capabilities: bool = False,
    settings: RegistrySettings | None = None,
) -> ProxyRuntime:
    """Build the proxy runtime and optionally discover conformance on startup.

    ``settings`` lets tests inject already-parsed configuration (e.g. with a
    fake Redis client wired into the store) without writing a config file;
    production callers should normally only pass config_path or rely on
    OGC_MCP_CONFIG.
    """
    resolved_settings = settings or load_settings(config_path)
    registry = ServerRegistry(resolved_settings)
    token_manager = TokenManager(transport=transport)
    client = OgcHttpClient(transport=transport, token_manager=token_manager)
    common = CommonService(registry, client)
    features = FeaturesService(registry, client)
    records = RecordsService(registry, client)
    processes = ProcessesService(registry, client)
    capabilities = CapabilityCache(registry, client)
    fallbacks = FallbackEngine()

    store_settings = resolved_settings.store
    memory_store = build_store(
        store_settings,
        namespace="memory",
        default_ttl_seconds=store_settings.memory_ttl_seconds,
    )
    plan_store = build_store(
        store_settings,
        namespace="plan",
        default_ttl_seconds=store_settings.plan_ttl_seconds,
    )
    memory = ProxyMemoryStore(store=memory_store, ttl_seconds=store_settings.memory_ttl_seconds)
    sanitizer = ResponseSanitizer()
    planner = ProxyPlanner(
        features=features,
        processes=processes,
        store=plan_store,
        ttl_seconds=store_settings.plan_ttl_seconds,
    )
    workflow = PlanningWorkflow(
        planner=planner,
        registry=registry,
        capabilities=capabilities,
        fallbacks=fallbacks,
    )
    runtime = ProxyRuntime(
        registry=registry,
        client=client,
        common=common,
        features=features,
        records=records,
        processes=processes,
        capabilities=capabilities,
        fallbacks=fallbacks,
        memory=memory,
        sanitizer=sanitizer,
        planner=planner,
        workflow=workflow,
        policy=resolved_settings.policy,
    )
    if bootstrap_capabilities:
        runtime.capabilities.bootstrap()
    return runtime
