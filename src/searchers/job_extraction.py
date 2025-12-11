"""Job extraction from career pages with pagination support."""

import logging
from typing import Optional, Callable, Awaitable

from rich.console import Console

from src.searchers.job_boards import (
    JobBoardParserRegistry,
    detect_job_board_platform,
    find_external_job_board,
)
from src.searchers.job_filters import normalize_title, normalize_location
from src.extraction.strategies import PdfLinkStrategy, SchemaOrgStrategy
from src.constants import MAX_PAGINATION_PAGES

logger = logging.getLogger(__name__)
console = Console()


class JobExtractor:
    """Extracts jobs from career pages with pagination and deduplication."""
    
    def __init__(
        self,
        llm_provider,
        job_board_parsers: JobBoardParserRegistry,
        fetch_with_page: Callable[[str, bool], Awaitable[tuple]],
        fetch_jobs_from_api: Callable[[str, str], Awaitable[list[dict]]],
    ):
        """
        Initialize job extractor.
        
        Args:
            llm_provider: LLM provider for extraction
            job_board_parsers: Registry of job board parsers
            fetch_with_page: Async function to fetch page with browser
                             Returns (html, final_url, page_obj, context_obj)
            fetch_jobs_from_api: Async function to fetch jobs from API
        """
        self.llm = llm_provider
        self.job_board_parsers = job_board_parsers
        self._fetch_with_page = fetch_with_page
        self._fetch_jobs_from_api = fetch_jobs_from_api
    
    async def extract_jobs(self, careers_url: str, original_url: str) -> list[dict]:
        """Extract jobs from a careers URL with pagination support.
        
        Args:
            careers_url: URL of careers/jobs page
            original_url: Original company URL (for filtering)
            
        Returns:
            List of job dictionaries from all pages (up to MAX_PAGINATION_PAGES)
        """
        all_jobs_data = []
        current_url = careers_url
        pages_visited = 0
        seen_job_keys = set()  # Track unique jobs to detect duplicates
        
        while pages_visited < MAX_PAGINATION_PAGES:
            pages_visited += 1
            
            jobs_data, next_page_url = await self._extract_from_single_page(
                current_url, original_url
            )
            
            if jobs_data:
                # Deduplicate jobs
                new_jobs = self._deduplicate_jobs(
                    jobs_data, seen_job_keys, current_url
                )
                
                if new_jobs:
                    all_jobs_data.extend(new_jobs)
                    logger.debug(
                        f"Page {pages_visited}: found {len(new_jobs)} new jobs "
                        f"({len(jobs_data)} total on page)"
                    )
                else:
                    # All jobs on this page are duplicates - we've looped back
                    logger.debug(
                        f"Page {pages_visited}: all {len(jobs_data)} jobs are "
                        "duplicates, stopping pagination"
                    )
                    break
            
            # Check if there are more pages
            if not next_page_url:
                break
            
            # Check if we've hit the pagination limit
            if pages_visited >= MAX_PAGINATION_PAGES:
                logger.warning(
                    f"Pagination limit reached ({MAX_PAGINATION_PAGES} pages). "
                    f"There may be more jobs at: {next_page_url}"
                )
                print(
                    f"⚠️  Достигнут лимит страниц ({MAX_PAGINATION_PAGES}). "
                    f"Возможно есть ещё вакансии: {next_page_url}"
                )
                break
            
            current_url = next_page_url
        
        if pages_visited > 1:
            logger.info(f"Total: {len(all_jobs_data)} unique jobs from {pages_visited} pages")
        
        return all_jobs_data
    
    def _deduplicate_jobs(
        self, 
        jobs_data: list[dict], 
        seen_keys: set, 
        current_url: str
    ) -> list[dict]:
        """Remove duplicate jobs based on URL or (title, location).
        
        Args:
            jobs_data: List of job dictionaries
            seen_keys: Set of already seen job keys (modified in place)
            current_url: Current page URL for detecting self-references
            
        Returns:
            List of new (non-duplicate) jobs
        """
        new_jobs = []
        base_page = current_url.rstrip('/')
        
        for job in jobs_data:
            # Primary key: URL (most reliable)
            job_url = job.get("url", "")
            
            # Handle None or "None" as empty
            if job_url is None or job_url == "None" or job_url == "null":
                job_url = ""
            else:
                job_url = str(job_url).strip()
            
            # Treat self-referencing URLs as empty
            if job_url:
                job_url_clean = job_url.rstrip('/')
                if (job_url_clean == base_page or 
                    job_url.endswith('#') or 
                    job_url_clean == base_page + '#'):
                    job_url = ""
            
            # Fallback key: (title, location) for jobs without URL
            title_loc_key = (
                normalize_title(job.get("title", "")),
                normalize_location(job.get("location", ""))
            )
            
            # Use URL as key if available, otherwise title+location
            job_key = job_url if job_url else title_loc_key
            
            if job_key not in seen_keys:
                seen_keys.add(job_key)
                new_jobs.append(job)
            else:
                key_str = job_key if isinstance(job_key, str) else job_key[0][:30]
                logger.debug(
                    f"Duplicate job skipped: {job.get('title', '')[:40]} | key={key_str}"
                )
        
        return new_jobs

    async def _extract_from_single_page(
        self, careers_url: str, original_url: str
    ) -> tuple[list[dict], Optional[str]]:
        """Extract jobs from a single page.
        
        Args:
            careers_url: URL of careers/jobs page
            original_url: Original company URL (for filtering)
            
        Returns:
            Tuple of (jobs_data, next_page_url)
        """
        jobs_data = []
        next_page_url = None
        page_obj = None
        context_obj = None
        
        try:
            # Load page - navigate to jobs only for base URL without query params
            has_query = '?' in careers_url
            
            html, final_url, page_obj, context_obj = await self._fetch_with_page(
                careers_url, not has_query
            )
            final_url = final_url or careers_url
            
            if not html:
                return [], None
            
            # Check for external job board
            external_platform = detect_job_board_platform(final_url, html)
            if not external_platform:
                external_board_url = find_external_job_board(html)
                if external_board_url:
                    external_platform = detect_job_board_platform(external_board_url)
                    # Close current page and load external board
                    if page_obj:
                        await page_obj.close()
                    if context_obj:
                        await context_obj.close()
                    
                    html, _, page_obj, context_obj = await self._fetch_with_page(
                        external_board_url, False
                    )
                    if not html:
                        return [], None
                    final_url = external_board_url
            
            # Extract jobs using parser or LLM
            if external_platform:
                if self.job_board_parsers.is_api_based(external_platform):
                    jobs_data = await self._fetch_jobs_from_api(final_url, external_platform)
                else:
                    jobs_data = self.job_board_parsers.parse(html, final_url, external_platform)
                # No pagination for external platforms
            else:
                # Try high-accuracy strategies first (Schema.org, PDF links)
                schema_strategy = SchemaOrgStrategy()
                schema_candidates = schema_strategy.extract(html, final_url)
                if schema_candidates:
                    jobs_data = [c.to_dict() for c in schema_candidates]
                    logger.debug(f"Schema.org extracted {len(jobs_data)} jobs")
                else:
                    pdf_strategy = PdfLinkStrategy()
                    pdf_candidates = pdf_strategy.extract(html, final_url)
                    if pdf_candidates:
                        jobs_data = [c.to_dict() for c in pdf_candidates]
                        logger.debug(f"PdfLinkStrategy extracted {len(jobs_data)} jobs")
                    else:
                        # Use LLM extraction with pagination support
                        result = await self.llm.extract_jobs_with_pagination(html, final_url)
                        jobs_data = result.get("jobs", [])
                        next_page_url = result.get("next_page_url")
            
            logger.debug(f"Extracted {len(jobs_data)} jobs from {final_url}")
            return jobs_data, next_page_url
            
        except Exception as e:
            error_msg = f"Error extracting jobs from {careers_url}: {e}"
            logger.warning(error_msg)
            console.print(f"[bold red]❌ {error_msg}[/bold red]")
            return [], None
        finally:
            # Clean up page and context
            if page_obj:
                try:
                    await page_obj.close()
                except Exception:
                    pass
            if context_obj:
                try:
                    await context_obj.close()
                except Exception:
                    pass

