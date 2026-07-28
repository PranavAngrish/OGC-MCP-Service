import assert from "node:assert/strict";
import test from "node:test";
import { buildMapVisualization } from "./geospatial.mjs";

const feature = (geometry, properties = {}) => ({
  type: "Feature",
  properties,
  geometry,
});

test("normalizes nested job outputs and every GeoJSON geometry family", () => {
  const geometries = [
    { type: "Point", coordinates: [77.59, 12.97] },
    { type: "MultiPoint", coordinates: [[77.5, 12.9], [77.6, 13]] },
    { type: "LineString", coordinates: [[77.4, 12.8], [77.7, 13.1]] },
    { type: "MultiLineString", coordinates: [[[77.4, 12.8], [77.5, 12.9]]] },
    { type: "Polygon", coordinates: [[[77.4, 12.8], [77.7, 12.8], [77.7, 13.1], [77.4, 12.8]]] },
    { type: "MultiPolygon", coordinates: [[[[77.4, 12.8], [77.5, 12.8], [77.5, 12.9], [77.4, 12.8]]]] },
    {
      type: "GeometryCollection",
      geometries: [{ type: "Point", coordinates: [77.55, 12.95] }],
    },
  ];
  const map = buildMapVisualization({
    outputs: {
      delineated_area: {
        type: "FeatureCollection",
        features: geometries.map((geometry, index) => feature(geometry, { index, html: "<b>text only</b>" })),
      },
    },
  }, { id: "job-map", title: "Job output", sourceTool: "ogc_jobs_get_results" });

  assert.equal(map.id, "job-map");
  assert.equal(map.sourceTool, "ogc_jobs_get_results");
  assert.equal(map.layers.length, 1);
  assert.equal(map.stats.featureCount, 7);
  assert.equal(map.stats.geometryTypes.Point, 2);
  assert.equal(map.stats.geometryTypes.GeometryCollection, 1);
  assert.deepEqual(map.bounds, [77.4, 12.8, 77.7, 13.1]);
  assert.equal(map.layers[0].data.features[0].properties.html, "<b>text only</b>");
});

test("maps named longitude/latitude records and rejects ambiguous coordinate arrays", () => {
  const records = buildMapVisualization({
    stations: [
      { id: "a", longitude: 77.59, latitude: 12.97, temperature: 24 },
      { id: "b", lon: 77.61, lat: 12.99, temperature: 25 },
    ],
  });
  assert.equal(records.stats.featureCount, 2);
  assert.deepEqual(records.layers[0].data.features[0].geometry.coordinates, [77.59, 12.97]);
  assert.equal(buildMapVisualization({ output: [[77.59, 12.97], [77.61, 12.99]] }), null);

  const explicit = buildMapVisualization({ output: { coordinates: [77.59, 12.97] } });
  assert.deepEqual(explicit.layers[0].data.features[0].geometry.coordinates, [77.59, 12.97]);

  const projectedRecord = buildMapVisualization({ output: { x: 0, y: 0, crs: "EPSG:3857", value: 4 } });
  assert.deepEqual(projectedRecord.layers[0].data.features[0].geometry.coordinates, [0, 0]);
  const projectedRecords = buildMapVisualization({ crs: "EPSG:3857", points: [{ x: 0, y: 0 }, { x: 111319.49, y: 0 }] });
  assert.equal(Math.round(projectedRecords.bounds[2]), 1);
});

test("renders bounding boxes including antimeridian extents", () => {
  const regular = buildMapVisualization({ result_bbox: [76, 12, 78, 14] });
  assert.equal(regular.layers[0].data.features[0].geometry.type, "Polygon");
  assert.deepEqual(regular.bounds, [76, 12, 78, 14]);

  const crossing = buildMapVisualization({ bounds: [170, -10, -170, 10] });
  assert.equal(crossing.layers[0].data.features[0].geometry.type, "MultiPolygon");
  assert.equal(crossing.warnings.some((item) => item.includes("antimeridian")), true);
});

test("parses basic WKT and reprojects explicitly declared Web Mercator", () => {
  const wkt = buildMapVisualization({ geometry_wkt: "POLYGON ((77 12, 78 12, 78 13, 77 12))" });
  assert.equal(wkt.layers[0].data.features[0].geometry.type, "Polygon");
  const wrappedWkt = buildMapVisualization({ outputs: { result: { value: "POINT (77 12)" } } });
  assert.deepEqual(wrappedWkt.layers[0].data.features[0].geometry.coordinates, [77, 12]);

  const mercator = buildMapVisualization({
    crs: "EPSG:3857",
    geometry: { type: "Point", coordinates: [0, 0] },
  });
  assert.deepEqual(mercator.layers[0].data.features[0].geometry.coordinates, [0, 0]);
  assert.equal(mercator.crs, "OGC:CRS84");

  const unsupported = buildMapVisualization({
    crs: "EPSG:32643",
    geometry: { type: "Point", coordinates: [500000, 1400000] },
  });
  assert.equal(unsupported, null);
});

test("turns a bounded numeric grid into weighted heatmap points", () => {
  const map = buildMapVisualization({
    rainfall: {
      bbox: [76, 12, 78, 14],
      values: [[0, 5], [10, null]],
    },
  });
  const layer = map.layers.find((item) => item.kind === "heatmap");
  assert.ok(layer);
  assert.equal(layer.featureCount, 3);
  assert.equal(layer.data.features[0].properties._heatmap_weight, 0.15);
  assert.equal(layer.data.features[2].properties._heatmap_weight, 1);
  assert.match(layer.description, /2 × 2/);

  const coverage = buildMapVisualization({
    type: "Coverage",
    domain: {
      axes: {
        x: { values: [76, 77] },
        y: { values: [12, 13] },
      },
      referencing: [{ system: { type: "GeographicCRS", id: "http://www.opengis.net/def/crs/OGC/1.3/CRS84" } }],
    },
    parameters: { temperature: { unit: { symbol: "°C" } } },
    ranges: {
      temperature: { shape: [2, 2], values: [20, 21, 22, 23] },
    },
  });
  assert.equal(coverage.layers[0].kind, "heatmap");
  assert.equal(coverage.layers[0].featureCount, 4);
  assert.match(coverage.layers[0].description, /°C/);

  const sampled = buildMapVisualization({
    bbox: [0, 0, 10, 10],
    values: Array.from({ length: 100 }, (_, row) => (
      Array.from({ length: 100 }, (_, column) => row * 100 + column)
    )),
  }, { maxGridCells: 10 });
  assert.equal(sampled.layers[0].featureCount, 10);
  assert.equal(sampled.stats.truncated, true);
  assert.match(sampled.layers[0].description, /sampled range/);
  assert.equal(sampled.warnings.some((item) => item.includes("10 cells")), true);
});

test("classifies georeferenced images, XYZ tiles, and COG references", () => {
  const map = buildMapVisualization({
    outputs: {
      preview: { href: "https://data.example/preview.png", mediaType: "image/png", bbox: [76, 12, 78, 14] },
      tiles: { href: "https://tiles.example/{z}/{x}/{y}.png", mediaType: "image/png" },
      cog: { href: "https://data.example/result.tif", mediaType: "image/tiff; application=geotiff; profile=cloud-optimized" },
    },
  });
  assert.deepEqual(map.layers.map((layer) => layer.kind).sort(), ["raster", "reference", "tiles"]);
  assert.equal(map.layers.find((layer) => layer.kind === "tiles").href.includes("{z}"), true);

  const relative = buildMapVisualization(
    { href: "/results/output.geojson", mediaType: "application/geo+json" },
    { baseUrl: "https://process.example/api/" },
  );
  assert.equal(relative.layers[0].href, "https://process.example/results/output.geojson");

  const tileJson = buildMapVisualization({
    href: "https://tiles.example/source.json",
    mediaType: "application/vnd.mapbox.tilejson+json",
  });
  assert.equal(tileJson.layers[0].kind, "reference");
});

test("enforces feature, coordinate, layer, and serialized-size limits", () => {
  const features = Array.from({ length: 12 }, (_, index) => feature(
    { type: "Point", coordinates: [70 + index / 100, 10] },
    { description: "x".repeat(500) },
  ));
  const map = buildMapVisualization(
    { type: "FeatureCollection", features },
    { maxFeatures: 3, maxCoordinates: 3, maxBytes: 20_000 },
  );
  assert.equal(map.stats.featureCount, 3);
  assert.equal(map.stats.truncated, true);
  assert.equal(map.warnings.some((item) => item.includes("limit")), true);

  const byteLimited = buildMapVisualization(
    { type: "FeatureCollection", features },
    { maxBytes: 850, maxFeatures: 20 },
  );
  assert.equal(byteLimited.stats.truncated, true);
  assert.ok(Buffer.byteLength(JSON.stringify(byteLimited)) < 3_000);
});
