"""Job converter - transforms raw job data to Job models."""

import asyncio
import logging
import re
from typing import Optional, Callable, Awaitable
from urllib.parse import urlparse

from src.models import Job
from src.llm.base import BaseLLMProvider

logger = logging.getLogger(__name__)


def extract_company_name(url: str) -> str:
    """Extract company name from URL.
    
    Args:
        url: Company URL
        
    Returns:
        Company name derived from domain
    """
    parsed = urlparse(url)
    domain = parsed.netloc
    
    # Remove www and common TLDs
    name = domain.replace('www.', '')
    name = re.sub(r'\.(com|ru|org|net|io|co|tech)$', '', name)
    
    return name.title()


class JobConverter:
    """Converts raw job dictionaries to Job model objects.
    
    Handles:
    - Translation of job titles to English
    - Extraction of company name from URL
    - Optional parallel company info extraction
    """
    
    def __init__(
        self,
        llm_provider: BaseLLMProvider,
        status_callback: Optional[Callable[[str], None]] = None,
    ):
        """
        Initialize job converter.
        
        Args:
            llm_provider: LLM provider for translations
            status_callback: Optional callback for status updates
        """
        self.llm = llm_provider
        self._status_callback = status_callback
    
    def set_status_callback(self, callback: Optional[Callable[[str], None]]) -> None:
        """Set callback for status updates."""
        self._status_callback = callback
    
    def _update_status(self, message: str) -> None:
        """Update status if callback is set."""
        if self._status_callback:
            self._status_callback(message)
    
    async def convert(
        self, 
        jobs_data: list[dict], 
        url: str, 
        careers_url: str
    ) -> list[Job]:
        """Convert raw job data to Job objects with translation.
        
        Args:
            jobs_data: Raw job dictionaries
            url: Original company URL
            careers_url: Career page URL (for fallback)
            
        Returns:
            List of Job objects
        """
        if not jobs_data:
            return []
        
        self._update_status("Перевожу вакансии...")
        
        # Translate job titles to English
        titles = [job_data.get("title", "Unknown Position") for job_data in jobs_data]
        titles_en = await self.llm.translate_job_titles(titles)
        
        return self._build_job_objects(jobs_data, titles_en, url, careers_url)
    
    async def convert_with_company_info(
        self, 
        jobs_data: list[dict], 
        url: str, 
        careers_url: str,
        domain: str,
        extract_and_save_company_info: Callable[[str, Optional[str]], Awaitable[None]],
        main_page_html: Optional[str] = None,
    ) -> list[Job]:
        """Convert raw job data to Job objects with translation + extract company info in parallel.
        
        Runs two LLM calls in parallel:
        1. Translate job titles to English
        2. Extract company info from main page (if not cached)
        
        Args:
            jobs_data: Raw job dictionaries
            url: Original URL
            careers_url: Career page URL (for fallback)
            domain: Domain for company info extraction
            extract_and_save_company_info: Async function to extract and save company info
            main_page_html: Pre-fetched HTML of main page (avoids re-fetch)
            
        Returns:
            List of Job objects
        """
        if not jobs_data:
            # Still extract company info even if no jobs
            await extract_and_save_company_info(domain, main_page_html)
            return []
        
        self._update_status("Перевожу вакансии...")
        
        # Prepare parallel tasks
        titles = [job_data.get("title", "Unknown Position") for job_data in jobs_data]
        
        # Task 1: Translate job titles
        translate_task = self.llm.translate_job_titles(titles)
        
        # Task 2: Extract company info
        company_info_task = extract_and_save_company_info(domain, main_page_html)
        
        # Run in parallel
        titles_en, _ = await asyncio.gather(translate_task, company_info_task)
        
        return self._build_job_objects(jobs_data, titles_en, url, careers_url)
    
    def _build_job_objects(
        self,
        jobs_data: list[dict],
        titles_en: list[str],
        url: str,
        careers_url: str,
    ) -> list[Job]:
        """Build Job objects from raw data.
        
        Args:
            jobs_data: Raw job dictionaries
            titles_en: English translations of titles
            url: Original company URL
            careers_url: Career page URL (fallback for job URLs)
            
        Returns:
            List of Job objects
        """
        jobs = []
        company_name = extract_company_name(url)
        
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
                extraction_method=job_data.get("extraction_method"),
                extraction_details=job_data.get("extraction_details"),
            )
            jobs.append(job)
        
        return jobs
