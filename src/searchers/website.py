"""Universal job searcher for company websites."""

import logging
import re
from typing import Optional
from urllib.parse import urlparse

from src.models import Job
from src.searchers.base import BaseSearcher
from src.searchers.http_client import AsyncHttpClient
from src.searchers.url_discovery import CareerUrlDiscovery
from src.searchers.job_boards import (
    JobBoardParserRegistry,
    detect_job_board_platform,
    find_external_job_board,
)
from src.llm.base import BaseLLMProvider
from src.browser import DomainUnreachableError

logger = logging.getLogger(__name__)


class WebsiteSearcher(BaseSearcher):
    """Universal job searcher using LLM for analysis."""

    name = "website"

    def __init__(
        self,
        llm_provider: BaseLLMProvider,
        use_browser: bool = False,
        headless: bool = True,
    ):
        """
        Initialize searcher.

        Args:
            llm_provider: LLM provider for page analysis
            use_browser: Use Playwright for loading pages (for SPA)
            headless: Run browser without GUI (only if use_browser=True)
        """
        self.llm = llm_provider
        self.use_browser = use_browser
        self.headless = headless
        self._browser_loader = None

        # Initialize components
        self.http_client = AsyncHttpClient()
        self.url_discovery = CareerUrlDiscovery(self.http_client)
        self.job_board_parsers = JobBoardParserRegistry()

    async def _get_browser_loader(self):
        """Get or create BrowserLoader."""
        if self._browser_loader is None:
            from src.browser import BrowserLoader
            self._browser_loader = BrowserLoader(headless=self.headless)
            await self._browser_loader.start()
        return self._browser_loader

    async def search(
        self,
        keywords: str,  # In this case, it's the website URL
        location: Optional[str] = None,
        experience: Optional[str] = None,
        salary_from: Optional[int] = None,
        page: int = 0,
        per_page: int = 20,
    ) -> list[Job]:
        """
        Search for jobs on a company website.

        Args:
            keywords: URL of company's main page
            location: Not used (for compatibility)
            experience: Not used
            salary_from: Not used
            page: Not used
            per_page: Not used

        Returns:
            List of found jobs
        """
        url = keywords  # URL is passed as keywords for compatibility
        
        # Normalize URL
        if not url.startswith(('http://', 'https://')):
            url = f'https://{url}'

        careers_url = None

        try:
            # 0. Quick domain availability check
            await self.http_client.check_domain_available(url)
            
            # 1. Try to find via sitemap.xml (fast and reliable)
            careers_url = await self.url_discovery.find_from_sitemap(url, llm_fallback=self.llm)

            # 2. Load main page and search heuristically
            if not careers_url:
                html = await self._fetch(url)
                if html:
                    careers_url = self.url_discovery.find_from_html_heuristic(html, url)
                    
                    # 3. If not found - use LLM
                    if not careers_url:
                        careers_url = await self.llm.find_careers_url(html, url)

            # 4. Try alternative URLs directly
            if not careers_url or careers_url == "NOT_FOUND":
                careers_url = await self._try_alternative_urls(url)
                if not careers_url:
                    return []

            # 5. Load careers page (try URL variants: plural/singular)
            jobs_data = []
            careers_html = None
            
            for variant_url in self.url_discovery.generate_url_variants(careers_url):
                # For browser mode, try navigation to jobs (for SPA)
                if self.use_browser:
                    careers_html = await self._fetch_with_browser(variant_url, navigate_to_jobs=True)
                else:
                    careers_html = await self._fetch(variant_url)
                
                if not careers_html:
                    continue
                
                # 5.5. Check for external job board (Personio, Greenhouse, etc.)
                external_board_url = find_external_job_board(careers_html)
                external_platform = None
                if external_board_url:
                    logger.info(f"Found external job board: {external_board_url}")
                    external_platform = detect_job_board_platform(external_board_url)
                    # Load external job board via browser (many are SPA)
                    if self.use_browser:
                        external_html = await self._fetch_with_browser(external_board_url)
                    else:
                        external_html = await self.http_client.fetch(external_board_url)
                    if external_html:
                        careers_html = external_html
                        variant_url = external_board_url
                
                # 6. Extract jobs - try direct parser first, then LLM
                jobs_data = []
                
                # For known platforms use direct parser (faster and more reliable)
                if external_platform:
                    jobs_data = self.job_board_parsers.parse(careers_html, variant_url, external_platform)
                
                # Fallback to LLM
                if not jobs_data:
                    jobs_data = await self.llm.extract_jobs(careers_html, variant_url)
                
                if jobs_data:
                    careers_url = variant_url
                    logger.debug(f"Found {len(jobs_data)} jobs at {variant_url}")
                    break
                else:
                    logger.debug(f"No jobs found at {variant_url}, trying next variant...")
            
            if not careers_html:
                return []

            # 7. Translate job titles to English
            titles = [job_data.get("title", "Unknown Position") for job_data in jobs_data]
            titles_en = await self.llm.translate_job_titles(titles)

            # 8. Convert to Job models
            jobs = []
            company_name = self._extract_company_name(url)
            
            for idx, job_data in enumerate(jobs_data):
                job = Job(
                    id=f"web-{urlparse(url).netloc}-{idx}",
                    title=job_data.get("title", "Unknown Position"),
                    company=company_name,
                    location=job_data.get("location", "Unknown"),
                    url=job_data.get("url", careers_url),
                    source=f"website:{urlparse(url).netloc}",
                    title_en=titles_en[idx] if idx < len(titles_en) else None,
                    description=job_data.get("description"),
                )
                jobs.append(job)

            return jobs
            
        except DomainUnreachableError as e:
            logger.error(f"Domain unreachable: {url} - {e}")
            return []

    async def get_job_details(self, job_id: str) -> Optional[Job]:
        """Get job details (not implemented for website)."""
        return None

    async def _fetch(self, url: str) -> Optional[str]:
        """Fetch HTML content from URL."""
        if self.use_browser:
            return await self._fetch_with_browser(url)
        return await self.http_client.fetch(url)

    async def _fetch_with_browser(self, url: str, navigate_to_jobs: bool = False) -> Optional[str]:
        """Fetch HTML via Playwright (slow, with JS).
        
        Args:
            url: Page URL
            navigate_to_jobs: Try to navigate to jobs page (for SPA)
        """
        try:
            loader = await self._get_browser_loader()
            if navigate_to_jobs:
                return await loader.fetch_with_navigation(url)
            return await loader.fetch(url)
        except DomainUnreachableError:
            raise
        except Exception as e:
            logger.warning(f"Browser fetch error for {url}: {e}")
            return None

    async def _try_alternative_urls(self, base_url: str) -> Optional[str]:
        """Try alternative URLs for careers page."""
        alternatives = self.url_discovery.generate_alternative_urls(base_url)
        for alt_url in alternatives:
            try:
                html = await self._fetch(alt_url)
                if html:
                    return alt_url
            except DomainUnreachableError:
                logger.info("Domain unreachable, stopping URL iteration")
                raise
        return None

    def _extract_company_name(self, url: str) -> str:
        """Extract company name from URL."""
        parsed = urlparse(url)
        domain = parsed.netloc
        
        # Remove www and common TLDs
        name = domain.replace('www.', '')
        name = re.sub(r'\.(com|ru|org|net|io|co|tech)$', '', name)
        
        return name.title()

    async def close(self):
        """Close HTTP client, browser and LLM provider."""
        await self.http_client.close()
        if self._browser_loader:
            await self._browser_loader.stop()
        await self.llm.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
