"""Generalized canonical output-artifact pipeline."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from ..errors import OgcMcpError, SecurityPolicyError
from ..models import OgcResponse, ServerProfile
from ..transport import OgcHttpClient, OutputResolutionBudget
from .detection import detect_media_type, normalize_media_type
from .extractors import extract_outputs
from .models import (
    SCHEMA_VERSION,
    OutputCandidate,
    ParsedArtifact,
    interpretation_state,
    retrieval_state,
)
from .parsers.geojson import bbox_for_geojson
from .previews import bounded_geojson_preview, bounded_json_preview
from .registry import ParserRegistry
from .store import ArtifactStore


@dataclass
class _ResolvedOutput:
    candidate: OutputCandidate
    value: Any
    source: str
    http_content_type: str
    size_bytes: int
    http_status: int | None = None
    redirect_count: int = 0
    request_path: str = ""
    container_warnings: tuple[str, ...] = ()


def _size(value: Any) -> int:
    if isinstance(value, bytes):
        return len(value)
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    return len(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    )


def _sha256(value: Any) -> str:
    if isinstance(value, bytes):
        raw = value
    elif isinstance(value, str):
        raw = value.encode("utf-8")
    else:
        raw = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _preview_was_truncated(parsed: ParsedArtifact, preview_value: Any, original: Any) -> bool:
    """Detect renderer subsets without confusing harmless GeoJSON metadata loss."""
    if parsed.has_canonical_data:
        canonical = parsed.canonical_data
        if parsed.semantic_type == "vector":
            canonical_features = (
                canonical.get("features") if isinstance(canonical, dict) else None
            )
            preview_features = (
                preview_value.get("features")
                if isinstance(preview_value, dict)
                else None
            )
            return (
                isinstance(canonical_features, list)
                and isinstance(preview_features, list)
                and len(preview_features) < len(canonical_features)
            )
        if parsed.semantic_type in {"table", "timeseries"}:
            return (
                isinstance(canonical, list)
                and isinstance(preview_value, list)
                and len(preview_value) < len(canonical)
            )
        return preview_value != canonical
    if parsed.has_preview:
        try:
            return _size(preview_value) < _size(original)
        except (TypeError, ValueError):
            return True
    return False


def _reported_status(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    value = data.get("status") or data.get("state")
    return str(value)[:200] if value is not None else ""


def _job_id(data: Any, location: str = "") -> str:
    if isinstance(data, dict):
        value = data.get("jobID") or data.get("jobId")
        if value:
            return str(value)[:300]
    if "/jobs/" in location:
        return location.split("/jobs/", 1)[1].split("/", 1)[0][:300]
    return ""


def _requested_output_ids(execute_request: dict[str, Any] | None) -> tuple[str, ...]:
    outputs = (execute_request or {}).get("outputs")
    if isinstance(outputs, dict):
        return tuple(str(key) for key in outputs)
    if isinstance(outputs, list):
        return tuple(
            str(item.get("id"))
            for item in outputs
            if isinstance(item, dict) and item.get("id")
        )
    return ()


def _error(code: str, message: str, phase: str, *, retryable: bool = False) -> dict[str, Any]:
    return {
        "code": code,
        "message": message[:2000],
        "phase": phase,
        "retryable": retryable,
    }


def _clarification_request(
    output_id: str,
    issues: list[dict[str, Any]],
    *,
    blocking: bool = False,
    scope: str = "interpretation",
) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(issues[:100]):
        field_path = str(item.get("fieldPath") or "columns")[:450]
        normalized.append(
            {
                "id": str(item.get("id") or f"output-issue-{index + 1}")[:200],
                "kind": str(item.get("kind") or "presentation")[:100],
                "fieldPath": f"outputs.{output_id[:200]}.{field_path}"[:500],
                "question": str(
                    item.get("question")
                    or "How should this output be interpreted?"
                )[:2000],
                "whyItMatters": str(
                    item.get("whyItMatters")
                    or "The answer determines whether a safe map can be created."
                )[:4000],
                "allowFreeText": bool(item.get("allowFreeText", True)),
                **(
                    {"observedValue": item["observedValue"]}
                    if "observedValue" in item
                    else {}
                ),
            }
        )
    return {
        "blocking": blocking,
        "scope": scope
        if scope in {"execution", "interpretation", "presentation"}
        else "interpretation",
        "issues": normalized,
    }


class OutputArtifactPipeline:
    """Resolve, parse, store and describe process outputs.

    The pipeline never mutates the legacy response body.  Its manifest is an
    additive contract that lets old clients keep using ``data``/``memory`` and
    new clients rely on explicit retrieval and interpretation states.
    """

    def __init__(
        self,
        *,
        client: OgcHttpClient,
        store: ArtifactStore,
        parsers: ParserRegistry | None = None,
    ) -> None:
        self._client = client
        self._store = store
        self._parsers = parsers or ParserRegistry()

    @property
    def store(self) -> ArtifactStore:
        return self._store

    def build(
        self,
        response: OgcResponse,
        *,
        server: ServerProfile,
        operation: str,
        process_id: str = "",
        job_id: str = "",
        plan_id: str = "",
        execute_request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build one schema-valid output manifest from an upstream response."""
        async_submission = operation == "processes.execute" and (
            response.status_code in {201, 202}
            or _reported_status(response.data).casefold()
            in {"accepted", "running", "queued", "pending"}
        )
        execution_state = "submitted" if async_submission else "succeeded"
        execution: dict[str, Any] = {
            "state": execution_state,
            "serverId": server.id,
        }
        if process_id:
            execution["processId"] = process_id[:300]
        resolved_job_id = job_id or _job_id(response.data, response.location)
        if resolved_job_id:
            execution["jobId"] = resolved_job_id
        if plan_id:
            execution["planId"] = plan_id[:300]
        reported_status = _reported_status(response.data)
        if reported_status:
            execution["reportedStatus"] = reported_status

        manifest: dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "manifestId": f"manifest_{uuid.uuid4().hex}",
            "execution": execution,
            "overallState": "pending" if async_submission else "unavailable",
            "outputs": [],
        }
        if async_submission:
            if not resolved_job_id and not response.location:
                execution["trackingState"] = "unavailable"
                execution["trackingError"] = {
                    "code": "async_job_untrackable",
                    "message": (
                        "The upstream server accepted asynchronous execution but "
                        "returned neither a job identifier nor a Location header."
                    ),
                }
                manifest["overallState"] = "unavailable"
                manifest["warnings"] = [
                    "The asynchronous execution cannot be monitored or have its "
                    "results retrieved because no job identifier or Location was returned."
                ]
                return manifest
            execution["trackingState"] = "available"
            return manifest

        reference_href = (
            response.location
            if operation == "jobs.get_results"
            and response.status_code in {301, 302, 303, 307, 308}
            else ""
        )
        candidates = extract_outputs(
            response.data,
            requested_output_ids=_requested_output_ids(execute_request),
            reference_href=reference_href,
            response_body=response.body,
            response_content_type=response.content_type,
            max_outputs=server.output_resolution.max_outputs,
        )
        if not candidates:
            manifest["warnings"] = ["Execution returned no advertised output values."]
            return manifest

        resolution_budget = OutputResolutionBudget.from_policy(server.output_resolution)
        outputs: list[dict[str, Any]] = []
        for candidate in candidates:
            outputs.extend(
                self._process_candidate(
                    candidate,
                    server=server,
                    initial_content_type=response.content_type,
                    request_path=response.path,
                    source="reference" if candidate.href else "inline",
                    reference_depth=0,
                    visited=set(),
                    resolution_budget=resolution_budget,
                )
            )
            if len(outputs) >= server.output_resolution.max_outputs:
                outputs = outputs[: server.output_resolution.max_outputs]
                break
        manifest["outputs"] = outputs
        manifest["overallState"] = self._overall_state(outputs)
        return manifest

    def _process_candidate(
        self,
        candidate: OutputCandidate,
        *,
        server: ServerProfile,
        initial_content_type: str,
        request_path: str,
        source: str,
        reference_depth: int,
        visited: set[str],
        resolution_budget: OutputResolutionBudget,
    ) -> list[dict[str, Any]]:
        if candidate.href:
            if reference_depth >= 4:
                return [
                    self._failed_output(
                        candidate,
                        server=server,
                        source="reference",
                        request_path=request_path,
                        state="failed",
                        error=_error(
                            "output_reference_depth_exceeded",
                            "Nested output references exceeded the safety limit.",
                            "retrieval",
                        ),
                    )
                ]
            if candidate.href in visited:
                return [
                    self._failed_output(
                        candidate,
                        server=server,
                        source="reference",
                        request_path=request_path,
                        state="blocked",
                        error=_error(
                            "output_reference_cycle",
                            "A cycle was detected while resolving output references.",
                            "retrieval",
                        ),
                    )
                ]
            visited = {*visited, candidate.href}
            try:
                fetched = self._client.fetch_output_reference(
                    server,
                    candidate.href,
                    server.output_resolution,
                    budget=resolution_budget,
                )
            except OgcMcpError as exc:
                blocked = isinstance(exc, SecurityPolicyError) or "operator" in exc.message.casefold()
                return [
                    self._failed_output(
                        candidate,
                        server=server,
                        source="reference",
                        request_path=request_path,
                        state="blocked" if blocked else "failed",
                        error=_error(
                            exc.code,
                            exc.message,
                            "retrieval",
                            retryable=exc.code in {"transport_error", "upstream_response_error"},
                        ),
                    )
                ]

            nested = extract_outputs(
                fetched.data,
                response_body=fetched.body,
                response_content_type=fetched.content_type,
                max_outputs=server.output_resolution.max_outputs,
            )
            # A referenced result container may itself contain several declared
            # outputs. Preserve the outer output ID only when there is a single
            # generic result; otherwise use the actual nested identifiers.
            if nested and not (
                len(nested) == 1
                and nested[0].id == "result"
                and not nested[0].href
                and nested[0].value is fetched.data
            ):
                expanded: list[dict[str, Any]] = []
                for nested_candidate in nested:
                    if nested_candidate.id == "result":
                        nested_candidate.id = candidate.id
                        nested_candidate.title = candidate.title
                    nested_candidate.declared_media_type = (
                        nested_candidate.declared_media_type
                        or candidate.declared_media_type
                    )
                    nested_candidate.warnings.extend(candidate.warnings)
                    nested_candidate.redirect_count += (
                        candidate.redirect_count + fetched.redirect_count
                    )
                    if nested_candidate.href:
                        expanded.extend(
                            self._process_candidate(
                                nested_candidate,
                                server=server,
                                initial_content_type=fetched.content_type,
                                request_path=fetched.path,
                                source="reference",
                                reference_depth=reference_depth + 1,
                                visited=visited,
                                resolution_budget=resolution_budget,
                            )
                        )
                    else:
                        expanded.append(
                            self._interpreted_output(
                                _ResolvedOutput(
                                    candidate=nested_candidate,
                                    value=nested_candidate.value,
                                    source="reference",
                                    http_content_type=fetched.content_type,
                                    size_bytes=len(fetched.body),
                                    http_status=fetched.status_code,
                                    redirect_count=(
                                        fetched.redirect_count + candidate.redirect_count
                                    ),
                                    request_path=fetched.path,
                                ),
                                server=server,
                            )
                        )
                return expanded

            resolved = _ResolvedOutput(
                candidate=candidate,
                value=fetched.body
                if fetched.body and "json" not in fetched.content_type.lower()
                else fetched.data,
                source="reference",
                http_content_type=fetched.content_type,
                size_bytes=len(fetched.body),
                http_status=fetched.status_code,
                redirect_count=fetched.redirect_count + candidate.redirect_count,
                request_path=fetched.path,
            )
        else:
            resolved = _ResolvedOutput(
                candidate=candidate,
                value=candidate.value,
                source=source,
                http_content_type=initial_content_type,
                size_bytes=_size(candidate.value),
                request_path=request_path,
            )
        return [self._interpreted_output(resolved, server=server)]

    def _interpreted_output(
        self,
        resolved: _ResolvedOutput,
        *,
        server: ServerProfile,
    ) -> dict[str, Any]:
        candidate = resolved.candidate
        media_type, detection_warnings = detect_media_type(
            resolved.value,
            declared_media_type=candidate.declared_media_type,
            http_content_type=resolved.http_content_type,
            href=candidate.href,
        )
        retrieval = retrieval_state(
            state="retrieved",
            source=resolved.source,
            declared_media_type=normalize_media_type(candidate.declared_media_type),
            detected_media_type=media_type,
            size_bytes=resolved.size_bytes,
        )
        if resolved.http_status is not None:
            retrieval["httpStatus"] = resolved.http_status
            retrieval["redirectCount"] = resolved.redirect_count

        original = self._store.put(
            resolved.value,
            media_type=media_type,
            role="original",
        )
        representations: list[dict[str, Any]] = [
            {
                "id": f"{candidate.id}-original",
                "role": "original",
                "mediaType": (media_type or "application/octet-stream")[:300],
                "handle": original.handle,
                "sizeBytes": original.size_bytes,
            }
        ]
        warnings = [*candidate.warnings, *detection_warnings]
        try:
            parsed, parser_name = self._parsers.parse(resolved.value, media_type)
        except (ValueError, TypeError) as exc:
            # Parser adapters normalize library-specific parse failures to
            # ValueError so arbitrary runtime failures are not swallowed.
            error = _error(
                "output_interpretation_failed",
                str(exc),
                "interpretation",
            )
            return {
                "id": candidate.id[:300] or "result",
                "title": (candidate.title or candidate.id or "Result")[:500],
                **({"description": candidate.description[:4000]} if candidate.description else {}),
                "status": "failed",
                "retrieval": retrieval,
                "interpretation": {
                    **interpretation_state(
                        state="failed",
                        semantic_type="unknown",
                        format_name=media_type,
                        units=candidate.units,
                        warnings=warnings,
                    ),
                    "error": error,
                },
                "representations": representations,
                "presentations": [
                    {
                        "id": f"{candidate.id}-download",
                        "kind": "download",
                        "state": "ready",
                        "artifactRef": original.handle,
                    }
                ],
                "provenance": self._provenance(
                    server,
                    request_path=resolved.request_path,
                    value=resolved.value,
                    parser="",
                ),
                "warnings": [
                    str(warning)[:2000]
                    for warning in [str(exc), *warnings][:100]
                ],
            }

        warnings.extend(parsed.warnings)
        canonical_handle = ""
        if parsed.has_canonical_data and parsed.canonical_media_type:
            canonical = self._store.put(
                parsed.canonical_data,
                media_type=parsed.canonical_media_type,
                role="canonical",
            )
            canonical_handle = canonical.handle
            representation: dict[str, Any] = {
                "id": f"{candidate.id}-canonical",
                "role": "canonical",
                "mediaType": parsed.canonical_media_type,
                "handle": canonical.handle,
                "sizeBytes": canonical.size_bytes,
            }
            if canonical.size_bytes <= server.output_resolution.inline_preview_bytes:
                representation["data"] = parsed.canonical_data
            representations.append(representation)

        preview_handle = ""
        preview_value: Any = None
        preview_truncated = False
        has_preview_value = parsed.has_preview or parsed.has_canonical_data
        if has_preview_value:
            source_preview = (
                parsed.preview if parsed.has_preview else parsed.canonical_data
            )
            preview_value = (
                bounded_geojson_preview(source_preview)
                if parsed.semantic_type == "vector"
                else bounded_json_preview(source_preview)
            )
            preview = self._store.put(
                preview_value,
                media_type=parsed.canonical_media_type or "application/json",
                role="preview",
            )
            preview_handle = preview.handle
            preview_truncated = _preview_was_truncated(
                parsed,
                preview_value,
                resolved.value,
            )
            representation = {
                "id": f"{candidate.id}-preview",
                "role": "preview",
                "mediaType": parsed.canonical_media_type or "application/json",
                "handle": preview.handle,
                "sizeBytes": preview.size_bytes,
            }
            if preview_truncated:
                representation["truncated"] = True
            if preview.size_bytes <= server.output_resolution.inline_preview_bytes:
                representation["data"] = preview_value
            representations.append(representation)
            if preview_truncated:
                warnings.append(
                    "Renderer preview was truncated to a bounded complete-item subset."
                )

        render_handle = preview_handle or canonical_handle or original.handle
        vector_preview_feature_count = (
            len(preview_value.get("features", []))
            if parsed.semantic_type == "vector"
            and isinstance(preview_value, dict)
            and isinstance(preview_value.get("features"), list)
            else None
        )
        vector_preview_drawable = (
            bool(bbox_for_geojson(preview_value))
            if parsed.semantic_type == "vector" and has_preview_value
            else None
        )
        table_preview_row_count = (
            len(preview_value)
            if parsed.semantic_type in {"table", "timeseries"}
            and isinstance(preview_value, list)
            else None
        )
        presentations, status = self._presentations(
            candidate.id,
            parsed,
            original_handle=original.handle,
            render_handle=render_handle,
            vector_preview_drawable=vector_preview_drawable,
            vector_preview_feature_count=vector_preview_feature_count,
            table_preview_row_count=table_preview_row_count,
            preview_truncated=preview_truncated,
        )
        provenance_transformations = list(parsed.transformations)
        if preview_truncated:
            provenance_transformations.append(
                "Renderer preview truncated to bounded complete items"
            )
        warnings = [str(warning)[:2000] for warning in warnings[:100]]
        interpretation = interpretation_state(
            state=(
                "ambiguous"
                if parsed.clarification_issues
                else "recognized"
                if parsed.semantic_type not in {"unknown", "binary"}
                else "unsupported"
            ),
            semantic_type=parsed.semantic_type,
            format_name=parsed.format,
            crs_value=parsed.crs_value,
            crs_status=parsed.crs_status,
            axis_order=parsed.axis_order,
            bbox=parsed.bbox,
            feature_count=parsed.feature_count,
            geometry_types=parsed.geometry_types,
            units=candidate.units,
            warnings=warnings,
            table_rows=parsed.table_rows,
            table_columns=parsed.table_columns,
        )
        output: dict[str, Any] = {
            "id": candidate.id[:300] or "result",
            "title": (candidate.title or candidate.id or "Result")[:500],
            "status": status,
            "retrieval": retrieval,
            "interpretation": interpretation,
            "representations": representations,
            "presentations": presentations,
            "provenance": self._provenance(
                server,
                request_path=resolved.request_path,
                value=resolved.value,
                parser=parser_name,
                transformations=provenance_transformations,
            ),
        }
        if candidate.description:
            output["description"] = candidate.description[:4000]
        if warnings:
            output["warnings"] = warnings[:100]
        if parsed.clarification_issues:
            output["clarificationRequest"] = _clarification_request(
                candidate.id or "result",
                parsed.clarification_issues,
                blocking=parsed.clarification_blocking,
                scope=parsed.clarification_scope,
            )
        return output

    @staticmethod
    def _presentations(
        output_id: str,
        parsed: ParsedArtifact,
        *,
        original_handle: str,
        render_handle: str,
        vector_preview_drawable: bool | None,
        vector_preview_feature_count: int | None,
        table_preview_row_count: int | None,
        preview_truncated: bool,
    ) -> tuple[list[dict[str, Any]], str]:
        presentations: list[dict[str, Any]] = []
        primary_state = "ready"
        semantic = parsed.semantic_type
        if semantic == "vector":
            if parsed.feature_count == 0:
                presentations.append(
                    {
                        "id": f"{output_id}-map",
                        "kind": "map",
                        "state": "unavailable",
                        "reason": "The vector output contains no features.",
                    }
                )
                primary_state = "empty"
            elif parsed.map_unavailable_reason:
                presentations.append(
                    {
                        "id": f"{output_id}-map",
                        "kind": "map",
                        "state": "unavailable",
                        "reason": parsed.map_unavailable_reason[:2000],
                    }
                )
                primary_state = "partial"
            elif not parsed.bbox:
                presentations.append(
                    {
                        "id": f"{output_id}-map",
                        "kind": "map",
                        "state": "unavailable",
                        "reason": (
                            "The vector output contains no validated drawable "
                            "coordinates."
                        ),
                    }
                )
                primary_state = "partial"
            elif parsed.crs_status == "unsupported":
                presentations.append(
                    {
                        "id": f"{output_id}-map",
                        "kind": "map",
                        "state": "unavailable",
                        "reason": "The native CRS requires a reprojection adapter before mapping.",
                    }
                )
                primary_state = "partial"
            elif vector_preview_drawable is not True:
                presentations.append(
                    {
                        "id": f"{output_id}-map",
                        "kind": "map",
                        "state": "unavailable",
                        "reason": (
                            "No complete drawable feature fit within the bounded "
                            "map-preview budget."
                        ),
                    }
                )
                primary_state = "partial"
            else:
                presentations.append(
                    {
                        "id": f"{output_id}-map",
                        "kind": "map",
                        "state": (
                            "partial"
                            if preview_truncated or parsed.force_partial
                            else "ready"
                        ),
                        "artifactRef": render_handle,
                        **(
                            {
                                "reason": (
                                    parsed.partial_reason
                                    or "The map displays a bounded feature subset; "
                                    "the canonical artifact contains the full result."
                                )
                            }
                            if preview_truncated or parsed.force_partial
                            else {}
                        ),
                    }
                )
                if preview_truncated or parsed.force_partial:
                    primary_state = "partial"
            vector_table_available = (
                not isinstance(parsed.feature_count, int)
                or parsed.feature_count <= 0
                or (
                    vector_preview_feature_count is not None
                    and vector_preview_feature_count > 0
                )
            )
            presentations.append(
                {
                    "id": f"{output_id}-table",
                    "kind": "table",
                    "state": (
                        "unavailable"
                        if not vector_table_available
                        else "partial"
                        if preview_truncated or parsed.force_partial
                        else "ready"
                    ),
                    **(
                        {"artifactRef": render_handle}
                        if vector_table_available
                        else {
                            "reason": (
                                "No complete feature fit within the bounded "
                                "table-preview budget."
                            )
                        }
                    ),
                }
            )
            if (
                not vector_table_available
                or preview_truncated
                or parsed.force_partial
            ):
                primary_state = "partial"
        elif semantic in {"table", "timeseries"}:
            table_available = (
                not isinstance(parsed.table_rows, int)
                or parsed.table_rows <= 0
                or (
                    table_preview_row_count is not None
                    and table_preview_row_count > 0
                )
            )
            table_state = (
                "unavailable"
                if not table_available
                else "partial"
                if preview_truncated
                else "ready"
            )
            presentations.append(
                {
                    "id": f"{output_id}-table",
                    "kind": "table",
                    "state": table_state,
                    **(
                        {"artifactRef": render_handle}
                        if table_available
                        else {
                            "reason": (
                                "No complete row fit within the bounded "
                                "table-preview budget."
                            )
                        }
                    ),
                }
            )
            if semantic == "timeseries":
                presentations.append(
                    {
                        "id": f"{output_id}-chart",
                        "kind": "chart",
                        "state": table_state,
                        **(
                            {"artifactRef": render_handle}
                            if table_available
                            else {
                                "reason": (
                                    "No complete row fit within the bounded "
                                    "chart-preview budget."
                                )
                            }
                        ),
                    }
                )
            if parsed.map_unavailable_reason:
                presentations.append(
                    {
                        "id": f"{output_id}-map",
                        "kind": "map",
                        "state": "unavailable",
                        "reason": parsed.map_unavailable_reason[:2000],
                    }
                )
            if not table_available or preview_truncated:
                primary_state = "partial"
        elif semantic == "scalar":
            presentations.append(
                {
                    "id": f"{output_id}-metric",
                    "kind": "metric",
                    "state": "partial" if preview_truncated else "ready",
                    "artifactRef": render_handle,
                    **(
                        {
                            "reason": (
                                "The metric value exceeds the bounded preview "
                                "budget; use the canonical artifact for the full value."
                            )
                        }
                        if preview_truncated
                        else {}
                    ),
                }
            )
            if preview_truncated:
                primary_state = "partial"
        elif semantic == "image":
            presentations.append(
                {
                    "id": f"{output_id}-image",
                    "kind": "image",
                    "state": "ready",
                    "artifactRef": original_handle,
                }
            )
        elif semantic == "document":
            presentations.append(
                {
                    "id": f"{output_id}-text",
                    "kind": "text",
                    "state": "partial" if preview_truncated else "ready",
                    "artifactRef": render_handle,
                    **(
                        {
                            "reason": (
                                "The text view is a bounded preview; the original "
                                "artifact contains the full document."
                            )
                        }
                        if preview_truncated
                        else {}
                    ),
                }
            )
            if preview_truncated:
                primary_state = "partial"
            if parsed.map_unavailable_reason:
                presentations.append(
                    {
                        "id": f"{output_id}-map",
                        "kind": "map",
                        "state": "unavailable",
                        "reason": parsed.map_unavailable_reason[:2000],
                    }
                )
                primary_state = "partial"
        elif semantic == "tiles":
            presentations.append(
                {
                    "id": f"{output_id}-map",
                    "kind": "map",
                    "state": "partial",
                    "artifactRef": render_handle,
                    "reason": "Tile metadata was identified; the client must validate advertised tile URLs.",
                }
            )
            primary_state = "partial"
        elif semantic in {"raster", "coverage"}:
            presentations.append(
                {
                    "id": f"{output_id}-map",
                    "kind": "map",
                    "state": "unavailable",
                    "reason": (
                        "The output was identified, but a georeferenced map preview "
                        "adapter is not available for this representation."
                    ),
                }
            )
            primary_state = "partial"
        else:
            primary_state = "unsupported"

        if parsed.force_partial and primary_state in {"ready", "empty"}:
            primary_state = "partial"
        presentations.append(
            {
                "id": f"{output_id}-download",
                "kind": "download",
                "state": "ready",
                "artifactRef": original_handle,
            }
        )
        return presentations, primary_state

    @staticmethod
    def _provenance(
        server: ServerProfile,
        *,
        request_path: str,
        value: Any,
        parser: str,
        transformations: Iterable[str] = (),
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "serverId": server.id,
            "requestPath": request_path[:2000],
            "retrievedAt": datetime.now(timezone.utc).isoformat(),
            "sha256": _sha256(value),
        }
        if parser:
            payload["parser"] = parser[:200]
        transformations_list = [item[:300] for item in transformations][:100]
        if transformations_list:
            payload["transformations"] = transformations_list
        return payload

    def _failed_output(
        self,
        candidate: OutputCandidate,
        *,
        server: ServerProfile,
        source: str,
        request_path: str,
        state: str,
        error: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "id": candidate.id[:300] or "result",
            "title": (candidate.title or candidate.id or "Result")[:500],
            "status": state,
            "retrieval": retrieval_state(
                state=state,
                source=source,
                declared_media_type=candidate.declared_media_type,
                error=error,
            ),
            "interpretation": interpretation_state(
                state="pending",
                semantic_type="unknown",
                units=candidate.units,
            ),
            "presentations": [
                {
                    "id": f"{candidate.id}-download",
                    "kind": "download",
                    "state": "unavailable",
                    "reason": "The output could not be safely retrieved.",
                }
            ],
            "provenance": {
                "serverId": server.id,
                "requestPath": request_path[:2000],
            },
            "warnings": [error["message"]],
        }

    @staticmethod
    def _overall_state(outputs: list[dict[str, Any]]) -> str:
        if not outputs:
            return "unavailable"
        states = {str(output.get("status", "")) for output in outputs}
        if states.issubset({"ready", "empty"}):
            return "ready"
        if states & {"ready", "empty", "partial"}:
            return "partial"
        if any(
            output.get("retrieval", {}).get("state") in {"retrieved", "partial"}
            for output in outputs
        ):
            # A safely retrieved but unsupported representation is still a
            # real result and remains available through its download artifact.
            return "partial"
        return "unavailable"
