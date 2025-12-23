"""Universal job searcher for company websites."""

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional, Any
from urllib.parse import urlparse

from src.models import Job
from src.searchers.base import BaseSearcher
from src.searchers.http_client import AsyncHttpClient
from src.searchers.rate_limiter import RateLimiter
from src.searchers.page_fetcher import PageFetcher
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
from src.searchers.job_converter import JobConverter, extract_company_name
from src.searchers.company_info import CompanyInfoExtractor
from src.searchers.cache_manager import CacheManager
from src.llm.base import BaseLLMProvider
from src.llm.cache import LLMCache
from src.browser import DomainUnreachableError
from src.database import JobRepository
from src.database.models import SyncResult

logger = logging.getLogger(__name__)


@dataclass
class PageContext:
    """Result of page fetch with platform detection."""
    html: str
    final_url: str
    platform: Optional[str]
    is_external_redirect: bool
    page: Any = None  # Playwright Page
    context: Any = None  # Playwright Context


class WebsiteSearcher(BaseSearcher):
    """Universal job searcher using LLM for analysis."""

    name = "website"

    def __init__(
        self,
        llm_provider: BaseLLMProvider,
        use_browser: bool = True,
        headless: bool = True,
        use_cache: bool = True,
    ):
        """
        Initialize searcher.

        Args:
            llm_provider: LLM provider for page analysis
            use_browser: Use Playwright for loading pages
            headless: Run browser without GUI
            use_cache: Use SQLite cache for career URLs and job tracking
        """
        self.llm = llm_provider
        self.use_browser = True  # Always use browser for accessibility tree
        self.headless = headless
        self.use_cache = use_cache

        # Last sync result (for reporting new/removed jobs)
        self.last_sync_result: Optional[SyncResult] = None

        # Status callback for progress updates
        self._status_callback = None

        # Initialize rate limiter from config
        from src.config import settings
        self.rate_limiter = None
        if settings.rate_limit_enabled:
            self.rate_limiter = RateLimiter(
                base_delay=settings.rate_limit_delay,
                max_concurrent=settings.rate_limit_max_concurrent,
            )
            logger.debug(
                f"Rate limiting enabled: {settings.rate_limit_delay}s delay, "
                f"{settings.rate_limit_max_concurrent} concurrent per domain"
            )

        # Initialize components
        self.http_client = AsyncHttpClient(rate_limiter=self.rate_limiter)
        self.page_fetcher = PageFetcher(
            http_client=self.http_client,
            headless=headless,
            use_browser=self.use_browser,
        )
        self.url_discovery = CareerUrlDiscovery(self.http_client)
        self.job_board_parsers = JobBoardParserRegistry()
        self.job_converter = JobConverter(llm_provider)

        # Database repository for caching
        self._repository = JobRepository() if use_cache else None

        # Company info extractor (depends on repository)
        self._company_info_extractor = CompanyInfoExtractor(
            repository=self._repository,
            extract_company_info=self.llm.extract_company_info,
            fetch_html=self.page_fetcher.fetch,
        ) if self._repository else None

        # Lazy-initialized components
        self._job_extractor = None
        self._cache_manager = None
        self._llm_cache = None

        # Set up LLM cache if caching is enabled
        if use_cache and self._repository:
            self._llm_cache = LLMCache(self._repository)
            self.llm.set_cache(self._llm_cache)

    def _get_job_extractor(self) -> JobExtractor:
        """Get or create JobExtractor."""
        if self._job_extractor is None:
            self._job_extractor = JobExtractor(
                llm_provider=self.llm,
                job_board_parsers=self.job_board_parsers,
                fetch_with_page=self.page_fetcher.fetch_with_page_object,
                fetch_jobs_from_api=self._fetch_jobs_from_api,
            )
        return self._job_extractor

    def _get_cache_manager(self) -> CacheManager:
        """Get or create CacheManager."""
        if self._cache_manager is None:
            self._cache_manager = CacheManager(
                repository=self._repository,
                extract_jobs=self._get_job_extractor().extract_jobs,
                convert_jobs=self.job_converter.convert,
                fetch_html=self.page_fetcher.fetch,
                extract_company_info=self.llm.extract_company_info,
                extract_company_name=extract_company_name,
                status_callback=self._status_callback,
            )
        return self._cache_manager

    def set_status_callback(self, callback) -> None:
        """Set callback for status updates."""
        self._status_callback = callback
        self.job_converter.set_status_callback(callback)

    def _update_status(self, message: str) -> None:
        """Update status if callback is set."""
        if self._status_callback:
            self._status_callback(message)

    async def search(
        self,
        keywords: str,
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
        url = keywords

        # Normalize URL
        if not url.startswith(('http://', 'https://')):
            url = f'https://{url}'

        # Reset last sync result
        self.last_sync_result = None

        # Extract domain for caching
        domain = urlparse(url).netloc.replace('www.', '')

        try:
            # Quick domain availability check
            await self.http_client.check_domain_available(url)

            # Check for domain redirect
            final_url, redirected = await self.http_client.check_redirect(url)
            if redirected:
                original_domain = urlparse(url).netloc.replace('www.', '')
                new_domain = urlparse(final_url).netloc.replace('www.', '')
                logger.warning(
                    f"Domain {original_domain} redirects to {new_domain}. "
                    f"Searching on {new_domain} instead."
                )
                url = f"https://{new_domain}"
                domain = new_domain

            # Try cached career URLs first
            if self.use_cache and self._repository:
                self._update_status("Проверяю кэш URL...")
                cache_mgr = self._get_cache_manager()
                jobs = await cache_mgr.search_with_cache(url, domain)
                if jobs is not None:
                    self.last_sync_result = cache_mgr.last_sync_result
                    return jobs

            # Full discovery
            return await self._search_full_discovery(url, domain)

        except DomainUnreachableError as e:
            logger.error(f"Domain unreachable: {url} - {e}")
            return []

    async def _search_full_discovery(self, url: str, domain: str) -> list[Job]:
        """Full career page discovery using LLM."""
        careers_url = None

        try:
            # 1. Load main page and sitemap URLs
            self._update_status("Загружаю главную страницу...")
            html = await self.page_fetcher.fetch(url)
            sitemap_urls = await self.url_discovery.fetch_all_sitemap_urls(url)

            # 2. LLM finds careers URL
            if not html:
                logger.warning(f"Could not load page: {url}")
                return []

            self._update_status("Ищу страницу вакансий (LLM)...")
            careers_url = await self.llm.find_careers_url(html, url, sitemap_urls)

            if not careers_url or careers_url == "NOT_FOUND":
                logger.warning(f"LLM could not find careers URL on {url}")
                return []

            logger.info(f"LLM found careers page: {careers_url}")

            # 3. Check for job board redirect on careers page
            if not detect_job_board_platform(careers_url):
                careers_html = await self.page_fetcher.fetch(careers_url)
                if careers_html:
                    job_board_url = await self.llm.find_job_board_url(careers_html, careers_url)
                    if job_board_url:
                        logger.info(f"LLM found job board: {job_board_url}")
                        careers_url = job_board_url

            # 4. Extract jobs from careers page
            jobs_data, final_url = await self._extract_jobs_from_careers(careers_url, url)

            if final_url:
                careers_url = final_url

            # 5. Convert to Job models with translation + company info (parallel)
            jobs = await self._convert_with_company_info(jobs_data, url, careers_url, domain, html)

            # 6. Save to cache
            if self.use_cache and self._repository and careers_url:
                cache_mgr = self._get_cache_manager()
                await cache_mgr.save_to_cache(domain, careers_url, jobs, skip_company_info=True)
                self.last_sync_result = cache_mgr.last_sync_result

            return jobs

        except DomainUnreachableError as e:
            logger.error(f"Domain unreachable: {url} - {e}")
            return []

    async def _extract_jobs_from_careers(
        self, careers_url: str, original_url: str
    ) -> tuple[list[dict], Optional[str]]:
        """Extract jobs from careers page with URL variants."""
        for variant_url in self.url_discovery.generate_url_variants(careers_url):
            jobs_data, final_url = await self._try_extract_from_url(variant_url, original_url)
            if jobs_data:
                return jobs_data, final_url
        return [], None

    async def _try_extract_from_url(
        self, variant_url: str, original_url: str
    ) -> tuple[list[dict], Optional[str]]:
        """Try to extract jobs from a single URL variant."""
        self._update_status("Загружаю страницу вакансий...")

        async with self._fetch_page_with_context(variant_url) as ctx:
            if not ctx.html:
                return [], None

            # Handle external job board if detected
            ctx = await self._handle_external_job_board(ctx, variant_url)
            if not ctx.html:
                return [], None

            # Extract jobs
            jobs_data = await self._extract_jobs_from_context(ctx, original_url)

            # Filter if redirected to external domain
            if ctx.is_external_redirect and jobs_data:
                jobs_data = filter_jobs_by_search_query(jobs_data, ctx.final_url)
                jobs_data = filter_jobs_by_source_company(jobs_data, original_url)

            if jobs_data:
                logger.debug(f"Found {len(jobs_data)} jobs at {ctx.final_url}")
                return jobs_data, ctx.final_url

            return [], None

    @asynccontextmanager
    async def _fetch_page_with_context(self, url: str):
        """Fetch page and yield PageContext, cleaning up resources on exit."""
        already_on_job_board = detect_job_board_platform(url) is not None
        page_obj = None
        context_obj = None

        try:
            html, final_url, page_obj, context_obj = await self.page_fetcher.fetch_with_page_object(
                url, navigate_to_jobs=not already_on_job_board
            )
            final_url = final_url or url

            # Ignore chrome-error:// URLs
            if final_url.startswith("chrome-error://"):
                final_url = url

            # Check for external redirect
            final_domain = urlparse(final_url).netloc.replace('www.', '')
            url_domain = urlparse(url).netloc.replace('www.', '')
            is_external = final_domain != url_domain

            # Detect platform
            platform = detect_job_board_platform(final_url, html) if html else None

            yield PageContext(
                html=html or "",
                final_url=final_url if (platform or is_external) else url,
                platform=platform,
                is_external_redirect=is_external,
                page=page_obj,
                context=context_obj,
            )
        finally:
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

    async def _handle_external_job_board(
        self, ctx: PageContext, original_url: str
    ) -> PageContext:
        """Check for and load external job board if found."""
        if ctx.platform:
            return ctx  # Already on a known platform

        external_board_url = find_external_job_board(ctx.html)
        if not external_board_url:
            return ctx

        logger.info(f"Found external job board: {external_board_url}")
        platform = detect_job_board_platform(external_board_url)

        # Close current page and load external
        if ctx.page:
            try:
                await ctx.page.close()
            except Exception:
                pass
        if ctx.context:
            try:
                await ctx.context.close()
            except Exception:
                pass

        html, _, page_obj, context_obj = await self.page_fetcher.fetch_with_page_object(
            external_board_url
        )

        return PageContext(
            html=html or "",
            final_url=external_board_url,
            platform=platform,
            is_external_redirect=True,
            page=page_obj,
            context=context_obj,
        )

    async def _extract_jobs_from_context(
        self, ctx: PageContext, original_url: str
    ) -> list[dict]:
        """Extract jobs from PageContext using parser or LLM."""
        jobs_data = []

        # Try job board parser first
        if ctx.platform:
            if self.job_board_parsers.is_api_based(ctx.platform):
                jobs_data = await self._fetch_jobs_from_api(ctx.final_url, ctx.platform)
            else:
                jobs_data = self.job_board_parsers.parse(ctx.html, ctx.final_url, ctx.platform)

        # Fallback to LLM extraction
        if not jobs_data:
            self._update_status("Извлекаю вакансии (LLM)...")
            # Close page before LLM pagination (releases browser resources)
            if ctx.page:
                try:
                    await ctx.page.close()
                except Exception:
                    pass
            if ctx.context:
                try:
                    await ctx.context.close()
                except Exception:
                    pass

            jobs_data = await self._get_job_extractor().extract_jobs(ctx.final_url, original_url)

        return jobs_data

    async def _convert_with_company_info(
        self,
        jobs_data: list[dict],
        url: str,
        careers_url: str,
        domain: str,
        main_page_html: Optional[str] = None,
    ) -> list[Job]:
        """Convert jobs and extract company info in parallel."""
        if self.use_cache and self._company_info_extractor:
            return await self.job_converter.convert_with_company_info(
                jobs_data=jobs_data,
                url=url,
                careers_url=careers_url,
                domain=domain,
                extract_and_save_company_info=self._company_info_extractor.extract_and_save,
                main_page_html=main_page_html,
            )
        return await self.job_converter.convert(jobs_data, url, careers_url)

    async def _fetch_jobs_from_api(self, base_url: str, platform: str) -> list[dict]:
        """Fetch jobs from API for platforms that require it."""
        api_url = self.job_board_parsers.get_api_url(base_url, platform)
        if not api_url:
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

    async def get_job_details(self, job_id: str) -> Optional[Job]:
        """Get job details (not implemented for website)."""
        return None

    async def close(self):
        """Close all resources."""
        await self.http_client.close()
        await self.page_fetcher.close()
        await self.llm.close()
        if self._repository:
            await self._repository.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
