from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

import httpx

from ogc_mcp_reference.app import create_mcp_server


BASE_CONFIG = {
    "default_servers": {
        "common": "example",
        "features": "example",
        "records": "example",
        "processes": "example",
    },
    "servers": [
        {
            "id": "example",
            "base_url": "https://example.org",
            "services": ["common", "features", "records", "processes"],
        }
    ],
}


def _write_config(directory: str, overrides: dict | None = None) -> Path:
    config = json.loads(json.dumps(BASE_CONFIG))
    if overrides:
        config.update(overrides)
    path = Path(directory) / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def _call(mcp, name: str, arguments: dict):
    _, structured = asyncio.run(mcp.call_tool(name, arguments))
    return structured


class AppTests(unittest.TestCase):
    def test_creates_fastmcp_server_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = _write_config(directory)
            server = create_mcp_server(path)
        self.assertEqual(server.name, "OGC API MCP Reference Server")


class DirectExecutionGatingTests(unittest.TestCase):
    """Item #2: ogc_processes_execute must be absent unless explicitly enabled."""

    def test_direct_execution_tool_is_absent_by_default(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={})

        with tempfile.TemporaryDirectory() as directory:
            path = _write_config(directory)
            mcp = create_mcp_server(path, transport=httpx.MockTransport(handler))

        names = {tool.name for tool in asyncio.run(mcp.list_tools())}
        self.assertNotIn("ogc_processes_execute", names)
        # The confirmation-gated proxy tools and the lower-risk cancel tool
        # must remain available regardless of the policy flag.
        self.assertIn("ogc_proxy_create_plan", names)
        self.assertIn("ogc_proxy_confirm_plan", names)
        self.assertIn("ogc_proxy_execute_plan", names)
        self.assertIn("ogc_jobs_dismiss", names)

    def test_direct_execution_tool_is_present_when_policy_enabled(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/processes/Delaunay/execution":
                return httpx.Response(200, json={"result": "ok"})
            return httpx.Response(404, json={})

        with tempfile.TemporaryDirectory() as directory:
            path = _write_config(
                directory,
                {"policy": {"expose_direct_execution_tools": True}},
            )
            mcp = create_mcp_server(path, transport=httpx.MockTransport(handler))

        names = {tool.name for tool in asyncio.run(mcp.list_tools())}
        self.assertIn("ogc_processes_execute", names)

        result = _call(
            mcp,
            "ogc_processes_execute",
            {
                "process_id": "Delaunay",
                "execute_request_json": "{\"inputs\": {}}",
                "response_mode": "raw",
            },
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"], {"result": "ok"})


class ResponseModeTests(unittest.TestCase):
    """Item #3: large/unbounded results are summarized behind a memory handle by default."""

    def test_discovery_and_escape_hatch_tools_default_to_summary(self) -> None:
        collections_payload = {
            "collections": [
                {"id": f"collection-{index}", "title": f"Collection {index}"}
                for index in range(25)
            ]
        }
        processes_payload = {
            "processes": [
                {"id": f"process-{index}", "title": f"Process {index}"}
                for index in range(25)
            ]
        }
        resource_payload = {
            "type": "FeatureCollection",
            "features": [
                {"id": f"feature-{index}", "properties": {"title": f"Feature {index}"}}
                for index in range(25)
            ],
        }

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/collections":
                return httpx.Response(200, json=collections_payload)
            if request.url.path == "/processes":
                return httpx.Response(200, json=processes_payload)
            if request.url.path == "/custom":
                return httpx.Response(200, json=resource_payload)
            return httpx.Response(404, json={})

        with tempfile.TemporaryDirectory() as directory:
            path = _write_config(directory)
            mcp = create_mcp_server(path, transport=httpx.MockTransport(handler))

        calls = [
            ("ogc_features_list_collections", {}),
            ("ogc_records_list_collections", {}),
            ("ogc_processes_list", {}),
            ("ogc_common_get_resource", {"server_id": "example", "path": "/custom"}),
        ]

        for tool_name, arguments in calls:
            summarized = _call(mcp, tool_name, arguments)
            self.assertTrue(summarized["ok"], tool_name)
            self.assertEqual(summarized["data"]["boundary"], "tool_result_data_only")
            self.assertIn("handle", summarized["memory"])

        records = _call(mcp, "ogc_proxy_memory_list", {})
        self.assertEqual(len(records["records"]), 4)

        raw = _call(
            mcp,
            "ogc_features_list_collections",
            {"response_mode": "raw"},
        )
        self.assertEqual(raw["data"], collections_payload)
        self.assertNotIn("memory", raw)

    def test_jobs_get_results_defaults_to_summary_and_stores_full_payload(self) -> None:
        full_result = {
            "outputs": {
                "Result": {
                    "type": "FeatureCollection",
                    "features": [{"id": str(i), "geometry": {"type": "Point"}} for i in range(50)],
                }
            }
        }

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/jobs/42/results":
                return httpx.Response(200, json=full_result)
            return httpx.Response(404, json={})

        with tempfile.TemporaryDirectory() as directory:
            path = _write_config(directory)
            mcp = create_mcp_server(path, transport=httpx.MockTransport(handler))

        summarized = _call(mcp, "ogc_jobs_get_results", {"job_id": "42"})
        self.assertTrue(summarized["ok"])
        self.assertIn("handle", summarized["memory"])
        self.assertEqual(summarized["data"]["boundary"], "tool_result_data_only")

        # The full payload must still be retrievable behind the handle.
        records = _call(mcp, "ogc_proxy_memory_list", {})
        self.assertEqual(len(records["records"]), 1)
        self.assertEqual(records["records"][0]["handle"], summarized["memory"]["handle"])

        raw = _call(mcp, "ogc_jobs_get_results", {"job_id": "42", "response_mode": "raw"})
        self.assertEqual(raw["data"], full_result)
        self.assertNotIn("memory", raw)

    def test_proxy_execute_plan_defaults_to_summary(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/processes":
                return httpx.Response(200, json={"processes": [{"id": "Delaunay"}]})
            if request.url.path == "/processes/Delaunay" and request.method == "GET":
                return httpx.Response(200, json={"id": "Delaunay", "inputs": {}})
            if request.url.path == "/conformance":
                return httpx.Response(200, json={"conformsTo": []})
            if request.url.path == "/processes/Delaunay/execution":
                return httpx.Response(200, json={"result": "ok", "extra": "payload"})
            return httpx.Response(404, json={})

        with tempfile.TemporaryDirectory() as directory:
            path = _write_config(directory)
            mcp = create_mcp_server(path, transport=httpx.MockTransport(handler))

        created = _call(
            mcp,
            "ogc_proxy_create_plan",
            {
                "plan_request_json": json.dumps(
                    {
                        "operation": "process_execute",
                        "process_id": "Delaunay",
                        "execute_request": {"inputs": {}},
                    }
                )
            },
        )
        self.assertTrue(created["confirmation_required"])
        plan_id = created["plan"]["plan_id"]

        _call(mcp, "ogc_proxy_confirm_plan", {"plan_id": plan_id, "approved": True})
        executed = _call(mcp, "ogc_proxy_execute_plan", {"plan_id": plan_id})

        self.assertTrue(executed["ok"])
        self.assertIn("handle", executed["memory"])
        self.assertEqual(executed["data"]["boundary"], "tool_result_data_only")


class CreatePlanInputValidationTests(unittest.TestCase):
    """Item #4 exercised through the actual ogc_proxy_create_plan tool."""

    def test_create_plan_flags_missing_required_input_through_the_tool_surface(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/processes":
                return httpx.Response(200, json={"processes": [{"id": "Delaunay"}]})
            if request.url.path == "/processes/Delaunay" and request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "id": "Delaunay",
                        "inputs": {
                            "InputPoints": {"title": "Input points", "minOccurs": 1, "schema": {"type": "string"}}
                        },
                    },
                )
            return httpx.Response(404, json={})

        with tempfile.TemporaryDirectory() as directory:
            path = _write_config(directory)
            mcp = create_mcp_server(path, transport=httpx.MockTransport(handler))

        created = _call(
            mcp,
            "ogc_proxy_create_plan",
            {
                "plan_request_json": json.dumps(
                    {
                        "operation": "process_execute",
                        "process_id": "Delaunay",
                        "execute_request": {"inputs": {}},
                    }
                )
            },
        )

        self.assertFalse(created["confirmation_required"])
        self.assertEqual(created["plan"]["status"], "needs_resolution")
        self.assertEqual(created["plan"]["unresolved"][0]["field"], "inputs.InputPoints")


if __name__ == "__main__":
    unittest.main()
