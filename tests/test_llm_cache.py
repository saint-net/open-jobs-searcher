"""Tests for LLM response caching."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from src.llm.cache import LLMCache, CacheNamespace, NAMESPACE_TTL, estimate_tokens
from src.database.models import LLMCacheEntry, LLMCacheStats


class TestCacheNamespaceTTL:
    """Test TTL values for different namespaces."""
    
    def test_jobs_ttl_is_6_hours(self):
        assert NAMESPACE_TTL[CacheNamespace.JOBS] == 6 * 3600
    
    def test_translation_ttl_is_30_days(self):
        assert NAMESPACE_TTL[CacheNamespace.TRANSLATION] == 30 * 24 * 3600
    
    def test_url_discovery_ttl_is_7_days(self):
        assert NAMESPACE_TTL[CacheNamespace.URL_DISCOVERY] == 7 * 24 * 3600
    
    def test_company_info_ttl_is_30_days(self):
        assert NAMESPACE_TTL[CacheNamespace.COMPANY_INFO] == 30 * 24 * 3600


class TestEstimateTokens:
    """Test token estimation."""
    
    def test_estimates_roughly_4_chars_per_token(self):
        text = "a" * 100
        assert estimate_tokens(text) == 25
    
    def test_handles_empty_string(self):
        assert estimate_tokens("") == 0
    
    def test_handles_short_string(self):
        assert estimate_tokens("hi") == 0  # 2 // 4 = 0


class TestLLMCacheKeyGeneration:
    """Test cache key generation."""
    
    def test_different_content_produces_different_keys(self):
        mock_repo = MagicMock()
        cache = LLMCache(mock_repo, model="test")
        
        key1 = cache._make_key(CacheNamespace.JOBS, "content1")
        key2 = cache._make_key(CacheNamespace.JOBS, "content2")
        
        assert key1 != key2
    
    def test_different_namespace_produces_different_keys(self):
        mock_repo = MagicMock()
        cache = LLMCache(mock_repo, model="test")
        
        key1 = cache._make_key(CacheNamespace.JOBS, "same content")
        key2 = cache._make_key(CacheNamespace.TRANSLATION, "same content")
        
        assert key1 != key2
    
    def test_different_model_produces_different_keys(self):
        mock_repo = MagicMock()
        cache1 = LLMCache(mock_repo, model="gpt-4")
        cache2 = LLMCache(mock_repo, model="claude-3")
        
        key1 = cache1._make_key(CacheNamespace.JOBS, "same content")
        key2 = cache2._make_key(CacheNamespace.JOBS, "same content")
        
        assert key1 != key2
    
    def test_key_is_32_chars_hex(self):
        mock_repo = MagicMock()
        cache = LLMCache(mock_repo)
        
        key = cache._make_key(CacheNamespace.JOBS, "test content")
        
        assert len(key) == 32
        assert all(c in "0123456789abcdef" for c in key)


class TestLLMCacheGet:
    """Test cache get operations."""
    
    @pytest.mark.asyncio
    async def test_returns_none_on_cache_miss(self):
        mock_repo = AsyncMock()
        mock_repo.get_llm_cache.return_value = None
        
        cache = LLMCache(mock_repo)
        result = await cache.get(CacheNamespace.JOBS, "test content")
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_returns_parsed_json_on_cache_hit(self):
        mock_repo = AsyncMock()
        mock_repo.get_llm_cache.return_value = LLMCacheEntry(
            key="abc123",
            namespace="jobs",
            value='[{"title": "Developer"}]',
            ttl_seconds=3600,
            tokens_saved=100
        )
        
        cache = LLMCache(mock_repo)
        result = await cache.get(CacheNamespace.JOBS, "test content")
        
        assert result == [{"title": "Developer"}]
    
    @pytest.mark.asyncio
    async def test_increments_session_hits_on_cache_hit(self):
        mock_repo = AsyncMock()
        mock_repo.get_llm_cache.return_value = LLMCacheEntry(
            key="abc123",
            namespace="jobs",
            value='[]',
            ttl_seconds=3600,
            tokens_saved=50
        )
        
        cache = LLMCache(mock_repo)
        await cache.get(CacheNamespace.JOBS, "test1")
        await cache.get(CacheNamespace.JOBS, "test2")
        
        assert cache._session_hits == 2
    
    @pytest.mark.asyncio
    async def test_increments_session_misses_on_cache_miss(self):
        mock_repo = AsyncMock()
        mock_repo.get_llm_cache.return_value = None
        
        cache = LLMCache(mock_repo)
        await cache.get(CacheNamespace.JOBS, "test1")
        await cache.get(CacheNamespace.JOBS, "test2")
        
        assert cache._session_misses == 2


class TestLLMCacheSet:
    """Test cache set operations."""
    
    @pytest.mark.asyncio
    async def test_serializes_to_json(self):
        mock_repo = AsyncMock()
        cache = LLMCache(mock_repo, model="test-model")
        
        await cache.set(
            CacheNamespace.JOBS,
            "test content",
            [{"title": "Developer"}],
            tokens_estimate=100
        )
        
        mock_repo.set_llm_cache.assert_called_once()
        call_kwargs = mock_repo.set_llm_cache.call_args
        assert '"title": "Developer"' in call_kwargs.kwargs["value"]
    
    @pytest.mark.asyncio
    async def test_uses_correct_ttl_for_namespace(self):
        mock_repo = AsyncMock()
        cache = LLMCache(mock_repo)
        
        await cache.set(CacheNamespace.TRANSLATION, "titles", ["Developer"], 100)
        
        call_kwargs = mock_repo.set_llm_cache.call_args
        assert call_kwargs.kwargs["ttl_seconds"] == 30 * 24 * 3600  # 30 days


class TestLLMCacheGetOrCompute:
    """Test get_or_compute operations."""
    
    @pytest.mark.asyncio
    async def test_returns_cached_value_without_computing(self):
        mock_repo = AsyncMock()
        mock_repo.get_llm_cache.return_value = LLMCacheEntry(
            key="abc",
            namespace="jobs",
            value='["cached"]',
            ttl_seconds=3600,
            tokens_saved=10
        )
        
        compute_fn = AsyncMock(return_value=["computed"])
        cache = LLMCache(mock_repo)
        
        result = await cache.get_or_compute(
            CacheNamespace.JOBS,
            "content",
            compute_fn
        )
        
        assert result == ["cached"]
        compute_fn.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_computes_and_caches_on_miss(self):
        mock_repo = AsyncMock()
        mock_repo.get_llm_cache.return_value = None
        
        compute_fn = AsyncMock(return_value=["computed"])
        cache = LLMCache(mock_repo)
        
        result = await cache.get_or_compute(
            CacheNamespace.JOBS,
            "content",
            compute_fn
        )
        
        assert result == ["computed"]
        compute_fn.assert_called_once()
        mock_repo.set_llm_cache.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_does_not_cache_empty_result(self):
        mock_repo = AsyncMock()
        mock_repo.get_llm_cache.return_value = None
        
        compute_fn = AsyncMock(return_value=[])  # Empty result
        cache = LLMCache(mock_repo)
        
        await cache.get_or_compute(CacheNamespace.JOBS, "content", compute_fn)
        
        mock_repo.set_llm_cache.assert_not_called()


class TestLLMCacheStats:
    """Test cache statistics."""
    
    @pytest.mark.asyncio
    async def test_session_stats_calculates_hit_rate(self):
        mock_repo = AsyncMock()
        mock_repo.get_llm_cache.side_effect = [
            LLMCacheEntry(key="a", namespace="jobs", value="[]", ttl_seconds=3600, tokens_saved=10),
            None,
            LLMCacheEntry(key="b", namespace="jobs", value="[]", ttl_seconds=3600, tokens_saved=20),
            None,
        ]
        
        cache = LLMCache(mock_repo)
        
        # 2 hits, 2 misses
        await cache.get(CacheNamespace.JOBS, "1")
        await cache.get(CacheNamespace.JOBS, "2")
        await cache.get(CacheNamespace.JOBS, "3")
        await cache.get(CacheNamespace.JOBS, "4")
        
        stats = cache.get_session_stats()
        
        assert stats["hits"] == 2
        assert stats["misses"] == 2
        assert stats["hit_rate"] == 0.5
        assert stats["tokens_saved"] == 30
    
    def test_session_stats_handles_zero_total(self):
        mock_repo = MagicMock()
        cache = LLMCache(mock_repo)
        
        stats = cache.get_session_stats()
        
        assert stats["hit_rate"] == 0.0


class TestLLMCacheEntryModel:
    """Test LLMCacheEntry model."""
    
    def test_is_expired_returns_true_when_expired(self):
        entry = LLMCacheEntry(
            key="test",
            namespace="jobs",
            value="[]",
            ttl_seconds=3600,
            created_at=datetime.now() - timedelta(hours=2)  # 2 hours ago
        )
        
        assert entry.is_expired() is True
    
    def test_is_expired_returns_false_when_valid(self):
        entry = LLMCacheEntry(
            key="test",
            namespace="jobs",
            value="[]",
            ttl_seconds=3600,
            created_at=datetime.now() - timedelta(minutes=30)  # 30 min ago
        )
        
        assert entry.is_expired() is False
    
    def test_is_expired_returns_true_when_no_created_at(self):
        entry = LLMCacheEntry(
            key="test",
            namespace="jobs",
            value="[]",
            ttl_seconds=3600,
            created_at=None
        )
        
        assert entry.is_expired() is True


class TestLLMCacheStatsModel:
    """Test LLMCacheStats model."""
    
    def test_hit_rate_calculation(self):
        stats = LLMCacheStats(hits=75, misses=25)
        assert stats.hit_rate == 0.75
    
    def test_hit_rate_handles_zero_total(self):
        stats = LLMCacheStats(hits=0, misses=0)
        assert stats.hit_rate == 0.0
    
    def test_estimated_cost_saved(self):
        stats = LLMCacheStats(total_tokens_saved=100000)
        assert stats.estimated_cost_saved == 1.0  # $1 for 100K tokens
