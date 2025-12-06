"""Simplified job extraction module: Schema.org + LLM."""

from .candidate import JobCandidate, ExtractionSource
from .extractor import HybridJobExtractor
from .strategies import SchemaOrgStrategy

__all__ = [
    "JobCandidate",
    "ExtractionSource",
    "HybridJobExtractor",
    "SchemaOrgStrategy",
]
