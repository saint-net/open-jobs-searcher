"""Async HTTP client with retry and domain availability checks."""

import logging
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.browser import DomainUnreachableError

logger = logging.getLogger(__name__)


class AsyncHttpClient:
    """Async HTTP client with retry logic and domain availability checks."""

    # Typical DNS/connection error patterns
    CONNECTION_ERROR_PATTERNS = [
        "name or service not known",
        "nodename nor servname provided",
        "getaddrinfo failed",
        "no address associated",
        "name resolution failed",
        "temporary failure in name resolution",
        "connection refused",
        "[errno 111]",  # Linux connection refused
        "[winerror 10061]",  # Windows connection refused
    ]

    def __init__(
        self,
        timeout: float = 30.0,
        headers: Optional[dict] = None,
    ):
        """
        Initialize HTTP client.
        
        Args:
            timeout: Request timeout in seconds
            headers: Custom HTTP headers
        """
        default_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        if headers:
            default_headers.update(headers)
            
        self.client = httpx.AsyncClient(
            headers=default_headers,
            follow_redirects=True,
            timeout=timeout,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.RequestError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _fetch_with_retry(self, url: str) -> httpx.Response:
        """Fetch with retry logic."""
        response = await self.client.get(url)
        response.raise_for_status()
        return response

    async def fetch(self, url: str) -> Optional[str]:
        """
        Fetch HTML content from URL.
        
        Args:
            url: URL to fetch
            
        Returns:
            HTML content or None on error
            
        Raises:
            DomainUnreachableError: If domain cannot be reached
        """
        try:
            response = await self._fetch_with_retry(url)
            return response.text
        except httpx.HTTPStatusError as e:
            logger.debug(f"HTTP error {e.response.status_code} for {url}")
            return None
        except httpx.ConnectError as e:
            error_str = str(e).lower()
            # Detect DNS resolution errors
            if any(err in error_str for err in self.CONNECTION_ERROR_PATTERNS):
                raise DomainUnreachableError(f"Домен недоступен: {url}") from e
            logger.warning(f"Connection error for {url}: {e}")
            return None
        except httpx.RequestError as e:
            logger.warning(f"Request failed after retries for {url}: {e}")
            return None

    async def fetch_response(self, url: str) -> Optional[httpx.Response]:
        """
        Fetch response object from URL (for accessing status, headers, etc.).
        
        Args:
            url: URL to fetch
            
        Returns:
            Response object or None on error
        """
        try:
            return await self._fetch_with_retry(url)
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            logger.debug(f"Fetch failed for {url}: {e}")
            return None

    async def check_domain_available(self, url: str) -> None:
        """
        Quick check if domain is reachable.
        
        Uses HEAD request with short timeout, falls back to GET if HEAD fails.
        Some servers don't support HEAD or disconnect on HEAD requests.
        
        Args:
            url: URL to check
            
        Raises:
            DomainUnreachableError: If domain is unreachable (DNS/network issues)
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Try HEAD first (faster)
                try:
                    response = await client.head(url, follow_redirects=True)
                    logger.debug(f"Domain check (HEAD): {url} -> {response.status_code}")
                    return
                except httpx.RequestError as head_error:
                    # HEAD failed, try GET as fallback (some servers don't support HEAD)
                    logger.debug(f"HEAD request failed for {url}, trying GET: {head_error}")
                    response = await client.get(url, follow_redirects=True)
                    logger.debug(f"Domain check (GET): {url} -> {response.status_code}")
        except httpx.ConnectError as e:
            error_str = str(e).lower()
            if any(err in error_str for err in self.CONNECTION_ERROR_PATTERNS):
                raise DomainUnreachableError(f"Домен недоступен: {url}") from e
            raise DomainUnreachableError(f"Не удалось подключиться к домену: {url}") from e
        except httpx.ConnectTimeout:
            raise DomainUnreachableError(f"Таймаут подключения к домену: {url}")

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

