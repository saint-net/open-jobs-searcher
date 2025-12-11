"""Ollama LLM провайдер."""

import logging
import time
from typing import Optional

import httpx

from .base import BaseLLMProvider
from .openrouter import LLMUsageStats

logger = logging.getLogger(__name__)


class OllamaProvider(BaseLLMProvider):
    """Провайдер для локальной Ollama."""

    def __init__(
        self,
        model: str = "gpt-oss:20b",
        base_url: str = "http://localhost:11434",
        timeout: float = 300.0,  # Увеличен таймаут для больших промптов
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

    async def complete(self, prompt: str, system: Optional[str] = None) -> str:
        """Generate response via Ollama API."""
        from .prompts import SYSTEM_PROMPT
        
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system or SYSTEM_PROMPT,
            "stream": False,
            "options": {
                "temperature": 0.0,  # Zero temperature for deterministic output
                "num_predict": 4096,  # Max output tokens
                "num_ctx": 32768,  # Large context window for HTML content
            },
        }

        start_time = time.perf_counter()
        
        try:
            response = await self.client.post(
                f"{self.base_url}/api/generate",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            
            elapsed = time.perf_counter() - start_time
            
            # Проверяем на ошибки в ответе
            if data.get("error"):
                return ""
            
            # Ollama returns token counts
            prompt_tokens = data.get("prompt_eval_count", 0)
            completion_tokens = data.get("eval_count", 0)
            
            self.usage_stats.add_call(prompt_tokens, completion_tokens, elapsed)
            
            logger.debug(
                f"Ollama call: {prompt_tokens}+{completion_tokens} tokens, "
                f"{elapsed:.2f}s, model={self.model}"
            )
            
            return data.get("response", "")
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Ollama API error: {e.response.status_code}") from e
        except httpx.ConnectError:
            raise RuntimeError(
                f"Cannot connect to Ollama at {self.base_url}. "
                "Make sure Ollama is running: ollama serve"
            )
        except httpx.ReadTimeout:
            return ""

    def get_usage_summary(self) -> str:
        """Get human-readable usage summary."""
        return self.usage_stats.summary()

    async def close(self):
        """Закрыть HTTP клиент."""
        if self.usage_stats.total_calls > 0:
            logger.info(self.usage_stats.summary())
        await self.client.aclose()

