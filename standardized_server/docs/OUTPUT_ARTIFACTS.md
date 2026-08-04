# Process Output Artifacts

Process execution and process output handling are deliberately separate. A
server can report that a process succeeded while its output is still pending,
stored behind a temporary reference, encoded in an unsupported representation,
or unavailable for visualization.

The reference implementation represents that lifecycle with a versioned output
manifest. The contract is defined by
[`../../spec/ogc-output-manifest.schema.json`](../../spec/ogc-output-manifest.schema.json).

## State Model

Four independent questions are tracked:

1. Did the process execute?
2. Was each output retrieved?
3. Was the retrieved representation interpreted?
4. Which presentations are ready?

For example, a successful process can legitimately produce:

```text
Execution       succeeded
Retrieval       retrieved
Interpretation  unsupported
Presentation    download ready; map unavailable
```

An unsupported preview never changes a successful process into a failed
process. Conversely, process success alone never means that an output was
downloaded, parsed, or displayed.

## Pipeline

```text
process description + confirmed execute request
  -> synchronous response or asynchronous job results
  -> advertised-output envelope extraction
  -> inline/reference resolution
  -> media-type detection
  -> parser adapter
  -> original, canonical, and bounded-preview artifact storage
  -> output manifest
  -> model-safe summary and UI presentations
```

The extractor recognizes advertised output identifiers and common OGC output
wrappers such as `value`, `data`, `href`, and nested `format.mediaType`. It does
not follow arbitrary links found in feature properties or records.

Format detection uses, in order:

1. the advertised process output;
2. the requested output format;
3. wrapper media-type metadata;
4. the resolved HTTP content type;
5. bounded content inspection;
6. a file extension as a weak final hint.

Declared and detected types are both retained. A disagreement becomes a
diagnostic rather than being silently ignored.

## Manifest Contents

Each manifest contains:

- execution identifiers and state;
- one entry per named output;
- independent retrieval and interpretation states;
- declared and detected media types;
- semantic type, CRS, bounding box, counts, units, and warnings when known;
- original, canonical, preview, or tile representations;
- available map, table, chart, metric, image, text, and download presentations;
- structured clarification requests when CRS, axis order, units, or coordinate
  columns cannot be interpreted without guessing;
- provenance for retrieval, parsing, conversion, and truncation.

Large or sensitive representations remain behind opaque handles. Canonical
representations preserve the complete converted result; distinct preview
representations contain bounded, renderer-safe subsets. The model receives a
compact verified summary, while a trusted client hydrates only the
representation needed for a presentation outside model context.

Renderer previews are capped at 100 KB. Tabular previews retain complete rows,
and GeoJSON previews retain complete features (up to 100 rows or 500 features);
an item that cannot fit is omitted rather than sliced into invalid JSON. Any
truncation is recorded on the preview representation, in output warnings, and
in provenance transformations. If no complete row or drawable feature fits,
the corresponding presentation is explicitly unavailable instead of falsely
reporting readiness.

## Output Types

The adapter registry distinguishes presentation from interpretation:

| Semantic output | Typical presentations |
| --- | --- |
| Vector feature or geometry | Map, feature table, canonical GeoJSON, original download |
| Raster or coverage | Metadata and original download; map unavailable until a deployment adds a compatible tiler or preview adapter |
| Tiles | Source metadata and a partial map presentation pending URL validation and user consent |
| Spatial table | Table and map |
| Non-spatial table | Paginated table |
| Time series | Chart and table |
| Scalar or statistic | Metric/value card |
| Image or document | Safe preview and download |
| Unknown or binary | Metadata and original download with an explicit unsupported diagnostic |

A map is created only when at least one validated drawable representation
exists. Reference-only and non-spatial outputs use their appropriate cards
instead of an empty map canvas.

Longitude/latitude columns can become a point layer when their names and values
are unambiguous. Generic `x`/`y` columns, CRS-less WKT, missing-CRS GML, mixed
CRS documents, and unsupported projections remain downloadable or
table-readable but unmapped. Their `clarificationRequest` explains the fact
needed before a safe interpretation can be made.

JSON and CSV tables are promoted to point GeoJSON only when exactly one
longitude column (`longitude`, `lon`, or `lng`) and one latitude column
(`latitude` or `lat`) are present and every retained coordinate is finite and
within CRS84 ranges. A supported declared `OGC:CRS84`/`EPSG:4326` CRS is
normalized; absent CRS metadata is inferred only from those explicit
longitude/latitude names. Ambiguous `x`/`y`, duplicate coordinate aliases,
unsupported declared CRS values, and naked numeric coordinate pairs remain
non-map outputs with warnings and a structured interpretation clarification.
Objects containing a `coordinates` pair require both a supported CRS and an
explicit axis order before conversion.

## Referenced Outputs

Output references are resolved by the standardized server, which owns the
registered server profile and its network policy. The browser and language
model do not fetch arbitrary upstream result URLs.

Resolution is bounded by origin policy, redirects, one shared wall-clock
deadline, one shared byte budget, fetch count, output count, parsing depth,
feature count, and coordinate count for the complete manifest build. Every
redirect target is revalidated. Registered-server authentication is never
forwarded to a different origin.

XML parsing rejects document type declarations and entity expansion, does not
load external resources, and applies element, depth, text, and coordinate
limits.

GML conversion is map-ready only when every geometry/member is successfully
interpreted, every effective CRS declaration is present and consistent, and
the normalized coordinates validate as CRS84. Missing, mixed, or unsupported
CRS declarations and skipped members preserve the original download but make
the map explicitly unavailable. CRS-less WKT follows the same fail-closed
rule and emits a presentation-scoped CRS clarification; only explicitly
declared supported SRIDs can produce a map.

See [Configuration](CONFIGURATION.md) for output-resolution policy and
[Security](SECURITY.md) for the wider trust boundary.

## Original And Derived Representations

The original server result is preserved. Conversion creates a separate derived
representation and records:

- the parser/converter;
- source and target media types;
- native and preview CRS;
- axis-order decision;
- transformations;
- sampling, simplification, or truncation;
- a digest linking the representation to its source.

Map-oriented vector previews use `OGC:CRS84`. Native data is not relabelled as
CRS84 without a supported transformation.

Bounded GeoJSON previews contain complete features only; geometry JSON is never
cut in the middle to meet a byte limit. Large table previews contain bounded
row subsets. Truncation is recorded as a warning or transformation, while the
original and complete canonical artifacts remain available for authorized
download.

## Synchronous And Asynchronous Results

Synchronous execution and `jobs.get_results` pass through the same resolver and
produce the same manifest shape. Background jobs add progress events, but do
not use a separate interpretation path. When a job reports success before its
result endpoint is ready, the gateway retries bounded transient failures and
pending or explicitly retryable artifact states; it never executes the process
a second time. A `201/202` response without a usable job identifier or Location
is reported as untrackable and unavailable rather than remaining in permanent
loading state.

An upstream `201`/`202` response is pending only when it supplies a job
identifier or tracking `Location`. An accepted response with neither is
terminally reported as `overallState="unavailable"` with
`execution.trackingState="unavailable"`; it is not left in an unmonitorable
pending state.

The activity lifecycle can therefore report:

```text
Process completed
-> Output reference received
-> Retrieving output
-> GML vector output detected
-> Canonical preview prepared
-> Map ready
```

Failures remain phase-specific, such as reference blocked, retrieval timed out,
media type unsupported, parsing failed, or presentation unavailable.

## Backward Compatibility

The manifest is additive. Existing `data`, `memory`, `guidance`, and legacy
`map_data` behavior remain available during migration. New clients should
prefer the canonical manifest. The UI gateway retains its bounded heuristic
normalizer only for older or third-party MCP servers that do not emit the
manifest.

Presentation readiness is verified again at the gateway boundary. A dangling
artifact reference, expired handle, invalid geometry, unsupported CRS, or
missing preview downgrades that presentation instead of leaving the renderer
in permanent loading state or displaying a blank map.

## Extending The Registry

New adapters implement four responsibilities:

1. probe a bounded sample and return a confidence level;
2. decode using explicit resource limits;
3. create a canonical or preview representation;
4. summarize only verified semantic metadata.

Unknown formats must fall back to an original artifact/download with a clear
diagnostic. An adapter must never perform the requested geospatial analysis
locally; representation conversion is permitted, while analytic computation
continues to belong to the selected OGC process.
