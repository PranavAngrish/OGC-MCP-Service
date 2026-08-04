import assert from "node:assert/strict";
import test from "node:test";
import { isModelCallableTool, modelVisibleMcpTools } from "./tool-policy.mjs";

test("renderer retrieval and explicit human decisions are hidden from the model", () => {
  const tools = [
    { name: "ogc_processes_list" },
    { name: "ogc_proxy_artifact_retrieve" },
    { name: "ogc_proxy_confirm_plan" },
    { name: "ogc_jobs_get_results" },
  ];
  assert.deepEqual(
    modelVisibleMcpTools(tools).map((tool) => tool.name),
    ["ogc_processes_list", "ogc_jobs_get_results"],
  );
  assert.equal(isModelCallableTool("ogc_proxy_artifact_retrieve"), false);
  assert.equal(isModelCallableTool("ogc_proxy_confirm_plan"), false);
  assert.equal(isModelCallableTool("ogc_processes_list"), true);
});
