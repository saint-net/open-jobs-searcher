"""Universal job searcher for company websites."""

import logging
import re
from typing import Optional
from urllib.parse import urlparse, parse_qs

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
            
            # 1. Check for career-related subdomains (e.g., jobs.example.com)
            careers_url = await self.url_discovery.discover_career_subdomain(url)
            if careers_url:
                logger.info(f"Found career subdomain: {careers_url}")
            
            # 2. Try to find via sitemap.xml (fast and reliable)
            if not careers_url:
                careers_url = await self.url_discovery.find_from_sitemap(url, llm_fallback=self.llm)

            # 3. Load main page and search heuristically
            if not careers_url:
                html = await self._fetch(url)
                if html:
                    careers_url = self.url_discovery.find_from_html_heuristic(html, url)
                    
                    # 4. If not found - use LLM
                    if not careers_url:
                        careers_url = await self.llm.find_careers_url(html, url)

            # 5. Try alternative URLs directly
            if not careers_url or careers_url == "NOT_FOUND":
                careers_url = await self._try_alternative_urls(url)
                if not careers_url:
                    return []

            # 6. Load careers page (try URL variants: plural/singular)
            jobs_data = []
            careers_html = None
            
            for variant_url in self.url_discovery.generate_url_variants(careers_url):
                # For browser mode, try navigation to jobs (for SPA)
                final_url = variant_url
                already_on_job_board = False
                
                if self.use_browser:
                    careers_html, final_url = await self._fetch_with_browser(variant_url, navigate_to_jobs=True)
                    final_url = final_url or variant_url
                    # Check if we navigated to a different domain (external career site)
                    # or a known external job board platform
                    already_on_job_board = detect_job_board_platform(final_url) is not None
                    navigated_to_external = urlparse(final_url).netloc != urlparse(variant_url).netloc
                    if already_on_job_board or navigated_to_external:
                        if navigated_to_external:
                            logger.debug(f"Navigated to external career site: {final_url}")
                        variant_url = final_url
                else:
                    careers_html = await self._fetch(variant_url)
                
                if not careers_html:
                    continue
                
                # 6.5. Check for external job board (Personio, Greenhouse, etc.)
                # Skip if we already navigated to an external job board
                external_platform = None
                if not already_on_job_board:
                    external_board_url = find_external_job_board(careers_html)
                    if external_board_url:
                        logger.info(f"Found external job board: {external_board_url}")
                        external_platform = detect_job_board_platform(external_board_url)
                        # Load external job board via browser (many are SPA)
                        if self.use_browser:
                            external_html, _ = await self._fetch_with_browser(external_board_url)
                        else:
                            external_html = await self.http_client.fetch(external_board_url)
                        if external_html:
                            careers_html = external_html
                            variant_url = external_board_url
                else:
                    # Already on external job board, get platform for parser
                    external_platform = detect_job_board_platform(final_url)
                    logger.debug(f"Already on external job board: {final_url} (platform: {external_platform})")
                
                # 7. Extract jobs - try direct parser first, then LLM
                jobs_data = []
                
                # For known platforms use direct parser (faster and more reliable)
                if external_platform:
                    jobs_data = self.job_board_parsers.parse(careers_html, variant_url, external_platform)
                
                # Fallback to LLM
                if not jobs_data:
                    jobs_data = await self.llm.extract_jobs(careers_html, variant_url)
                
                # Filter jobs if we're on a search results page
                jobs_data = self._filter_jobs_by_search_query(jobs_data, variant_url)
                
                # Filter jobs by source company (for multi-company career portals)
                if navigated_to_external and jobs_data:
                    jobs_data = self._filter_jobs_by_source_company(jobs_data, url)
                
                if jobs_data:
                    careers_url = variant_url
                    logger.debug(f"Found {len(jobs_data)} jobs at {variant_url}")
                    break
                else:
                    logger.debug(f"No jobs found at {variant_url}, trying next variant...")
            
            if not careers_html:
                return []

            # 8. Translate job titles to English
            titles = [job_data.get("title", "Unknown Position") for job_data in jobs_data]
            titles_en = await self.llm.translate_job_titles(titles)

            # 9. Convert to Job models
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
            html, _ = await self._fetch_with_browser(url)
            return html
        return await self.http_client.fetch(url)

    async def _fetch_with_browser(
        self, url: str, navigate_to_jobs: bool = False
    ) -> tuple[Optional[str], Optional[str]]:
        """Fetch HTML via Playwright (slow, with JS).
        
        Args:
            url: Page URL
            navigate_to_jobs: Try to navigate to jobs page (for SPA)
            
        Returns:
            Tuple (HTML, final_url) - final_url may differ from url if navigation occurred
        """
        try:
            loader = await self._get_browser_loader()
            if navigate_to_jobs:
                return await loader.fetch_with_navigation(url)
            html = await loader.fetch(url)
            return html, url
        except DomainUnreachableError:
            raise
        except Exception as e:
            logger.warning(f"Browser fetch error for {url}: {e}")
            return None, None

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

    def _filter_jobs_by_search_query(self, jobs_data: list[dict], url: str) -> list[dict]:
        """Filter jobs to only those matching the search query in URL.
        
        When navigating to a job board search page (e.g., job.deloitte.com/search?search=27pilots),
        the page may show both search results AND recommended/featured jobs.
        This method filters to keep only jobs that match the search query.
        
        Args:
            jobs_data: List of job dictionaries
            url: Current page URL
            
        Returns:
            Filtered list of jobs matching the search query
        """
        if not jobs_data:
            return jobs_data
        
        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)
        
        # Check for common search parameter names
        search_term = None
        for param_name in ['search', 'q', 'query', 'keyword', 'keywords']:
            if param_name in query_params:
                search_term = query_params[param_name][0].lower()
                break
        
        if not search_term:
            return jobs_data
        
        # Filter jobs that contain the search term in their title
        filtered = []
        for job in jobs_data:
            title = job.get('title', '').lower()
            if search_term in title:
                filtered.append(job)
        
        if filtered:
            logger.debug(f"Filtered jobs by search term '{search_term}': {len(jobs_data)} -> {len(filtered)}")
            return filtered
        
        # If no jobs match, return all (search might be for company name/tag not in title)
        logger.debug(f"No jobs matched search term '{search_term}', keeping all {len(jobs_data)}")
        return jobs_data

    def _filter_jobs_by_source_company(self, jobs_data: list[dict], source_url: str) -> list[dict]:
        """Filter jobs to only those related to the source company.
        
        When navigating from a company website (e.g., 2rsoftware.de) to a 
        multi-company career portal (e.g., karriere.synqony.com), filter
        jobs to only show positions from the original company.
        
        Args:
            jobs_data: List of job dictionaries
            source_url: Original company website URL
            
        Returns:
            Filtered list of jobs (or all jobs if no matches found)
        """
        if not jobs_data:
            return jobs_data
        
        # Extract company identifier from source URL
        parsed = urlparse(source_url)
        domain = parsed.netloc.replace('www.', '')
        
        # Get company name variants from domain
        # e.g., "2rsoftware.de" -> ["2rsoftware", "2r software", "2r"]
        company_base = domain.split('.')[0]  # "2rsoftware"
        company_variants = [
            company_base.lower(),  # "2rsoftware"
            company_base.lower().replace('-', ' '),  # for domains like "my-company"
        ]
        
        # Add common variations
        # "2rsoftware" -> also match "2r software", "2r"
        if company_base.lower().startswith('2r'):
            company_variants.extend(['2r software', '2r'])
        
        # Filter jobs that mention the source company
        filtered = []
        for job in jobs_data:
            job_text = (
                job.get('title', '') + ' ' + 
                job.get('location', '') + ' ' +
                job.get('description', '') + ' ' +
                job.get('company', '')  # Company name from job card
            ).lower()
            
            # Check if any company variant is mentioned
            for variant in company_variants:
                if variant in job_text:
                    filtered.append(job)
                    break
        
        if filtered:
            logger.debug(f"Filtered jobs by source company: {len(jobs_data)} -> {len(filtered)}")
            return filtered
        
        # If no matches, return all jobs (company name might not be in job text)
        logger.debug(f"No jobs matched source company variants {company_variants}, keeping all {len(jobs_data)}")
        return jobs_data

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
