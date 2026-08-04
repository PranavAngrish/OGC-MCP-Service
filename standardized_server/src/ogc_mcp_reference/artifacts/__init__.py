"""Canonical process-output artifact pipeline.

The package turns implementation-specific OGC process results into a stable,
versioned manifest.  It deliberately keeps protocol retrieval, semantic
interpretation, and presentation readiness as separate states so callers
cannot mistake an HTTP success for a successfully interpreted map layer.
"""

from .pipeline import OutputArtifactPipeline
from .store import ArtifactStore

__all__ = ["ArtifactStore", "OutputArtifactPipeline"]
