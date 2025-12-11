"""Job extraction logic for LLM providers."""

import logging
import re
from typing import Callable, Awaitable, Optional, Any

from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, retry_if_result

from src.constants import MAX_LLM_RETRIES, MIN_JOB_SECTION_SIZE, MAX_JOB_SECTION_SIZE
from src.models import JobDict, JobExtractionResult

logger = logging.getLogger(__name__)


def _is_empty_result(result: JobExtractionResult) -> bool:
    """Check if extraction result has no jobs (trigger retry)."""
    return not result.get("jobs")


# Non-job titles to filter out (open applications, general inquiries, etc.)
NON_JOB_PATTERNS = [
    r'initiativbewerbung',  # German: Open/unsolicited application
    r'initiativ\s*bewerbung',
    r'spontanbewerbung',  # German: Spontaneous application
    r'open\s*application',  # English variants
    r'unsolicited\s*application',
    r'speculative\s*application',
    r'general\s*application',
    r'blindbewerbung',  # German: Blind application
]

# CSS selectors for common job listing containers/widgets
JOB_SECTION_SELECTORS = [
    # Odoo job widgets
    '.oe_website_jobs',
    '.o_website_hr_recruitment_jobs_list',
    '[class*="website_jobs"]',
    '[class*="hr_recruitment"]',
    # Join.com widget
    '.join-jobs-widget',
    '[class*="join-jobs"]',
    # Personio
    '.personio-jobs',
    '[class*="personio"]',
    # Generic job containers
    '[class*="job-list"]',
    '[class*="jobs-list"]',
    '[class*="vacancies"]',
    '[class*="career-list"]',
    '[class*="openings"]',
    '[id*="jobs"]',
    '[id*="vacancies"]',
    '[id*="careers"]',
    # Main content with job-related text
    'main',
    'article',
    '.content',
]

# Job-related markers for content detection
JOB_CONTENT_MARKERS = [
    '(m/w/d)', '(m/f/d)', 'vollzeit', 'teilzeit', 
    'job', 'position', 'stelle', 'develop', 'engineer', 'manager'
]


class LLMJobExtractor:
    """Handles job extraction using LLM."""
    
    def __init__(
        self,
        complete_fn: Callable[[str], Awaitable[str]],
        clean_html_fn: Callable[[str], str],
        extract_json_fn: Callable[[str], list | dict],
    ):
        """
        Initialize extractor with LLM provider functions.
        
        Args:
            complete_fn: Async function to call LLM (prompt -> response)
            clean_html_fn: Function to clean HTML
            extract_json_fn: Function to extract JSON from LLM response
        """
        self._complete = complete_fn
        self._clean_html = clean_html_fn
        self._extract_json = extract_json_fn
    
    async def extract_jobs(self, html: str, url: str, page: Any = None) -> list[JobDict]:
        """
        Extract job listings from HTML page using hybrid approach.

        Args:
            html: HTML content of the careers page
            url: URL of the page
            page: Optional Playwright Page object

        Returns:
            List of job dictionaries
        """
        from src.extraction import HybridJobExtractor
        
        # Create hybrid extractor with LLM fallback
        extractor = HybridJobExtractor(
            llm_extract_fn=self._llm_extract_jobs
        )
        
        jobs = await extractor.extract(html, url, page=page)
        
        if jobs:
            logger.debug(f"Hybrid extraction found {len(jobs)} jobs from {url}")
            return validate_jobs(jobs)
        
        logger.warning(f"Failed to extract jobs from {url}")
        return []
    
    async def extract_jobs_with_pagination(self, html: str, url: str) -> JobExtractionResult:
        """
        Extract job listings with pagination info using LLM directly.

        Args:
            html: HTML content of the careers page
            url: URL of the page

        Returns:
            Dict with "jobs" (list) and "next_page_url" (str or None)
        """
        result = await self._llm_extract_jobs_with_pagination(html, url)
        
        jobs = result.get("jobs", [])
        if jobs:
            result["jobs"] = validate_jobs(jobs)
        
        return result
    
    async def _llm_extract_jobs(self, html: str, url: str) -> list[JobDict]:
        """LLM-based job extraction (used as fallback by hybrid extractor)."""
        result = await self._llm_extract_jobs_with_pagination(html, url)
        return result.get("jobs", [])
    
    async def _llm_extract_jobs_with_pagination(self, html: str, url: str) -> JobExtractionResult:
        """LLM-based job extraction with pagination support."""
        from .prompts import EXTRACT_JOBS_PROMPT
        
        soup = BeautifulSoup(html, 'lxml')
        body = soup.find('body')
        
        # Try to find job listing sections first
        job_section_html = find_job_section(soup)
        
        if job_section_html:
            clean_html = self._clean_html(job_section_html)
            logger.debug(f"Found job section, size: {len(clean_html)} chars")
        else:
            body_html = str(body) if body else html
            clean_html = self._clean_html(body_html)

        # Limit HTML size (80000 chars for large pages)
        html_truncated = clean_html[:80000] if len(clean_html) > 80000 else clean_html
        
        logger.debug(f"LLM extracting jobs from {url}, HTML size: {len(html_truncated)} chars")

        prompt = EXTRACT_JOBS_PROMPT.format(url=url, html=html_truncated)

        return await self._call_llm_for_jobs(prompt)
    
    @retry(
        stop=stop_after_attempt(MAX_LLM_RETRIES),
        retry=retry_if_result(_is_empty_result),
    )
    async def _call_llm_for_jobs(self, prompt: str) -> JobExtractionResult:
        """Call LLM and parse job extraction response. Retries on empty result."""
        response = await self._complete(prompt)
        result = self._extract_json(response)
        
        # Debug: log raw response if no jobs found
        if not result or (isinstance(result, dict) and not result.get("jobs")) or (isinstance(result, list) and len(result) == 0):
            logger.debug(f"LLM response (first 500 chars): {response[:500] if response else 'EMPTY'}")
        
        # Handle new format: {"jobs": [...], "next_page_url": ...}
        if isinstance(result, dict) and "jobs" in result:
            jobs = result.get("jobs", [])
            next_page_url = result.get("next_page_url")
            if isinstance(jobs, list) and len(jobs) > 0:
                logger.debug(f"LLM extracted {len(jobs)} jobs")
                return {"jobs": jobs, "next_page_url": next_page_url}
        # Handle old format: [...] (for backward compatibility)
        elif isinstance(result, list) and len(result) > 0:
            logger.debug(f"LLM extracted {len(result)} jobs")
            return {"jobs": result, "next_page_url": None}
        
        logger.debug("LLM returned no jobs, will retry...")
        return {"jobs": [], "next_page_url": None}


def find_job_section(soup: BeautifulSoup) -> Optional[str]:
    """Find the HTML section containing job listings.
    
    Many pages have job widgets at the end of large HTML documents.
    This function finds the relevant section to avoid truncation issues.
    
    Args:
        soup: BeautifulSoup object of the page
        
    Returns:
        HTML string of job section, or None if not found
    """
    # Check if this is an Odoo site first (most reliable detection)
    from src.searchers.job_boards.odoo import OdooParser
    
    if OdooParser.is_odoo_site(soup):
        logger.debug("Detected Odoo site, using Odoo-specific selectors")
        odoo_html = OdooParser.find_job_section(soup)
        if odoo_html:
            return odoo_html
    
    # Try generic selectors for other platforms
    candidates = []
    
    for selector in JOB_SECTION_SELECTORS:
        try:
            elements = soup.select(selector)
            valid_elements = []
            for el in elements:
                el_text = el.get_text().lower()
                # Check if element contains job-related content
                if any(marker in el_text for marker in JOB_CONTENT_MARKERS):
                    html = str(el)
                    if MIN_JOB_SECTION_SIZE < len(html) < MAX_JOB_SECTION_SIZE:
                        valid_elements.append(html)
            
            if valid_elements:
                combined_html = "\n<hr>\n".join(valid_elements)
                if len(combined_html) > 1000:
                    candidates.append((len(combined_html), combined_html))
        except Exception:
            continue
            
    # Sort candidates by size (descending) to prefer larger collections
    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
        
    return None


def validate_jobs(jobs: list) -> list[JobDict]:
    """Validate and filter job entries."""
    valid_jobs = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        if not job.get("title"):
            continue
        
        title = str(job.get("title", "")).strip()
        
        # Filter out non-job entries (open applications, etc.)
        if is_non_job_entry(title):
            logger.debug(f"Filtered non-job entry: {title}")
            continue
        
        valid_job: JobDict = {
            "title": title,
            "location": str(job.get("location", "Unknown")).strip() or "Unknown",
            "url": str(job.get("url", "")).strip(),
            "department": job.get("department"),
        }
        valid_jobs.append(valid_job)
    return valid_jobs


def is_non_job_entry(title: str) -> bool:
    """Check if title is a non-job entry (open application, etc.)."""
    title_lower = title.lower()
    for pattern in NON_JOB_PATTERNS:
        if re.search(pattern, title_lower, re.IGNORECASE):
            return True
    return False

