"""LLM response caching with different TTLs per operation type.

Caches LLM responses to reduce token usage and costs:
- Job extraction: 6 hours TTL (jobs change frequently)
- Translation: 30 days TTL (translations are stable)  
- URL discovery: 7 days TTL (career URLs rarely change)
- Company info: 30 days TTL (company descriptions are stable)
"""

import hashlib
import json
import logging
from enum import Enum
from typing import Optional, Any, Callable, TypeVar, ParamSpec

from src.database import JobRepository
from src.database.models import LLMCacheStats

logger = logging.getLogger(__name__)

P = ParamSpec('P')
T = TypeVar('T')


class CacheNamespace(str, Enum):
    """Cache namespaces with their TTLs."""
    
    JOBS = "jobs"           # 6 hours
    TRANSLATION = "trans"   # 30 days
    URL_DISCOVERY = "url"   # 7 days  
    COMPANY_INFO = "company"  # 30 days


# TTL in seconds for each namespace
NAMESPACE_TTL = {
    CacheNamespace.JOBS: 6 * 3600,           # 6 hours
    CacheNamespace.TRANSLATION: 30 * 24 * 3600,  # 30 days
    CacheNamespace.URL_DISCOVERY: 7 * 24 * 3600,  # 7 days
    CacheNamespace.COMPANY_INFO: 30 * 24 * 3600,  # 30 days
}


class LLMCache:
    """LLM response cache with namespace-based TTLs.
    
    Usage:
        cache = LLMCache(repository)
        
        # Check cache
        result = await cache.get(CacheNamespace.TRANSLATION, key)
        if result is None:
            result = await llm.complete(prompt)
            await cache.set(CacheNamespace.TRANSLATION, key, result)
    """
    
    def __init__(self, repository: JobRepository, model: Optional[str] = None):
        """Initialize LLM cache.
        
        Args:
            repository: JobRepository for database operations
            model: LLM model name (for cache key differentiation)
        """
        self._repo = repository
        self._model = model
        
        # Runtime statistics (session-based)
        self._session_hits = 0
        self._session_misses = 0
        self._session_tokens_saved = 0
    
    def _make_key(self, namespace: CacheNamespace, content: str) -> str:
        """Create cache key from namespace and content.
        
        Args:
            namespace: Cache namespace
            content: Content to hash (cleaned HTML, titles, etc.)
            
        Returns:
            SHA-256 hash truncated to 32 chars
        """
        # Include model in key to avoid cross-model cache pollution
        key_content = f"{namespace.value}:{self._model or 'default'}:{content}"
        return hashlib.sha256(key_content.encode()).hexdigest()[:32]
    
    async def get(
        self, 
        namespace: CacheNamespace, 
        content: str
    ) -> Optional[Any]:
        """Get cached LLM response.
        
        Args:
            namespace: Cache namespace (determines TTL)
            content: Content that was sent to LLM (for key generation)
            
        Returns:
            Parsed JSON response or None if not cached/expired
        """
        key = self._make_key(namespace, content)
        
        try:
            entry = await self._repo.get_llm_cache(key)
            if entry:
                self._session_hits += 1
                self._session_tokens_saved += entry.tokens_saved
                logger.debug(f"LLM cache HIT [{namespace.value}]: {key[:8]}...")
                return json.loads(entry.value)
        except Exception as e:
            logger.warning(f"LLM cache get error: {e}")
        
        self._session_misses += 1
        logger.debug(f"LLM cache MISS [{namespace.value}]: {key[:8]}...")
        return None
    
    async def set(
        self,
        namespace: CacheNamespace,
        content: str,
        response: Any,
        tokens_estimate: int = 0
    ) -> None:
        """Cache LLM response.
        
        Args:
            namespace: Cache namespace (determines TTL)
            content: Content that was sent to LLM (for key generation)
            response: LLM response (will be JSON serialized)
            tokens_estimate: Estimated tokens this response represents
        """
        key = self._make_key(namespace, content)
        ttl = NAMESPACE_TTL.get(namespace, 6 * 3600)  # Default 6 hours
        
        try:
            value = json.dumps(response, ensure_ascii=False)
            await self._repo.set_llm_cache(
                key=key,
                namespace=namespace.value,
                value=value,
                ttl_seconds=ttl,
                model=self._model,
                tokens_saved=tokens_estimate
            )
            logger.debug(f"LLM cache SET [{namespace.value}]: {key[:8]}... (TTL: {ttl//3600}h)")
        except Exception as e:
            logger.warning(f"LLM cache set error: {e}")
    
    async def get_or_compute(
        self,
        namespace: CacheNamespace,
        content: str,
        compute_fn: Callable[[], Any],
        tokens_estimate: int = 0
    ) -> Any:
        """Get from cache or compute and cache result.
        
        This is the main method for using the cache.
        
        Args:
            namespace: Cache namespace
            content: Content for cache key
            compute_fn: Async function to call on cache miss
            tokens_estimate: Estimated tokens for the response
            
        Returns:
            Cached or computed result
        """
        # Try cache first
        cached = await self.get(namespace, content)
        if cached is not None:
            return cached
        
        # Compute
        result = await compute_fn()
        
        # Cache result (only if not empty)
        if result:
            await self.set(namespace, content, result, tokens_estimate)
        
        return result
    
    def get_session_stats(self) -> dict:
        """Get cache statistics for current session.
        
        Returns:
            Dict with hits, misses, hit_rate, tokens_saved
        """
        total = self._session_hits + self._session_misses
        return {
            "hits": self._session_hits,
            "misses": self._session_misses,
            "hit_rate": self._session_hits / total if total > 0 else 0.0,
            "tokens_saved": self._session_tokens_saved,
            "estimated_cost_saved": self._session_tokens_saved * 0.00001,
        }
    
    async def get_total_stats(self) -> LLMCacheStats:
        """Get total cache statistics from database.
        
        Returns:
            LLMCacheStats with all-time statistics
        """
        return await self._repo.get_llm_cache_stats()
    
    async def cleanup(self) -> int:
        """Remove expired cache entries.
        
        Returns:
            Number of entries removed
        """
        count = await self._repo.cleanup_expired_cache()
        if count > 0:
            logger.info(f"Cleaned up {count} expired LLM cache entries")
        return count
    
    def log_session_stats(self) -> None:
        """Log session cache statistics."""
        stats = self.get_session_stats()
        if stats["hits"] > 0 or stats["misses"] > 0:
            logger.info(
                f"LLM Cache: {stats['hits']} hits, {stats['misses']} misses "
                f"({stats['hit_rate']:.1%} hit rate), "
                f"~{stats['tokens_saved']} tokens saved"
            )


def estimate_tokens(text: str) -> int:
    """Rough token estimate (1 token ≈ 4 chars for English).
    
    Args:
        text: Text to estimate tokens for
        
    Returns:
        Estimated token count
    """
    return len(text) // 4
