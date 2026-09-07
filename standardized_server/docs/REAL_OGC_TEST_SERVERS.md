# Real OGC test deployment and full-potential prompt

This note records a public, operational test target for the proxy. The real
server profiles are included directly in `config.example.json`; the demo
profiles remain available for smoke testing and fallback comparisons.

## Recommended target: Spain's National Cartographic System

The best public match found for this project is the IDEE/IGN (Infraestructura
de Datos Espaciales de España / Instituto Geográfico Nacional) deployment:

| Capability | Base URL | Why it is useful |
| --- | --- | --- |
| OGC API - Processes | `https://api-processes.idee.es` | Official processes for point elevation, elevation profiles, polygon elevation statistics, buffers, coordinate transformation, cadastral/solar-radiation queries, and footprint searches. |
| OGC API - Features | `https://api-features.idee.es` | Large national feature catalogue (addresses, land use, transport, hydrography and other INSPIRE themes) with paginated GeoJSON. |
| OGC API - Maps/Coverages | `https://api-maps.idee.es` / `https://api-coverages.idee.es` | National map and coverage representations, including the 5-metre digital terrain model. These are useful as reference URLs, although the current proxy configuration exposes common/features/processes only. |

The official IGN service catalogue identifies the Processes endpoint and the
Features endpoint. The Processes landing page describes the provider as IDEE
and exposes the service under the OGC API - Processes standard:
[IGN service catalogue](https://www.ign.es/web/es/ign/portal/ide-area-nodo-ide-ign),
[Processes landing page](https://api-processes.idee.es/?f=html), and
[Features collections](https://api-features.idee.es/collections?f=json).

The service is substantially more realistic than a demo. Its process
descriptions identify the MDT05 (5-metre digital terrain model) as the source
for elevation, profiles and statistics. For example,
[getElevation](https://api-processes.idee.es/processes/getElevation?f=json)
accepts a GeoJSON FeatureCollection of points and returns one elevation per
point; [elevationProfile](https://api-processes.idee.es/processes/elevationProfile?f=json)
densifies a line of points and returns elevations and sub-segment distances;
and [simplifiedStatistics](https://api-processes.idee.es/processes/simplifiedStatistics?f=json)
returns minimum, maximum, mean and standard deviation for a polygon or bbox.
The [solar-radiation process](https://api-processes.idee.es/processes/radiacion_solar?f=json)
queries building/point data and returns GeoJSON plus aggregate values.

The OGC API - Processes contract is the expected discover → describe → execute
→ job/result sequence: `/processes`, `/processes/{id}`, and
`/processes/{id}/execution`, with `/jobs` for asynchronous implementations.
See the [OGC Processes overview](https://ogcapi.ogc.org/processes/overview.html).

## Configuration

The ready-to-use profiles are included in
[`config.example.json`](../config.example.json). Start the Python MCP server
with that configuration, for example:

```bash
ogc-mcp-server --config standardized_server/config.example.json
```

Keep `expose_direct_execution_tools` disabled. Let the model discover and
describe a process, create a plan, and use the approval step before execution.
The profile uses bounded timeouts and response sizes because a national
collection must never be downloaded into the model context in one request.

## Prompt to exercise the whole system

Paste the following as one user message after selecting the real-OGC profile:

> Use the registered Spain National Cartographic System servers (`idee-features` and `idee-processes`) and complete this end-to-end geospatial analysis for the Madrid area (approximately bbox `[-3.90, 40.30, -3.55, 40.55]`, WGS84). First discover the available feature collections and OGC API Processes; do not download an unbounded collection. Query a bounded, paginated sample of an appropriate national feature collection for that bbox and retain the full response in proxy memory. Then run `simplifiedStatistics` on the bbox using the MDT05 terrain model, run `getElevation` for at least five points distributed across the bbox, and run `elevationProfile` along a line crossing the area with intermediate samples every 1 km. If the process metadata supports it, run `bufferElevation` around one point with a 2 km radius and request statistics. Ask for approval before every mutating or costly process execution. After the tools finish, return a concise natural-language interpretation and render every applicable output: (1) a map for returned GeoJSON/features, with coordinates hydrated from the `mem_*` handles rather than sent to the model; (2) a table for the bounded feature sample and point elevations; (3) a line chart of the elevation profile, using distance on the x-axis and elevation on the y-axis; (4) metric cards for min/max/mean/standard-deviation and any solar or buffer aggregates; and (5) download links for the complete raw results. Explain which outputs were truncated for model context, show the memory/artifact handles, state the CRS and units, and report any unsupported raster/coverage visualisation instead of inventing a chart. Do not fabricate values, coordinates, process IDs, or collection IDs; if a collection or process is unavailable, use the discovered metadata and continue with the closest valid alternative.

## What a successful run should demonstrate

1. Capability discovery selects the registered real servers instead of the
   demo server.
2. Feature results are paginated and summarized; the complete payload is kept
   behind a `mem_*` handle.
3. The node gateway receives coordinate-stripped context while the renderer
   privately hydrates geometry for the map.
4. Process metadata is consulted before input construction and execution.
5. The approval gate and (where offered by the upstream) job/status path are
   visible in the event stream.
6. The output artifact manifest drives map, table, chart, metric and download
   renderers independently.

### IDEE/IGN result-retrieval quirk

The IDEE `getElevation` endpoint can return a complete result with HTTP 200
and a `Location: /jobs/...` header. The inline body is valid (for example, the
`values` array contains the elevation), but the corresponding `/jobs/{id}` and
`/jobs/{id}/results` routes may return HTTP 500. The proxy now recognizes an
inline result, marks the execution completed, and does not follow that
misleading job location. This preserves the returned values and prevents the
failure described above.

## Important limits and alternatives

The IDEE service is the recommended no-credential test. Public production OGC
API - Processes deployments that combine very large Earth-observation holdings
with unrestricted processing are uncommon. NASA Harmony is an excellent
second-stage target for genuinely large Earth-observation transformations, but
it uses OGC-inspired Coverages/EDR/WMS APIs and requires an Earthdata Login for
transformations, so it is not a drop-in OGC API - Processes server for the
current proxy. See the [Harmony documentation](https://harmony.earthdata.nasa.gov/docs)
and [Harmony landing page](https://harmony.earthdata.nasa.gov/).

USGS Water Data is another strong real-data source for the Features side: its
official OGC API exposes continuous and daily monitoring data, pagination, and
large result sets. Its landing page advertises a `/processes` link, but its
published conformance declaration is Features-focused; treat it as a data
server unless a live capability check confirms a process implementation. See
the [USGS Water OGC API guide](https://api.waterdata.usgs.gov/docs/ogcapi).
