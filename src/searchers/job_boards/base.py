"""Base class for job board parsers."""

from abc import ABC, abstractmethod
from urllib.parse import urlparse, urljoin

from bs4 import BeautifulSoup


class BaseJobBoardParser(ABC):
    """Abstract base class for job board parsers."""

    platform_name: str = "base"

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






