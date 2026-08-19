import assert from "node:assert/strict";
import test from "node:test";
import {
  coordinateStrippedSummary,
  modelToolResultText,
} from "./model-output.mjs";

test("bounded discovery summaries preserve useful facts while removing spatial values", () => {
  const payload = {
    ok: true,
    collections: [{
      id: "lakes",
      title: "Large Lakes",
      count: 12,
      api_key: "secret",
      bbox: [-180, -90, 180, 90],
      geometry: { type: "Point", coordinates: [77.59, 12.97] },
    }],
  };
  const output = modelToolResultText({
    toolName: "ogc_features_list_collections",
    payload,
    rawOutput: JSON.stringify(payload),
  });
  assert.match(output, /"id":"lakes"/);
  assert.match(output, /"title":"Large Lakes"/);
  assert.match(output, /"count":12/);
  assert.equal(output.includes("[spatial value omitted]"), true);
  assert.equal(output.includes("77.59"), false);
  assert.equal(output.includes("12.97"), false);
  assert.equal(output.includes("secret"), false);
});

test("validated feature queries preserve bounded coordinate-free fact rows", () => {
  const rows = Array.from({ length: 38 }, (_, index) => ({
    name: `Country ${index + 1}`,
    area_km2: index + 1,
  }));
  const payload = {
    ok: true,
    data: {
      facts: { columns: ["name", "area_km2"], rows, retrievedRows: 38, truncated: false },
      evidence: { safeToAnswer: true, complete: true },
    },
  };
  const output = modelToolResultText({
    toolName: "ogc_features_query",
    payload,
    rawOutput: JSON.stringify(payload),
  });
  assert.match(output, /Country 38/);
  assert.equal(output.includes("more items"), false);
});

test("memory summaries keep feature IDs and properties but strip coordinates and numeric arrays", () => {
  const summary = coordinateStrippedSummary({
    data: {
      type: "FeatureCollection",
      features: [{
        id: "lake-1",
        properties: { name: "Lake Winnipeg", score: 0.8 },
        geometry: { type: "Point", coordinates: [-97.2, 52.1] },
      }],
      samples: [1, 2, 3],
    },
  });
  const output = JSON.stringify(summary);
  assert.match(output, /lake-1/);
  assert.match(output, /Lake Winnipeg/);
  assert.match(output, /"score":0.8/);
  assert.equal(output.includes("-97.2"), false);
  assert.match(output, /numeric array omitted/);
});

test("process descriptions preserve spatially named schema IDs while omitting runtime examples", () => {
  const payload = {
    ok: true,
    data: {
      id: "buffer",
      title: "Buffer",
      inputs: {
        geometry: {
          title: "Input geometry",
          schema: {
            type: "object",
            properties: {
              coordinates: {
                type: "array",
                items: { type: "number" },
                minItems: 2,
              },
              x: { type: "number", description: "Horizontal component" },
              y: { type: "number", description: "Vertical component" },
            },
            required: ["coordinates"],
          },
          example: {
            type: "Point",
            coordinates: [77.59, 12.97],
          },
        },
        bbox: {
          title: "Area of interest",
          schema: {
            type: "array",
            items: { type: "number" },
            minItems: 4,
            maxItems: 4,
          },
        },
        x: { schema: { type: "number" } },
        y: { schema: { type: "number" } },
        coordinates: { schema: { type: "string", format: "wkt" } },
      },
    },
  };
  const output = modelToolResultText({
    toolName: "ogc_processes_describe",
    payload,
    rawOutput: JSON.stringify(payload),
  });
  assert.match(output, /"geometry":\{"title":"Input geometry"/);
  assert.match(output, /"bbox":\{"title":"Area of interest"/);
  assert.match(output, /"x":\{"schema":\{"type":"number"\}\}/);
  assert.match(output, /"y":\{"schema":\{"type":"number"\}\}/);
  assert.match(output, /"coordinates":\{"schema":\{"type":"string","format":"wkt"\}\}/);
  assert.match(output, /"required":\["coordinates"\]/);
  assert.match(output, /"coordinates":\{"type":"array","items":\{"type":"number"\},"minItems":2\}/);
  assert.equal(
    output.includes('"example":{"type":"Point","coordinates":"[spatial value omitted]"}'),
    true,
  );
  assert.equal(output.includes("77.59"), false);
  assert.equal(output.includes("12.97"), false);
});

test("runtime features remain coordinate-free even when schema preservation exists for process descriptions", () => {
  const payload = {
    ok: true,
    data: {
      type: "Feature",
      id: "station-1",
      geometry: {
        type: "Point",
        coordinates: [77.59, 12.97],
      },
      properties: {
        title: "Station 1",
        x: 77.59,
        y: 12.97,
      },
      bbox: [77.59, 12.97, 77.59, 12.97],
    },
  };
  const output = modelToolResultText({
    toolName: "ogc_features_get_item",
    payload,
    rawOutput: JSON.stringify(payload),
  });
  assert.match(output, /station-1/);
  assert.match(output, /Station 1/);
  assert.equal(output.includes("77.59"), false);
  assert.equal(output.includes("12.97"), false);
  assert.match(output, /spatial value omitted/);
});

test("capital coordinate property aliases are stripped from model summaries", () => {
  const output = JSON.stringify(coordinateStrippedSummary({
    name: "Example",
    caplat: 52.5,
    caplong: 13.4,
  }));
  assert.match(output, /Example/);
  assert.equal(output.includes("52.5"), false);
  assert.equal(output.includes("13.4"), false);
});

test("strict process outputs expose manifest facts but never raw vector coordinates", () => {
  const manifest = {
    schemaVersion: "ogc-output-manifest/1",
    manifestId: "manifest-vector",
    execution: { state: "succeeded", serverId: "process-server" },
    overallState: "ready",
    outputs: [{
      id: "result",
      title: "Result",
      status: "ready",
      retrieval: { state: "retrieved", source: "inline" },
      interpretation: { state: "recognized", semanticType: "vector", featureCount: 1 },
      representations: [{
        id: "result-preview",
        role: "canonical",
        mediaType: "application/geo+json",
        data: {
          type: "Feature",
          properties: { name: "A" },
          geometry: { type: "Point", coordinates: [77.59, 12.97] },
        },
      }],
      presentations: [{ id: "result-map", kind: "map", state: "ready", artifactRef: "result-preview" }],
      provenance: { serverId: "process-server" },
    }],
  };
  const output = modelToolResultText({
    toolName: "ogc_jobs_get_results",
    payload: {
      ok: true,
      data: { jobID: "job-42", status: "successful", coordinates: [77.59, 12.97] },
      response: { status_code: 200, location: "https://example.invalid/result" },
    },
    rawOutput: "{\"coordinates\":[77.59,12.97]}",
    artifacts: {
      manifest,
      modelContext: {
        authority: "gateway_verified_output_manifest",
        manifestId: manifest.manifestId,
        execution: manifest.execution,
        overallState: manifest.overallState,
        outputs: [{
          id: "result",
          status: "ready",
          retrieval: { state: "retrieved", source: "inline" },
          interpretation: { state: "recognized", semanticType: "vector", featureCount: 1 },
          presentations: [{ kind: "map", state: "ready" }],
        }],
      },
    },
  });
  assert.match(output, /GATEWAY VERIFIED OUTPUT STATE/);
  assert.match(output, /"semanticType":"vector"/);
  assert.match(output, /"jobId":"job-42"/);
  assert.equal(output.includes("77.59"), false);
  assert.equal(output.includes("12.97"), false);
  assert.equal(output.includes("example.invalid"), false);
});

test("verified process scalar values remain visible to the model", () => {
  const manifest = {
    schemaVersion: "ogc-output-manifest/1",
    manifestId: "manifest-scalar",
    execution: { state: "succeeded", serverId: "process-server" },
    overallState: "ready",
    outputs: [{
      id: "temperature",
      title: "Mean temperature",
      status: "ready",
      retrieval: { state: "retrieved", source: "inline" },
      interpretation: {
        state: "recognized",
        semanticType: "scalar",
        units: [{ quantity: "temperature", value: "°C", status: "declared" }],
      },
      representations: [{
        id: "temperature-value",
        role: "canonical",
        mediaType: "text/plain",
        data: 18.4,
      }],
      presentations: [{ id: "temperature-metric", kind: "metric", state: "ready", artifactRef: "temperature-value" }],
      provenance: { serverId: "process-server" },
    }],
  };
  const output = modelToolResultText({
    toolName: "ogc_processes_execute",
    payload: { ok: true },
    rawOutput: "{\"value\":18.4}",
    artifacts: {
      manifest,
      modelContext: {
        authority: "gateway_verified_output_manifest",
        manifestId: manifest.manifestId,
        execution: manifest.execution,
        overallState: "ready",
        outputs: [],
      },
    },
  });
  assert.match(output, /verifiedScalarOutputs/);
  assert.match(output, /18.4/);
  assert.match(output, /Mean temperature/);
});

test("one-key primitive objects classified as scalars remain model-visible", () => {
  const manifest = {
    schemaVersion: "ogc-output-manifest/1",
    manifestId: "manifest-object-scalar",
    execution: { state: "succeeded", serverId: "process-server" },
    overallState: "ready",
    outputs: [{
      id: "feature-count",
      title: "Feature count",
      status: "ready",
      retrieval: { state: "retrieved", source: "inline" },
      interpretation: { state: "recognized", semanticType: "scalar" },
      representations: [{
        id: "feature-count-value",
        role: "canonical",
        mediaType: "application/json",
        data: { count: 42 },
      }],
      presentations: [{
        id: "feature-count-metric",
        kind: "metric",
        state: "ready",
        artifactRef: "feature-count-value",
      }],
      provenance: { serverId: "process-server" },
    }],
  };
  const output = modelToolResultText({
    toolName: "ogc_processes_execute",
    payload: { ok: true },
    rawOutput: "{\"count\":42}",
    artifacts: {
      manifest,
      modelContext: {
        authority: "gateway_verified_output_manifest",
        manifestId: manifest.manifestId,
        execution: manifest.execution,
        overallState: "ready",
        outputs: [],
      },
    },
  });
  assert.match(output, /verifiedScalarOutputs/);
  assert.match(output, /"value":\{"count":42\}/);
});

test("strict preparation failures withhold the raw process body", () => {
  const output = modelToolResultText({
    toolName: "ogc_jobs_get_results",
    payload: { ok: true, data: { coordinates: [77.59, 12.97] } },
    rawOutput: "raw secret coordinates 77.59 12.97",
    preparationFailed: true,
  });
  assert.match(output, /raw output was withheld/);
  assert.equal(output.includes("77.59"), false);
  assert.equal(output.includes("12.97"), false);
});
