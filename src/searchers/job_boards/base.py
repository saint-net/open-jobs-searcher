"""Base class for job board parsers."""

import re
from abc import ABC, abstractmethod
from urllib.parse import urlparse, urljoin

from bs4 import BeautifulSoup


class BaseJobBoardParser(ABC):
    """Abstract base class for job board parsers."""

    platform_name: str = "base"
    
    # Patterns for non-job entries (open applications, etc.)
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

    @abstractmethod
    def parse(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """
        Parse jobs from job board HTML.

        Args:
            soup: BeautifulSoup object of the page
            base_url: Base URL for resolving relative links

        Returns:
            List of job dictionaries with keys: title, location, url, department
        """
        pass
    
    def parse_and_filter(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Parse jobs and filter out non-job entries."""
        jobs = self.parse(soup, base_url)
        return [job for job in jobs if not self._is_non_job_entry(job.get("title", ""))]
    
    def _is_non_job_entry(self, title: str) -> bool:
        """Check if title is a non-job entry (open application, etc.)."""
        if not title:
            return False
        title_lower = title.lower()
        for pattern in self.NON_JOB_PATTERNS:
            if re.search(pattern, title_lower, re.IGNORECASE):
                return True
        return False

    def _build_full_url(self, href: str, base_url: str) -> str:
        """Build full URL from href and base URL."""
        if not href:
            return base_url
        if href.startswith('http'):
            return href
        if href.startswith('/'):
            parsed = urlparse(base_url)
            return f"{parsed.scheme}://{parsed.netloc}{href}"
        return urljoin(base_url, href)
