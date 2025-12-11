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
from src.searchers.job_filters import (
    filter_jobs_by_search_query,
    filter_jobs_by_source_company,
)
from src.searchers.job_extraction import JobExtractor
from src.searchers.cache_manager import CacheManager
from src.llm.base import BaseLLMProvider
from src.llm.cache import LLMCache
from src.browser import DomainUnreachableError, PlaywrightBrowsersNotInstalledError
from src.database import JobRepository
from src.database.models import SyncResult

logger = logging.getLogger(__name__)


class WebsiteSearcher(BaseSearcher):
    """Universal job searcher using LLM for analysis."""

    name = "website"

    def __init__(
        self,
        llm_provider: BaseLLMProvider,
        use_browser: bool = True,  # Always use browser for better accuracy
        headless: bool = True,
        use_cache: bool = True,  # Use SQLite cache for faster re-scans
    ):
        """
        Initialize searcher.

        Args:
            llm_provider: LLM provider for page analysis
            use_browser: Use Playwright for loading pages (always True for accuracy)
            headless: Run browser without GUI
            use_cache: Use SQLite cache for career URLs and job tracking
        """
        self.llm = llm_provider
        self.use_browser = True  # Always use browser for accessibility tree
        self.headless = headless
        self.use_cache = use_cache
        self._browser_loader = None
        self._job_extractor = None
        self._cache_manager = None
        self._llm_cache = None
        
        # Last sync result (for reporting new/removed jobs)
        self.last_sync_result: Optional[SyncResult] = None

        # Initialize components
        self.http_client = AsyncHttpClient()
        self.url_discovery = CareerUrlDiscovery(self.http_client)
        self.job_board_parsers = JobBoardParserRegistry()
        
        # Database repository for caching
        self._repository = JobRepository() if use_cache else None
        
        # Set up LLM cache if caching is enabled
        if use_cache and self._repository:
            self._llm_cache = LLMCache(self._repository)
            self.llm.set_cache(self._llm_cache)

    async def _get_browser_loader(self):
        """Get or create BrowserLoader."""
        if self._browser_loader is None:
            from src.browser import BrowserLoader
            self._browser_loader = BrowserLoader(headless=self.headless)
            await self._browser_loader.start()
        return self._browser_loader

    def _get_job_extractor(self) -> JobExtractor:
        """Get or create JobExtractor."""
        if self._job_extractor is None:
            self._job_extractor = JobExtractor(
                llm_provider=self.llm,
                job_board_parsers=self.job_board_parsers,
                fetch_with_page=self._fetch_with_page_object,
                fetch_jobs_from_api=self._fetch_jobs_from_api,
            )
        return self._job_extractor

    def _get_cache_manager(self) -> CacheManager:
        """Get or create CacheManager."""
        if self._cache_manager is None:
            self._cache_manager = CacheManager(
                repository=self._repository,
                extract_jobs=self._get_job_extractor().extract_jobs,
                convert_jobs=self._convert_jobs_data,
                fetch_html=self._fetch,
                extract_company_info=self.llm.extract_company_info,
                extract_company_name=self._extract_company_name,
            )
        return self._cache_manager

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
        
        # Reset last sync result
        self.last_sync_result = None

        # Extract domain for caching
        domain = urlparse(url).netloc.replace('www.', '')

        try:
            # 0. Quick domain availability check
            await self.http_client.check_domain_available(url)
            
            # 0.1 Check for domain redirect (e.g., 7pace.com -> appfire.com)
            final_url, redirected_to_different_domain = await self.http_client.check_redirect(url)
            if redirected_to_different_domain:
                original_domain = urlparse(url).netloc.replace('www.', '')
                new_domain = urlparse(final_url).netloc.replace('www.', '')
                logger.warning(
                    f"Domain {original_domain} redirects to {new_domain}. "
                    f"Company may have been acquired or rebranded. "
                    f"Searching on {new_domain} instead."
                )
                # Use new domain for search
                new_base_url = f"https://{new_domain}"
                url = new_base_url
                domain = new_domain
            
            # Try to use cached career URLs first
            if self.use_cache and self._repository:
                cache_mgr = self._get_cache_manager()
                jobs = await cache_mgr.search_with_cache(url, domain)
                if jobs is not None:  # None means cache miss or all URLs failed
                    self.last_sync_result = cache_mgr.last_sync_result
                    return jobs
            
            # Full discovery (first time or cache miss)
            return await self._search_full_discovery(url, domain)
            
        except DomainUnreachableError as e:
            logger.error(f"Domain unreachable: {url} - {e}")
            return []
    
    def _choose_best_careers_url(self, sitemap_url: Optional[str], nav_url: Optional[str]) -> Optional[str]:
        """Choose the best careers URL between sitemap and navigation link.
        
        Navigation links from main page are often better because:
        - Sitemap might return specific job page instead of listing
        - Navigation links point to actual job listing pages
        
        Args:
            sitemap_url: URL found from sitemap.xml
            nav_url: URL found from main page navigation
            
        Returns:
            Best URL to use, or None if both are invalid
        """
        # If only one exists, use it
        if not sitemap_url or sitemap_url == "NOT_FOUND":
            return nav_url
        if not nav_url:
            return sitemap_url
        
        # Both exist - compare them
        sitemap_path = urlparse(sitemap_url).path.rstrip('/')
        nav_path = urlparse(nav_url).path.rstrip('/')
        
        sitemap_segments = [s for s in sitemap_path.split('/') if s]
        nav_segments = [s for s in nav_path.split('/') if s]
        
        # Check if sitemap URL looks like a specific job page (has slug after /career/)
        # e.g., /en/career/devops-engineer vs /en/career or /en/ui
        sitemap_last = sitemap_segments[-1] if sitemap_segments else ''
        nav_last = nav_segments[-1] if nav_segments else ''
        
        # Job listing keywords that indicate a listing page (not specific job)
        listing_keywords = {'jobs', 'careers', 'career', 'vacancies', 'openings', 
                          'stellen', 'karriere', 'stellenangebote', 'offene-stellen',
                          'вакансии', 'карьера'}
        
        sitemap_is_listing = sitemap_last.lower() in listing_keywords
        nav_is_listing = nav_last.lower() in listing_keywords
        
        # Prefer listing pages over specific job pages
        if nav_is_listing and not sitemap_is_listing:
            logger.debug(f"Preferring nav URL (listing page): {nav_url} over sitemap: {sitemap_url}")
            return nav_url
        if sitemap_is_listing and not nav_is_listing:
            logger.debug(f"Preferring sitemap URL (listing page): {sitemap_url} over nav: {nav_url}")
            return sitemap_url
        
        # Both are similar type - prefer shorter path (likely parent/listing page)
        if len(nav_segments) < len(sitemap_segments):
            logger.debug(f"Preferring nav URL (shorter path): {nav_url} over sitemap: {sitemap_url}")
            return nav_url
        
        # If sitemap URL has a long slug (likely specific job), prefer nav
        if len(sitemap_last) > 20 and len(nav_last) <= 20:
            logger.debug(f"Preferring nav URL (sitemap has long slug): {nav_url} over sitemap: {sitemap_url}")
            return nav_url
        
        # Default: prefer sitemap (usually more reliable)
        logger.debug(f"Using sitemap URL: {sitemap_url} (nav was: {nav_url})")
        return sitemap_url
    
    async def _search_full_discovery(self, url: str, domain: str) -> list[Job]:
        """Full career page discovery using LLM.
        
        Args:
            url: Original URL
            domain: Site domain
            
        Returns:
            List of found jobs
        """
        careers_url = None

        try:
            # 1. Load main page and sitemap URLs for LLM analysis
            html = await self._fetch(url)
            sitemap_urls = await self.url_discovery.fetch_all_sitemap_urls(url)
            
            # 2. LLM analyzes HTML + sitemap to find careers URL
            if html:
                logger.info("Using LLM to find careers/jobs URL (HTML + sitemap)")
                careers_url = await self.llm.find_careers_url(html, url, sitemap_urls)
                
                if careers_url and careers_url != "NOT_FOUND":
                    logger.info(f"LLM found careers page: {careers_url}")
                    
                    # 3. Load careers page and look for job board URL
                    # Many companies have a landing page that links to external job board
                    # BUT: Skip if we're already on a known job board platform
                    if not detect_job_board_platform(careers_url):
                        careers_html = await self._fetch(careers_url)
                        if careers_html:
                            job_board_url = await self.llm.find_job_board_url(careers_html, careers_url)
                            if job_board_url:
                                logger.info(f"LLM found job board: {job_board_url}")
                                careers_url = job_board_url
                    else:
                        logger.debug(f"Already on job board platform, skipping job_board_url search")
                else:
                    logger.warning(f"LLM could not find careers URL on {url}")
                    return []
            else:
                logger.warning(f"Could not load page: {url}")
                return []

            # 6. Load careers page (try URL variants: plural/singular)
            jobs_data = []
            careers_html = None
            
            for variant_url in self.url_discovery.generate_url_variants(careers_url):
                # Always use browser with page object for accessibility tree
                final_url = variant_url
                already_on_job_board = detect_job_board_platform(variant_url) is not None
                page_obj = None
                context_obj = None
                navigated_to_external = False
                
                try:
                    # Fetch with page object for accessibility tree extraction
                    # Don't navigate if we're already on a job board platform
                    careers_html, final_url, page_obj, context_obj = await self._fetch_with_page_object(
                        variant_url, navigate_to_jobs=not already_on_job_board
                    )
                    final_url = final_url or variant_url
                    
                    # Ignore chrome-error:// URLs (navigation failed)
                    if final_url.startswith("chrome-error://"):
                        logger.debug(f"Navigation failed (chrome-error), using original URL")
                        final_url = variant_url
                    
                    # Check if we navigated to a different domain (external career site)
                    # or a known external job board platform
                    already_on_job_board = detect_job_board_platform(final_url) is not None
                    # Normalize domains by removing www. prefix for comparison
                    final_domain = urlparse(final_url).netloc.replace('www.', '')
                    variant_domain = urlparse(variant_url).netloc.replace('www.', '')
                    navigated_to_external = final_domain != variant_domain
                    if already_on_job_board or navigated_to_external:
                        if navigated_to_external:
                            logger.debug(f"Navigated to external career site: {final_url}")
                        variant_url = final_url
                    
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
                            # Close current page and load external job board
                            if page_obj:
                                await page_obj.close()
                            if context_obj:
                                await context_obj.close()
                            
                            careers_html, _, page_obj, context_obj = await self._fetch_with_page_object(
                                external_board_url
                            )
                            if careers_html:
                                variant_url = external_board_url
                        else:
                            # No external board URL found, but page might be an embedded job board
                            # (e.g., Recruitee with custom domain)
                            external_platform = detect_job_board_platform(variant_url, careers_html)
                            if external_platform:
                                logger.debug(f"Detected embedded job board platform: {external_platform}")
                    else:
                        # Already on external job board, get platform for parser
                        external_platform = detect_job_board_platform(final_url, careers_html)
                        logger.debug(f"Already on external job board: {final_url} (platform: {external_platform})")
                    
                    if not careers_html:
                        continue
                    
                    # 7. Extract jobs - try direct parser first, then LLM with pagination
                    jobs_data = []
                    
                    # For known platforms use direct parser (faster and more reliable)
                    if external_platform:
                        # Check if platform requires API call (e.g., Recruitee)
                        if self.job_board_parsers.is_api_based(external_platform):
                            jobs_data = await self._fetch_jobs_from_api(variant_url, external_platform)
                        else:
                            jobs_data = self.job_board_parsers.parse(careers_html, variant_url, external_platform)
                    
                    # Use LLM extraction with pagination support
                    if not jobs_data:
                        # Close page objects before pagination loop (we'll open new ones per page)
                        if page_obj:
                            try:
                                await page_obj.close()
                            except Exception:
                                pass
                            page_obj = None
                        if context_obj:
                            try:
                                await context_obj.close()
                            except Exception:
                                pass
                            context_obj = None
                        
                        # Extract jobs with pagination
                        jobs_data = await self._get_job_extractor().extract_jobs(variant_url, url)
                    
                    # Filter jobs by source company and search query (for multi-company career portals)
                    # Only applies to external job boards, not internal navigation
                    if navigated_to_external and jobs_data:
                        jobs_data = filter_jobs_by_search_query(jobs_data, variant_url)
                        jobs_data = filter_jobs_by_source_company(jobs_data, url)
                    
                    if jobs_data:
                        careers_url = variant_url
                        logger.debug(f"Found {len(jobs_data)} jobs at {variant_url}")
                        break
                    else:
                        logger.debug(f"No jobs found at {variant_url}, trying next variant...")
                        
                finally:
                    # Always clean up page and context
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
            
            if not careers_html:
                return []

            # 7. Convert to Job models with translation
            jobs = await self._convert_jobs_data(jobs_data, url, careers_url)
            
            # 9. Save to cache if enabled
            # Сохраняем сайт и career_url даже если вакансий сейчас нет,
            # чтобы отслеживать компанию при следующих сканированиях
            if self.use_cache and self._repository and careers_url:
                cache_mgr = self._get_cache_manager()
                await cache_mgr.save_to_cache(domain, careers_url, jobs)
                self.last_sync_result = cache_mgr.last_sync_result

            return jobs
            
        except DomainUnreachableError as e:
            logger.error(f"Domain unreachable: {url} - {e}")
            return []
    
    async def _convert_jobs_data(
        self, 
        jobs_data: list[dict], 
        url: str, 
        careers_url: str
    ) -> list[Job]:
        """Convert raw job data to Job objects with translation.
        
        Args:
            jobs_data: Raw job dictionaries
            url: Original URL
            careers_url: Career page URL (for fallback)
            
        Returns:
            List of Job objects
        """
        if not jobs_data:
            return []
        
        # Translate job titles to English
        titles = [job_data.get("title", "Unknown Position") for job_data in jobs_data]
        titles_en = await self.llm.translate_job_titles(titles)

        # Convert to Job models
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
        except (DomainUnreachableError, PlaywrightBrowsersNotInstalledError):
            raise
        except Exception as e:
            logger.warning(f"Browser fetch error for {url}: {e}")
            return None, None

    async def _fetch_with_page_object(
        self, url: str, navigate_to_jobs: bool = False
    ) -> tuple[Optional[str], Optional[str], Optional[object], Optional[object]]:
        """Fetch HTML and return page object for accessibility tree extraction.
        
        Args:
            url: Page URL
            navigate_to_jobs: Try to navigate to jobs page (for SPA)
            
        Returns:
            Tuple (HTML, final_url, page, context) - caller must close page and context!
        """
        try:
            loader = await self._get_browser_loader()
            return await loader.fetch_with_page(url, navigate_to_jobs=navigate_to_jobs)
        except (DomainUnreachableError, PlaywrightBrowsersNotInstalledError):
            raise
        except Exception as e:
            logger.warning(f"Browser fetch error for {url}: {e}")
            return None, None, None, None

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

    async def _fetch_jobs_from_api(self, base_url: str, platform: str) -> list[dict]:
        """Fetch jobs from API for platforms that require it.
        
        Some platforms (like Recruitee) render job listings via JavaScript
        and provide a JSON API endpoint instead of static HTML.
        
        Args:
            base_url: Base URL of the career site
            platform: Platform name (e.g., 'recruitee')
            
        Returns:
            List of job dictionaries
        """
        api_url = self.job_board_parsers.get_api_url(base_url, platform)
        if not api_url:
            logger.debug(f"No API URL for platform: {platform}")
            return []
        
        try:
            logger.debug(f"Fetching jobs from API: {api_url}")
            json_text = await self.http_client.fetch(api_url)
            if not json_text:
                return []
            
            import json
            json_data = json.loads(json_text)
            jobs = self.job_board_parsers.parse_api_json(json_data, base_url, platform)
            logger.debug(f"Fetched {len(jobs)} jobs from {platform} API")
            return jobs
            
        except Exception as e:
            logger.warning(f"Error fetching jobs from API {api_url}: {e}")
            return []

    def _extract_company_name(self, url: str) -> str:
        """Extract company name from URL."""
        parsed = urlparse(url)
        domain = parsed.netloc
        
        # Remove www and common TLDs
        name = domain.replace('www.', '')
        name = re.sub(r'\.(com|ru|org|net|io|co|tech)$', '', name)
        
        return name.title()

    async def close(self):
        """Close HTTP client, browser, LLM provider and database."""
        await self.http_client.close()
        if self._browser_loader:
            await self._browser_loader.stop()
        await self.llm.close()
        if self._repository:
            await self._repository.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
