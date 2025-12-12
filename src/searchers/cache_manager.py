"""Cache management for career URLs and jobs.

Handles SQLite-based caching of discovered career pages and job listings.
"""

import logging
from typing import Optional, Callable, Awaitable
from urllib.parse import urlparse, urlunparse

from src.models import Job
from src.database import JobRepository
from src.database.models import SyncResult
from src.searchers.job_boards import detect_job_board_platform
from src.searchers.job_filters import (
    normalize_title,
    normalize_location,
    filter_jobs_by_source_company,
)

logger = logging.getLogger(__name__)


def _clean_career_url(url: str) -> str:
    """Remove query params from career URL before caching.
    
    Query params like ?q=Center are filters that may return 0 jobs.
    We cache only the base URL to avoid stale filtered results.
    """
    parsed = urlparse(url)
    # Keep only scheme, netloc, path (remove query and fragment)
    return urlunparse(parsed._replace(query='', fragment=''))


class CacheManager:
    """Manages caching of career URLs and jobs in SQLite."""
    
    def __init__(
        self,
        repository: JobRepository,
        extract_jobs: Callable[[str, str], Awaitable[list[dict]]],
        convert_jobs: Callable[[list[dict], str, str], Awaitable[list[Job]]],
        fetch_html: Callable[[str], Awaitable[Optional[str]]],
        extract_company_info: Callable[[str, str], Awaitable[Optional[str]]],
        extract_company_name: Callable[[str], str],
        status_callback: Optional[Callable[[str], None]] = None,
    ):
        """
        Initialize cache manager.
        
        Args:
            repository: JobRepository for database operations
            extract_jobs: Async function to extract jobs from URL
            convert_jobs: Async function to convert job dicts to Job objects
            fetch_html: Async function to fetch HTML from URL
            extract_company_info: Async function to extract company info via LLM
            extract_company_name: Function to extract company name from URL
            status_callback: Optional callback for status updates
        """
        self._repository = repository
        self._extract_jobs = extract_jobs
        self._convert_jobs = convert_jobs
        self._fetch_html = fetch_html
        self._extract_company_info = extract_company_info
        self._extract_company_name = extract_company_name
        self._status_callback = status_callback
        
        # Last sync result (for reporting new/removed jobs)
        self.last_sync_result: Optional[SyncResult] = None
    
    def _update_status(self, message: str) -> None:
        """Update status if callback is set."""
        if self._status_callback:
            self._status_callback(message)
    
    async def search_with_cache(self, url: str, domain: str) -> Optional[list[Job]]:
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
                self._update_status("Загружаю страницу вакансий...")
                jobs_data = await self._extract_jobs(career_url.url, url)
                
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
        
        # Filter jobs by source company if using external career portal
        if working_url:
            career_domain = urlparse(working_url.url).netloc
            source_domain = urlparse(url).netloc.replace('www.', '')
            if career_domain != source_domain and career_domain != f"www.{source_domain}":
                # External career portal - filter by source company
                logger.debug(f"Filtering jobs from external portal {career_domain} for {source_domain}")
                all_jobs_data = filter_jobs_by_source_company(all_jobs_data, url)
        
        # Deduplicate jobs
        unique_jobs_data = self._deduplicate_jobs(
            all_jobs_data, 
            working_url.url if working_url else url
        )
        
        # Translate jobs and extract company info IN PARALLEL
        import asyncio
        
        self._update_status("Перевожу вакансии...")
        
        # Task 1: Translate and convert to Job objects
        convert_task = self._convert_jobs(
            unique_jobs_data, url, working_url.url if working_url else url
        )
        
        # Task 2: Extract company info if not yet available
        company_info_task = self._maybe_extract_company_info(site, domain)
        
        # Run in parallel
        jobs, _ = await asyncio.gather(convert_task, company_info_task)
        
        # Sync with database and track changes
        self._update_status("Синхронизирую с базой...")
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
    
    async def save_to_cache(
        self, 
        domain: str, 
        careers_url: str, 
        jobs: list[Job],
        skip_company_info: bool = False,
    ) -> None:
        """Save discovered career URL and jobs to cache.
        
        Сохраняет сайт и career URL даже если вакансий сейчас нет,
        чтобы отслеживать компанию при следующих сканированиях.
        
        Args:
            domain: Site domain
            careers_url: Discovered career page URL
            jobs: Found jobs (может быть пустым, если вакансий сейчас нет)
            skip_company_info: Skip company info extraction (already done in parallel)
        """
        try:
            # Get or create site
            company_name = self._extract_company_name(f"https://{domain}")
            site = await self._repository.get_or_create_site(domain, company_name)
            
            # Extract company info on first scan (when no description yet)
            if not skip_company_info:
                await self._maybe_extract_company_info(site, domain)
            
            # Clean URL (remove query params that may be filters)
            clean_url = _clean_career_url(careers_url)
            if clean_url != careers_url:
                logger.debug(f"Cleaned career URL: {careers_url} -> {clean_url}")
            
            # Detect platform from URL
            platform = detect_job_board_platform(clean_url)
            
            # Save career URL
            await self._repository.add_career_url(site.id, clean_url, platform)
            logger.debug(f"Cached career URL for {domain}: {clean_url}")
            
            # Sync jobs (this also handles new/removed tracking)
            sync_result = await self._repository.sync_jobs(site.id, jobs)
            self.last_sync_result = sync_result
            
            # Update site scan timestamp
            await self._repository.update_site_scanned(site.id)
            
            if jobs:
                logger.info(f"Cached {len(jobs)} jobs for {domain}")
            else:
                logger.info(f"Cached career URL for {domain} (no jobs currently)")
            
            if sync_result.has_changes:
                logger.info(
                    f"First scan for {domain}: "
                    f"+{len(sync_result.new_jobs)} jobs added"
                )
                
        except Exception as e:
            logger.warning(f"Failed to save to cache: {e}")
    
    async def _maybe_extract_company_info(self, site, domain: str) -> None:
        """Extract company info if not yet available.
        
        Uses simple HTTP fetch (not browser) since main page usually doesn't need JS.
        """
        if site.description:
            return
            
        try:
            import aiohttp
            main_page_url = f"https://{domain}"
            
            # Use simple HTTP fetch (faster than browser for main page)
            async with aiohttp.ClientSession() as session:
                async with session.get(main_page_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                    else:
                        html = None
            
            if html:
                description = await self._extract_company_info(html, main_page_url)
                if description:
                    await self._repository.update_site_description(site.id, description)
                    logger.info(f"Extracted company info for {domain}: {description[:50]}...")
        except Exception as e:
            logger.warning(f"Failed to extract company info for {domain}: {e}")
    
    def _deduplicate_jobs(self, jobs_data: list[dict], base_url: str) -> list[dict]:
        """Deduplicate jobs by URL or (title, location).
        
        Args:
            jobs_data: List of job dictionaries
            base_url: Base URL for detecting self-references
            
        Returns:
            List of unique jobs
        """
        seen = set()
        unique_jobs = []
        base_page = base_url.rstrip('/')
        
        for job_data in jobs_data:
            job_url = job_data.get("url", "")
            
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
            
            title_loc_key = (
                normalize_title(job_data.get("title", "")),
                normalize_location(job_data.get("location", ""))
            )
            
            # Use URL as key if available, otherwise title+location
            key = job_url if job_url else title_loc_key
            
            if key not in seen:
                seen.add(key)
                unique_jobs.append(job_data)
        
        return unique_jobs

