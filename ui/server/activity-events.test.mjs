import assert from "node:assert/strict";
import test from "node:test";
import {
  activityResultPreview,
  compactToolResult,
  eventTiming,
  safeToolArguments,
  summarizeToolOutcome,
  summarizeToolPurpose,
} from "./activity-events.mjs";

test("safeToolArguments redacts credentials and decodes JSON arguments for display", () => {
  const safe = safeToolArguments({
    server_id: "process-server",
    execute_request_json: JSON.stringify({
      inputs: {
        distance: 750,
        headers: {
          authorization: "Bearer top-secret",
          api_key: "private-key",
        },
      },
    }),
    href: "https://example.test/items?token=secret-value&f=json",
  });

  assert.deepEqual(safe.execute_request_json, {
    inputs: {
      distance: 750,
      headers: {
        authorization: "[redacted]",
        api_key: "[redacted]",
      },
    },
  });
  assert.equal(safe.href, "https://example.test/items?token=[redacted]&f=json");
  assert.equal(JSON.stringify(safe).includes("top-secret"), false);
  assert.equal(JSON.stringify(safe).includes("private-key"), false);
  assert.equal(JSON.stringify(safe).includes("secret-value"), false);
});

test("summarizeToolPurpose explains discovery, validation, approval, and retrieval calls", () => {
  assert.equal(
    summarizeToolPurpose("ogc_processes_list", {
      server_id: "geolabs",
      search_text: "buffer",
    }),
    "Search on “geolabs” for processes matching “buffer”.",
  );
  assert.equal(
    summarizeToolPurpose("ogc_proxy_create_plan", {
      plan_request_json: JSON.stringify({ process_id: "Buffer" }),
    }),
    "Validate a human-confirmed execution plan for “Buffer”.",
  );
  assert.equal(
    summarizeToolPurpose("ogc_proxy_confirm_plan", {
      plan_id: "plan-42",
      approved: true,
    }),
    "Record the user’s explicit approval for plan “plan-42”.",
  );
  assert.equal(
    summarizeToolPurpose("ogc_jobs_get_results", {
      server_id: "geolabs",
      job_id: "job-7",
    }),
    "Retrieve the completed outputs for background job “job-7” on “geolabs”.",
  );
});

test("summarizeToolOutcome reports counts and human-in-the-loop state", () => {
  assert.equal(
    summarizeToolOutcome("ogc_features_get_items", {
      ok: true,
      server: { title: "Demo Features" },
      data: {
        boundary: "tool_result_data_only",
        summary: { type: "FeatureCollection", count: 4, truncated: false },
      },
    }),
    "4 features returned from Demo Features.",
  );
  assert.equal(
    summarizeToolOutcome("ogc_proxy_create_plan", {
      ok: true,
      workflow: { status: "needs_resolution" },
      resolution_required: true,
      plan: { unresolved: [{ field: "distance" }] },
    }),
    "Plan needs 1 user input before approval.",
  );
  assert.equal(
    summarizeToolOutcome("ogc_proxy_update_plan", {
      ok: true,
      workflow: { status: "ready_for_confirmation" },
      confirmation_required: true,
    }),
    "Plan validated and ready for explicit user approval.",
  );
});

test("summarizeToolOutcome keeps execution, retrieval, interpretation, and map readiness distinct", () => {
  const manifest = {
    execution: { state: "succeeded" },
    outputs: [{
      retrieval: { state: "resolving" },
      interpretation: { state: "pending" },
      presentations: [{ kind: "map", state: "preparing" }],
    }],
  };
  assert.equal(
    summarizeToolOutcome("ogc_jobs_get_results", { ok: true }, false, manifest),
    "Execution succeeded; 0/1 output retrieved, 0/1 interpreted, 0/1 map-ready.",
  );
  const ready = structuredClone(manifest);
  ready.outputs[0].retrieval.state = "retrieved";
  ready.outputs[0].interpretation.state = "recognized";
  ready.outputs[0].presentations[0].state = "ready";
  assert.equal(
    summarizeToolOutcome("ogc_jobs_get_results", { ok: true }, false, ready),
    "Execution succeeded; 1/1 output retrieved, 1/1 interpreted, 1/1 map-ready.",
  );
});

test("summarizeToolOutcome redacts secrets from failures", () => {
  const summary = summarizeToolOutcome("ogc_processes_list", {
    ok: false,
    error: {
      message: "Request failed for https://example.test/processes?api_key=do-not-show",
    },
  }, true);

  assert.equal(summary.includes("do-not-show"), false);
  assert.match(summary, /api_key=\[redacted\]/);
});

test("compactToolResult keeps useful result structure without full feature payloads", () => {
  const compact = compactToolResult({
    ok: true,
    operation: "features.get_items",
    server: {
      id: "demo",
      title: "Demo Features",
      base_url: "https://example.test",
    },
    request: { method: "GET", path: "/collections/lakes/items" },
    response: {
      status_code: 200,
      content_type: "application/geo+json",
      headers: { authorization: "Bearer hidden" },
    },
    data: {
      boundary: "tool_result_data_only",
      summary: {
        type: "FeatureCollection",
        count: 1,
        items: [{ id: "lake-1", "geometry.type": "Polygon" }],
        truncated: false,
      },
    },
  });

  assert.deepEqual(compact.server, { id: "demo", title: "Demo Features" });
  assert.deepEqual(compact.response, {
    status_code: 200,
    content_type: "application/geo+json",
    location: undefined,
  });
  assert.equal(compact.data.summary.count, 1);
  assert.equal(JSON.stringify(compact).includes("base_url"), false);
  assert.equal(JSON.stringify(compact).includes("Bearer hidden"), false);
});

test("activity previews are pretty, bounded, and credential-safe", () => {
  const preview = activityResultPreview({
    ok: false,
    error: {
      message: "Bad request",
      authorization: "Bearer secret-value",
    },
  });

  assert.match(preview, /\n/);
  assert.match(preview, /\[redacted\]/);
  assert.equal(preview.includes("secret-value"), false);
  assert.ok(activityResultPreview({ value: "x".repeat(4_000) }).length <= 1_601);
});

test("eventTiming emits stable ISO timestamps and turn-relative duration", () => {
  assert.deepEqual(eventTiming(1_000, 1_425), {
    timestamp: "1970-01-01T00:00:01.425Z",
    elapsedMs: 425,
  });
  assert.equal(eventTiming(2_000, 1_000).elapsedMs, 0);
});
