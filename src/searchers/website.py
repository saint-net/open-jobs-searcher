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
        
        # Last sync result (for reporting new/removed jobs)
        self.last_sync_result: Optional[SyncResult] = None

        # Initialize components
        self.http_client = AsyncHttpClient()
        self.url_discovery = CareerUrlDiscovery(self.http_client)
        self.job_board_parsers = JobBoardParserRegistry()
        
        # Database repository for caching
        self._repository = JobRepository() if use_cache else None

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
        
        # Reset last sync result
        self.last_sync_result = None

        # Extract domain for caching
        domain = urlparse(url).netloc.replace('www.', '')

        try:
            # 0. Quick domain availability check
            await self.http_client.check_domain_available(url)
            
            # Try to use cached career URLs first
            if self.use_cache and self._repository:
                jobs = await self._search_with_cache(url, domain)
                if jobs is not None:  # None means cache miss or all URLs failed
                    return jobs
            
            # Full discovery (first time or cache miss)
            return await self._search_full_discovery(url, domain)
            
        except DomainUnreachableError as e:
            logger.error(f"Domain unreachable: {url} - {e}")
            return []
    
    async def _search_with_cache(self, url: str, domain: str) -> Optional[list[Job]]:
        """Try to search using cached career URLs.
        
        Args:
            url: Original URL
            domain: Site domain
            
        Returns:
            List of jobs if cache hit and successful, None if should fall back to full discovery
        """
        site = await self._repository.get_site_by_domain(domain)
        if not site:
            logger.debug(f"No cached data for {domain}, will do full discovery")
            return None
        
        # Get cached career URLs
        career_urls = await self._repository.get_career_urls(site.id)
        if not career_urls:
            logger.debug(f"No cached career URLs for {domain}, will do full discovery")
            return None
        
        logger.info(f"Using {len(career_urls)} cached career URL(s) for {domain}")
        
        # Try each cached URL
        all_jobs_data = []
        working_url = None
        
        for career_url in career_urls:
            try:
                logger.debug(f"Trying cached URL: {career_url.url}")
                jobs_data = await self._extract_jobs_from_url(career_url.url, url)
                
                if jobs_data:
                    all_jobs_data.extend(jobs_data)
                    working_url = career_url
                    await self._repository.mark_url_success(career_url.id)
                    logger.debug(f"Cached URL worked: {len(jobs_data)} jobs from {career_url.url}")
                else:
                    # No jobs found - might be suspicious
                    prev_count = await self._repository.get_previous_job_count(site.id)
                    if prev_count > 5:
                        # Had many jobs before, now 0 - URL might be broken
                        logger.warning(f"Suspicious: {prev_count} jobs -> 0 at {career_url.url}")
                        is_inactive = await self._repository.mark_url_failed(career_url.id)
                        if is_inactive:
                            continue
                    
            except Exception as e:
                logger.warning(f"Cached URL failed: {career_url.url} - {e}")
                await self._repository.mark_url_failed(career_url.id)
                continue
        
        if not all_jobs_data:
            # All cached URLs failed - fall back to full discovery
            logger.info(f"All cached URLs failed for {domain}, falling back to full discovery")
            return None
        
        # Deduplicate by (title, location)
        seen = set()
        unique_jobs_data = []
        for job_data in all_jobs_data:
            key = (
                job_data.get("title", "").lower().strip(),
                job_data.get("location", "").lower().strip()
            )
            if key not in seen:
                seen.add(key)
                unique_jobs_data.append(job_data)
        
        # Translate and convert to Job objects
        jobs = await self._convert_jobs_data(unique_jobs_data, url, working_url.url if working_url else url)
        
        # Sync with database and track changes
        sync_result = await self._repository.sync_jobs(site.id, jobs)
        self.last_sync_result = sync_result
        
        # Update site scan timestamp
        await self._repository.update_site_scanned(site.id)
        
        if sync_result.has_changes:
            logger.info(
                f"Job changes for {domain}: "
                f"+{len(sync_result.new_jobs)} new, "
                f"-{len(sync_result.removed_jobs)} removed, "
                f"↻{len(sync_result.reactivated_jobs)} reactivated"
            )
        
        return jobs
    
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
        """Full career page discovery (first time or fallback).
        
        Args:
            url: Original URL
            domain: Site domain
            
        Returns:
            List of found jobs
        """
        careers_url = None
        career_subdomain = None

        try:
            # 1. Check for career-related subdomains (e.g., jobs.example.com)
            # Save for later - we'll also check main domain
            career_subdomain = await self.url_discovery.discover_career_subdomain(url)
            if career_subdomain:
                logger.info(f"Found career subdomain: {career_subdomain}")
            
            # 2. Try to find careers page on MAIN domain first
            # (often has more complete job listings than subdomain)
            
            # 2a. Try sitemap.xml
            sitemap_url = await self.url_discovery.find_from_sitemap(url, llm_fallback=self.llm)
            
            # 2b. ALWAYS load main page and search for career nav link
            # (even if sitemap found something - sitemap might return specific job page)
            html = await self._fetch(url)
            nav_url = None
            if html:
                nav_url = self.url_discovery.find_from_html_heuristic(html, url)
            
            # 2c. Choose best URL between sitemap and navigation
            careers_url = self._choose_best_careers_url(sitemap_url, nav_url)
            
            # 2d. If still nothing - use LLM on main page
            if not careers_url and html:
                careers_url = await self.llm.find_careers_url(html, url)

            # 2e. Try alternative URLs directly
            if not careers_url or careers_url == "NOT_FOUND":
                careers_url = await self._try_alternative_urls(url)
            
            # 3. If no careers page on main domain, use subdomain
            if (not careers_url or careers_url == "NOT_FOUND") and career_subdomain:
                careers_url = career_subdomain
            
            if not careers_url or careers_url == "NOT_FOUND":
                return []

            # 6. Load careers page (try URL variants: plural/singular)
            jobs_data = []
            careers_html = None
            
            for variant_url in self.url_discovery.generate_url_variants(careers_url):
                # Always use browser with page object for accessibility tree
                final_url = variant_url
                already_on_job_board = False
                page_obj = None
                context_obj = None
                navigated_to_external = False
                
                try:
                    # Fetch with page object for accessibility tree extraction
                    careers_html, final_url, page_obj, context_obj = await self._fetch_with_page_object(
                        variant_url, navigate_to_jobs=True
                    )
                    final_url = final_url or variant_url
                    
                    # Check if we navigated to a different domain (external career site)
                    # or a known external job board platform
                    already_on_job_board = detect_job_board_platform(final_url) is not None
                    navigated_to_external = urlparse(final_url).netloc != urlparse(variant_url).netloc
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
                    
                    # 7. Extract jobs - try direct parser first, then hybrid with accessibility
                    jobs_data = []
                    
                    # For known platforms use direct parser (faster and more reliable)
                    if external_platform:
                        # Check if platform requires API call (e.g., Recruitee)
                        if self.job_board_parsers.is_api_based(external_platform):
                            jobs_data = await self._fetch_jobs_from_api(variant_url, external_platform)
                        else:
                            jobs_data = self.job_board_parsers.parse(careers_html, variant_url, external_platform)
                    
                    # Use hybrid extraction with accessibility tree (page object)
                    if not jobs_data:
                        jobs_data = await self.llm.extract_jobs(careers_html, variant_url, page=page_obj)
                    
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

            # 7.5. If we have a subdomain AND we got jobs from main page,
            # also check subdomain for additional jobs (subdomain often has more detail)
            if career_subdomain and careers_url != career_subdomain:
                subdomain_jobs = await self._extract_jobs_from_url(career_subdomain, url)
                if subdomain_jobs:
                    # Merge jobs from both sources
                    # Start with subdomain jobs (usually more detailed with individual URLs)
                    merged_jobs = list(subdomain_jobs)
                    subdomain_titles = {j.get('title', '').lower().strip() for j in subdomain_jobs}
                    
                    # Add jobs from main page that aren't in subdomain
                    added_from_main = 0
                    for job in jobs_data:
                        job_title = job.get('title', '').lower().strip()
                        if job_title and job_title not in subdomain_titles:
                            merged_jobs.append(job)
                            subdomain_titles.add(job_title)
                            added_from_main += 1
                    
                    if added_from_main:
                        logger.info(f"Added {added_from_main} unique jobs from main careers page")
                    
                    jobs_data = merged_jobs
                    logger.info(f"Total jobs after merge: {len(jobs_data)}")

            # 8. Convert to Job models with translation
            jobs = await self._convert_jobs_data(jobs_data, url, careers_url)
            
            # 9. Save to cache if enabled
            if self.use_cache and self._repository and jobs:
                await self._save_to_cache(domain, careers_url, jobs)

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
    
    async def _save_to_cache(self, domain: str, careers_url: str, jobs: list[Job]) -> None:
        """Save discovered career URL and jobs to cache.
        
        Args:
            domain: Site domain
            careers_url: Discovered career page URL
            jobs: Found jobs
        """
        try:
            # Get or create site
            company_name = self._extract_company_name(f"https://{domain}")
            site = await self._repository.get_or_create_site(domain, company_name)
            
            # Detect platform from URL
            platform = detect_job_board_platform(careers_url)
            
            # Save career URL
            await self._repository.add_career_url(site.id, careers_url, platform)
            logger.debug(f"Cached career URL for {domain}: {careers_url}")
            
            # Sync jobs (this also handles new/removed tracking)
            sync_result = await self._repository.sync_jobs(site.id, jobs)
            self.last_sync_result = sync_result
            
            # Update site scan timestamp
            await self._repository.update_site_scanned(site.id)
            
            logger.info(f"Cached {len(jobs)} jobs for {domain}")
            
            if sync_result.has_changes:
                logger.info(
                    f"First scan for {domain}: "
                    f"+{len(sync_result.new_jobs)} jobs added"
                )
                
        except Exception as e:
            logger.warning(f"Failed to save to cache: {e}")

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

    async def _extract_jobs_from_url(self, careers_url: str, original_url: str) -> list[dict]:
        """Extract jobs from a single careers URL.
        
        Args:
            careers_url: URL of careers/jobs page
            original_url: Original company URL (for filtering)
            
        Returns:
            List of job dictionaries
        """
        jobs_data = []
        page_obj = None
        context_obj = None
        
        try:
            # Load page with page object for accessibility tree
            html, final_url, page_obj, context_obj = await self._fetch_with_page_object(
                careers_url, navigate_to_jobs=True
            )
            final_url = final_url or careers_url
            
            if not html:
                return []
            
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
                    
                    html, _, page_obj, context_obj = await self._fetch_with_page_object(external_board_url)
                    if not html:
                        return []
                    final_url = external_board_url
            
            # Extract jobs using parser or hybrid with accessibility
            if external_platform:
                # Check if platform requires API call (e.g., Recruitee)
                if self.job_board_parsers.is_api_based(external_platform):
                    jobs_data = await self._fetch_jobs_from_api(final_url, external_platform)
                else:
                    jobs_data = self.job_board_parsers.parse(html, final_url, external_platform)
            
            if not jobs_data:
                jobs_data = await self.llm.extract_jobs(html, final_url, page=page_obj)
            
            logger.debug(f"Extracted {len(jobs_data)} jobs from {final_url}")
            return jobs_data
            
        except Exception as e:
            logger.warning(f"Error extracting jobs from {careers_url}: {e}")
            return []
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
