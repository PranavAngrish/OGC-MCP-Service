const GEOMETRY_TYPES = new Set([
  "Point",
  "MultiPoint",
  "LineString",
  "MultiLineString",
  "Polygon",
  "MultiPolygon",
  "GeometryCollection",
]);

const COLORS = ["#b9e66c", "#70d6ad", "#f2a765", "#8cb8ff", "#dca6ff"];
const DEFAULT_LIMITS = {
  maxDepth: 8,
  maxNodes: 4_000,
  maxLayers: 12,
  maxFeatures: 2_000,
  maxCoordinates: 50_000,
  maxGridCells: 5_000,
  maxBytes: 1_250_000,
};

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function finite(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function positiveLimit(value, fallback) {
  return Number.isInteger(value) && value > 0 ? value : fallback;
}

function slug(value) {
  return String(value || "layer")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48) || "layer";
}

function humanize(value) {
  const text = String(value || "result")
    .replace(/[_-]+/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .trim();
  return text ? text.replace(/^./, (letter) => letter.toUpperCase()).slice(0, 120) : "Result";
}

function layerLabel(path, suffix = "") {
  const ignored = new Set(["data", "outputs", "output", "result", "results", "items"]);
  const segment = [...path].reverse().find((part) => !ignored.has(String(part).toLowerCase()));
  const base = humanize(segment || "Process result");
  return suffix ? `${base} ${suffix}` : base;
}

function warning(context, message) {
  if (!context.warnings.includes(message) && context.warnings.length < 12) {
    context.warnings.push(message);
  }
}

function markTruncated(context, message) {
  context.truncated = true;
  warning(context, message);
}

function sanitizeValue(value, depth = 0) {
  if (value === null || typeof value === "boolean" || finite(value)) return value;
  if (typeof value === "string") return value.slice(0, 1_000);
  if (depth >= 3) return "[nested value]";
  if (Array.isArray(value)) return value.slice(0, 30).map((item) => sanitizeValue(item, depth + 1));
  if (!isObject(value)) return String(value).slice(0, 1_000);
  return Object.fromEntries(
    Object.entries(value)
      .slice(0, 50)
      .map(([key, item]) => [key.slice(0, 120), sanitizeValue(item, depth + 1)]),
  );
}

function sanitizeProperties(value) {
  return isObject(value) ? sanitizeValue(value) : {};
}

function crsText(value) {
  if (typeof value === "string") return value.trim();
  if (!isObject(value)) return "";
  if (typeof value.name === "string") return value.name.trim();
  if (typeof value.id === "string" || finite(value.id)) {
    const authority = typeof value.authority === "string" ? `${value.authority}:` : "";
    return `${authority}${value.id}`;
  }
  if (isObject(value.properties) && typeof value.properties.name === "string") {
    return value.properties.name.trim();
  }
  return "";
}

function classifyCrs(value, fallback = { id: "OGC:CRS84", mode: "geographic" }) {
  const text = crsText(value);
  if (!text) return fallback;
  const normalized = text.toUpperCase().replace(/\s+/g, "");
  if (
    normalized.includes("CRS84")
    || normalized.includes("EPSG:4326")
    || normalized.includes("EPSG/0/4326")
    || normalized === "4326"
    || normalized.includes("WGS84")
  ) {
    return { id: "OGC:CRS84", mode: "geographic", declared: true };
  }
  if (normalized.includes("EPSG:3857") || normalized.includes("EPSG/0/3857") || normalized.includes("900913")) {
    return { id: "EPSG:3857", mode: "mercator", declared: true };
  }
  return { id: text.slice(0, 120), mode: "unsupported", declared: true };
}

function objectCrs(value, inherited) {
  if (!isObject(value)) return inherited;
  for (const key of ["crs", "srsName", "srs", "coordinateReferenceSystem", "coordRefSys"]) {
    if (key in value) return classifyCrs(value[key], inherited);
  }
  return inherited;
}

function coverageCrs(value, inherited) {
  if (String(value?.type).toLowerCase() !== "coverage" || !Array.isArray(value?.domain?.referencing)) {
    return inherited;
  }
  for (const reference of value.domain.referencing) {
    const system = reference?.system;
    const identifier = isObject(system) ? system.id ?? system.name ?? system : system;
    const text = crsText(identifier);
    if (text) return classifyCrs(text, inherited);
  }
  return inherited;
}

function toPosition(value, crs) {
  if (!Array.isArray(value) || value.length < 2 || !finite(value[0]) || !finite(value[1])) return null;
  let longitude = value[0];
  let latitude = value[1];
  if (crs.mode === "mercator") {
    if (Math.abs(longitude) > 20_037_508.35 || Math.abs(latitude) > 20_037_508.35) return null;
    longitude = (longitude / 20_037_508.34) * 180;
    latitude = (latitude / 20_037_508.34) * 180;
    latitude = (180 / Math.PI) * (2 * Math.atan(Math.exp((latitude * Math.PI) / 180)) - Math.PI / 2);
  }
  if (crs.mode === "unsupported" || longitude < -180 || longitude > 180 || latitude < -90 || latitude > 90) {
    return null;
  }
  const position = [longitude, latitude];
  if (finite(value[2])) position.push(value[2]);
  return position;
}

function consumePosition(value, crs, context) {
  if (context.coordinateCount >= context.limits.maxCoordinates) {
    markTruncated(context, `Coordinate limit reached (${context.limits.maxCoordinates.toLocaleString("en-US")}).`);
    return null;
  }
  const position = toPosition(value, crs);
  if (!position) return null;
  context.coordinateCount += 1;
  return position;
}

function positionsEqual(first, second) {
  return first?.[0] === second?.[0] && first?.[1] === second?.[1];
}

function normalizePositionList(value, crs, context, minimum) {
  if (!Array.isArray(value)) return null;
  const positions = [];
  for (const item of value) {
    const position = consumePosition(item, crs, context);
    if (!position) return null;
    positions.push(position);
  }
  return positions.length >= minimum ? positions : null;
}

function normalizeRing(value, crs, context) {
  const positions = normalizePositionList(value, crs, context, 3);
  if (!positions) return null;
  if (!positionsEqual(positions[0], positions.at(-1))) {
    if (context.coordinateCount >= context.limits.maxCoordinates) return null;
    positions.push([...positions[0]]);
    context.coordinateCount += 1;
  }
  return positions.length >= 4 ? positions : null;
}

function normalizeGeometry(value, crs, context) {
  if (!isObject(value) || !GEOMETRY_TYPES.has(value.type)) return null;
  const before = context.coordinateCount;
  let geometry = null;

  if (value.type === "Point") {
    const coordinates = consumePosition(value.coordinates, crs, context);
    if (coordinates) geometry = { type: "Point", coordinates };
  } else if (value.type === "MultiPoint") {
    const coordinates = normalizePositionList(value.coordinates, crs, context, 1);
    if (coordinates) geometry = { type: "MultiPoint", coordinates };
  } else if (value.type === "LineString") {
    const coordinates = normalizePositionList(value.coordinates, crs, context, 2);
    if (coordinates) geometry = { type: "LineString", coordinates };
  } else if (value.type === "MultiLineString" && Array.isArray(value.coordinates)) {
    const coordinates = value.coordinates.map((line) => normalizePositionList(line, crs, context, 2));
    if (coordinates.length && coordinates.every(Boolean)) geometry = { type: "MultiLineString", coordinates };
  } else if (value.type === "Polygon" && Array.isArray(value.coordinates)) {
    const coordinates = value.coordinates.map((ring) => normalizeRing(ring, crs, context));
    if (coordinates.length && coordinates.every(Boolean)) geometry = { type: "Polygon", coordinates };
  } else if (value.type === "MultiPolygon" && Array.isArray(value.coordinates)) {
    const coordinates = value.coordinates.map((polygon) => (
      Array.isArray(polygon) ? polygon.map((ring) => normalizeRing(ring, crs, context)) : null
    ));
    if (
      coordinates.length
      && coordinates.every((polygon) => Array.isArray(polygon) && polygon.length && polygon.every(Boolean))
    ) {
      geometry = { type: "MultiPolygon", coordinates };
    }
  } else if (value.type === "GeometryCollection" && Array.isArray(value.geometries)) {
    const geometries = value.geometries
      .map((item) => normalizeGeometry(item, crs, context))
      .filter(Boolean);
    if (geometries.length) geometry = { type: "GeometryCollection", geometries };
  }

  if (!geometry) context.coordinateCount = before;
  return geometry;
}

function countGeometryTypes(geometry, counts) {
  counts[geometry.type] = (counts[geometry.type] || 0) + 1;
  if (geometry.type === "GeometryCollection") {
    for (const child of geometry.geometries) countGeometryTypes(child, counts);
  }
}

function visitPositions(geometry, visitor) {
  if (geometry.type === "GeometryCollection") {
    for (const child of geometry.geometries) visitPositions(child, visitor);
    return;
  }
  const walk = (value) => {
    if (!Array.isArray(value)) return;
    if (value.length >= 2 && finite(value[0]) && finite(value[1])) {
      visitor(value[0], value[1]);
      return;
    }
    for (const child of value) walk(child);
  };
  walk(geometry.coordinates);
}

function dataBounds(features) {
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  for (const feature of features) {
    if (!feature.geometry) continue;
    visitPositions(feature.geometry, (longitude, latitude) => {
      west = Math.min(west, longitude);
      south = Math.min(south, latitude);
      east = Math.max(east, longitude);
      north = Math.max(north, latitude);
    });
  }
  return Number.isFinite(west) ? [west, south, east, north] : undefined;
}

function mergeBounds(first, second) {
  if (!first) return second;
  if (!second) return first;
  return [
    Math.min(first[0], second[0]),
    Math.min(first[1], second[1]),
    Math.max(first[2], second[2]),
    Math.max(first[3], second[3]),
  ];
}

function uniqueLayerId(context, label) {
  const base = slug(label);
  const count = (context.layerIds.get(base) || 0) + 1;
  context.layerIds.set(base, count);
  return count === 1 ? base : `${base}-${count}`;
}

function addLayer(context, layer) {
  if (context.layers.length >= context.limits.maxLayers) {
    markTruncated(context, `Layer limit reached (${context.limits.maxLayers}).`);
    return false;
  }
  const normalized = { ...layer, id: uniqueLayerId(context, layer.label) };
  context.layers.push(normalized);
  if (!normalized.bounds || normalized.bounds[0] <= normalized.bounds[2]) {
    context.bounds = mergeBounds(context.bounds, normalized.bounds);
  }
  return true;
}

function normalizeFeature(value, crs, context) {
  if (!isObject(value) || value.type !== "Feature" || !value.geometry) return null;
  if (context.featureCount >= context.limits.maxFeatures) {
    markTruncated(context, `Feature limit reached (${context.limits.maxFeatures.toLocaleString("en-US")}).`);
    return null;
  }
  const beforeCoordinates = context.coordinateCount;
  const geometry = normalizeGeometry(value.geometry, crs, context);
  if (!geometry) {
    context.coordinateCount = beforeCoordinates;
    return null;
  }
  const feature = {
    type: "Feature",
    properties: sanitizeProperties(value.properties),
    geometry,
  };
  if (typeof value.id === "string" || finite(value.id)) feature.id = value.id;
  const bytes = Buffer.byteLength(JSON.stringify(feature));
  if (context.byteCount + bytes > context.limits.maxBytes) {
    context.coordinateCount = beforeCoordinates;
    markTruncated(context, "Map artifact size limit reached; remaining features were omitted.");
    return null;
  }
  context.byteCount += bytes;
  context.featureCount += 1;
  countGeometryTypes(geometry, context.geometryTypes);
  return feature;
}

function isPointGeometry(geometry) {
  if (!geometry) return false;
  if (geometry.type === "Point" || geometry.type === "MultiPoint") return true;
  return geometry.type === "GeometryCollection" && geometry.geometries.every(isPointGeometry);
}

function addFeatureLayer(context, rawFeatures, crs, path, options = {}) {
  if (context.layers.length >= context.limits.maxLayers) return false;
  if (crs.mode === "unsupported") {
    warning(context, `${layerLabel(path)} uses unsupported CRS ${crs.id}; it was not placed on the map.`);
    return false;
  }
  const features = [];
  for (const rawFeature of rawFeatures) {
    const feature = normalizeFeature(rawFeature, crs, context);
    if (feature) features.push(feature);
    if (context.featureCount >= context.limits.maxFeatures || context.byteCount >= context.limits.maxBytes) break;
  }
  if (!features.length) return false;
  if (features.length < rawFeatures.length) {
    context.truncated = true;
    if (!context.warnings.some((item) => /limit|omitted/i.test(item))) {
      warning(context, "Some features were omitted because they were invalid, non-spatial, or exceeded preview limits.");
    }
  }
  const label = options.label || layerLabel(path);
  const bounds = dataBounds(features);
  return addLayer(context, {
    label,
    kind: options.kind || (features.length >= 250 && features.every((feature) => isPointGeometry(feature.geometry)) ? "heatmap" : "vector"),
    data: { type: "FeatureCollection", features },
    bounds,
    featureCount: features.length,
    description: options.description,
    style: { color: COLORS[context.layers.length % COLORS.length], opacity: 0.78, radius: options.radius || 6 },
    crs: "OGC:CRS84",
  });
}

function addGeoJson(context, value, crs, path) {
  let features;
  if (value.type === "FeatureCollection" && Array.isArray(value.features)) {
    features = value.features;
  } else if (value.type === "Feature") {
    features = [value];
  } else if (GEOMETRY_TYPES.has(value.type)) {
    features = [{ type: "Feature", properties: {}, geometry: value }];
  } else {
    return false;
  }
  return addFeatureLayer(context, features, crs, path);
}

function normalizeBbox(value, crs) {
  if (!Array.isArray(value) || ![4, 6].includes(value.length) || !value.every(finite)) return null;
  const raw = value.length === 4 ? value : [value[0], value[1], value[3], value[4]];
  const southwest = toPosition([raw[0], raw[1]], crs);
  const northeast = toPosition([raw[2], raw[3]], crs);
  if (!southwest || !northeast || southwest[1] > northeast[1]) return null;
  return [southwest[0], southwest[1], northeast[0], northeast[1]];
}

function bboxFromObject(value, crs) {
  const keys = Object.keys(value).filter((key) => /(?:^|_)(?:bbox|bounds|extent|bounding_?box)$|^boundingBox$/i.test(key));
  for (const key of keys) {
    const bounds = normalizeBbox(value[key], crs);
    if (bounds) return bounds;
    if (isObject(value[key])) {
      const box = value[key];
      const candidate = [box.west ?? box.minx, box.south ?? box.miny, box.east ?? box.maxx, box.north ?? box.maxy];
      const nested = normalizeBbox(candidate, crs);
      if (nested) return nested;
    }
  }
  return null;
}

function bboxFeature(bounds) {
  const [west, south, east, north] = bounds;
  if (west <= east) {
    return {
      type: "Feature",
      properties: { kind: "bounding box" },
      geometry: { type: "Polygon", coordinates: [[[west, south], [east, south], [east, north], [west, north], [west, south]]] },
    };
  }
  return {
    type: "Feature",
    properties: { kind: "bounding box", crosses_antimeridian: true },
    geometry: {
      type: "MultiPolygon",
      coordinates: [
        [[[west, south], [180, south], [180, north], [west, north], [west, south]]],
        [[[-180, south], [east, south], [east, north], [-180, north], [-180, south]]],
      ],
    },
  };
}

function addBbox(context, bounds, path) {
  const viewBounds = bounds[0] <= bounds[2] ? bounds : [-180, bounds[1], 180, bounds[3]];
  if (bounds[0] > bounds[2]) warning(context, `${layerLabel(path)} crosses the antimeridian; the initial view spans both parts.`);
  return addFeatureLayer(context, [bboxFeature(bounds)], { id: "OGC:CRS84", mode: "geographic" }, path, {
    label: layerLabel(path, "extent"),
  }) && (context.bounds = mergeBounds(context.bounds, viewBounds));
}

function splitTopLevel(value) {
  const parts = [];
  let depth = 0;
  let start = 0;
  for (let index = 0; index < value.length; index += 1) {
    if (value[index] === "(") depth += 1;
    if (value[index] === ")") depth -= 1;
    if (value[index] === "," && depth === 0) {
      parts.push(value.slice(start, index).trim());
      start = index + 1;
    }
  }
  parts.push(value.slice(start).trim());
  return parts.filter(Boolean);
}

function unwrapParens(value) {
  const text = value.trim();
  return text.startsWith("(") && text.endsWith(")") ? text.slice(1, -1).trim() : text;
}

function wktPosition(value) {
  const numbers = value.trim().split(/\s+/).map(Number);
  return numbers.length >= 2 && numbers.every(Number.isFinite) ? numbers : null;
}

function parseWkt(value) {
  if (typeof value !== "string" || value.length > 250_000) return null;
  let text = value.trim();
  let srid = "";
  const sridMatch = text.match(/^SRID=(\d+)\s*;/i);
  if (sridMatch) {
    srid = `EPSG:${sridMatch[1]}`;
    text = text.slice(sridMatch[0].length).trim();
  }
  const match = text.match(/^([A-Z]+)(?:\s+(?:Z|M|ZM))?\s*(EMPTY|\(.*\))$/is);
  if (!match || match[2].toUpperCase() === "EMPTY") return null;
  const type = match[1].toUpperCase();
  const body = unwrapParens(match[2]);
  const line = (input) => splitTopLevel(unwrapParens(input)).map(wktPosition);
  let geometry = null;
  if (type === "POINT") geometry = { type: "Point", coordinates: wktPosition(body) };
  if (type === "MULTIPOINT") geometry = { type: "MultiPoint", coordinates: splitTopLevel(body).map((item) => wktPosition(unwrapParens(item))) };
  if (type === "LINESTRING") geometry = { type: "LineString", coordinates: line(body) };
  if (type === "MULTILINESTRING") geometry = { type: "MultiLineString", coordinates: splitTopLevel(body).map(line) };
  if (type === "POLYGON") geometry = { type: "Polygon", coordinates: splitTopLevel(body).map(line) };
  if (type === "MULTIPOLYGON") {
    geometry = {
      type: "MultiPolygon",
      coordinates: splitTopLevel(body).map((polygon) => splitTopLevel(unwrapParens(polygon)).map(line)),
    };
  }
  if (type === "GEOMETRYCOLLECTION") {
    const geometries = splitTopLevel(body).map((item) => parseWkt(`${srid ? `SRID=${srid.split(":")[1]};` : ""}${item}`)?.geometry).filter(Boolean);
    geometry = geometries.length ? { type: "GeometryCollection", geometries } : null;
  }
  if (!geometry || JSON.stringify(geometry).includes("null")) return null;
  return { geometry, crs: srid };
}

function wktFromObject(value) {
  for (const key of ["wkt", "wellKnownText", "geometry_wkt", "geometryWkt"]) {
    const parsed = parseWkt(value[key]);
    if (parsed) return parsed;
  }
  return null;
}

function pointFromRecord(value, inheritedCrs = { id: "OGC:CRS84", mode: "geographic" }) {
  if (!isObject(value)) return null;
  const entries = Object.fromEntries(Object.entries(value).map(([key, item]) => [key.toLowerCase(), item]));
  const longitude = entries.longitude ?? entries.lon ?? entries.lng ?? entries.long;
  const latitude = entries.latitude ?? entries.lat;
  const namedGeographic = finite(longitude) && finite(latitude);
  const hasDeclaredCrs = ["crs", "srsname", "srs", "coordinatereferencesystem", "coordrefsys"]
    .some((key) => key in entries);
  const x = entries.x ?? entries.easting;
  const y = entries.y ?? entries.northing;
  if (!namedGeographic && !((hasDeclaredCrs || inheritedCrs.declared) && finite(x) && finite(y))) return null;
  const recordCrs = namedGeographic ? { id: "OGC:CRS84", mode: "geographic" } : objectCrs(value, inheritedCrs);
  const properties = Object.fromEntries(
    Object.entries(value).filter(([key]) => ![
      "longitude", "lon", "lng", "long", "latitude", "lat", "x", "y", "easting", "northing",
      "crs", "srsname", "srs", "coordinatereferencesystem", "coordrefsys",
    ].includes(key.toLowerCase())),
  );
  return {
    crs: recordCrs,
    feature: {
      type: "Feature",
      properties,
      geometry: { type: "Point", coordinates: namedGeographic ? [longitude, latitude] : [x, y] },
    },
  };
}

function semanticGeometry(key, value) {
  const name = String(key || "").toLowerCase();
  const pointNames = new Set(["coordinate", "coordinates", "location", "position", "centroid", "point"]);
  const multiPointNames = new Set(["points", "locations", "positions", "stations"]);
  const lineNames = new Set(["line", "path", "track", "route", "trajectory"]);
  const polygonNames = new Set(["polygon", "boundary", "footprint"]);
  if (pointNames.has(name) && Array.isArray(value) && finite(value[0]) && finite(value[1])) {
    return { type: "Point", coordinates: value };
  }
  if (!Array.isArray(value) || !value.length || !value.every((item) => Array.isArray(item))) return null;
  if (multiPointNames.has(name)) return { type: "MultiPoint", coordinates: value };
  if (lineNames.has(name)) return { type: "LineString", coordinates: value };
  if (polygonNames.has(name)) return { type: "Polygon", coordinates: [value] };
  return null;
}

function httpUrl(value, baseUrl = "") {
  if (typeof value !== "string" || value.length > 8_192) return "";
  try {
    const parsed = new URL(value, baseUrl || undefined);
    return ["http:", "https:"].includes(parsed.protocol) && !parsed.username && !parsed.password
      ? parsed.href.replace(/%7B(z|x|y|-y|ratio|quadkey)%7D/gi, (_match, token) => `{${token}}`)
      : "";
  } catch {
    return "";
  }
}

function referenceFromObject(value, crs, baseUrl) {
  if (!isObject(value)) return null;
  const href = httpUrl(value.href ?? value.url ?? value.uri, baseUrl);
  if (!href) return null;
  const format = String(value.mediaType ?? value.contentType ?? value.format ?? value.type ?? "").toLowerCase().slice(0, 160);
  const bounds = bboxFromObject(value, crs);
  const tileTemplate = /\{(?:z|x|y|-y|quadkey)\}/i.test(href);
  const vectorTile = /mapbox-vector-tile|\bmvt\b|application\/vnd\.mapbox/i.test(format);
  if (vectorTile) return { kind: "reference", href, bounds, format: format || "vector tiles" };
  if (tileTemplate) return { kind: "tiles", href, bounds, format: format || "XYZ tiles" };
  if (/tilejson/i.test(format)) return { kind: "reference", href, bounds, format: format || "TileJSON" };
  if (/raster.?tile/i.test(format)) return { kind: "reference", href, bounds, format: format || "raster tiles" };
  if (bounds && bounds[0] <= bounds[2] && (/^image\/(png|jpeg|jpg|webp)/i.test(format) || /\.(png|jpe?g|webp)(?:[?#]|$)/i.test(href))) {
    return { kind: "raster", href, bounds, format: format || "image" };
  }
  return { kind: "reference", href, bounds, format: format || undefined };
}

function matrixFromObject(value) {
  for (const key of ["values", "grid", "matrix"]) {
    const matrix = value[key];
    if (Array.isArray(matrix) && matrix.length && Array.isArray(matrix[0]) && matrix[0].length) {
      return {
        rows: matrix.length,
        columns: matrix[0].length,
        valueAt: (row, column) => matrix[row]?.[column],
      };
    }
  }
  if (Array.isArray(value.data) && value.data.length && Array.isArray(value.data[0]) && value.data[0].length) {
    return {
      rows: value.data.length,
      columns: value.data[0].length,
      valueAt: (row, column) => value.data[row]?.[column],
    };
  }
  return null;
}

function coverageMatrix(value) {
  if (String(value.type).toLowerCase() !== "coverage" || !isObject(value.ranges)) return null;
  const [parameter, range] = Object.entries(value.ranges).find(([, item]) => isObject(item) && Array.isArray(item.values)) || [];
  if (!parameter || !range) return null;
  const shape = Array.isArray(range.shape) ? range.shape : [];
  const rows = shape.at(-2);
  const columns = shape.at(-1);
  const cellCount = rows * columns;
  if (
    !Number.isSafeInteger(cellCount)
    || !Number.isInteger(rows)
    || !Number.isInteger(columns)
    || rows <= 0
    || columns <= 0
    || range.values.length < cellCount
  ) return null;
  const unit = value.parameters?.[parameter]?.unit?.label ?? value.parameters?.[parameter]?.unit?.symbol;
  return {
    rows,
    columns,
    valueAt: (row, column) => range.values[row * columns + column],
    parameter,
    unit: typeof unit === "string" ? unit : "",
  };
}

function coverageBounds(value, crs) {
  const axes = value?.domain?.axes;
  if (!isObject(axes)) return null;
  const axis = (names) => {
    const entry = Object.entries(axes).find(([key]) => names.includes(key.toLowerCase()))?.[1];
    if (!isObject(entry)) return null;
    const values = Array.isArray(entry.values) ? entry.values : [];
    if (finite(values[0]) && finite(values.at(-1))) {
      return [Math.min(values[0], values.at(-1)), Math.max(values[0], values.at(-1))];
    }
    if (finite(entry.start) && finite(entry.stop)) return [Math.min(entry.start, entry.stop), Math.max(entry.start, entry.stop)];
    return null;
  };
  const x = axis(["x", "lon", "longitude"]);
  const y = axis(["y", "lat", "latitude"]);
  return x && y ? normalizeBbox([x[0], y[0], x[1], y[1]], crs) : null;
}

function addGrid(context, value, crs, path) {
  const coverage = coverageMatrix(value);
  const grid = coverage || matrixFromObject(value);
  const bounds = bboxFromObject(value, crs)
    || bboxFromObject(value.domain || {}, crs)
    || coverageBounds(value, crs);
  if (!grid || !bounds || crs.mode === "unsupported") return false;
  const { rows, columns } = grid;
  const totalCells = rows * columns;
  if (!Number.isSafeInteger(totalCells) || totalCells <= 0) return false;
  const gridSampled = totalCells > context.limits.maxGridCells;
  const sampleCount = Math.min(totalCells, context.limits.maxGridCells);
  const cells = [];
  for (let sample = 0; sample < sampleCount; sample += 1) {
    const flatIndex = sampleCount === 1
      ? 0
      : Math.floor((sample * (totalCells - 1)) / (sampleCount - 1));
    const row = Math.floor(flatIndex / columns);
    const column = flatIndex % columns;
    const cellValue = grid.valueAt(row, column);
    if (finite(cellValue)) cells.push({ row, column, value: cellValue });
  }
  if (!cells.length) return false;
  if (gridSampled) {
    markTruncated(context, `Grid preview limited to ${context.limits.maxGridCells.toLocaleString("en-US")} cells.`);
  }
  const values = cells.map((cell) => cell.value);
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const features = cells.map((cell) => {
    const x = bounds[0] + ((cell.column + 0.5) / columns) * (bounds[2] - bounds[0]);
    const y = bounds[3] - ((cell.row + 0.5) / rows) * (bounds[3] - bounds[1]);
    return {
      type: "Feature",
      properties: {
        value: cell.value,
        _heatmap_weight: maximum === minimum
          ? 1
          : 0.15 + 0.85 * ((cell.value - minimum) / (maximum - minimum)),
        row: cell.row,
        column: cell.column,
        ...(coverage?.parameter ? { parameter: coverage.parameter } : {}),
        ...(coverage?.unit ? { unit: coverage.unit } : {}),
      },
      geometry: { type: "Point", coordinates: [x, y] },
    };
  });
  const range = `${minimum.toLocaleString("en-US")}–${maximum.toLocaleString("en-US")}${coverage?.unit ? ` ${coverage.unit}` : ""}`;
  return addFeatureLayer(context, features, { id: "OGC:CRS84", mode: "geographic" }, path, {
    kind: "heatmap",
    label: layerLabel(path, "grid"),
    description: `Numeric grid (${rows} × ${columns}); ${gridSampled ? "sampled " : ""}range ${range}`,
    radius: 9,
  });
}

function traverse(context, value, path, depth, inheritedCrs) {
  if (value === null || value === undefined) return;
  context.nodeCount += 1;
  if (context.nodeCount > context.limits.maxNodes) {
    markTruncated(context, "Nested result traversal limit reached.");
    return;
  }
  if (depth > context.limits.maxDepth) {
    markTruncated(context, `Nested result depth limit reached (${context.limits.maxDepth}).`);
    return;
  }

  if (typeof value === "string") {
    const wkt = parseWkt(value);
    if (wkt) {
      addGeoJson(context, wkt.geometry, classifyCrs(wkt.crs, inheritedCrs), path);
      return;
    }
    const trimmed = value.trim();
    if (trimmed.length <= context.limits.maxBytes && ["{", "["].includes(trimmed[0])) {
      try {
        traverse(context, JSON.parse(trimmed), path, depth + 1, inheritedCrs);
      } catch {
        // A normal textual result is not geospatial JSON.
      }
    }
    return;
  }

  if (Array.isArray(value)) {
    const featureValues = value.filter((item) => isObject(item) && item.type === "Feature");
    if (featureValues.length && featureValues.length === value.length) {
      addFeatureLayer(context, featureValues, inheritedCrs, path);
      return;
    }
    const pointRecords = value.map((item) => pointFromRecord(item, inheritedCrs)).filter(Boolean);
    if (
      pointRecords.length
      && pointRecords.length === value.filter(isObject).length
      && pointRecords.every((item) => item.crs.id === pointRecords[0].crs.id)
    ) {
      addFeatureLayer(context, pointRecords.map((item) => item.feature), pointRecords[0].crs, path);
      return;
    }
    const semantic = semanticGeometry(path.at(-1), value);
    if (semantic) {
      addGeoJson(context, semantic, inheritedCrs, path);
      return;
    }
    for (let index = 0; index < Math.min(value.length, 250); index += 1) {
      traverse(context, value[index], [...path, String(index + 1)], depth + 1, inheritedCrs);
      if (context.layers.length >= context.limits.maxLayers) break;
    }
    if (value.length > 250) markTruncated(context, "Only the first 250 nested result entries were inspected for map data.");
    return;
  }

  if (!isObject(value)) return;
  if (context.seen.has(value)) return;
  context.seen.add(value);
  const crs = coverageCrs(value, objectCrs(value, inheritedCrs));

  if (GEOMETRY_TYPES.has(value.type) || value.type === "Feature" || value.type === "FeatureCollection") {
    addGeoJson(context, value, crs, path);
    return;
  }

  const recordPoint = pointFromRecord(value, crs);
  if (recordPoint) {
    addFeatureLayer(context, [recordPoint.feature], recordPoint.crs, path);
    return;
  }

  const wkt = wktFromObject(value);
  if (wkt) {
    addGeoJson(context, wkt.geometry, classifyCrs(wkt.crs, crs), path);
    return;
  }

  if (addGrid(context, value, crs, path)) return;

  const reference = referenceFromObject(value, crs, context.baseUrl);
  if (reference) {
    if (reference.kind === "reference" && /mapbox-vector-tile|\bmvt\b/i.test(reference.format || "")) {
      warning(context, `${layerLabel(path)} is a vector-tile reference; source-layer metadata is required before it can be drawn.`);
    }
    addLayer(context, {
      label: layerLabel(path),
      description: reference.kind === "reference" ? "External geospatial result" : undefined,
      ...reference,
      style: { opacity: 0.78 },
    });
    return;
  }

  const semantic = Object.entries(value)
    .map(([key, item]) => ({ key, geometry: semanticGeometry(key, item) }))
    .find((candidate) => candidate.geometry);
  if (semantic) {
    addGeoJson(context, semantic.geometry, crs, [...path, semantic.key]);
    return;
  }

  const bounds = bboxFromObject(value, crs);
  if (bounds && crs.mode !== "unsupported") addBbox(context, bounds, path);

  const skipped = new Set([
    "ok", "operation", "server", "request", "response", "guidance", "memory", "links",
    "bbox", "bounds", "extent", "boundingBox", "crs", "srs", "srsName",
  ]);
  const preferred = ["outputs", "output", "result", "results", "data", "items"];
  const entries = Object.entries(value).sort(([first], [second]) => {
    const firstIndex = preferred.indexOf(first);
    const secondIndex = preferred.indexOf(second);
    return (firstIndex < 0 ? 99 : firstIndex) - (secondIndex < 0 ? 99 : secondIndex);
  });
  for (const [key, item] of entries) {
    if (skipped.has(key) || item === value) continue;
    traverse(context, item, [...path, key], depth + 1, crs);
    if (context.layers.length >= context.limits.maxLayers) break;
  }
}

export function buildMapVisualization(payload, options = {}) {
  if (payload === null || payload === undefined) return null;
  const limits = {
    maxDepth: positiveLimit(options.maxDepth, DEFAULT_LIMITS.maxDepth),
    maxNodes: positiveLimit(options.maxNodes, DEFAULT_LIMITS.maxNodes),
    maxLayers: positiveLimit(options.maxLayers, DEFAULT_LIMITS.maxLayers),
    maxFeatures: positiveLimit(options.maxFeatures, DEFAULT_LIMITS.maxFeatures),
    maxCoordinates: positiveLimit(options.maxCoordinates, DEFAULT_LIMITS.maxCoordinates),
    maxGridCells: positiveLimit(options.maxGridCells, DEFAULT_LIMITS.maxGridCells),
    maxBytes: positiveLimit(options.maxBytes, DEFAULT_LIMITS.maxBytes),
  };
  const context = {
    limits,
    layers: [],
    warnings: [],
    bounds: undefined,
    featureCount: 0,
    coordinateCount: 0,
    byteCount: 0,
    nodeCount: 0,
    geometryTypes: {},
    layerIds: new Map(),
    seen: new WeakSet(),
    truncated: false,
    baseUrl: typeof options.baseUrl === "string" ? options.baseUrl : "",
  };
  const envelope = isObject(payload)
    && ("ok" in payload || "operation" in payload)
    && "data" in payload
    ? payload.data
    : payload;
  traverse(context, envelope, ["result"], 0, { id: "OGC:CRS84", mode: "geographic", declared: false });
  if (!context.layers.length) return null;
  return {
    id: String(options.id || "geospatial-result").slice(0, 160),
    title: String(options.title || "Geospatial result").slice(0, 240),
    ...(options.sourceTool ? { sourceTool: String(options.sourceTool).slice(0, 160) } : {}),
    layers: context.layers,
    ...(context.bounds ? { bounds: context.bounds } : {}),
    crs: "OGC:CRS84",
    ...(context.warnings.length ? { warnings: context.warnings } : {}),
    stats: {
      featureCount: context.featureCount,
      geometryTypes: context.geometryTypes,
      layerCount: context.layers.length,
      truncated: context.truncated,
    },
  };
}

export const GEOSPATIAL_LIMITS = Object.freeze({ ...DEFAULT_LIMITS });
