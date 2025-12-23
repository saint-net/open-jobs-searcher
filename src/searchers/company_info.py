"""Company info extraction utilities."""

import logging
from typing import Optional, Callable, Awaitable

from src.database import JobRepository
from src.searchers.job_converter import extract_company_name

logger = logging.getLogger(__name__)


class CompanyInfoExtractor:
    """Extracts and saves company information from main page.
    
    Uses LLM to analyze company's main page and extract description.
    Skips extraction if company already has a description in database.
    """
    
    def __init__(
        self,
        repository: Optional[JobRepository],
        extract_company_info: Callable[[str, str], Awaitable[Optional[str]]],
        fetch_html: Callable[[str], Awaitable[Optional[str]]],
    ):
        """
        Initialize company info extractor.
        
        Args:
            repository: JobRepository for database operations (or None if caching disabled)
            extract_company_info: LLM function to extract company info from HTML
            fetch_html: Function to fetch HTML from URL
        """
        self._repository = repository
        self._extract_company_info = extract_company_info
        self._fetch_html = fetch_html
    
    async def extract_and_save(
        self, domain: str, html: Optional[str] = None
    ) -> None:
        """Extract company info from main page and save to database.
        
        Skips if company already has description or caching is disabled.
        
        Args:
            domain: Company domain
            html: Pre-fetched HTML of main page (avoids re-fetch if provided)
        """
        if not self._repository:
            return
            
        try:
            # Check if site exists and already has description
            site = await self._repository.get_site_by_domain(domain)
            if site and site.description:
                return  # Already has description
            
            # Use pre-fetched HTML or fetch main page
            main_page_url = f"https://{domain}"
            if not html:
                html = await self._fetch_html(main_page_url)
            
            if html:
                description = await self._extract_company_info(html, main_page_url)
                if description:
                    # Get or create site first
                    company_name = extract_company_name(main_page_url)
                    site = await self._repository.get_or_create_site(domain, company_name)
                    await self._repository.update_site_description(site.id, description)
                    logger.info(f"Extracted company info for {domain}: {description[:50]}...")
        except Exception as e:
            logger.warning(f"Failed to extract company info for {domain}: {e}")
