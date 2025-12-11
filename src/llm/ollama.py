"""Ollama LLM провайдер."""

import json
import logging
import time
from typing import Optional

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from .base import BaseLLMProvider
from .openrouter import LLMUsageStats

logger = logging.getLogger(__name__)


class OllamaRetryableError(Exception):
    """Transient error that should trigger retry."""
    pass


class OllamaProvider(BaseLLMProvider):
    """Провайдер для локальной Ollama."""

    MAX_RETRIES = 3

    def __init__(
        self,
        model: str = "gpt-oss:20b",
        base_url: str = "http://localhost:11434",
        timeout: float = 300.0,
    ):
        """
        Инициализация Ollama провайдера.

        Args:
            model: Название модели (по умолчанию gpt-oss:20b)
            base_url: URL Ollama сервера
            timeout: Таймаут запросов в секундах
        """
        self.model = model
        self.base_url = base_url.rstrip('/')
        self.client = httpx.AsyncClient(timeout=timeout)
        self.usage_stats = LLMUsageStats()

    def _build_payload(
        self, 
        prompt: str, 
        system: Optional[str] = None,
        json_format: bool = False,
    ) -> dict:
        """Build request payload."""
        from .prompts import SYSTEM_PROMPT
        
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system or SYSTEM_PROMPT,
            "stream": False,
            "options": {
                "temperature": 0.0,
                "num_predict": 4096,
                "num_ctx": 32768,
            },
        }
        
        if json_format:
            payload["format"] = "json"
        
        return payload

    async def _make_request(self, payload: dict) -> dict:
        """
        Make HTTP request to Ollama API.
        
        Raises:
            OllamaRetryableError: On transient errors (timeout, connection issues)
            RuntimeError: On permanent errors
        """
        try:
            response = await self.client.post(
                f"{self.base_url}/api/generate",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            
            if data.get("error"):
                error_msg = data.get("error", "Unknown error")
                logger.debug(f"Ollama error response: {error_msg}")
                raise RuntimeError(f"Ollama API error: {error_msg}")
            
            return data
            
        except httpx.HTTPStatusError as e:
            if e.response.status_code >= 500:
                raise OllamaRetryableError(f"HTTP {e.response.status_code}") from e
            raise RuntimeError(f"Ollama API error: {e.response.status_code}") from e
        except httpx.ConnectError as e:
            raise RuntimeError(
                f"Cannot connect to Ollama at {self.base_url}. "
                "Make sure Ollama is running: ollama serve"
            ) from e
        except httpx.ReadTimeout as e:
            raise OllamaRetryableError(f"Timeout: {e}") from e

    def _track_usage(self, data: dict, elapsed: float, json_mode: bool = False) -> None:
        """Track usage statistics from API response."""
        prompt_tokens = data.get("prompt_eval_count", 0)
        completion_tokens = data.get("eval_count", 0)
        
        self.usage_stats.add_call(prompt_tokens, completion_tokens, elapsed)
        
        mode = "JSON" if json_mode else "text"
        logger.debug(
            f"Ollama {mode} call: {prompt_tokens}+{completion_tokens} tokens, "
            f"{elapsed:.2f}s, model={self.model}"
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=16),
        retry=retry_if_exception_type(OllamaRetryableError),
        reraise=True,
    )
    async def complete(self, prompt: str, system: Optional[str] = None) -> str:
        """Generate response via Ollama API with retry on transient errors."""
        payload = self._build_payload(prompt, system)
        start_time = time.perf_counter()
        
        try:
            data = await self._make_request(payload)
            elapsed = time.perf_counter() - start_time
            
            self._track_usage(data, elapsed)
            return data.get("response", "")
            
        except OllamaRetryableError:
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=16),
        retry=retry_if_exception_type(OllamaRetryableError),
        reraise=True,
    )
    async def complete_json(self, prompt: str, system: Optional[str] = None) -> dict | list:
        """
        Generate JSON response via Ollama API with structured output.
        
        Uses format="json" for guaranteed valid JSON output.
        Includes automatic retry on transient errors.
        
        Args:
            prompt: User prompt (should explicitly request JSON)
            system: System prompt (optional)
            
        Returns:
            Parsed JSON (dict or list)
        """
        payload = self._build_payload(prompt, system, json_format=True)
        start_time = time.perf_counter()
        
        try:
            data = await self._make_request(payload)
            elapsed = time.perf_counter() - start_time
            
            self._track_usage(data, elapsed, json_mode=True)
            
            content = data.get("response", "")
            if content:
                try:
                    return json.loads(content)
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON parse failed despite format=json: {e}")
                    logger.debug(f"Raw content (first 500 chars): {content[:500]}")
                    from .html_utils import extract_json
                    return extract_json(content)
            
            return {}
            
        except OllamaRetryableError:
            raise

    def get_usage_summary(self) -> str:
        """Get human-readable usage summary."""
        return self.usage_stats.summary()

    async def close(self):
        """Закрыть HTTP клиент."""
        if self.usage_stats.total_calls > 0:
            logger.info(self.usage_stats.summary())
        await self.client.aclose()
