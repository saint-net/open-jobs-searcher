"""Tests for rate limiter.

Run after changes to: src/searchers/rate_limiter.py, src/searchers/http_client.py
"""

import asyncio
import time

import pytest

from src.searchers.rate_limiter import RateLimiter


class TestRateLimiterBasics:
    """Test basic rate limiter functionality."""
    
    def test_creates_with_defaults(self):
        """Should create rate limiter with default settings."""
        limiter = RateLimiter()
        
        assert limiter.base_delay == 0.5
        assert limiter.max_concurrent == 2
        assert limiter.max_delay == 30.0
    
    def test_creates_with_custom_settings(self):
        """Should accept custom settings."""
        limiter = RateLimiter(
            base_delay=1.0,
            max_concurrent=5,
            max_delay=60.0,
        )
        
        assert limiter.base_delay == 1.0
        assert limiter.max_concurrent == 5
        assert limiter.max_delay == 60.0
    
    def test_get_domain_from_url(self):
        """Should extract domain from URL."""
        limiter = RateLimiter()
        
        assert limiter._get_domain("https://example.com/path") == "example.com"
        assert limiter._get_domain("http://sub.example.com:8080/path") == "sub.example.com:8080"
        assert limiter._get_domain("example.com") == "example.com"


class TestRateLimiterDelay:
    """Test rate limiting delay functionality."""
    
    @pytest.mark.asyncio
    async def test_wait_enforces_delay(self):
        """Should enforce minimum delay between requests."""
        limiter = RateLimiter(base_delay=0.1)
        
        start = time.time()
        await limiter.wait("example.com")
        await limiter.wait("example.com")
        elapsed = time.time() - start
        
        # Second wait should have waited ~0.1s
        assert elapsed >= 0.09  # Allow small tolerance
    
    @pytest.mark.asyncio
    async def test_different_domains_no_delay(self):
        """Should not delay between different domains."""
        limiter = RateLimiter(base_delay=0.5)
        
        start = time.time()
        await limiter.wait("example1.com")
        await limiter.wait("example2.com")
        elapsed = time.time() - start
        
        # No delay between different domains
        assert elapsed < 0.1
    
    @pytest.mark.asyncio
    async def test_delay_increases_on_rate_limit(self):
        """Should increase delay after rate limit response."""
        limiter = RateLimiter(base_delay=0.1, backoff_multiplier=2.0)
        
        # Simulate rate limit
        limiter.on_rate_limited("example.com")
        
        # Delay should have doubled
        assert limiter._get_delay("example.com") == 0.2
        
        # Another rate limit
        limiter.on_rate_limited("example.com")
        assert limiter._get_delay("example.com") == 0.4
    
    @pytest.mark.asyncio
    async def test_delay_capped_at_max(self):
        """Should cap delay at max_delay."""
        limiter = RateLimiter(base_delay=1.0, max_delay=5.0, backoff_multiplier=10.0)
        
        # Simulate multiple rate limits
        for _ in range(5):
            limiter.on_rate_limited("example.com")
        
        # Should be capped at 5.0
        assert limiter._get_delay("example.com") == 5.0
    
    @pytest.mark.asyncio
    async def test_delay_recovers_on_success(self):
        """Should gradually reduce delay after successful requests."""
        limiter = RateLimiter(base_delay=0.1, recovery_factor=0.5)
        
        # Set elevated delay
        limiter._domain_delays["example.com"] = 1.0
        
        # Simulate successful requests
        limiter.on_success("example.com")
        assert limiter._get_delay("example.com") == 0.5
        
        limiter.on_success("example.com")
        assert limiter._get_delay("example.com") == 0.25
        
        # Eventually returns to base
        for _ in range(10):
            limiter.on_success("example.com")
        
        # Should be back to base (domain removed from elevated list)
        assert "example.com" not in limiter._domain_delays


class TestRateLimiterSemaphore:
    """Test concurrent request limiting."""
    
    @pytest.mark.asyncio
    async def test_limits_concurrent_requests(self):
        """Should limit concurrent requests per domain."""
        limiter = RateLimiter(base_delay=0.0, max_concurrent=2)
        
        active = 0
        max_active = 0
        
        async def task():
            nonlocal active, max_active
            async with await limiter.acquire("example.com"):
                active += 1
                max_active = max(max_active, active)
                await asyncio.sleep(0.05)
                active -= 1
        
        # Run 5 tasks concurrently
        await asyncio.gather(*[task() for _ in range(5)])
        
        # Should never have more than 2 active
        assert max_active == 2
    
    @pytest.mark.asyncio
    async def test_different_domains_independent(self):
        """Should allow concurrent requests to different domains."""
        limiter = RateLimiter(base_delay=0.0, max_concurrent=1)
        
        results = []
        
        async def task(domain):
            async with await limiter.acquire(domain):
                results.append(f"start-{domain}")
                await asyncio.sleep(0.05)
                results.append(f"end-{domain}")
        
        # Run tasks to different domains concurrently
        await asyncio.gather(
            task("example1.com"),
            task("example2.com"),
        )
        
        # Both should start before either ends
        assert results.index("start-example1.com") < results.index("end-example2.com")
        assert results.index("start-example2.com") < results.index("end-example1.com")


class TestRetryAfterParsing:
    """Test Retry-After header parsing."""
    
    def test_parses_integer_seconds(self):
        """Should parse integer seconds."""
        limiter = RateLimiter()
        
        assert limiter._parse_retry_after("60") == 60
        assert limiter._parse_retry_after("1") == 1
        assert limiter._parse_retry_after("3600") == 3600
    
    def test_returns_none_for_invalid(self):
        """Should return None for invalid values."""
        limiter = RateLimiter()
        
        assert limiter._parse_retry_after(None) is None
        assert limiter._parse_retry_after("") is None
        assert limiter._parse_retry_after("invalid") is None
    
    def test_on_response_handles_429(self):
        """Should handle 429 response correctly."""
        limiter = RateLimiter(base_delay=0.1)
        
        retry_after = limiter.on_response(429, "example.com", {"Retry-After": "30"})
        
        assert retry_after == 30
        assert limiter._get_delay("example.com") == 30.0
    
    def test_on_response_handles_503(self):
        """Should handle 503 response correctly."""
        limiter = RateLimiter(base_delay=0.1)
        
        limiter.on_response(503, "example.com", {})
        
        # Should use backoff since no Retry-After
        assert limiter._get_delay("example.com") > 0.1
    
    def test_on_response_handles_success(self):
        """Should handle successful response."""
        limiter = RateLimiter()
        limiter._domain_delays["example.com"] = 5.0
        
        limiter.on_response(200, "example.com", {})
        
        # Should reduce delay
        assert limiter._get_delay("example.com") < 5.0


class TestRateLimiterStats:
    """Test rate limiter statistics."""
    
    @pytest.mark.asyncio
    async def test_get_stats(self):
        """Should return correct statistics."""
        limiter = RateLimiter()
        
        await limiter.wait("example1.com")
        await limiter.wait("example2.com")
        limiter.on_rate_limited("example1.com")
        
        stats = limiter.get_stats()
        
        assert stats["domains_tracked"] == 2
        assert stats["domains_with_elevated_delay"] == 1
        assert "example1.com" in stats["elevated_delays"]


class TestRateLimiterIntegration:
    """Integration tests for rate limiter with HTTP client."""
    
    def test_http_client_accepts_rate_limiter(self):
        """Should be able to create HTTP client with rate limiter."""
        from src.searchers.http_client import AsyncHttpClient
        
        limiter = RateLimiter(base_delay=0.1, max_concurrent=2)
        client = AsyncHttpClient(rate_limiter=limiter)
        
        assert client._rate_limiter is limiter
    
    def test_http_client_works_without_rate_limiter(self):
        """Should work without rate limiter (backward compatible)."""
        from src.searchers.http_client import AsyncHttpClient
        
        client = AsyncHttpClient()
        
        assert client._rate_limiter is None


# Run with: pytest tests/test_rate_limiter.py -v
