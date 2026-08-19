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


class ToolContractParityTests(unittest.TestCase):
    def test_machine_readable_contract_matches_registered_tool_surface(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = _write_config(
                directory,
                {"policy": {"expose_direct_execution_tools": True}},
            )
            mcp = create_mcp_server(path)

        registered_names = {tool.name for tool in asyncio.run(mcp.list_tools())}
        contract_path = Path(__file__).parents[1] / "spec" / "ogc-mcp-tool-contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract_names = {tool["name"] for tool in contract["tools"]}

        self.assertEqual(contract_names, registered_names)


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
        # Confirmation-gated proxy tools remain available; state-changing
        # interoperability tools stay absent unless explicitly enabled.
        self.assertIn("ogc_proxy_create_plan", names)
        self.assertIn("ogc_proxy_confirm_plan", names)
        self.assertIn("ogc_proxy_execute_plan", names)
        self.assertNotIn("ogc_jobs_dismiss", names)

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
        self.assertIn("ogc_jobs_dismiss", names)

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
        self.assertEqual(
            executed["output_manifest"]["execution"]["planId"],
            plan_id,
        )
        self.assertNotIn(
            "data",
            next(
                representation
                for representation in executed["output_manifest"]["outputs"][0][
                    "representations"
                ]
                if representation["role"] == "original"
            ),
        )


class ArtifactRetrievalToolTests(unittest.TestCase):
    def test_retrieves_canonical_artifact_without_exposing_upstream_url(self) -> None:
        feature_collection = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "Example"},
                    "geometry": {"type": "Point", "coordinates": [7.0, 52.0]},
                }
            ],
        }

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/processes/Example/execution":
                return httpx.Response(200, json=feature_collection)
            return httpx.Response(404, json={})

        with tempfile.TemporaryDirectory() as directory:
            path = _write_config(
                directory,
                {"policy": {"expose_direct_execution_tools": True}},
            )
            mcp = create_mcp_server(path, transport=httpx.MockTransport(handler))

        executed = _call(
            mcp,
            "ogc_processes_execute",
            {
                "process_id": "Example",
                "execute_request_json": "{\"inputs\": {}}",
                "response_mode": "raw",
            },
        )
        canonical = next(
            representation
            for representation in executed["output_manifest"]["outputs"][0][
                "representations"
            ]
            if representation["role"] == "canonical"
        )
        self.assertNotIn("data", canonical)

        retrieved = _call(
            mcp,
            "ogc_proxy_artifact_retrieve",
            {"handle": canonical["handle"]},
        )
        self.assertTrue(retrieved["ok"])
        self.assertEqual(retrieved["artifact"]["mediaType"], "application/geo+json")
        self.assertEqual(retrieved["artifact"]["encoding"], "identity")
        self.assertEqual(retrieved["artifact"]["data"], feature_collection)
        self.assertEqual(retrieved["data"], feature_collection)
        self.assertNotIn("href", retrieved["artifact"])

    def test_rejects_non_artifact_handle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            mcp = create_mcp_server(_write_config(directory))
        result = _call(
            mcp,
            "ogc_proxy_artifact_retrieve",
            {"handle": "mem_not_an_artifact"},
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid_argument")


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

    def test_unit_ambiguity_uses_structured_clarification_and_updates_in_place(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/processes/Buffer" and request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "id": "Buffer",
                        "inputs": {
                            "BufferDistance": {
                                "title": "Buffer distance",
                                "minOccurs": 1,
                                "schema": {"type": "number"},
                            }
                        },
                    },
                )
            return httpx.Response(404, json={})

        with tempfile.TemporaryDirectory() as directory:
            mcp = create_mcp_server(
                _write_config(directory),
                transport=httpx.MockTransport(handler),
            )

        execute_request = {"inputs": {"BufferDistance": 0.5}}
        created = _call(
            mcp,
            "ogc_proxy_create_plan",
            {
                "plan_request_json": json.dumps(
                    {
                        "operation": "process_execute",
                        "process_id": "Buffer",
                        "execute_request": execute_request,
                    }
                )
            },
        )

        self.assertTrue(created["resolution_required"])
        clarification = created["clarification_request"]
        self.assertTrue(clarification["blocking"])
        self.assertEqual(clarification["scope"], "execution")
        self.assertEqual(clarification["issues"][0]["kind"], "unit")
        self.assertEqual(
            clarification["issues"][0]["fieldPath"],
            "inputs.BufferDistance",
        )
        try:
            import jsonschema
        except ImportError:
            jsonschema = None
        if jsonschema is not None:
            schema_path = (
                Path(__file__).resolve().parents[2]
                / "spec"
                / "ogc-clarification-request.schema.json"
            )
            jsonschema.Draft7Validator(
                json.loads(schema_path.read_text(encoding="utf-8"))
            ).validate(clarification)

        updated = _call(
            mcp,
            "ogc_proxy_update_plan",
            {
                "plan_id": created["plan"]["plan_id"],
                "execute_request_json": json.dumps(execute_request),
                "input_context_json": json.dumps(
                    {
                        "BufferDistance": {
                            "origin": "user",
                            "unit": "server-native-unspecified",
                            "confirmed": True,
                            "note": "User explicitly accepted the server ambiguity.",
                        }
                    }
                ),
            },
        )
        self.assertFalse(updated["resolution_required"])
        self.assertTrue(updated["confirmation_required"])
        self.assertEqual(
            updated["confirmation_prompt"]["input_context"]["BufferDistance"]["unit"],
            "server-native-unspecified",
        )
        self.assertEqual(updated["plan"]["plan_id"], created["plan"]["plan_id"])


if __name__ == "__main__":
    unittest.main()
