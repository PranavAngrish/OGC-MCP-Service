"""Ordered parser adapter registry."""

from __future__ import annotations

from typing import Any, Protocol

from .models import ParsedArtifact
from .parsers import GenericParser, GeoJsonParser, GmlParser, WktParser


class ArtifactParser(Protocol):
    name: str

    def supports(self, media_type: str, value: Any) -> bool:
        ...

    def parse(self, value: Any, media_type: str) -> ParsedArtifact:
        ...


class ParserRegistry:
    """Select the first specific adapter, ending with the generic fallback."""

    def __init__(self, parsers: list[ArtifactParser] | None = None) -> None:
        self._parsers = parsers or [
            GeoJsonParser(),
            GmlParser(),
            WktParser(),
            GenericParser(),
        ]

    def parse(self, value: Any, media_type: str) -> tuple[ParsedArtifact, str]:
        for parser in self._parsers:
            if parser.supports(media_type, value):
                return parser.parse(value, media_type), parser.name
        # The built-in generic parser always matches, but retain a deterministic
        # failure if a custom registry omits it.
        raise ValueError(f"No parser is registered for '{media_type}'.")
