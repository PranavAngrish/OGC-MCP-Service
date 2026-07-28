import assert from "node:assert/strict";
import test from "node:test";
import {
  findMemoryHandle,
  prepareMapArtifact,
  structuredToolPayload,
} from "./map-artifacts.mjs";

const pointCollection = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      properties: { name: "Station A" },
      geometry: { type: "Point", coordinates: [77.59, 12.97] },
    },
  ],
};

test("structuredToolPayload prefers structured content and parses full text fallback", () => {
  const structured = { ok: true, data: pointCollection };
  assert.equal(structuredToolPayload({ structuredContent: structured }), structured);
  assert.deepEqual(
    structuredToolPayload({ content: [{ type: "text", text: JSON.stringify(structured) }] }),
    structured,
  );
  assert.equal(structuredToolPayload({ content: [{ type: "text", text: "not JSON" }] }), null);
});

test("findMemoryHandle accepts only the canonical top-level proxy handle", () => {
  const handle = "mem_1234567890abcdef1234567890abcdef";
  assert.equal(findMemoryHandle({ memory: { handle } }), handle);
  assert.equal(findMemoryHandle({ data: { memory: { handle } } }), "");
  assert.equal(findMemoryHandle({ memory: { handle: "mem_untrusted" } }), "");
});

test("prepareMapArtifact hydrates memory without mutating the original result", async () => {
  const original = {
    structuredContent: {
      ok: true,
      data: { type: "FeatureCollection", count: 1 },
      memory: { handle: "mem_1234567890abcdef1234567890abcdef" },
    },
  };
  const calls = [];
  const artifact = await prepareMapArtifact({
    toolName: "ogc_jobs_get_results",
    args: { job_id: "42" },
    activityId: "tool-1",
    result: original,
    callTool: async (name, args) => {
      calls.push({ name, args });
      return {
        structuredContent: {
          ok: true,
          operation: "proxy.memory.retrieve",
          data: { outputs: { result: pointCollection } },
        },
      };
    },
  });

  assert.deepEqual(calls, [{
    name: "ogc_proxy_memory_retrieve",
    args: { handle: "mem_1234567890abcdef1234567890abcdef", offset: 0, limit: 1_000 },
  }]);
  assert.equal(artifact.id, "job-default-42-map");
  assert.equal(artifact.title, "Job 42 result");
  assert.equal(artifact.stats.featureCount, 1);
  assert.deepEqual(original.structuredContent.data, { type: "FeatureCollection", count: 1 });
});

test("prepareMapArtifact uses the resolved server identity and marks partial retrievals", async () => {
  const artifact = await prepareMapArtifact({
    toolName: "ogc_proxy_memory_retrieve",
    args: { job_id: "42", server_id: "requested-server" },
    activityId: "tool-2",
    result: {
      structuredContent: {
        ok: true,
        server: { id: "resolved-server" },
        data: pointCollection,
        has_more: true,
      },
    },
    callTool: async () => assert.fail("unexpected hydration"),
  });

  assert.equal(artifact.id, "tool-2-map");
  assert.equal(artifact.stats.truncated, true);
  assert.equal(artifact.warnings.some((item) => item.includes("first 1,000 features")), true);

  const jobArtifact = await prepareMapArtifact({
    toolName: "ogc_jobs_get_results",
    args: { job_id: "42", server_id: "requested-server" },
    activityId: "tool-3",
    result: {
      structuredContent: {
        ok: true,
        server: { id: "resolved-server" },
        data: pointCollection,
      },
    },
    callTool: async () => assert.fail("unexpected hydration"),
  });
  assert.equal(jobArtifact.id, "job-resolved-server-42-map");
});

test("prepareMapArtifact does not render a summary when memory hydration fails", async () => {
  const artifact = await prepareMapArtifact({
    toolName: "ogc_jobs_get_results",
    args: { job_id: "42" },
    activityId: "tool-4",
    result: {
      structuredContent: {
        ok: true,
        data: { bbox: [76, 12, 78, 14] },
        memory: { handle: "mem_1234567890abcdef1234567890abcdef" },
      },
    },
    callTool: async () => ({ isError: true, structuredContent: { ok: false } }),
  });
  assert.equal(artifact, null);
});

test("prepareMapArtifact ignores errors and non-map tools", async () => {
  const never = async () => assert.fail("unexpected hydration");
  assert.equal(await prepareMapArtifact({
    toolName: "ogc_jobs_get_status",
    activityId: "tool-1",
    result: { structuredContent: { ok: true, data: pointCollection } },
    callTool: never,
  }), null);
  assert.equal(await prepareMapArtifact({
    toolName: "ogc_jobs_get_results",
    activityId: "tool-2",
    result: { isError: true, structuredContent: { ok: false } },
    callTool: never,
  }), null);
});
