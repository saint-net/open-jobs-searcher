"""Simplified job extractor: Schema.org + LLM.

Strategy:
1. Try Schema.org structured data first (100% accuracy when available)
2. If no Schema.org data, use LLM extraction (main method)

This approach eliminates false positives from heuristic-based strategies
(AccessibilityTree, KeywordMatch, ListStructure, GenderNotation).
"""

import logging
from typing import Optional, Callable, Awaitable, Any

from .candidate import JobCandidate, ExtractionSource
from .strategies import SchemaOrgStrategy, PdfLinkStrategy

logger = logging.getLogger(__name__)


class HybridJobExtractor:
    """
    Simplified job extractor: Schema.org + LLM.
    
    1. Schema.org structured data (100% accuracy, ~20-30% of sites)
    2. LLM extraction (main method for everything else)
    
    This eliminates false positives from heuristic strategies.
    """
    
    def __init__(
        self,
        llm_extract_fn: Optional[Callable[[str, str], Awaitable[list[dict]]]] = None,
    ):
        """
        Initialize extractor.
        
        Args:
            llm_extract_fn: LLM extraction function.
                           Should accept (html, url) and return list of job dicts.
        """
        self.llm_extract_fn = llm_extract_fn
        
        # High-accuracy strategies (use before LLM)
        self.schema_strategy = SchemaOrgStrategy()
        self.pdf_link_strategy = PdfLinkStrategy()
    
    async def extract(self, html: str, url: str, page: Any = None) -> list[dict]:
        """
        Extract jobs: Schema.org first, then LLM + PDF.
        
        Args:
            html: HTML content of the careers page
            url: URL of the page
            page: Optional Playwright Page object (not used in simplified version)
            
        Returns:
            List of job dictionaries with title, url, location, etc.
        """
        # 1. Try Schema.org first (100% accuracy when available)
        try:
            schema_candidates = self.schema_strategy.extract(html, url)
            if schema_candidates:
                logger.debug(f"Schema.org found {len(schema_candidates)} jobs, using these")
                return self._finalize(schema_candidates)
            logger.debug("Schema.org found 0 jobs")
        except Exception as e:
            logger.warning(f"SchemaOrgStrategy failed: {e}")
        
        # 2. Collect PDF links as supplement (strategy logs internally)
        pdf_candidates = []
        try:
            pdf_candidates = self.pdf_link_strategy.extract(html, url)
        except Exception as e:
            logger.warning(f"PdfLinkStrategy failed: {e}")
        
        # 3. LLM as main extraction method
        llm_jobs = await self._llm_extract(html, url)
        if llm_jobs:
            llm_candidates = self._convert_llm_jobs(llm_jobs)
            # Merge LLM + PDF results, deduplicate
            all_candidates = self._deduplicate(llm_candidates + pdf_candidates)
            logger.debug(f"Combined: {len(llm_candidates)} LLM + {len(pdf_candidates)} PDF = {len(all_candidates)} unique")
            return self._finalize(all_candidates)
        
        # 4. Fallback: PDF only if LLM found nothing
        if pdf_candidates:
            logger.debug(f"LLM found nothing, using {len(pdf_candidates)} PDF candidates")
            return self._finalize(pdf_candidates)
        
        # No jobs found
        logger.debug("No jobs found via Schema.org, LLM, or PDF")
        return []
    
    def _deduplicate(self, candidates: list[JobCandidate]) -> list[JobCandidate]:
        """Deduplicate candidates by normalized title."""
        seen = set()
        unique = []
        for c in candidates:
            if c.normalized_title not in seen:
                seen.add(c.normalized_title)
                unique.append(c)
        return unique
    
    # Keep for backward compatibility
    async def extract_with_browser(self, html: str, url: str, page: Any) -> list[dict]:
        """Extract jobs (browser page not used in simplified version)."""
        return await self.extract(html, url, page)
    
    async def _llm_extract(self, html: str, url: str) -> list[dict]:
        """Use LLM to extract jobs."""
        if not self.llm_extract_fn:
            logger.warning("No LLM extraction function provided")
            return []
        
        try:
            logger.debug("Using LLM for job extraction")
            return await self.llm_extract_fn(html, url)
        except Exception as e:
            logger.warning(f"LLM extraction failed: {e}")
            return []
    
    def _convert_llm_jobs(self, llm_jobs: list[dict]) -> list[JobCandidate]:
        """Convert LLM job dicts to JobCandidate objects."""
        candidates = []
        seen_titles = set()
        
        for job in llm_jobs:
            title = job.get("title", "")
            if not title or not title.strip():
                continue
            
            candidate = JobCandidate(
                title=title,
                url=job.get("url", ""),
                location=job.get("location", "Unknown"),
                department=job.get("department"),
                source=ExtractionSource.LLM,
                signals={"from_llm": True},
            )
            
            # Deduplicate by normalized title
            if candidate.normalized_title not in seen_titles:
                candidates.append(candidate)
                seen_titles.add(candidate.normalized_title)
        
        logger.debug(f"LLM extracted {len(candidates)} unique jobs")
        return candidates
    
    def _finalize(self, candidates: list[JobCandidate]) -> list[dict]:
        """Convert candidates to final dictionary format."""
        return [c.to_dict() for c in candidates]
    
    def extract_sync(self, html: str, url: str) -> list[dict]:
        """
        Synchronous extraction (Schema.org only, no LLM).
        
        Use this when you don't have async context.
        Note: This only extracts Schema.org data, no LLM fallback.
        """
        try:
            schema_candidates = self.schema_strategy.extract(html, url)
            if schema_candidates:
                logger.debug(f"Schema.org found {len(schema_candidates)} jobs")
                return self._finalize(schema_candidates)
        except Exception as e:
            logger.warning(f"SchemaOrgStrategy failed: {e}")
        
        logger.debug("No Schema.org data found (use async extract() for LLM)")
        return []
