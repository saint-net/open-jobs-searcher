"""Async HTTP client with retry, connection pooling, rate limiting, and domain availability checks."""

import logging
from typing import Optional, TYPE_CHECKING

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.browser import DomainUnreachableError

if TYPE_CHECKING:
    from src.searchers.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


# Connection pool limits for better performance
DEFAULT_POOL_LIMITS = httpx.Limits(
    max_keepalive_connections=20,  # Max persistent connections
    max_connections=100,  # Max total connections
    keepalive_expiry=30.0,  # Keep connections alive for 30s
)


class AsyncHttpClient:
    """Async HTTP client with retry logic, connection pooling, and domain availability checks."""

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
        pool_limits: Optional[httpx.Limits] = None,
        rate_limiter: Optional["RateLimiter"] = None,
    ):
        """
        Initialize HTTP client with connection pooling and rate limiting.
        
        Args:
            timeout: Request timeout in seconds
            headers: Custom HTTP headers
            pool_limits: Connection pool limits (uses defaults if not provided)
            rate_limiter: Optional rate limiter for per-domain throttling
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
        self._pool_limits = pool_limits or DEFAULT_POOL_LIMITS
        self._rate_limiter = rate_limiter
        
        # Main client with SSL verification and connection pooling
        self.client = httpx.AsyncClient(
            headers=default_headers,
            follow_redirects=True,
            timeout=timeout,
            limits=self._pool_limits,
        )
        
        # Client without SSL verification (for problematic certificates)
        self._insecure_client: Optional[httpx.AsyncClient] = None
    
    def _is_ssl_error(self, error: Exception) -> bool:
        """Check if error is SSL-related."""
        error_str = str(error).lower()
        return any(pattern in error_str for pattern in self.SSL_ERROR_PATTERNS)
    
    async def _get_insecure_client(self) -> httpx.AsyncClient:
        """Get or create client without SSL verification (shares pool limits)."""
        if self._insecure_client is None:
            self._insecure_client = httpx.AsyncClient(
                headers=self._headers,
                follow_redirects=True,
                timeout=self._timeout,
                verify=False,
                limits=self._pool_limits,
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
        Fetch HTML content from URL with rate limiting.
        
        Args:
            url: URL to fetch
            
        Returns:
            HTML content or None on error
            
        Raises:
            DomainUnreachableError: If domain cannot be reached
        """
        return await self._fetch_with_rate_limit(url)
    
    async def _fetch_with_rate_limit(self, url: str, use_insecure: bool = False) -> Optional[str]:
        """Internal fetch with rate limiting support."""
        try:
            # Apply rate limiting if configured
            if self._rate_limiter:
                async with await self._rate_limiter.acquire(url):
                    response = await self._do_fetch(url, use_insecure)
                    if response:
                        # Update rate limiter based on response
                        self._rate_limiter.on_response(
                            response.status_code, 
                            url, 
                            dict(response.headers)
                        )
                    return response.text if response else None
            else:
                response = await self._do_fetch(url, use_insecure)
                return response.text if response else None
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            logger.debug(f"HTTP error {status} for {url}")
            
            # Handle rate limiting
            if status in (429, 503) and self._rate_limiter:
                retry_after = self._rate_limiter.on_response(
                    status, url, dict(e.response.headers)
                )
                if retry_after:
                    logger.info(f"Rate limited, waiting {retry_after}s before retry")
            
            return None
        except httpx.ConnectError as e:
            error_str = str(e).lower()
            # Detect DNS resolution errors
            if any(err in error_str for err in self.CONNECTION_ERROR_PATTERNS):
                raise DomainUnreachableError(f"Домен недоступен: {url}") from e
            # Retry with disabled SSL verification for certificate errors
            if self._is_ssl_error(e) and not use_insecure:
                logger.debug(f"SSL error for {url}, retrying without verification")
                return await self._fetch_with_rate_limit(url, use_insecure=True)
            logger.warning(f"Connection error for {url}: {e}")
            return None
        except httpx.RequestError as e:
            # Check for SSL errors wrapped in RequestError
            if self._is_ssl_error(e) and not use_insecure:
                logger.debug(f"SSL error for {url}, retrying without verification")
                return await self._fetch_with_rate_limit(url, use_insecure=True)
            logger.warning(f"Request failed after retries for {url}: {e}")
            return None
    
    async def _do_fetch(self, url: str, use_insecure: bool = False) -> Optional[httpx.Response]:
        """Perform the actual HTTP fetch."""
        try:
            return await self._fetch_with_retry(url, use_insecure)
        except httpx.HTTPStatusError:
            raise  # Re-raise for handling in caller
        except httpx.RequestError:
            raise  # Re-raise for handling in caller

    async def fetch_response(self, url: str) -> Optional[httpx.Response]:
        """
        Fetch response object from URL with rate limiting.
        
        Args:
            url: URL to fetch
            
        Returns:
            Response object or None on error
        """
        return await self._fetch_response_with_rate_limit(url)
    
    async def _fetch_response_with_rate_limit(
        self, url: str, use_insecure: bool = False
    ) -> Optional[httpx.Response]:
        """Internal fetch_response with rate limiting support."""
        try:
            if self._rate_limiter:
                async with await self._rate_limiter.acquire(url):
                    response = await self._fetch_with_retry(url, use_insecure)
                    self._rate_limiter.on_response(
                        response.status_code, url, dict(response.headers)
                    )
                    return response
            else:
                return await self._fetch_with_retry(url, use_insecure)
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status in (429, 503) and self._rate_limiter:
                self._rate_limiter.on_response(status, url, dict(e.response.headers))
            return None
        except httpx.RequestError as e:
            if self._is_ssl_error(e) and not use_insecure:
                logger.debug(f"SSL error for {url}, retrying without verification")
                return await self._fetch_response_with_rate_limit(url, use_insecure=True)
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

