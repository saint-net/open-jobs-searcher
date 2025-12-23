"""Rate limiting for HTTP requests to prevent bans during mass scanning.

Implements:
- Fixed delay between requests to the same domain
- Domain-based semaphore to limit concurrent requests
- Adaptive backoff on 429/503 responses
- Retry-After header support
"""

import asyncio
import logging
import time
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class RateLimiter:
    """Rate limiter with per-domain tracking and adaptive backoff.
    
    Features:
    - Fixed minimum delay between requests to the same domain
    - Semaphore to limit concurrent requests per domain
    - Adaptive delay increase on rate limit responses (429/503)
    - Retry-After header support
    
    Usage:
        limiter = RateLimiter(base_delay=0.5, max_concurrent=2)
        
        async with limiter.acquire("example.com"):
            response = await client.get(url)
            limiter.on_response(response, "example.com")
    """
    
    def __init__(
        self,
        base_delay: float = 0.5,
        max_concurrent: int = 2,
        max_delay: float = 30.0,
        backoff_multiplier: float = 2.0,
        recovery_factor: float = 0.9,
    ):
        """
        Initialize rate limiter.
        
        Args:
            base_delay: Minimum seconds between requests to same domain
            max_concurrent: Max parallel requests to same domain
            max_delay: Maximum delay after repeated rate limits
            backoff_multiplier: Multiply delay by this on rate limit
            recovery_factor: Multiply delay by this on success (< 1 to recover)
        """
        self.base_delay = base_delay
        self.max_concurrent = max_concurrent
        self.max_delay = max_delay
        self.backoff_multiplier = backoff_multiplier
        self.recovery_factor = recovery_factor
        
        # Per-domain state
        self._last_request: dict[str, float] = {}  # domain -> timestamp
        self._domain_delays: dict[str, float] = {}  # domain -> current delay
        self._semaphores: dict[str, asyncio.Semaphore] = {}  # domain -> semaphore
        self._locks: dict[str, asyncio.Lock] = {}  # domain -> lock for delay
        
        # Global lock for creating per-domain resources
        self._global_lock = asyncio.Lock()
    
    def _get_domain(self, url_or_domain: str) -> str:
        """Extract domain from URL or return as-is if already a domain."""
        if url_or_domain.startswith(('http://', 'https://')):
            return urlparse(url_or_domain).netloc.lower()
        return url_or_domain.lower()
    
    async def _get_semaphore(self, domain: str) -> asyncio.Semaphore:
        """Get or create semaphore for domain."""
        if domain not in self._semaphores:
            async with self._global_lock:
                if domain not in self._semaphores:
                    self._semaphores[domain] = asyncio.Semaphore(self.max_concurrent)
        return self._semaphores[domain]
    
    async def _get_lock(self, domain: str) -> asyncio.Lock:
        """Get or create lock for domain delay enforcement."""
        if domain not in self._locks:
            async with self._global_lock:
                if domain not in self._locks:
                    self._locks[domain] = asyncio.Lock()
        return self._locks[domain]
    
    def _get_delay(self, domain: str) -> float:
        """Get current delay for domain (base or increased after rate limit)."""
        return self._domain_delays.get(domain, self.base_delay)
    
    async def wait(self, url_or_domain: str) -> None:
        """
        Wait for rate limit before making request.
        
        Args:
            url_or_domain: URL or domain to rate limit
        """
        domain = self._get_domain(url_or_domain)
        lock = await self._get_lock(domain)
        
        async with lock:
            now = time.time()
            last = self._last_request.get(domain, 0)
            delay = self._get_delay(domain)
            
            wait_time = delay - (now - last)
            if wait_time > 0:
                logger.debug(f"Rate limit: waiting {wait_time:.2f}s for {domain}")
                await asyncio.sleep(wait_time)
            
            self._last_request[domain] = time.time()
    
    async def acquire(self, url_or_domain: str):
        """
        Context manager that combines semaphore and delay.
        
        Usage:
            async with limiter.acquire("https://example.com"):
                response = await fetch(url)
        """
        domain = self._get_domain(url_or_domain)
        semaphore = await self._get_semaphore(domain)
        
        return _RateLimitContext(self, domain, semaphore)
    
    def on_rate_limited(self, url_or_domain: str, retry_after: Optional[int] = None) -> None:
        """
        Called when request got rate limited (429/503).
        
        Increases delay for the domain using exponential backoff.
        
        Args:
            url_or_domain: URL or domain that was rate limited
            retry_after: Seconds from Retry-After header (if provided)
        """
        domain = self._get_domain(url_or_domain)
        current = self._domain_delays.get(domain, self.base_delay)
        
        if retry_after:
            # Use server-specified delay
            new_delay = min(float(retry_after), self.max_delay)
            logger.info(f"Rate limited on {domain}, server says wait {retry_after}s")
        else:
            # Exponential backoff
            new_delay = min(current * self.backoff_multiplier, self.max_delay)
            logger.info(f"Rate limited on {domain}, increasing delay to {new_delay:.1f}s")
        
        self._domain_delays[domain] = new_delay
    
    def on_success(self, url_or_domain: str) -> None:
        """
        Called on successful request.
        
        Gradually reduces delay back to base.
        
        Args:
            url_or_domain: URL or domain of successful request
        """
        domain = self._get_domain(url_or_domain)
        
        if domain in self._domain_delays:
            current = self._domain_delays[domain]
            new_delay = current * self.recovery_factor
            
            if new_delay <= self.base_delay * 1.1:
                # Close enough to base, remove override
                del self._domain_delays[domain]
                logger.debug(f"Delay for {domain} recovered to base")
            else:
                self._domain_delays[domain] = new_delay
    
    def on_response(self, status_code: int, url_or_domain: str, headers: dict = None) -> Optional[int]:
        """
        Process response and update rate limit state.
        
        Args:
            status_code: HTTP status code
            url_or_domain: URL or domain
            headers: Response headers (to check Retry-After)
            
        Returns:
            Retry-After value in seconds if rate limited, None otherwise
        """
        headers = headers or {}
        
        if status_code in (429, 503):
            retry_after = self._parse_retry_after(headers.get("Retry-After"))
            self.on_rate_limited(url_or_domain, retry_after)
            return retry_after
        elif 200 <= status_code < 400:
            self.on_success(url_or_domain)
        
        return None
    
    def _parse_retry_after(self, value: Optional[str]) -> Optional[int]:
        """
        Parse Retry-After header value.
        
        Can be either seconds (integer) or HTTP date.
        
        Args:
            value: Retry-After header value
            
        Returns:
            Seconds to wait, or None if not parseable
        """
        if not value:
            return None
        
        # Try as integer seconds
        try:
            return int(value)
        except ValueError:
            pass
        
        # Try as HTTP date
        try:
            retry_date = parsedate_to_datetime(value)
            now = time.time()
            wait_seconds = int(retry_date.timestamp() - now)
            return max(0, wait_seconds)
        except (ValueError, TypeError):
            pass
        
        return None
    
    def get_stats(self) -> dict:
        """Get current rate limiter statistics."""
        return {
            "domains_tracked": len(self._last_request),
            "domains_with_elevated_delay": len(self._domain_delays),
            "elevated_delays": dict(self._domain_delays),
        }


class _RateLimitContext:
    """Context manager for rate-limited request."""
    
    def __init__(self, limiter: RateLimiter, domain: str, semaphore: asyncio.Semaphore):
        self.limiter = limiter
        self.domain = domain
        self.semaphore = semaphore
    
    async def __aenter__(self):
        # First acquire semaphore (limit concurrency)
        await self.semaphore.acquire()
        # Then wait for rate limit delay
        await self.limiter.wait(self.domain)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.semaphore.release()
        return False
