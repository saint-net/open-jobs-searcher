"""Hybrid job extraction module."""

from .candidate import JobCandidate, ExtractionSource
from .extractor import HybridJobExtractor
from .strategies import (
    BaseExtractionStrategy,
    SchemaOrgStrategy,
    GenderNotationStrategy,
    ListStructureStrategy,
)

__all__ = [
    "JobCandidate",
    "ExtractionSource",
    "HybridJobExtractor",
    "BaseExtractionStrategy",
    "SchemaOrgStrategy",
    "GenderNotationStrategy",
    "ListStructureStrategy",
]
