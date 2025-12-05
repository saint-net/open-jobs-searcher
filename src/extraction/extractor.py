"""Hybrid job extractor combining multiple strategies."""

import logging
from typing import Optional, Callable, Awaitable

from .candidate import JobCandidate, ExtractionSource
from .strategies import (
    BaseExtractionStrategy,
    SchemaOrgStrategy,
    GenderNotationStrategy,
    ListStructureStrategy,
    KeywordMatchStrategy,
)

logger = logging.getLogger(__name__)


class HybridJobExtractor:
    """
    Hybrid job extractor that combines multiple extraction strategies.
    
    Strategies are applied in order of reliability:
    1. Schema.org structured data (highest confidence)
    2. Gender notation patterns (m/w/d, etc.)
    3. List structure detection
    4. Keyword matching (lowest confidence)
    
    Results are merged and deduplicated, with higher confidence
    candidates taking precedence.
    """
    
    # Minimum confidence threshold to include a candidate
    MIN_CONFIDENCE = 0.4
    
    # Minimum number of candidates before using LLM fallback
    MIN_CANDIDATES_FOR_LLM_SKIP = 3
    
    # Confidence threshold below which we should also try LLM
    LLM_FALLBACK_CONFIDENCE = 0.6
    
    def __init__(
        self,
        llm_extract_fn: Optional[Callable[[str, str], Awaitable[list[dict]]]] = None,
    ):
        """
        Initialize hybrid extractor.
        
        Args:
            llm_extract_fn: Optional LLM extraction function for fallback.
                           Should accept (html, url) and return list of job dicts.
        """
        self.llm_extract_fn = llm_extract_fn
        
        # Initialize strategies in order of reliability
        self.strategies: list[BaseExtractionStrategy] = [
            SchemaOrgStrategy(),
            GenderNotationStrategy(),
            ListStructureStrategy(),
            KeywordMatchStrategy(),
        ]
    
    async def extract(self, html: str, url: str) -> list[dict]:
        """
        Extract jobs using hybrid approach.
        
        Args:
            html: HTML content of the careers page
            url: URL of the page
            
        Returns:
            List of job dictionaries with title, url, location, etc.
        """
        all_candidates: list[JobCandidate] = []
        
        # Apply each strategy
        for strategy in self.strategies:
            try:
                candidates = strategy.extract(html, url)
                all_candidates.extend(candidates)
                
                # If schema.org found enough jobs, we can skip others
                if strategy.name == "schema_org" and len(candidates) >= 3:
                    logger.debug(f"Schema.org found {len(candidates)} jobs, using these")
                    return self._finalize(candidates)
                    
            except Exception as e:
                logger.warning(f"Strategy {strategy.name} failed: {e}")
                continue
        
        # Merge and deduplicate candidates
        merged = self._merge_candidates(all_candidates)
        
        # Filter by confidence
        confident = [c for c in merged if c.confidence >= self.MIN_CONFIDENCE]
        
        logger.debug(
            f"Hybrid extraction: {len(all_candidates)} raw -> "
            f"{len(merged)} merged -> {len(confident)} confident"
        )
        
        # Decide if we need LLM fallback
        if self._should_use_llm_fallback(confident):
            llm_jobs = await self._llm_fallback(html, url)
            if llm_jobs:
                # Merge LLM results with existing
                merged = self._merge_with_llm_results(confident, llm_jobs)
                confident = merged
        
        return self._finalize(confident)
    
    def _merge_candidates(self, candidates: list[JobCandidate]) -> list[JobCandidate]:
        """
        Merge candidates from different strategies, keeping highest confidence.
        """
        # Group by normalized title
        by_title: dict[str, list[JobCandidate]] = {}
        
        for candidate in candidates:
            # Skip empty or whitespace-only titles
            if not candidate.title or not candidate.title.strip():
                continue
            key = candidate.normalized_title
            if not key:
                continue
            if key not in by_title:
                by_title[key] = []
            by_title[key].append(candidate)
        
        # For each group, keep the one with highest confidence
        merged = []
        for title, group in by_title.items():
            # Sort by confidence (descending)
            group.sort(key=lambda c: c.confidence, reverse=True)
            best = group[0]
            
            # If best doesn't have URL but another does, use that URL
            if best.url == "" or best.url.endswith('/'):
                for other in group[1:]:
                    if other.url and not other.url.endswith('/'):
                        best.url = other.url
                        best.signals["has_job_url"] = True
                        break
            
            merged.append(best)
        
        return merged
    
    def _should_use_llm_fallback(self, candidates: list[JobCandidate]) -> bool:
        """Decide if we should use LLM fallback."""
        if not self.llm_extract_fn:
            return False
        
        # Too few candidates
        if len(candidates) < self.MIN_CANDIDATES_FOR_LLM_SKIP:
            logger.debug(f"Only {len(candidates)} candidates, will try LLM")
            return True
        
        # Low average confidence
        if candidates:
            avg_confidence = sum(c.confidence for c in candidates) / len(candidates)
            if avg_confidence < self.LLM_FALLBACK_CONFIDENCE:
                logger.debug(f"Low confidence ({avg_confidence:.2f}), will try LLM")
                return True
        
        return False
    
    async def _llm_fallback(self, html: str, url: str) -> list[dict]:
        """Use LLM to extract jobs as fallback."""
        if not self.llm_extract_fn:
            return []
        
        try:
            logger.debug("Using LLM fallback for job extraction")
            return await self.llm_extract_fn(html, url)
        except Exception as e:
            logger.warning(f"LLM fallback failed: {e}")
            return []
    
    def _merge_with_llm_results(
        self,
        candidates: list[JobCandidate],
        llm_jobs: list[dict]
    ) -> list[JobCandidate]:
        """Merge existing candidates with LLM results."""
        # Convert LLM jobs to candidates
        llm_candidates = []
        for job in llm_jobs:
            title = job.get("title", "")
            if not title:
                continue
            
            llm_candidates.append(JobCandidate(
                title=title,
                url=job.get("url", ""),
                location=job.get("location", "Unknown"),
                department=job.get("department"),
                source=ExtractionSource.LLM,
                signals={"from_llm": True},
            ))
        
        # Existing titles (normalized)
        existing_titles = {c.normalized_title for c in candidates}
        
        # Add LLM candidates that aren't already present
        for llm_candidate in llm_candidates:
            if llm_candidate.normalized_title not in existing_titles:
                candidates.append(llm_candidate)
                existing_titles.add(llm_candidate.normalized_title)
        
        logger.debug(f"Added {len(llm_candidates)} LLM candidates, total: {len(candidates)}")
        return candidates
    
    def _finalize(self, candidates: list[JobCandidate]) -> list[dict]:
        """Convert candidates to final dictionary format."""
        return [c.to_dict() for c in candidates]
    
    def extract_sync(self, html: str, url: str) -> list[dict]:
        """
        Synchronous extraction (without LLM fallback).
        
        Use this when you don't need async or want to skip LLM.
        """
        all_candidates: list[JobCandidate] = []
        
        for strategy in self.strategies:
            try:
                candidates = strategy.extract(html, url)
                all_candidates.extend(candidates)
                
                if strategy.name == "schema_org" and len(candidates) >= 3:
                    return self._finalize(candidates)
                    
            except Exception as e:
                logger.warning(f"Strategy {strategy.name} failed: {e}")
                continue
        
        merged = self._merge_candidates(all_candidates)
        confident = [c for c in merged if c.confidence >= self.MIN_CONFIDENCE]
        
        return self._finalize(confident)
