"""Async HTTP client with retry and domain availability checks."""

import logging
import ssl
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
    
    # SSL/TLS error patterns (retry without verification)
    SSL_ERROR_PATTERNS = [
        "certificate verify failed",
        "ssl: certificate_verify_failed",
        "certificate_verify_failed",
        "unable to get local issuer certificate",
        "self signed certificate",
        "ssl handshake",
        "[ssl:",
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
        
        self._headers = default_headers
        self._timeout = timeout
        
        # Main client with SSL verification
        self.client = httpx.AsyncClient(
            headers=default_headers,
            follow_redirects=True,
            timeout=timeout,
        )
        
        # Client without SSL verification (for problematic certificates)
        self._insecure_client: Optional[httpx.AsyncClient] = None
    
    def _is_ssl_error(self, error: Exception) -> bool:
        """Check if error is SSL-related."""
        error_str = str(error).lower()
        return any(pattern in error_str for pattern in self.SSL_ERROR_PATTERNS)
    
    async def _get_insecure_client(self) -> httpx.AsyncClient:
        """Get or create client without SSL verification."""
        if self._insecure_client is None:
            self._insecure_client = httpx.AsyncClient(
                headers=self._headers,
                follow_redirects=True,
                timeout=self._timeout,
                verify=False,
            )
        return self._insecure_client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.RequestError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _fetch_with_retry(self, url: str, use_insecure: bool = False) -> httpx.Response:
        """Fetch with retry logic."""
        client = await self._get_insecure_client() if use_insecure else self.client
        response = await client.get(url)
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
            # Retry with disabled SSL verification for certificate errors
            if self._is_ssl_error(e):
                logger.debug(f"SSL error for {url}, retrying without verification")
                try:
                    response = await self._fetch_with_retry(url, use_insecure=True)
                    return response.text
                except Exception as retry_error:
                    logger.warning(f"SSL retry also failed for {url}: {retry_error}")
                    return None
            logger.warning(f"Connection error for {url}: {e}")
            return None
        except httpx.RequestError as e:
            # Check for SSL errors wrapped in RequestError
            if self._is_ssl_error(e):
                logger.debug(f"SSL error for {url}, retrying without verification")
                try:
                    response = await self._fetch_with_retry(url, use_insecure=True)
                    return response.text
                except Exception as retry_error:
                    logger.warning(f"SSL retry also failed for {url}: {retry_error}")
                    return None
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
            # Retry with disabled SSL verification for certificate errors
            if self._is_ssl_error(e):
                logger.debug(f"SSL error for {url}, retrying without verification")
                try:
                    return await self._fetch_with_retry(url, use_insecure=True)
                except Exception as retry_error:
                    logger.debug(f"SSL retry also failed for {url}: {retry_error}")
                    return None
            logger.debug(f"Fetch failed for {url}: {e}")
            return None

    async def check_domain_available(self, url: str) -> None:
        """
        Quick check if domain is reachable.
        
        Uses HEAD request with short timeout, falls back to GET if HEAD fails.
        Some servers don't support HEAD or disconnect on HEAD requests.
        Automatically retries without SSL verification if certificate issues occur.
        
        Args:
            url: URL to check
            
        Raises:
            DomainUnreachableError: If domain is unreachable (DNS/network issues)
        """
        async def _try_check(verify: bool = True) -> bool:
            """Try domain check with specified SSL verification setting."""
            try:
                async with httpx.AsyncClient(timeout=10.0, verify=verify) as client:
                    # Try HEAD first (faster)
                    try:
                        response = await client.head(url, follow_redirects=True)
                        logger.debug(f"Domain check (HEAD, verify={verify}): {url} -> {response.status_code}")
                        return True
                    except httpx.RequestError as head_error:
                        # Check for SSL errors on HEAD
                        if self._is_ssl_error(head_error) and verify:
                            raise  # Will be caught and retried without verification
                        # HEAD failed, try GET as fallback (some servers don't support HEAD)
                        logger.debug(f"HEAD request failed for {url}, trying GET: {head_error}")
                        response = await client.get(url, follow_redirects=True)
                        logger.debug(f"Domain check (GET, verify={verify}): {url} -> {response.status_code}")
                        return True
            except httpx.ConnectError as e:
                error_str = str(e).lower()
                if any(err in error_str for err in self.CONNECTION_ERROR_PATTERNS):
                    raise DomainUnreachableError(f"Домен недоступен: {url}") from e
                # Check for SSL error - will be retried
                if self._is_ssl_error(e) and verify:
                    raise
                raise DomainUnreachableError(f"Не удалось подключиться к домену: {url}") from e
            except httpx.ConnectTimeout:
                raise DomainUnreachableError(f"Таймаут подключения к домену: {url}")
            except httpx.RequestError as e:
                # Check for SSL error - will be retried
                if self._is_ssl_error(e) and verify:
                    raise
                raise DomainUnreachableError(f"Ошибка запроса к домену: {url}") from e
        
        try:
            # First try with SSL verification
            await _try_check(verify=True)
        except (httpx.ConnectError, httpx.RequestError) as e:
            # If SSL error, retry without verification
            if self._is_ssl_error(e):
                logger.debug(f"SSL error checking {url}, retrying without verification")
                await _try_check(verify=False)
            else:
                raise

    async def close(self):
        """Close the HTTP clients."""
        await self.client.aclose()
        if self._insecure_client is not None:
            await self._insecure_client.aclose()

    async def check_redirect(self, url: str) -> tuple[str, bool]:
        """
        Check if URL redirects to a different domain.
        
        Args:
            url: URL to check
            
        Returns:
            Tuple (final_url, is_different_domain)
        """
        from urllib.parse import urlparse
        
        original_domain = urlparse(url).netloc.replace('www.', '').lower()
        
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                response = await client.head(url)
                final_url = str(response.url)
                final_domain = urlparse(final_url).netloc.replace('www.', '').lower()
                
                is_different = original_domain != final_domain
                
                if is_different:
                    logger.info(f"Domain redirect detected: {url} -> {final_url}")
                
                return final_url, is_different
        except Exception as e:
            logger.debug(f"Redirect check failed for {url}: {e}")
            return url, False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

