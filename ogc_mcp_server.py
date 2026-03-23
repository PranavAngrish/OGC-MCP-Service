"""
OGC API – MCP Server (FastMCP version)
Exposes OGC API operations as MCP tools for LLM consumption.
"""

import json
import requests
from mcp.server.fastmcp import FastMCP

# ─── Configuration ────────────────────────────────────────────────────────────

OGC_BASE_URL = "http://localhost"
OGC_USERNAME = "admin"
OGC_PASSWORD = "admin123"

# ─── FastMCP instance ─────────────────────────────────────────────────────────

mcp = FastMCP("ogc-api-mcp")

# ─── Auth helper ──────────────────────────────────────────────────────────────

def get_token() -> str:
    """Get a fresh JWT token from the OGC API auth service."""
    response = requests.post(
        f"{OGC_BASE_URL}/auth/login",
        json={"username": OGC_USERNAME, "password": OGC_PASSWORD}
    )
    response.raise_for_status()
    return response.json()["token"]


def auth_headers() -> dict:
    """Return headers with a valid JWT token."""
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_token()}"
    }

# ─── Tools ────────────────────────────────────────────────────────────────────

@mcp.tool()
def list_processes() -> str:
    """Lists all geospatial processes available on this OGC API server.
    Use this when the user asks what processes are available,
    what the system can do, or whether a specific process exists."""

    response = requests.get(
        f"{OGC_BASE_URL}/processes",
        headers=auth_headers(),
        params={"f": "json"}
    )
    response.raise_for_status()
    processes = response.json().get("processes", [])

    lines = []
    for p in processes:
        lines.append(f"- {p.get('id')}: {p.get('description', 'No description')}")

    return f"Available processes ({len(processes)} total):\n" + "\n".join(lines)


@mcp.tool()
def get_process_details(process_id: str) -> str:
    """Gets the full description of a specific OGC API process including
    its required inputs and expected outputs.
    Use this before executing a process to understand what inputs it needs.

    Args:
        process_id: The ID of the process (e.g. 'buffer' or 'zonal-stats')
    """

    response = requests.get(
        f"{OGC_BASE_URL}/processes/{process_id}",
        headers=auth_headers(),
        params={"f": "json"}
    )
    response.raise_for_status()
    p = response.json()

    inputs_lines = []
    for input_name, input_def in p.get("inputs", {}).items():
        schema = input_def.get("schema", {})
        inputs_lines.append(
            f"  - {input_name} ({schema.get('type', 'unknown')}): "
            f"{input_def.get('description', 'No description')}"
        )

    return f"""Process: {p.get('id')}
Title: {p.get('title')}
Description: {p.get('description')}

Inputs:
{chr(10).join(inputs_lines)}"""


@mcp.tool()
def execute_buffer(latitude: float, longitude: float, distance: float) -> str:
    """Creates a circular buffer polygon around a coordinate point.
    Use when the user wants to:
    - Find things within a certain distance of a location
    - Create a zone or boundary around a point
    - Draw a radius around a place
    - Analyse what falls within X metres of somewhere

    Args:
        latitude: Latitude of the centre point in decimal degrees
        longitude: Longitude of the centre point in decimal degrees
        distance: Buffer radius in metres
    """

    response = requests.post(
        f"{OGC_BASE_URL}/processes/buffer/execution",
        headers=auth_headers(),
        json={"inputs": {
            "latitude": latitude,
            "longitude": longitude,
            "distance": distance
        }}
    )
    response.raise_for_status()
    result = response.json()

    props = result.get("properties", {})
    coords = result.get("geometry", {}).get("coordinates", [[]])[0]

    return f"""Buffer created successfully.

Centre: {props.get('center_latitude')}, {props.get('center_longitude')}
Radius: {props.get('distance_metres')} metres
Polygon points: {len(coords)}

Full GeoJSON:
{json.dumps(result, indent=2)}"""


@mcp.tool()
def execute_zonal_stats(
    zone_coordinates: list,
    values: list
) -> str:
    """Computes statistics over numeric values within a geographic zone.
    Use when the user wants to analyse values within a specific area
    or get statistics (average, min, max) for a region.

    Args:
        zone_coordinates: List of [longitude, latitude] pairs forming
                         a closed polygon ring. First and last point
                         must be the same.
                         Example: [[77.58,12.96],[77.61,12.96],
                                   [77.61,12.99],[77.58,12.99],
                                   [77.58,12.96]]
        values: List of numeric values to compute statistics on.
                Example: [12.5, 34.2, 8.9, 45.1, 23.7]
    """

    zone = {
        "type": "Polygon",
        "coordinates": [zone_coordinates]
    }

    response = requests.post(
        f"{OGC_BASE_URL}/processes/zonal-stats/execution",
        headers=auth_headers(),
        json={"inputs": {"zone": zone, "values": values}}
    )
    response.raise_for_status()
    stats = response.json().get("statistics", {})

    return f"""Zonal statistics computed successfully.

Count:          {stats.get('count')}
Sum:            {stats.get('sum')}
Minimum:        {stats.get('min')}
Maximum:        {stats.get('max')}
Mean:           {stats.get('mean')}
Median:         {stats.get('median')}
Std deviation:  {stats.get('std_dev')}
Range:          {stats.get('range')}"""


@mcp.tool()
def list_jobs() -> str:
    """Lists all submitted jobs and their current status.
    Use when the user wants to check on previous jobs or
    monitor running analyses."""

    response = requests.get(
        f"{OGC_BASE_URL}/jobs",
        headers=auth_headers(),
        params={"f": "json"}
    )
    response.raise_for_status()
    jobs = response.json().get("jobs", [])

    if not jobs:
        return "No jobs found."

    lines = []
    for j in jobs:
        lines.append(
            f"- {j.get('jobID', '')[:8]}... | "
            f"{j.get('processID')} | "
            f"{j.get('status')} | "
            f"{j.get('created', '')[:19]}"
        )

    return f"Jobs ({len(jobs)} total):\n" + "\n".join(lines)


@mcp.tool()
def get_job_results(job_id: str) -> str:
    """Retrieves the results of a completed OGC API job.
    Use when a job was submitted and you need to retrieve its output.

    Args:
        job_id: The full job UUID returned when the process was submitted
    """

    response = requests.get(
        f"{OGC_BASE_URL}/jobs/{job_id}/results",
        headers=auth_headers(),
        params={"f": "json"}
    )
    response.raise_for_status()
    result = response.json()

    return f"Results for job {job_id}:\n{json.dumps(result, indent=2)}"

# ─── OGC API – Features Tools ─────────────────────────────────────────────────

FEATURES_BASE_URL = "https://demo.pygeoapi.io/master"


@mcp.tool()
def features_list_collections() -> str:
    """Lists all available feature collections on the OGC API – Features server.
    Use this when the user wants to know:
    - What datasets are available
    - What layers exist on the server
    - What geographic data can be queried
    - What collections exist (roads, buildings, lakes, airports, etc.)
    Returns a list of collection IDs, titles, and descriptions."""

    response = requests.get(
        f"{FEATURES_BASE_URL}/collections",
        params={"f": "json"}
    )
    response.raise_for_status()
    collections = response.json().get("collections", [])

    lines = []
    for c in collections:
        title = c.get("title", c.get("id", "unknown"))
        cid = c.get("id", "unknown")
        desc = c.get("description", "No description")[:100]
        lines.append(f"- {cid}: {title} — {desc}")

    return f"""Available feature collections ({len(collections)} total):

{chr(10).join(lines)}

Use features_get_items with a collection_id to fetch actual features."""


@mcp.tool()
def features_get_collection_info(collection_id: str) -> str:
    """Gets detailed information about a specific feature collection.
    Use this before querying a collection to understand:
    - What attributes/properties the features have
    - What geographic area it covers (bounding box)
    - How many features it contains
    - What coordinate reference system it uses

    Args:
        collection_id: The ID of the collection (e.g. 'lakes', 'airports', 'roads')
    """

    response = requests.get(
        f"{FEATURES_BASE_URL}/collections/{collection_id}",
        params={"f": "json"}
    )
    response.raise_for_status()
    c = response.json()

    bbox = c.get("extent", {}).get("spatial", {}).get("bbox", [[]])[0]
    bbox_str = f"{bbox}" if bbox else "Not specified"

    return f"""Collection: {c.get('id')}
Title: {c.get('title', 'No title')}
Description: {c.get('description', 'No description')}
Bounding box: {bbox_str}

Use features_get_items to fetch actual features from this collection."""


@mcp.tool()
def features_get_items(
    collection_id: str,
    bbox: str = None,
    limit: int = 10,
    property_filter: str = None
) -> str:
    """Fetches features from an OGC API – Features collection.
    Use this when the user wants to:
    - Get actual geographic data (points, lines, polygons)
    - Find features in a specific area
    - Query a dataset for specific locations or objects
    - Retrieve roads, buildings, lakes, airports, or any vector data

    Args:
        collection_id: The collection to query (e.g. 'lakes', 'airports')
        bbox: Optional bounding box as 'minLon,minLat,maxLon,maxLat'
              Example: '77.4,12.8,77.8,13.1' for Bangalore area
              Leave empty to get features from anywhere
        limit: Maximum number of features to return (default 10, max 50)
        property_filter: Optional property name and value to filter by
                        Example: 'name=Bangalore' or 'type=airport'
    """

    params = {"f": "json", "limit": min(limit, 50)}

    if bbox:
        params["bbox"] = bbox

    if property_filter and "=" in property_filter:
        key, value = property_filter.split("=", 1)
        params[key.strip()] = value.strip()

    response = requests.get(
        f"{FEATURES_BASE_URL}/collections/{collection_id}/items",
        params=params
    )
    response.raise_for_status()
    data = response.json()

    features = data.get("features", [])
    total = data.get("numberMatched", "unknown")

    if not features:
        return f"No features found in collection '{collection_id}' with the given filters."

    lines = []
    for f in features:
        fid = f.get("id", "unknown")
        props = f.get("properties", {})
        geom_type = f.get("geometry", {}).get("type", "unknown") if f.get("geometry") else "no geometry"

        prop_summary = ", ".join(
            f"{k}={v}" for k, v in list(props.items())[:4] if v is not None
        )
        lines.append(f"- [{fid}] ({geom_type}) {prop_summary}")

    return f"""Features from '{collection_id}' (showing {len(features)} of {total} total):

{chr(10).join(lines)}

Use features_get_feature_by_id to get full details of a specific feature."""


@mcp.tool()
def features_get_feature_by_id(collection_id: str, feature_id: str) -> str:
    """Gets the complete details of a single feature by its ID.
    Use this when the user wants full details about a specific feature,
    or when you need the exact geometry of a feature to use in
    another operation (like zonal stats or buffer).

    Args:
        collection_id: The collection the feature belongs to
        feature_id: The ID of the specific feature to retrieve
    """

    response = requests.get(
        f"{FEATURES_BASE_URL}/collections/{collection_id}/items/{feature_id}",
        params={"f": "json"}
    )
    response.raise_for_status()
    feature = response.json()

    props = feature.get("properties", {})
    geom = feature.get("geometry", {})
    geom_type = geom.get("type", "unknown")

    props_lines = [f"  {k}: {v}" for k, v in props.items() if v is not None]

    return f"""Feature {feature_id} from '{collection_id}':

Geometry type: {geom_type}
Properties:
{chr(10).join(props_lines)}

Full GeoJSON:
{json.dumps(feature, indent=2)}"""



# ─── OGC API – Records Tools ──────────────────────────────────────────────────

RECORDS_BASE_URL = "https://demo.pycsw.org/gisdata"
RECORDS_COLLECTION = "metadata:main"


@mcp.tool()
def records_search(
    keyword: str = None,
    bbox: str = None,
    limit: int = 10
) -> str:
    """Searches a geospatial catalogue for datasets, maps, and data records.
    Use this when the user wants to:
    - Discover what datasets exist for a topic or area
    - Find data before querying or analysing it
    - Search for maps, satellite imagery, or geographic datasets
    - Look up metadata about available geospatial resources
    - Answer questions like 'is there data about X?'

    This should typically be the FIRST step before fetching or
    analysing data — use it to discover what is available.

    Args:
        keyword: Search term to find relevant datasets
                 Example: 'temperature', 'roads', 'flood', 'land use'
        bbox: Optional area filter as 'minLon,minLat,maxLon,maxLat'
              Example: '77.4,12.8,77.8,13.1' to find data near Bangalore
        limit: Maximum number of records to return (default 10)
    """

    params = {"f": "json", "limit": min(limit, 20)}

    if keyword:
        params["q"] = keyword

    if bbox:
        params["bbox"] = bbox

    response = requests.get(
        f"{RECORDS_BASE_URL}/collections/{RECORDS_COLLECTION}/items",
        params=params
    )
    response.raise_for_status()
    data = response.json()

    features = data.get("features", [])
    total = data.get("numberMatched", "unknown")

    if not features:
        return f"No records found matching '{keyword}'. Try a different search term."

    lines = []
    for f in features:
        props = f.get("properties", {})
        record_id = f.get("id", "unknown")
        title = props.get("title", "No title")
        description = props.get("description", props.get("abstract", "No description"))
        if description and len(description) > 120:
            description = description[:120] + "..."
        record_type = props.get("type", props.get("recordtype", "dataset"))
        lines.append(f"- [{record_id}]\n  Title: {title}\n  Type: {record_type}\n  Description: {description}")

    return f"""Catalogue search results for '{keyword}' ({len(features)} of {total} total):

{chr(10).join(lines)}

Use records_get_record with a record ID to get full metadata including download links."""


@mcp.tool()
def records_get_record(record_id: str) -> str:
    """Gets complete metadata for a specific catalogue record.
    Use this when the user wants full details about a specific dataset,
    including download links, data format, coordinate system,
    temporal coverage, and data provider information.

    Args:
        record_id: The ID of the record from records_search results
    """

    response = requests.get(
        f"{RECORDS_BASE_URL}/collections/{RECORDS_COLLECTION}/items/{record_id}",
        params={"f": "json"}
    )
    response.raise_for_status()
    feature = response.json()
    props = feature.get("properties", {})

    # Extract links
    links = feature.get("links", [])
    link_lines = []
    for link in links:
        rel = link.get("rel", "link")
        href = link.get("href", "")
        title = link.get("title", rel)
        if href:
            link_lines.append(f"  - {title}: {href}")

    # Extract key metadata
    title = props.get("title", "No title")
    description = props.get("description", props.get("abstract", "No description"))
    record_type = props.get("type", props.get("recordtype", "unknown"))
    created = props.get("created", props.get("date", "unknown"))
    updated = props.get("updated", props.get("modified", "unknown"))
    language = props.get("language", "unknown")
    keywords = props.get("keywords", props.get("subject", []))

    if isinstance(keywords, list):
        keywords_str = ", ".join(keywords[:8])
    else:
        keywords_str = str(keywords)

    # Spatial extent
    bbox = feature.get("bbox", [])
    bbox_str = f"{bbox}" if bbox else "Not specified"

    return f"""Record: {record_id}
Title: {title}
Type: {record_type}
Description: {description}

Spatial extent: {bbox_str}
Created: {created}
Updated: {updated}
Language: {language}
Keywords: {keywords_str}

Links:
{chr(10).join(link_lines) if link_lines else '  No links available'}"""


@mcp.tool()
def records_list_collections() -> str:
    """Lists all available catalogue collections on the OGC API – Records server.
    Use this first to discover what catalogues are available before searching.
    Returns collection IDs and descriptions."""

    response = requests.get(
        f"{RECORDS_BASE_URL}/collections",
        params={"f": "json"}
    )
    response.raise_for_status()
    collections = response.json().get("collections", [])

    lines = []
    for c in collections:
        cid = c.get("id", "unknown")
        title = c.get("title", "No title")
        desc = c.get("description", "No description")[:100]
        lines.append(f"- {cid}: {title} — {desc}")

    return f"""Available catalogue collections ({len(collections)} total):

{chr(10).join(lines)}

Use records_search with a keyword to find specific datasets."""


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()