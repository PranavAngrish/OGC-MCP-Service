import assert from "node:assert/strict";
import test from "node:test";
import {
  appendVerifiedResultContext,
  clearResultArtifactSession,
  parseEmbeddedGml,
  prepareResultArtifacts,
  retrieveSessionArtifact,
} from "./result-artifacts.mjs";

const structured = (payload) => ({ structuredContent: payload });

const pointCollection = {
  type: "FeatureCollection",
  features: [{
    type: "Feature",
    properties: { name: "Station A" },
    geometry: { type: "Point", coordinates: [77.59, 12.97] },
  }],
};

const gml = `<?xml version="1.0" encoding="utf-8"?>
<ogr:FeatureCollection xmlns:ogr="http://ogr.maptools.org/" xmlns:gml="http://www.opengis.net/gml">
  <gml:featureMember>
    <ogr:Result fid="Result.0">
      <ogr:geometryProperty>
        <gml:Polygon srsName="EPSG:4326">
          <gml:outerBoundaryIs><gml:LinearRing>
            <gml:coordinates>-99.4,50 -95.7,50 -95.7,54.8 -99.4,54.8 -99.4,50</gml:coordinates>
          </gml:LinearRing></gml:outerBoundaryIs>
        </gml:Polygon>
      </ogr:geometryProperty>
      <ogr:name>Lake Winnipeg buffer</ogr:name>
    </ogr:Result>
  </gml:featureMember>
</ogr:FeatureCollection>`;

test("bounded GML parser rejects unsafe XML and converts a Simple Features polygon", () => {
  assert.equal(parseEmbeddedGml("<!DOCTYPE foo><gml:Point><gml:pos>1 2</gml:pos></gml:Point>").ok, false);
  const parsed = parseEmbeddedGml(gml);
  assert.equal(parsed.ok, true);
  assert.equal(parsed.data.features.length, 1);
  assert.equal(parsed.data.features[0].geometry.type, "Polygon");
  assert.equal(parsed.data.features[0].properties.name, "Lake Winnipeg buffer");
  assert.equal(parsed.crs, "EPSG:4326");
});

test("legacy nested format.mediaType GML becomes one verified manifest and drawable map", async () => {
  const bundle = await prepareResultArtifacts({
    toolName: "ogc_jobs_get_results",
    args: { server_id: "geolabs-tb17", job_id: "job-42" },
    activityId: "tool-42",
    result: structured({
      ok: true,
      operation: "jobs.get_results",
      server: { id: "geolabs-tb17" },
      response: { status_code: 200, content_type: "application/json" },
      data: {
        Result: {
          value: gml,
          format: { mediaType: "text/xml", encoding: "utf-8" },
        },
      },
    }),
    callTool: async () => assert.fail("unexpected hydration"),
  });

  assert.equal(bundle.manifest.schemaVersion, "ogc-output-manifest/1");
  assert.equal(bundle.manifest.execution.state, "succeeded");
  assert.equal(bundle.manifest.overallState, "ready");
  assert.equal(bundle.manifest.outputs[0].retrieval.state, "retrieved");
  assert.equal(bundle.manifest.outputs[0].retrieval.declaredMediaType, "text/xml");
  assert.equal(bundle.manifest.outputs[0].retrieval.detectedMediaType, "application/gml+xml");
  assert.equal(bundle.manifest.outputs[0].interpretation.state, "recognized");
  assert.equal(bundle.manifest.outputs[0].interpretation.semanticType, "vector");
  assert.equal(bundle.manifest.outputs[0].interpretation.featureCount, 1);
  assert.equal(bundle.manifest.outputs[0].interpretation.crs.value, "OGC:CRS84");
  assert.equal(bundle.manifest.outputs[0].interpretation.crs.nativeValue, "EPSG:4326");
  assert.equal(bundle.manifest.outputs[0].presentations[0].state, "ready");
  assert.equal(bundle.manifest.outputs[0].presentations[0].artifactRef, "Result-canonical");
  assert.equal(bundle.manifest.outputs[0].representations[1].mediaType, "application/geo+json");
  assert.equal(bundle.manifest.outputs[0].representations[1].data.type, "FeatureCollection");
  assert.equal(bundle.visualization.id, "job-geolabs-tb17-job-42-map");
  assert.equal(bundle.visualization.layers.length, 1);
  assert.equal(bundle.visualization.stats.featureCount, 1);
  assert.ok(bundle.artifactEvents.some((event) => event.stage === "retrieval" && event.status === "complete"));
  assert.ok(bundle.artifactEvents.some((event) => event.stage === "presentation" && event.status === "complete"));
});

test("a JSON-string output wrapper still honors the nested representation media type", async () => {
  const bundle = await prepareResultArtifacts({
    toolName: "ogc_jobs_get_results",
    args: { job_id: "json-wrapper" },
    activityId: "tool-json-wrapper",
    result: structured({
      ok: true,
      server: { id: "legacy-server" },
      response: { status_code: 200, content_type: "application/json" },
      data: JSON.stringify({
        Result: {
          value: gml,
          format: { mediaType: "application/gml+xml" },
        },
      }),
    }),
    callTool: async () => assert.fail("unexpected hydration"),
  });
  assert.equal(bundle.manifest.outputs[0].retrieval.declaredMediaType, "application/gml+xml");
  assert.equal(bundle.manifest.outputs[0].interpretation.semanticType, "vector");
  assert.equal(bundle.visualization.stats.featureCount, 1);
});

test("an HTTP redirect remains an unresolved reference instead of a successful retrieval", async () => {
  const location = "http://outputs.example/temp/job-42.json?token=secret";
  const bundle = await prepareResultArtifacts({
    toolName: "ogc_jobs_get_results",
    args: { server_id: "process-server", job_id: "job-42" },
    activityId: "tool-redirect",
    result: structured({
      ok: true,
      server: { id: "process-server" },
      response: {
        status_code: 302,
        content_type: "text/html",
        location,
      },
      data: { summary: "<html><body>Moved</body></html>" },
    }),
    callTool: async () => assert.fail("the gateway must not fetch an arbitrary output URL"),
  });

  assert.equal(bundle.manifest.execution.state, "succeeded");
  assert.equal(bundle.manifest.overallState, "pending");
  assert.equal(bundle.manifest.outputs[0].status, "pending");
  assert.equal(bundle.manifest.outputs[0].retrieval.state, "resolving");
  assert.equal(bundle.manifest.outputs[0].retrieval.source, "reference");
  assert.equal(bundle.manifest.outputs[0].interpretation.state, "pending");
  assert.equal(bundle.manifest.outputs[0].presentations[0].state, "preparing");
  assert.equal(bundle.manifest.outputs[0].representations[0].href, undefined);
  assert.equal(JSON.stringify(bundle.modelContext).includes(location), false);
  assert.equal(bundle.visualization, null);
});

test("legacy output hrefs are neither fetched nor exposed as browser map layers", async () => {
  const calls = [];
  const bundle = await prepareResultArtifacts({
    toolName: "ogc_jobs_get_results",
    args: { job_id: "reference-output" },
    activityId: "tool-reference",
    result: structured({
      ok: true,
      server: { id: "legacy-server" },
      data: {
        result: {
          href: "https://untrusted.example/output.geojson?signature=secret",
          mediaType: "application/geo+json",
        },
      },
    }),
    callTool: async (...args) => calls.push(args),
  });
  assert.deepEqual(calls, []);
  assert.equal(bundle.manifest.overallState, "pending");
  assert.equal(bundle.manifest.outputs[0].retrieval.source, "reference");
  assert.equal(bundle.manifest.outputs[0].retrieval.state, "resolving");
  assert.equal(bundle.manifest.outputs[0].representations[0].href, undefined);
  assert.equal(JSON.stringify(bundle.manifest).includes("untrusted.example"), false);
  assert.equal(bundle.visualization, null);
});

test("canonical inline previews are normalized, kept bounded, and mapped without legacy guessing", async () => {
  const bundle = await prepareResultArtifacts({
    toolName: "ogc_jobs_get_results",
    args: { job_id: "canonical-1" },
    activityId: "tool-canonical",
    result: structured({
      ok: true,
      server: { id: "canonical-server" },
      output_manifest: {
        schemaVersion: "ogc-output-manifest/1",
        manifestId: "canonical-manifest",
        execution: { state: "succeeded", serverId: "canonical-server", jobId: "canonical-1" },
        overallState: "ready",
        outputs: [{
          id: "geometry",
          title: "Canonical geometry",
          status: "ready",
          retrieval: {
            state: "retrieved",
            source: "inline",
            declaredMediaType: "application/gml+xml",
            detectedMediaType: "application/geo+json",
          },
          interpretation: {
            state: "recognized",
            semanticType: "vector",
            format: "GeoJSON",
            crs: { status: "declared", value: "OGC:CRS84" },
            featureCount: 1,
            geometryTypes: ["Point"],
          },
          representations: [{
            id: "geometry-preview",
            role: "canonical",
            mediaType: "application/geo+json",
            data: pointCollection,
          }],
          presentations: [{
            id: "geometry-map",
            kind: "map",
            state: "ready",
            artifactRef: "geometry-preview",
          }],
          provenance: { serverId: "canonical-server", parser: "python-geojson" },
        }],
      },
    }),
    callTool: async () => assert.fail("unexpected hydration"),
  });

  assert.equal(bundle.manifest.manifestId, "job-canonical-server-canonical-1");
  assert.deepEqual(bundle.manifest.outputs[0].representations[0].data, pointCollection);
  assert.equal(bundle.manifest.outputs[0].presentations.find((item) => item.kind === "map").state, "ready");
  assert.equal(
    bundle.manifest.outputs[0].presentations.find((item) => item.kind === "map").artifactRef,
    "geometry-preview",
  );
  assert.equal(bundle.visualization.stats.featureCount, 1);
  const modelText = appendVerifiedResultContext("raw tool result", bundle.modelContext);
  assert.match(modelText, /GATEWAY VERIFIED OUTPUT STATE/);
  assert.match(modelText, /Do not claim an output was retrieved/);
});

test("canonical async submission and job results share one lifecycle manifest ID", async () => {
  const submission = await prepareResultArtifacts({
    toolName: "ogc_proxy_execute_plan",
    args: { plan_id: "plan-1" },
    activityId: "submit-call",
    result: structured({
      ok: true,
      server: { id: "process-server" },
      output_manifest: {
        schemaVersion: "ogc-output-manifest/1",
        manifestId: "python-submission-random-id",
        execution: {
          state: "submitted",
          serverId: "process-server",
          planId: "plan-1",
          jobId: "job-77",
        },
        overallState: "pending",
        outputs: [],
      },
    }),
    callTool: async () => assert.fail("unexpected hydration"),
  });
  const completed = await prepareResultArtifacts({
    toolName: "ogc_jobs_get_results",
    args: { server_id: "process-server", job_id: "job-77" },
    activityId: "result-call",
    result: structured({
      ok: true,
      server: { id: "process-server" },
      output_manifest: {
        schemaVersion: "ogc-output-manifest/1",
        manifestId: "python-results-random-id",
        execution: {
          state: "succeeded",
          serverId: "process-server",
          jobId: "job-77",
        },
        overallState: "ready",
        outputs: [{
          id: "count",
          title: "Count",
          status: "ready",
          retrieval: { state: "retrieved", source: "inline" },
          interpretation: {
            state: "recognized",
            semanticType: "scalar",
            crs: { status: "missing" },
          },
          representations: [{
            id: "count-value",
            role: "canonical",
            mediaType: "application/json",
            data: 42,
          }],
          presentations: [{
            id: "count-metric",
            kind: "metric",
            state: "ready",
            artifactRef: "count-value",
          }],
          provenance: { serverId: "process-server" },
        }],
      },
    }),
    callTool: async () => assert.fail("unexpected hydration"),
  });

  assert.equal(submission.manifest.manifestId, "job-process-server-job-77");
  assert.equal(completed.manifest.manifestId, submission.manifest.manifestId);
  assert.equal(completed.manifest.overallState, "ready");
});

test("canonical art handles are privately hydrated for rendering but coordinates stay out of model context", async () => {
  const handle = "art_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
  const calls = [];
  const bundle = await prepareResultArtifacts({
    toolName: "ogc_jobs_get_results",
    args: { job_id: "private-preview" },
    activityId: "tool-private-preview",
    result: structured({
      ok: true,
      server: { id: "canonical-server" },
      output_manifest: {
        schemaVersion: "ogc-output-manifest/1",
        manifestId: "private-preview-manifest",
        execution: { state: "succeeded", serverId: "canonical-server" },
        overallState: "ready",
        outputs: [{
          id: "geometry",
          title: "Geometry",
          status: "ready",
          retrieval: { state: "retrieved", source: "reference", detectedMediaType: "application/geo+json" },
          interpretation: {
            state: "recognized",
            semanticType: "vector",
            format: "application/geo+json",
            crs: { status: "declared", value: "OGC:CRS84" },
            featureCount: 1,
          },
          representations: [{
            id: "geometry-canonical",
            role: "canonical",
            mediaType: "application/geo+json",
            handle,
            sizeBytes: 200,
          }],
          presentations: [{
            id: "geometry-map",
            kind: "map",
            state: "ready",
            artifactRef: handle,
          }],
          provenance: { serverId: "canonical-server" },
        }],
      },
    }),
    callTool: async (name, args) => {
      calls.push({ name, args });
      return structured({
        ok: true,
        artifact: {
          handle,
          mediaType: "application/geo+json",
          role: "canonical",
          sizeBytes: 200,
          encoding: "identity",
        },
        data: pointCollection,
      });
    },
  });

  assert.deepEqual(calls, [{ name: "ogc_proxy_artifact_retrieve", args: { handle } }]);
  assert.deepEqual(bundle.manifest.outputs[0].representations[0].data, pointCollection);
  assert.equal(bundle.visualization.stats.featureCount, 1);
  assert.equal(
    bundle.manifest.outputs[0].presentations.find((item) => item.kind === "map").artifactRef,
    handle,
  );
  assert.equal(JSON.stringify(bundle.modelContext).includes("77.59"), false);
  assert.equal(JSON.stringify(bundle.modelContext).includes("12.97"), false);
});

test("canonical dangling presentation references are downgraded instead of replaced by visualization IDs", async () => {
  const bundle = await prepareResultArtifacts({
    toolName: "ogc_jobs_get_results",
    args: { job_id: "dangling-map" },
    activityId: "tool-dangling-map",
    result: structured({
      ok: true,
      server: { id: "canonical-server" },
      output_manifest: {
        schemaVersion: "ogc-output-manifest/1",
        manifestId: "dangling-map-manifest",
        execution: { state: "succeeded", serverId: "canonical-server" },
        overallState: "ready",
        outputs: [{
          id: "geometry",
          title: "Geometry",
          status: "ready",
          retrieval: { state: "retrieved", source: "inline" },
          interpretation: {
            state: "recognized",
            semanticType: "vector",
            crs: { status: "declared", value: "OGC:CRS84" },
            featureCount: 1,
          },
          representations: [{
            id: "real-preview",
            role: "canonical",
            mediaType: "application/geo+json",
            data: pointCollection,
          }],
          presentations: [{
            id: "geometry-map",
            kind: "map",
            state: "ready",
            artifactRef: "missing-preview",
          }],
          provenance: { serverId: "canonical-server" },
        }],
      },
    }),
    callTool: async () => assert.fail("unexpected hydration"),
  });
  const map = bundle.manifest.outputs[0].presentations.find((item) => item.kind === "map");
  assert.equal(map.state, "unavailable");
  assert.equal(map.artifactRef, undefined);
  assert.match(map.reason, /does not match a stored representation/);
  assert.equal(bundle.visualization, null);
});

test("canonical normalization drops invalid HTTP status and bounds unit strings", async () => {
  const oversized = "u".repeat(500);
  const bundle = await prepareResultArtifacts({
    toolName: "ogc_jobs_get_results",
    args: { job_id: "schema-bounds" },
    activityId: "tool-schema-bounds",
    result: structured({
      ok: true,
      server: { id: "schema-server" },
      output_manifest: {
        schemaVersion: "ogc-output-manifest/1",
        manifestId: "schema-bounds-manifest",
        execution: { state: "succeeded", serverId: "schema-server" },
        overallState: "ready",
        outputs: [{
          id: "metric",
          title: "Metric",
          status: "ready",
          retrieval: { state: "retrieved", source: "inline", httpStatus: 999 },
          interpretation: {
            state: "recognized",
            semanticType: "scalar",
            units: [{ quantity: oversized, value: oversized, status: "invalid" }],
          },
          representations: [{
            id: "metric-value",
            role: "canonical",
            mediaType: "text/plain",
            data: 42,
          }],
          presentations: [{
            id: "metric-view",
            kind: "metric",
            state: "ready",
            artifactRef: "metric-value",
          }],
          provenance: { serverId: "schema-server" },
        }],
      },
    }),
    callTool: async () => assert.fail("unexpected hydration"),
  });
  const output = bundle.manifest.outputs[0];
  assert.equal(output.retrieval.httpStatus, undefined);
  assert.equal(output.interpretation.units[0].quantity.length, 200);
  assert.equal(output.interpretation.units[0].value.length, 200);
  assert.equal(output.interpretation.units[0].status, "declared");
});

test("proxy-memory hydration failure is explicit and never renders a summary bbox", async () => {
  const bundle = await prepareResultArtifacts({
    toolName: "ogc_jobs_get_results",
    args: { job_id: "memory-1" },
    activityId: "tool-memory",
    result: structured({
      ok: true,
      data: { bbox: [76, 12, 78, 14] },
      memory: { handle: "mem_1234567890abcdef1234567890abcdef" },
    }),
    callTool: async () => structured({ ok: false, error: "expired" }),
  });

  assert.equal(bundle.manifest.overallState, "unavailable");
  assert.equal(bundle.manifest.outputs[0].retrieval.state, "failed");
  assert.equal(bundle.manifest.outputs[0].status, "failed");
  assert.match(bundle.manifest.outputs[0].retrieval.error.message, /could not be retrieved/);
  assert.equal(bundle.visualization, null);
});

test("opaque artifact downloads are session-scoped and retrieved only through the MCP artifact tool", async () => {
  const sessionId = "session-artifact-test";
  const handle = "art_1234567890abcdef1234567890abcdef";
  const bundle = await prepareResultArtifacts({
    toolName: "ogc_jobs_get_results",
    args: { job_id: "artifact-1" },
    activityId: "tool-artifact",
    sessionId,
    result: structured({
      ok: true,
      server: { id: "artifact-server" },
      output_manifest: {
        schemaVersion: "ogc-output-manifest/1",
        manifestId: "artifact-manifest",
        execution: { state: "succeeded", serverId: "artifact-server" },
        overallState: "ready",
        outputs: [{
          id: "report",
          title: "Report",
          status: "ready",
          retrieval: { state: "retrieved", source: "reference", detectedMediaType: "application/json" },
          interpretation: {
            state: "recognized",
            semanticType: "document",
            format: "application/json",
            crs: { status: "missing" },
          },
          representations: [{
            id: "report-original",
            role: "original",
            mediaType: "application/json",
            handle,
            sizeBytes: 12,
          }],
          presentations: [{
            id: "report-download",
            kind: "download",
            state: "ready",
            artifactRef: handle,
          }],
          provenance: { serverId: "artifact-server" },
        }],
      },
    }),
    callTool: async () => assert.fail("unexpected preparation call"),
  });
  assert.equal(
    bundle.manifest.outputs[0].representations[0].href,
    `/api/artifacts/${handle}?sessionId=${sessionId}`,
  );

  const calls = [];
  const retrieved = await retrieveSessionArtifact({
    sessionId,
    handle,
    callTool: async (name, args) => {
      calls.push({ name, args });
      return structured({
        ok: true,
        artifact: {
          handle,
          mediaType: "application/json",
          encoding: "identity",
          data: { value: 42 },
        },
      });
    },
  });
  assert.deepEqual(calls, [{ name: "ogc_proxy_artifact_retrieve", args: { handle } }]);
  assert.equal(retrieved.ok, true);
  assert.equal(retrieved.mediaType, "application/json");
  assert.equal(retrieved.data, "{\"value\":42}");

  const denied = await retrieveSessionArtifact({
    sessionId: "different-session",
    handle,
    callTool: async () => assert.fail("unregistered handles must not reach MCP"),
  });
  assert.equal(denied.status, 404);
  clearResultArtifactSession(sessionId);
});

test("one schema-maximum manifest never returns already-evicted artifact links", async () => {
  const sessionId = "maximum-artifact-session";
  const representations = Array.from({ length: 20 }, (_item, representationIndex) => {
    const numeric = representationIndex + 1;
    return {
      id: `representation-${numeric}`,
      role: "original",
      mediaType: "application/octet-stream",
      handle: `art_${numeric.toString(16).padStart(32, "0")}`,
    };
  });
  const outputs = Array.from({ length: 100 }, (_item, outputIndex) => ({
    id: `output-${outputIndex + 1}`,
    title: `Output ${outputIndex + 1}`,
    status: "ready",
    retrieval: { state: "retrieved", source: "reference" },
    interpretation: {
      state: "recognized",
      semanticType: "binary",
      crs: { status: "missing" },
    },
    representations: representations.map((representation, representationIndex) => {
      const numeric = outputIndex * 20 + representationIndex + 1;
      return {
        ...representation,
        id: `representation-${numeric}`,
        handle: `art_${numeric.toString(16).padStart(32, "0")}`,
      };
    }),
    presentations: [],
    provenance: { serverId: "canonical-server" },
  }));
  const bundle = await prepareResultArtifacts({
    toolName: "ogc_jobs_get_results",
    args: { server_id: "canonical-server", job_id: "maximum-artifacts" },
    activityId: "maximum-artifacts",
    sessionId,
    result: structured({
      ok: true,
      output_manifest: {
        schemaVersion: "ogc-output-manifest/1",
        manifestId: "maximum-artifacts",
        execution: { state: "succeeded", serverId: "canonical-server" },
        overallState: "ready",
        outputs,
      },
    }),
    callTool: async () => assert.fail("download-only originals should not be hydrated"),
  });
  const first = bundle.manifest.outputs[0].representations[0];
  const last = bundle.manifest.outputs.at(-1).representations.at(-1);
  assert.match(first.href, /^\/api\/artifacts\//);
  assert.match(last.href, /^\/api\/artifacts\//);

  for (const handle of [first.handle, last.handle]) {
    const retrieved = await retrieveSessionArtifact({
      sessionId,
      handle,
      callTool: async () => structured({
        ok: true,
        artifact: {
          handle,
          mediaType: "application/octet-stream",
          sizeBytes: 1,
        },
        data: "x",
      }),
    });
    assert.equal(retrieved.ok, true);
  }
  clearResultArtifactSession(sessionId);
});

test("recognized non-spatial outputs receive a presentation instead of silently returning null", async () => {
  const bundle = await prepareResultArtifacts({
    toolName: "ogc_jobs_get_results",
    args: { job_id: "table-1" },
    activityId: "tool-table",
    result: structured({
      ok: true,
      server: { id: "table-server" },
      data: {
        Result: {
          value: [{ place: "A", score: 2 }, { place: "B", score: 4 }],
          format: { mediaType: "application/json" },
        },
      },
    }),
    callTool: async () => assert.fail("unexpected hydration"),
  });
  assert.equal(bundle.manifest.overallState, "ready");
  assert.equal(bundle.manifest.outputs[0].interpretation.semanticType, "table");
  assert.equal(bundle.manifest.outputs[0].interpretation.rowCount, 2);
  assert.equal(bundle.manifest.outputs[0].presentations[0].kind, "table");
  assert.equal(bundle.manifest.outputs[0].presentations[0].state, "ready");
  assert.equal(bundle.visualization, null);
});

test("canonical outputs without presentations are partial rather than falsely ready", async () => {
  const bundle = await prepareResultArtifacts({
    toolName: "ogc_jobs_get_results",
    args: { server_id: "canonical-server", job_id: "no-presentation" },
    activityId: "no-presentation",
    result: structured({
      ok: true,
      output_manifest: {
        schemaVersion: "ogc-output-manifest/1",
        manifestId: "upstream-no-presentation",
        execution: { state: "succeeded", serverId: "canonical-server" },
        overallState: "ready",
        outputs: [{
          id: "result",
          title: "Unpresented result",
          status: "ready",
          retrieval: { state: "retrieved", source: "inline" },
          interpretation: {
            state: "recognized",
            semanticType: "document",
            crs: { status: "missing" },
          },
          representations: [{
            id: "result-preview",
            role: "preview",
            mediaType: "text/plain",
            data: "Result exists",
          }],
          presentations: [],
          provenance: { serverId: "canonical-server" },
        }],
      },
    }),
    callTool: async () => assert.fail("unexpected hydration"),
  });

  assert.equal(bundle.manifest.outputs[0].status, "partial");
  assert.equal(bundle.manifest.overallState, "partial");
});

test("a chart is unavailable when rows contain no numeric series", async () => {
  const bundle = await prepareResultArtifacts({
    toolName: "ogc_jobs_get_results",
    args: { server_id: "canonical-server", job_id: "non-numeric-chart" },
    activityId: "non-numeric-chart",
    result: structured({
      ok: true,
      output_manifest: {
        schemaVersion: "ogc-output-manifest/1",
        manifestId: "upstream-non-numeric-chart",
        execution: { state: "succeeded", serverId: "canonical-server" },
        overallState: "ready",
        outputs: [{
          id: "series",
          title: "Labels only",
          status: "ready",
          retrieval: { state: "retrieved", source: "inline" },
          interpretation: {
            state: "recognized",
            semanticType: "timeseries",
            crs: { status: "missing" },
          },
          representations: [{
            id: "series-preview",
            role: "preview",
            mediaType: "application/json",
            data: [{ timestamp: "2026-01-01" }, { timestamp: "2026-01-02" }],
          }],
          presentations: [{
            id: "series-chart",
            kind: "chart",
            state: "ready",
            artifactRef: "series-preview",
          }],
          provenance: { serverId: "canonical-server" },
        }],
      },
    }),
    callTool: async () => assert.fail("unexpected hydration"),
  });

  assert.equal(bundle.manifest.outputs[0].presentations[0].state, "unavailable");
  assert.equal(bundle.manifest.outputs[0].status, "partial");
  assert.equal(bundle.manifest.overallState, "partial");
});

test("canonical output clarification stays model-visible and UI-renderable", async () => {
  const bundle = await prepareResultArtifacts({
    toolName: "ogc_jobs_get_results",
    args: { server_id: "canonical-server", job_id: "ambiguous-columns" },
    activityId: "ambiguous-columns",
    result: structured({
      ok: true,
      output_manifest: {
        schemaVersion: "ogc-output-manifest/1",
        manifestId: "upstream-ambiguous-columns",
        execution: { state: "succeeded", serverId: "canonical-server" },
        overallState: "partial",
        outputs: [{
          id: "rows",
          title: "Coordinate rows",
          status: "unresolved",
          retrieval: { state: "retrieved", source: "inline" },
          interpretation: {
            state: "ambiguous",
            semanticType: "table",
            crs: { status: "missing" },
          },
          representations: [{
            id: "rows-preview",
            role: "preview",
            mediaType: "application/json",
            data: [{ x: 10, y: 20 }, { x: 11, y: 21 }],
          }],
          presentations: [{
            id: "rows-table",
            kind: "table",
            state: "ready",
            artifactRef: "rows-preview",
          }],
          clarificationRequest: {
            blocking: false,
            scope: "interpretation",
            issues: [{
              id: "axis-order",
              kind: "axis_order",
              fieldPath: "outputs.rows.columns",
              question: "Which columns are longitude and latitude?",
              whyItMatters: "The system will not guess coordinate order.",
              observedValue: ["x", "y"],
              allowFreeText: true,
            }],
          },
          provenance: { serverId: "canonical-server" },
        }],
      },
    }),
    callTool: async () => assert.fail("unexpected hydration"),
  });

  const clarification = bundle.manifest.outputs[0].clarificationRequest;
  assert.equal(bundle.manifest.overallState, "partial");
  assert.equal(clarification.scope, "interpretation");
  assert.equal(clarification.issues[0].kind, "axis_order");
  assert.equal(
    clarification.issues[0].question,
    "Which columns are longitude and latitude?",
  );
  assert.equal(
    bundle.modelContext.outputs[0].clarificationRequest.issues[0].question,
    "Which columns are longitude and latitude?",
  );
  assert.ok(bundle.artifactEvents.some(
    (event) => event.stage === "interpretation" && event.status === "waiting",
  ));
});

test("unstructured output-tool text still produces an explicit manifest", async () => {
  const bundle = await prepareResultArtifacts({
    toolName: "ogc_jobs_get_results",
    args: { job_id: "text-result" },
    activityId: "tool-text-result",
    result: { content: [{ type: "text", text: "The process returned a short textual result." }] },
    callTool: async () => assert.fail("unexpected hydration"),
  });
  assert.equal(bundle.manifest.schemaVersion, "ogc-output-manifest/1");
  assert.equal(bundle.manifest.outputs.length, 1);
  assert.equal(bundle.manifest.outputs[0].retrieval.state, "retrieved");
  assert.equal(bundle.manifest.outputs[0].interpretation.state, "recognized");
  assert.equal(bundle.manifest.outputs[0].presentations[0].state, "ready");
});

function scalarArtifactManifest(count) {
  const outputs = Array.from({ length: count }, (_, index) => {
    const suffix = index.toString(16).padStart(32, "0");
    const handle = `art_${suffix}`;
    return {
      id: `metric-${index + 1}`,
      title: `Metric ${index + 1}`,
      status: "ready",
      retrieval: { state: "retrieved", source: "memory" },
      interpretation: { state: "recognized", semanticType: "scalar" },
      representations: [{
        id: `metric-${index + 1}-value`,
        role: "canonical",
        mediaType: "text/plain",
        handle,
        sizeBytes: 16,
      }],
      presentations: [{
        id: `metric-${index + 1}-view`,
        kind: "metric",
        state: "ready",
        artifactRef: handle,
      }],
      provenance: { serverId: "budget-server" },
    };
  });
  return {
    schemaVersion: "ogc-output-manifest/1",
    manifestId: "budget-manifest",
    execution: { state: "succeeded", serverId: "budget-server" },
    overallState: "ready",
    outputs,
  };
}

test("canonical hydration enforces one aggregate fetch-count budget and downgrades the remainder", async () => {
  const calls = [];
  const bundle = await prepareResultArtifacts({
    toolName: "ogc_jobs_get_results",
    args: { job_id: "fetch-budget" },
    activityId: "tool-fetch-budget",
    artifactHydrationBudget: {
      maxFetches: 2,
      maxTotalBytes: 10_000,
      maxElapsedMs: 1_000,
    },
    result: structured({
      ok: true,
      server: { id: "budget-server" },
      output_manifest: scalarArtifactManifest(5),
    }),
    callTool: async (name, args, options) => {
      calls.push({ name, args, options });
      return structured({
        ok: true,
        artifact: {
          handle: args.handle,
          mediaType: "text/plain",
          role: "canonical",
          sizeBytes: 2,
          encoding: "identity",
          data: 42,
        },
        data: 42,
      });
    },
  });
  assert.equal(calls.length, 2);
  assert.ok(calls.every((call) => call.name === "ogc_proxy_artifact_retrieve"));
  assert.ok(calls.every((call) => call.options.timeout > 0 && call.options.timeout <= 1_000));
  assert.equal(bundle.manifest.outputs[0].presentations[0].state, "ready");
  assert.equal(bundle.manifest.outputs[1].presentations[0].state, "ready");
  assert.equal(bundle.manifest.outputs[2].presentations[0].state, "unavailable");
  assert.match(bundle.manifest.outputs[2].warnings.join(" "), /aggregate fetch limit/);
  assert.match(bundle.manifest.warnings.join(" "), /stopped after 2 fetches/);
  assert.equal(bundle.manifest.overallState, "partial");
});

test("canonical hydration applies one total-byte budget before fetching more representations", async () => {
  const manifest = scalarArtifactManifest(3);
  for (const output of manifest.outputs) output.representations[0].sizeBytes = 700;
  let calls = 0;
  const bundle = await prepareResultArtifacts({
    toolName: "ogc_jobs_get_results",
    args: { job_id: "byte-budget" },
    activityId: "tool-byte-budget",
    artifactHydrationBudget: {
      maxFetches: 8,
      maxTotalBytes: 1_024,
      maxElapsedMs: 1_000,
    },
    result: structured({
      ok: true,
      server: { id: "budget-server" },
      output_manifest: manifest,
    }),
    callTool: async (_name, args) => {
      calls += 1;
      const data = "v".repeat(700);
      return structured({
        ok: true,
        artifact: {
          handle: args.handle,
          mediaType: "text/plain",
          role: "canonical",
          sizeBytes: 700,
          encoding: "identity",
          data,
        },
        data,
      });
    },
  });
  assert.equal(calls, 1);
  assert.equal(bundle.manifest.outputs[0].presentations[0].state, "ready");
  assert.equal(bundle.manifest.outputs[1].presentations[0].state, "unavailable");
  assert.match(bundle.manifest.outputs[1].warnings.join(" "), /remaining aggregate byte budget/);
  assert.equal(bundle.manifest.overallState, "partial");
});

test("canonical hydration stops at one aggregate elapsed deadline without sequentially calling the remainder", async () => {
  let calls = 0;
  const startedAt = Date.now();
  const bundle = await prepareResultArtifacts({
    toolName: "ogc_jobs_get_results",
    args: { job_id: "deadline-budget" },
    activityId: "tool-deadline-budget",
    artifactHydrationBudget: {
      maxFetches: 8,
      maxTotalBytes: 10_000,
      maxElapsedMs: 10,
    },
    result: structured({
      ok: true,
      server: { id: "budget-server" },
      output_manifest: scalarArtifactManifest(4),
    }),
    callTool: async () => {
      calls += 1;
      return new Promise(() => undefined);
    },
  });
  assert.equal(calls, 1);
  assert.ok(Date.now() - startedAt < 500);
  assert.ok(bundle.manifest.outputs.every((output) => output.presentations[0].state === "unavailable"));
  assert.match(bundle.manifest.warnings.join(" "), /hydration deadline/);
  assert.match(bundle.manifest.warnings.join(" "), /stopped after 1 fetch/);
});
