"""Page fetcher - unified HTTP and browser fetching."""

import logging
from typing import Optional, Tuple

from src.browser import (
    BrowserLoader,
    DomainUnreachableError,
    PlaywrightBrowsersNotInstalledError,
)
from src.searchers.http_client import AsyncHttpClient

logger = logging.getLogger(__name__)


class PageFetcher:
    """Unified page fetcher with HTTP and browser support.
    
    Wraps AsyncHttpClient and BrowserLoader into a single interface.
    Handles lazy browser initialization and proper cleanup.
    """
    
    def __init__(
        self,
        http_client: AsyncHttpClient,
        headless: bool = True,
        use_browser: bool = True,
    ):
        """
        Initialize page fetcher.
        
        Args:
            http_client: HTTP client for simple requests
            headless: Run browser without GUI
            use_browser: Use browser for page loading (vs HTTP only)
        """
        self.http_client = http_client
        self.headless = headless
        self.use_browser = use_browser
        self._browser_loader: Optional[BrowserLoader] = None
    
    async def _get_browser_loader(self) -> BrowserLoader:
        """Get or create BrowserLoader (lazy initialization)."""
        if self._browser_loader is None:
            self._browser_loader = BrowserLoader(headless=self.headless)
            await self._browser_loader.start()
        return self._browser_loader
    
    async def fetch(self, url: str) -> Optional[str]:
        """Fetch HTML content from URL.
        
        Uses browser if configured, falls back to HTTP.
        
        Args:
            url: URL to fetch
            
        Returns:
            HTML content or None on error
        """
        if self.use_browser:
            html, _ = await self.fetch_with_browser(url)
            return html
        return await self.http_client.fetch(url)
    
    async def fetch_with_browser(
        self, url: str, navigate_to_jobs: bool = False
    ) -> Tuple[Optional[str], Optional[str]]:
        """Fetch HTML via Playwright browser.
        
        Args:
            url: Page URL
            navigate_to_jobs: Try to navigate to jobs page (for SPA)
            
        Returns:
            Tuple (HTML, final_url) - final_url may differ if navigation occurred
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
    
    async def fetch_with_page_object(
        self, url: str, navigate_to_jobs: bool = False
    ) -> Tuple[Optional[str], Optional[str], Optional[object], Optional[object]]:
        """Fetch HTML and return page object for accessibility tree extraction.
        
        IMPORTANT: Caller must close page and context after use!
        
        Args:
            url: Page URL
            navigate_to_jobs: Try to navigate to jobs page (for SPA)
            
        Returns:
            Tuple (HTML, final_url, page, context) - caller must close page/context!
        """
        try:
            loader = await self._get_browser_loader()
            return await loader.fetch_with_page(url, navigate_to_jobs=navigate_to_jobs)
        except (DomainUnreachableError, PlaywrightBrowsersNotInstalledError):
            raise
        except Exception as e:
            logger.warning(f"Browser fetch error for {url}: {e}")
            return None, None, None, None
    
    async def close(self):
        """Close browser if open."""
        if self._browser_loader:
            await self._browser_loader.stop()
            self._browser_loader = None
