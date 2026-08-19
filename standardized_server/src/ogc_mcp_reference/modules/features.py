"""OGC API - Features operations."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlsplit

from ..errors import OgcMcpError
from ..registry import ServerRegistry
from ..result import success
from ..transport import OgcHttpClient
from ..services.sanitization import INSTRUCTION_PATTERNS


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]{0,199}$")
_SUPPORTED_FILTER_OPERATORS = frozenset(
    {"eq", "ne", "lt", "lte", "gt", "gte", "like", "contains_ci", "candidate_ci", "in"}
)
_FACT_ROW_LIMIT = 250
_FACT_COLUMN_LIMIT = 20
_FACT_BYTE_LIMIT = 256 * 1024
_MAX_QUERY_PAGES = 20
_MAX_QUERY_ITEMS = 5_000


def _segment(value: str) -> str:
    return quote(value, safe="")


class FeaturesService:
    """Discover and retrieve vector features from OGC API - Features."""

    def __init__(self, registry: ServerRegistry, client: OgcHttpClient) -> None:
        self._registry = registry
        self._client = client
        self._query_surfaces: dict[tuple[str, str], dict[str, Any]] = {}

    def list_collections(self, server_id: str = "") -> dict[str, Any]:
        server = self._registry.get(server_id, service="features")
        path = server.path("collections", "/collections")
        response = self._client.request(server, "GET", path, query={"f": "json"})
        return success(
            "features.list_collections",
            server,
            response,
            guidance={"next_tools": ["ogc_features_describe_collection", "ogc_features_get_items"]},
        )

    def describe_collection(self, collection_id: str, server_id: str = "") -> dict[str, Any]:
        server = self._registry.get(server_id, service="features")
        path = f"{server.path('collections', '/collections')}/{_segment(collection_id)}"
        response = self._client.request(server, "GET", path, query={"f": "json"})
        return success(
            "features.describe_collection",
            server,
            response,
            guidance={"next_tools": ["ogc_features_get_items"]},
        )

    def get_items(
        self,
        collection_id: str,
        *,
        server_id: str = "",
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        server = self._registry.get(server_id, service="features")
        path = f"{server.path('collections', '/collections')}/{_segment(collection_id)}/items"
        params = {"f": "json", **(query or {})}
        response = self._client.request(server, "GET", path, query=params)
        query_string = urlencode(params, doseq=True)
        reference_href = f"{server.base_url}{path}"
        if query_string:
            reference_href = f"{reference_href}?{query_string}"
        return success(
            "features.get_items",
            server,
            response,
            guidance={
                "reference_href": reference_href,
                "source": {
                    "server_id": server.id,
                    "collection_id": collection_id,
                    "href": reference_href,
                },
                "next_tools": ["ogc_features_get_item", "ogc_processes_list", "ogc_proxy_create_plan"],
                "workflow_hint": (
                    "To run a geospatial process on this data, follow the proxy plan workflow: "
                    "ogc_processes_list \u2192 ogc_processes_describe \u2192 ogc_proxy_create_plan. "
                    "Pass reference_href as a referenced input "
                    '({\"href\": \"<reference_href value>\"}) rather than copying feature '
                    "coordinates into model context, and include guidance.source in "
                    "the create-plan sources array. "
                    "NEVER perform spatial analysis yourself in any form \u2014 Python, bash, "
                    "JavaScript, visualization artifacts, or any other mechanism. "
                    "All geospatial computation MUST go through an OGC process (RULE 0)."
                ),
            },
        )

    def get_item(
        self,
        collection_id: str,
        item_id: str,
        *,
        server_id: str = "",
    ) -> dict[str, Any]:
        server = self._registry.get(server_id, service="features")
        path = (
            f"{server.path('collections', '/collections')}/"
            f"{_segment(collection_id)}/items/{_segment(item_id)}"
        )
        response = self._client.request(server, "GET", path, query={"f": "json"})
        return success(
            "features.get_item",
            server,
            response,
            guidance={"usage": "Use the returned GeoJSON inline only when a process expects one feature."},
        )

    def describe_query_surface(
        self,
        collection_id: str,
        server_id: str = "",
        *,
        refresh: bool = False,
    ) -> dict[str, Any]:
        """Discover the filterable and returnable surface of one collection.

        Discovery is deliberately best-effort across optional OGC API parts:
        the collection description is authoritative, while conformance,
        queryables, schema and one bounded sample are merged when available.
        This prevents an incomplete queryables document from hiding scalar
        properties that are nevertheless returned by the server.
        """
        server = self._registry.get(server_id, service="features")
        key = (server.id, collection_id)
        if not refresh and key in self._query_surfaces:
            cached = self._query_surfaces[key]
            return {**cached, "cache": {"hit": True}}

        collection_path = f"{server.path('collections', '/collections')}/{_segment(collection_id)}"
        collection_response = self._client.request(
            server,
            "GET",
            collection_path,
            query={"f": "json"},
        )
        collection = collection_response.data if isinstance(collection_response.data, dict) else {}
        warnings: list[str] = []

        conformance = self._optional_json(
            server,
            server.path("conformance", "/conformance"),
            warnings,
            label="conformance",
        )
        queryables = self._optional_json(
            server,
            f"{collection_path}/queryables",
            warnings,
            label="queryables",
        )
        sortables = self._optional_json(
            server,
            f"{collection_path}/sortables",
            warnings,
            label="sortables",
        )
        feature_schema = self._optional_json(
            server,
            f"{collection_path}/schema",
            warnings,
            label="feature schema",
        )
        sample_payload = self._optional_json(
            server,
            f"{collection_path}/items",
            warnings,
            label="sample feature",
            query={"f": "json", "limit": 1},
        )

        conforms_to = _string_list(
            conformance.get("conformsTo", conformance.get("conformsto", []))
            if isinstance(conformance, dict)
            else []
        )
        fields = _merge_fields(queryables, sortables, feature_schema, sample_payload)
        lowered_conformance = " ".join(conforms_to).lower()
        surface = {
            "ok": True,
            "operation": "features.describe_query_surface",
            "server": {
                "id": server.id,
                "title": server.title,
            },
            "collection": {
                "id": collection_id,
                "title": collection.get("title", collection_id),
                "description": collection.get("description", ""),
                "extent": _bounded_metadata(collection.get("extent")),
            },
            "capabilities": {
                "cql2": "cql2" in lowered_conformance,
                "cql2_text": "cql2-text" in lowered_conformance,
                "temporal_filter": "temporal" in lowered_conformance or "datetime" in lowered_conformance,
                "property_selection": "properties" in lowered_conformance,
                "queryables": bool(queryables),
                "sortables": bool(sortables),
                "feature_schema": bool(feature_schema),
                "versioned_features": "versioned-features" in lowered_conformance,
            },
            "fields": fields,
            "pagination": {
                "strategy": "follow_rel_next",
                "hardMaxPages": _MAX_QUERY_PAGES,
                "hardMaxItems": _MAX_QUERY_ITEMS,
            },
            "conformsTo": conforms_to,
            "warnings": warnings,
            "cache": {"hit": False},
        }
        self._query_surfaces[key] = surface
        return surface

    def query(self, plan: dict[str, Any]) -> dict[str, Any]:
        """Validate and execute one bounded, automatically paginated feature query."""
        collection_id = _required_text(plan.get("collection_id"), "collection_id")
        server_id = str(plan.get("server_id", ""))
        server = self._registry.get(server_id, service="features")
        surface = self.describe_query_surface(collection_id, server.id)
        fields_by_name = {
            str(field.get("name")): field
            for field in surface.get("fields", [])
            if isinstance(field, dict) and field.get("name")
        }

        requested_properties = _property_list(plan.get("properties"), fields_by_name)
        fact_properties = requested_properties or _default_fact_properties(fields_by_name)
        include_geometry = _boolean_parameter(plan.get("include_geometry", False), "include_geometry")
        filters = _filters(plan.get("filters", []), fields_by_name)
        combine = str(plan.get("combine", "and")).lower()
        if combine not in {"and", "or"}:
            raise OgcMcpError(
                "invalid_argument",
                "query_plan.combine must be 'and' or 'or'.",
                {"combine": combine},
            )
        if filters and not surface["capabilities"].get("cql2_text"):
            raise OgcMcpError(
                "unsupported_capability",
                "The collection does not advertise CQL2 text filtering.",
                {"server_id": server.id, "collection_id": collection_id},
            )

        page_size = _bounded_integer(plan.get("page_size", 100), "page_size", 1, 1_000)
        max_pages = _bounded_integer(plan.get("max_pages", 10), "max_pages", 1, _MAX_QUERY_PAGES)
        max_items = _bounded_integer(plan.get("max_items", 1_000), "max_items", 1, _MAX_QUERY_ITEMS)
        query: dict[str, Any] = {
            "f": "json",
            "limit": min(page_size, max_items),
        }
        if filters:
            query["filter"] = _cql_expression(filters, combine)
            query["filter-lang"] = "cql2-text"
        datetime_value = _datetime_parameter(plan.get("datetime"))
        if surface["capabilities"].get("versioned_features") and not datetime_value:
            raise OgcMcpError(
                "invalid_argument",
                "Versioned feature collections require an explicit query_plan.datetime. Use an instant for a snapshot or start/end for a historical interval.",
                {"field": "datetime", "collection_id": collection_id},
            )
        if datetime_value:
            query["datetime"] = datetime_value
        bbox_value = _bbox_parameter(plan.get("bbox"))
        if bbox_value:
            query["bbox"] = bbox_value
        if fact_properties and surface["capabilities"].get("property_selection"):
            selected = [item for item in fact_properties if item not in {"id", "geometry.type"}]
            if include_geometry:
                selected.append("geometry")
            if selected:
                query["properties"] = ",".join(dict.fromkeys(selected))
        sortby = _sort_parameter(plan.get("sortby"), fields_by_name)
        if sortby:
            query["sortby"] = sortby

        items_path = f"{server.path('collections', '/collections')}/{_segment(collection_id)}/items"
        first_query = dict(query)
        current_query = dict(query)
        pages = 0
        matched: int | None = None
        features: list[dict[str, Any]] = []
        seen_pages: set[tuple[tuple[str, str], ...]] = set()
        stopped_reason = ""
        first_response = None
        next_available = False

        while pages < max_pages and len(features) < max_items:
            signature = tuple(sorted((str(key), str(value)) for key, value in current_query.items()))
            if signature in seen_pages:
                stopped_reason = "pagination_loop"
                break
            seen_pages.add(signature)
            response = self._client.request(server, "GET", items_path, query=current_query)
            if first_response is None:
                first_response = response
            payload = response.data
            if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
                raise OgcMcpError(
                    "invalid_upstream_response",
                    "The collection query did not return a GeoJSON FeatureCollection.",
                    {"server_id": server.id, "collection_id": collection_id},
                )
            pages += 1
            if isinstance(payload.get("numberMatched"), int):
                matched = max(matched or 0, payload["numberMatched"])
            remaining = max_items - len(features)
            page_features = [item for item in payload["features"] if isinstance(item, dict)]
            features.extend(page_features[:remaining])
            next_query = _next_page_query(payload, server.base_url, items_path)
            next_available = next_query is not None
            if not next_query:
                break
            if len(features) >= max_items:
                stopped_reason = "max_items"
                break
            current_query = next_query

        if next_available and not stopped_reason and pages >= max_pages:
            stopped_reason = "max_pages"
        complete = not next_available and not stopped_reason
        if matched is not None and len(features) < matched:
            complete = False
            if not stopped_reason:
                stopped_reason = "upstream_results_remaining"

        facts = _facts_table(features, fact_properties)
        missing_properties = [
            name for name in facts["columns"]
            if features and not any(name in row for row in facts["rows"])
        ]
        facts_truncated = len(facts["rows"]) < len(features)
        evidence_reasons: list[str] = []
        evidence_qualifications: list[str] = []
        candidate_discovery = any(item.get("operator") == "candidate_ci" for item in filters)
        if not complete:
            evidence_reasons.append(
                f"Upstream retrieval is incomplete ({stopped_reason or 'additional results remain'})."
            )
        if facts_truncated:
            evidence_reasons.append(
                f"The model-safe facts table contains {len(facts['rows'])} of {len(features)} retrieved rows within its row/byte bounds; refine the query."
            )
        if missing_properties:
            evidence_reasons.append(
                f"Requested properties were absent from every returned feature: {', '.join(missing_properties)}."
            )
        if candidate_discovery:
            evidence_reasons.append(
                "This fuzzy name query is candidate discovery only. Select the intended aliases and run a precise eq or in query before making factual claims."
            )
        exact_name_miss = (
            not features
            and surface["capabilities"].get("versioned_features")
            and any(
                item.get("property") == "name" and item.get("operator") == "eq"
                for item in filters
            )
        )
        if exact_name_miss:
            evidence_reasons.append(
                "The exact historical name query returned no rows. Discover candidates with contains_ci and a stable name prefix, then query the confirmed aliases with one in filter."
            )
        if bbox_value:
            evidence_qualifications.append(
                "The bbox filter uses spatial-intersection semantics; it identifies features that touch the box, not semantic membership in a named region."
            )
        if not filters and not bbox_value:
            evidence_qualifications.append(
                "No region or property predicate was applied. Any named-region subset derived from these rows is an interpretive classification, not a classification asserted by the OGC collection."
            )
        if not include_geometry and not surface["capabilities"].get("property_selection"):
            evidence_qualifications.append(
                "The server does not advertise property selection, so geometry could not be excluded from the private upstream response."
            )
        safe_to_answer = not evidence_reasons

        aggregated = {
            "type": "FeatureCollection",
            "numberReturned": len(features),
            **({"numberMatched": matched} if matched is not None else {}),
            "features": features,
            "queryCompleteness": {
                "complete": complete,
                "pages": pages,
                "retrieved": len(features),
                "matched": matched,
                "stoppedReason": stopped_reason or None,
            },
        }
        assert first_response is not None
        result = success(
            "features.query",
            server,
            first_response,
            data={
                "facts": {
                    **facts,
                    "retrievedRows": len(features),
                    "truncated": facts_truncated,
                },
                "pagination": {
                    "matched": matched,
                    "retrieved": len(features),
                    "pages": pages,
                    "complete": complete,
                    "stoppedReason": stopped_reason or None,
                },
                "evidence": {
                    "safeToAnswer": safe_to_answer,
                    "complete": complete,
                    "serverId": server.id,
                    "collectionId": collection_id,
                    "requestedProperties": fact_properties,
                    "missingProperties": missing_properties,
                    "reasons": evidence_reasons,
                    "qualifications": evidence_qualifications,
                    **(
                        {"suggestedFilters": _historical_name_suggestions(filters)}
                        if exact_name_miss
                        else {}
                    ),
                },
                "query": {
                    "filters": filters,
                    "combine": combine,
                    "datetime": datetime_value or None,
                    "bbox": bbox_value or None,
                    "sortby": sortby or None,
                    "includeGeometry": include_geometry,
                },
            },
            guidance={
                "reference_href": _reference_href(server.base_url, items_path, first_query),
                "source": {
                    "server_id": server.id,
                    "collection_id": collection_id,
                },
                "answer_policy": (
                    "Verified facts are complete and safe to summarize."
                    if safe_to_answer
                    else "Do not answer from these rows yet; refine the query using evidence.reasons."
                ),
            },
        )
        result["_feature_collection"] = aggregated
        return result

    def _optional_json(
        self,
        server,
        path: str,
        warnings: list[str],
        *,
        label: str,
        query: dict[str, Any] | None = None,
    ) -> Any:
        try:
            return self._client.request(
                server,
                "GET",
                path,
                query=query or {"f": "json"},
            ).data
        except OgcMcpError as exc:
            warnings.append(f"Optional {label} discovery failed: {exc.code}.")
            return {}


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _bounded_metadata(value: Any) -> Any:
    if not isinstance(value, dict):
        return None
    return json.loads(json.dumps(value))


def _schema_properties(value: Any, depth: int = 0) -> dict[str, Any]:
    if not isinstance(value, dict) or depth > 6:
        return {}
    properties = value.get("properties")
    if isinstance(properties, dict):
        nested = properties.get("properties")
        if isinstance(nested, dict) and isinstance(nested.get("properties"), dict):
            return nested["properties"]
        non_geo = {
            key: item for key, item in properties.items()
            if key not in {"type", "id", "geometry", "bbox"}
        }
        if non_geo:
            return non_geo
    for item in value.values():
        discovered = _schema_properties(item, depth + 1)
        if discovered:
            return discovered
    return {}


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _merge_fields(
    queryables: Any,
    sortables: Any,
    feature_schema: Any,
    sample_payload: Any,
) -> list[dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {
        "id": {"name": "id", "type": "string", "filterable": False, "sortable": False, "returnable": True, "observed": True},
        "geometry.type": {"name": "geometry.type", "type": "string", "filterable": False, "sortable": False, "returnable": True, "observed": True},
    }
    queryable_properties = queryables.get("properties", {}) if isinstance(queryables, dict) else {}
    if isinstance(queryable_properties, dict):
        for name, schema in queryable_properties.items():
            if name == "geometry" or not _IDENTIFIER.fullmatch(str(name)):
                continue
            schema = schema if isinstance(schema, dict) else {}
            fields[str(name)] = {
                "name": str(name),
                "title": str(schema.get("title", name)),
                "type": str(schema.get("type", "unknown")),
                "format": str(schema.get("format", "")),
                "filterable": True,
                "sortable": False,
                "returnable": False,
                "observed": False,
            }
    sortable_properties = sortables.get("properties", {}) if isinstance(sortables, dict) else {}
    if isinstance(sortable_properties, dict):
        for name, schema in sortable_properties.items():
            if not _IDENTIFIER.fullmatch(str(name)):
                continue
            schema = schema if isinstance(schema, dict) else {}
            field = fields.setdefault(str(name), {"name": str(name)})
            field.update({
                "title": str(schema.get("title", field.get("title", name))),
                "type": str(schema.get("type", field.get("type", "unknown"))),
                "filterable": bool(field.get("filterable", False)),
                "sortable": True,
                "returnable": bool(field.get("returnable", False)),
                "observed": bool(field.get("observed", False)),
            })
    for name, schema in _schema_properties(feature_schema).items():
        if not _IDENTIFIER.fullmatch(str(name)):
            continue
        schema = schema if isinstance(schema, dict) else {}
        field = fields.setdefault(str(name), {"name": str(name)})
        field.update({
            "title": str(schema.get("title", field.get("title", name))),
            "type": str(schema.get("type", field.get("type", "unknown"))),
            "format": str(schema.get("format", field.get("format", ""))),
            "filterable": bool(field.get("filterable", False)),
            "sortable": bool(field.get("sortable", False)),
            "returnable": True,
            "observed": bool(field.get("observed", False)),
        })
    features = sample_payload.get("features", []) if isinstance(sample_payload, dict) else []
    sample = features[0] if isinstance(features, list) and features and isinstance(features[0], dict) else {}
    sample_properties = sample.get("properties", {}) if isinstance(sample, dict) else {}
    if isinstance(sample_properties, dict):
        for name, value in sample_properties.items():
            if not _IDENTIFIER.fullmatch(str(name)):
                continue
            field = fields.setdefault(str(name), {"name": str(name)})
            field.update({
                "title": str(field.get("title", name)),
                "type": str(field.get("type", _value_type(value))),
                "format": str(field.get("format", "")),
                "filterable": bool(field.get("filterable", False)),
                "sortable": bool(field.get("sortable", False)),
                "returnable": True,
                "observed": True,
            })
    return sorted(fields.values(), key=lambda item: item["name"])


def _required_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise OgcMcpError("invalid_argument", f"query_plan.{label} is required.", {"field": label})
    return text


def _bounded_integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise OgcMcpError(
            "invalid_argument",
            f"query_plan.{label} must be an integer between {minimum} and {maximum}.",
            {"field": label, "minimum": minimum, "maximum": maximum},
        )
    return value


def _boolean_parameter(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise OgcMcpError("invalid_argument", f"query_plan.{label} must be a boolean.")
    return value


def _property_list(value: Any, fields: dict[str, dict[str, Any]]) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise OgcMcpError("invalid_argument", "query_plan.properties must be a non-empty string array.")
    names = list(dict.fromkeys(item.strip() for item in value if item.strip()))
    unknown = [name for name in names if name not in fields]
    if unknown:
        raise OgcMcpError(
            "invalid_argument",
            "query_plan.properties contains fields not discovered for this collection.",
            {"unknown": unknown, "available": sorted(fields)},
        )
    return names[:_FACT_COLUMN_LIMIT]


def _filters(value: Any, fields: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise OgcMcpError("invalid_argument", "query_plan.filters must be an array.")
    normalized = []
    for index, candidate in enumerate(value):
        if not isinstance(candidate, dict):
            raise OgcMcpError("invalid_argument", "Every query_plan.filters item must be an object.")
        name = str(candidate.get("property", ""))
        operator = str(candidate.get("operator", "eq")).lower()
        if name not in fields or not fields[name].get("filterable"):
            raise OgcMcpError(
                "invalid_argument",
                f"Filter property '{name}' is not advertised as queryable.",
                {"index": index, "available": sorted(key for key, item in fields.items() if item.get("filterable"))},
            )
        if operator not in _SUPPORTED_FILTER_OPERATORS:
            raise OgcMcpError(
                "invalid_argument",
                f"Unsupported filter operator '{operator}'.",
                {"index": index, "supported": sorted(_SUPPORTED_FILTER_OPERATORS)},
            )
        filter_value = candidate.get("value")
        if operator == "in" and (not isinstance(filter_value, list) or not filter_value):
            raise OgcMcpError("invalid_argument", "The 'in' filter operator requires a non-empty value array.")
        normalized.append({"property": name, "operator": operator, "value": filter_value})
    return normalized[:20]


def _cql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return f"'{str(value).replace(chr(39), chr(39) * 2)}'"


def _cql_expression(filters: list[dict[str, Any]], combine: str) -> str:
    operators = {"eq": "=", "ne": "<>", "lt": "<", "lte": "<=", "gt": ">", "gte": ">="}
    expressions = []
    for item in filters:
        name = item["property"]
        operator = item["operator"]
        value = item["value"]
        if operator in operators:
            expression = f"{name} {operators[operator]} {_cql_literal(value)}"
        elif operator == "like":
            expression = f"{name} LIKE {_cql_literal(value)}"
        elif operator in {"contains_ci", "candidate_ci"}:
            expression = f"CASEI({name}) LIKE CASEI({_cql_literal(f'%{value}%')})"
        else:
            expression = f"{name} IN ({', '.join(_cql_literal(candidate) for candidate in value)})"
        expressions.append(f"({expression})")
    return f" {combine.upper()} ".join(expressions)


def _datetime_parameter(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        raise OgcMcpError("invalid_argument", "query_plan.datetime must be a string or object.")
    start = str(value.get("start", "..")).strip() or ".."
    end = str(value.get("end", "..")).strip() or ".."
    return f"{start}/{end}"


def _bbox_parameter(value: Any) -> str:
    if value in (None, ""):
        return ""
    if not isinstance(value, list) or len(value) not in {4, 6} or not all(
        isinstance(item, (int, float)) and not isinstance(item, bool) for item in value
    ):
        raise OgcMcpError("invalid_argument", "query_plan.bbox must contain four or six numbers.")
    return ",".join(str(item) for item in value)


def _sort_parameter(value: Any, fields: dict[str, dict[str, Any]]) -> str:
    if value in (None, ""):
        return ""
    values = [value] if isinstance(value, (str, dict)) else value
    if not isinstance(values, list):
        raise OgcMcpError("invalid_argument", "query_plan.sortby must be a string or array.")
    normalized = []
    for item in values:
        if isinstance(item, dict):
            name = str(item.get("property", "")).strip()
            order = str(item.get("order", "asc")).strip().lower()
            if order not in {"a", "asc", "ascending", "d", "desc", "descending"}:
                raise OgcMcpError("invalid_argument", f"Unknown sort order '{order}'.")
            direction = "-" if order in {"d", "desc", "descending"} else "+"
        elif isinstance(item, str):
            candidate = item.strip()
            match = re.fullmatch(r"([+-]?)([A-Za-z_][A-Za-z0-9_.:-]*)(?:\s+(ASC|DESC))?", candidate, re.I)
            if not match:
                raise OgcMcpError("invalid_argument", f"Invalid sort expression '{candidate}'.")
            prefix, name, word_order = match.groups()
            direction = "-" if (word_order or "").upper() == "DESC" else prefix
            if word_order and word_order.upper() == "ASC":
                direction = "+"
        else:
            raise OgcMcpError("invalid_argument", "Every query_plan.sortby item must be a string or object.")
        if name not in fields or not fields[name].get("sortable"):
            raise OgcMcpError(
                "invalid_argument",
                f"Sort property '{name}' is not advertised as sortable.",
                {"available": sorted(key for key, item in fields.items() if item.get("sortable"))},
            )
        normalized.append(f"{direction}{name}")
    return ",".join(normalized)


def _next_page_query(payload: dict[str, Any], base_url: str, expected_path: str) -> dict[str, Any] | None:
    base = urlsplit(base_url)
    for link in payload.get("links", []):
        if not isinstance(link, dict) or str(link.get("rel", "")).lower() != "next":
            continue
        href = str(link.get("href", ""))
        parsed = urlsplit(href)
        if parsed.scheme and (
            parsed.scheme.lower() != base.scheme.lower()
            or (parsed.hostname or "").lower() != (base.hostname or "").lower()
            or parsed.port != base.port
        ):
            raise OgcMcpError("security_policy_error", "Upstream pagination link changed origin.")
        base_path = base.path.rstrip("/")
        relative_path = parsed.path
        if base_path and relative_path.startswith(base_path):
            relative_path = relative_path[len(base_path):] or "/"
        if relative_path != expected_path:
            raise OgcMcpError(
                "security_policy_error",
                "Upstream pagination link changed the collection items path.",
                {"expected": expected_path, "received": relative_path},
            )
        return {
            key: values if len(values) > 1 else values[0]
            for key, values in parse_qs(parsed.query, keep_blank_values=True).items()
        }
    return None


def _safe_fact(value: Any) -> Any:
    if isinstance(value, str):
        cleaned = value.strip()[:2_000]
        return "[removed]" if any(pattern.search(cleaned) for pattern in INSTRUCTION_PATTERNS) else cleaned
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return None


def _fact_value(feature: dict[str, Any], name: str) -> Any:
    if name == "id":
        return _safe_fact(feature.get("id"))
    if name == "geometry.type":
        geometry = feature.get("geometry")
        return _safe_fact(geometry.get("type")) if isinstance(geometry, dict) else None
    properties = feature.get("properties")
    if not isinstance(properties, dict):
        return None
    path = name[len("properties."):] if name.startswith("properties.") else name
    current: Any = properties
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return _safe_fact(current)


def _facts_table(features: list[dict[str, Any]], properties: list[str]) -> dict[str, Any]:
    columns = list(dict.fromkeys(properties))[:_FACT_COLUMN_LIMIT]
    rows = []
    serialized_bytes = 0
    for feature in features[:_FACT_ROW_LIMIT]:
        row = {
            name: value
            for name in columns
            if (value := _fact_value(feature, name)) is not None
        }
        row_bytes = len(json.dumps(row, ensure_ascii=False).encode("utf-8"))
        if rows and serialized_bytes + row_bytes > _FACT_BYTE_LIMIT:
            break
        rows.append(row)
        serialized_bytes += row_bytes
    return {
        "columns": columns,
        "rows": rows,
        "serializedBytes": serialized_bytes,
        "rowLimit": _FACT_ROW_LIMIT,
        "byteLimit": _FACT_BYTE_LIMIT,
    }


def _historical_name_suggestions(filters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    suggestions = []
    for item in filters:
        if item.get("property") != "name" or item.get("operator") != "eq":
            continue
        value = str(item.get("value", "")).strip()
        prefix_length = max(4, min(len(value), len(value) - 1 if len(value) > 6 else len(value)))
        suggestions.append({
            "property": "name",
            "operator": "candidate_ci",
            "value": value[:prefix_length],
        })
    return suggestions


def _default_fact_properties(fields: dict[str, dict[str, Any]]) -> list[str]:
    scalar = [
        name for name, field in fields.items()
        if field.get("type") in {"string", "number", "integer", "boolean"}
        and not re.search(
            r"(?:^|[_.:-])(?:geometry|bbox|bounds|coordinates?|lon|lng|long|longitude|lat|latitude|x|y|z|easting|northing)(?:$|[_.:-])",
            name,
            re.I,
        )
        and not re.fullmatch(r"cap(?:lat|lon|lng|long|latitude|longitude)", name, re.I)
    ]
    preferred = ["id", "name", "title", "description"]
    return list(dict.fromkeys(
        [name for name in preferred if name in scalar]
        + scalar
    ))[:_FACT_COLUMN_LIMIT]


def _reference_href(base_url: str, path: str, query: dict[str, Any]) -> str:
    return f"{base_url}{path}?{urlencode(query, doseq=True)}"
