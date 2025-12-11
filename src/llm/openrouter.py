"""OpenRouter LLM провайдер."""

import logging
import time
from dataclasses import dataclass
from typing import Optional

import httpx
from rich.console import Console
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from .base import BaseLLMProvider

logger = logging.getLogger(__name__)
console = Console()


@dataclass
class LLMUsageStats:
    """Statistics for LLM usage tracking."""
    total_calls: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_time_seconds: float = 0.0
    total_cost_usd: float = 0.0
    
    def add_call(self, prompt_tokens: int, completion_tokens: int, time_seconds: float, cost_usd: float = 0.0):
        """Record a single LLM call."""
        self.total_calls += 1
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_time_seconds += time_seconds
        self.total_cost_usd += cost_usd
    
    @property
    def total_tokens(self) -> int:
        return self.total_prompt_tokens + self.total_completion_tokens
    
    def summary(self) -> str:
        """Human-readable summary."""
        return (
            f"LLM Stats: {self.total_calls} calls, "
            f"{self.total_tokens:,} tokens ({self.total_prompt_tokens:,}+{self.total_completion_tokens:,}), "
            f"{self.total_time_seconds:.1f}s total, "
            f"${self.total_cost_usd:.4f}"
        )


class OpenRouterRetryableError(Exception):
    """Transient error that should trigger retry."""
    pass


class OpenRouterProvider(BaseLLMProvider):
    """Провайдер для OpenRouter API."""

    BASE_URL = "https://openrouter.ai/api/v1"

    # Настройки для разных моделей
    MODEL_CONFIGS = {
        "openai/gpt-oss-20b": {
            "temperature": 0.0,
            "max_tokens": 8192,
        },
        "openai/gpt-oss-120b": {
            "temperature": 0.0,
            "max_tokens": 8192,
        },
    }

    # Дефолтная конфигурация для неизвестных моделей
    DEFAULT_CONFIG = {
        "temperature": 0.0,
        "max_tokens": 8192,
    }

    # Retry settings (used by tenacity decorator)
    MAX_RETRIES = 3
    
    # Errors that indicate transient provider issues (should retry)
    TRANSIENT_ERROR_PATTERNS = [
        "provider returned error",
        "rate limit",
        "overloaded",
        "capacity",
        "temporarily unavailable",
        "service unavailable",
        "internal server error",  # 500 errors
        "502", "503", "504",  # Gateway errors
    ]
    
    # Доступные провайдеры OpenRouter для gpt-oss-120b
    # Список slug-ов провайдеров: https://openrouter.ai/openai/gpt-oss-120b (вкладка Providers)
    AVAILABLE_PROVIDERS = [
        "chutes",       # Uptime ~97.6%
        "siliconflow",  # Uptime ~97.7%
        "novitaai",     # Uptime ~85.5%
        "gmicloud",     # Uptime ~88.7%
        "deepinfra",    # Uptime ~69.3%
        "ncompass",     # Uptime ~77.2%
    ]

    def __init__(
        self,
        api_key: str,
        model: str = "openai/gpt-oss-120b",
        timeout: float = 300.0,
        provider: Optional[str] = None,
        provider_order: Optional[list[str]] = None,
        allow_fallbacks: bool = True,
    ):
        """
        Инициализация OpenRouter провайдера.

        Args:
            api_key: API ключ OpenRouter
            model: Название модели (например, openai/gpt-oss-120b)
            timeout: Таймаут запросов в секундах
            provider: Конкретный провайдер для использования (например, "chutes")
            provider_order: Список провайдеров в порядке приоритета
            allow_fallbacks: Разрешать ли fallback на другие провайдеры
        """
        if not api_key:
            raise ValueError("OpenRouter API key is required")
        
        self.api_key = api_key
        self.model = model
        self.config = self.MODEL_CONFIGS.get(model, self.DEFAULT_CONFIG)
        self.client = httpx.AsyncClient(timeout=timeout)
        
        # Provider routing configuration
        self.provider = provider
        self.provider_order = provider_order
        self.allow_fallbacks = allow_fallbacks
        
        # Usage tracking
        self.usage_stats = LLMUsageStats()

    def _is_transient_error(self, error_msg: str) -> bool:
        """Check if error is transient and should be retried."""
        error_lower = error_msg.lower()
        return any(pattern in error_lower for pattern in self.TRANSIENT_ERROR_PATTERNS)
    
    def _build_provider_config(self) -> Optional[dict]:
        """
        Построить конфигурацию provider routing для запроса.
        
        Returns:
            dict с настройками провайдера или None если не указаны
        """
        if not self.provider and not self.provider_order:
            return None
        
        config = {}
        
        # Если указан конкретный провайдер, используем его как единственный в order
        if self.provider:
            config["order"] = [self.provider]
        elif self.provider_order:
            config["order"] = self.provider_order
        
        config["allow_fallbacks"] = self.allow_fallbacks
        
        return config

    def _log_retry(self, retry_state) -> None:
        """Log retry attempt with console output."""
        attempt = retry_state.attempt_number
        exc = retry_state.outcome.exception()
        wait_time = retry_state.next_action.sleep if retry_state.next_action else 0
        
        retry_msg = f"OpenRouter error (attempt {attempt}/{self.MAX_RETRIES}): {exc}. Retrying in {wait_time:.1f}s..."
        logger.warning(retry_msg)
        console.print(f"[bold red]⚠️  {retry_msg}[/bold red]")

    @retry(
        stop=stop_after_attempt(3),  # MAX_RETRIES
        wait=wait_exponential(multiplier=2, min=2, max=16),
        retry=retry_if_exception_type(OpenRouterRetryableError),
        before_sleep=lambda rs: OpenRouterProvider._log_retry(rs.args[0], rs),
        reraise=True,
    )
    async def complete(self, prompt: str, system: Optional[str] = None) -> str:
        """Generate response via OpenRouter API with automatic retry on transient errors."""
        from .prompts import SYSTEM_PROMPT

        messages = []
        
        # Добавляем системный промпт
        system_content = system or SYSTEM_PROMPT
        if system_content:
            messages.append({"role": "system", "content": system_content})
        
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.config["temperature"],
            "max_tokens": self.config["max_tokens"],
        }
        
        # Добавляем provider routing если указан
        provider_config = self._build_provider_config()
        if provider_config:
            payload["provider"] = provider_config

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/open-jobs-searcher",
            "X-Title": "Open Jobs Searcher",
        }

        start_time = time.perf_counter()
        
        try:
            response = await self.client.post(
                f"{self.BASE_URL}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            
            elapsed = time.perf_counter() - start_time
            
            # Проверяем на ошибки в ответе
            if data.get("error"):
                error_data = data["error"]
                error_msg = error_data.get("message", "Unknown error")
                error_code = error_data.get("code", "")
                error_type = error_data.get("type", "")
                
                full_error = error_msg
                if error_code:
                    full_error = f"[{error_code}] {full_error}"
                if error_type:
                    full_error = f"{full_error} (type: {error_type})"
                
                logger.debug(f"OpenRouter error response: {error_data}")
                
                if self._is_transient_error(error_msg):
                    raise OpenRouterRetryableError(full_error)
                raise RuntimeError(f"OpenRouter API error: {full_error}")
            
            # Parse usage stats
            usage = data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            
            # OpenRouter returns cost in generation_time or we estimate from tokens
            # Most free models have $0 cost
            cost_usd = 0.0
            
            # Track usage
            self.usage_stats.add_call(prompt_tokens, completion_tokens, elapsed, cost_usd)
            
            logger.debug(
                f"LLM call: {prompt_tokens}+{completion_tokens} tokens, "
                f"{elapsed:.2f}s, model={self.model}"
            )
            
            # Извлекаем ответ
            choices = data.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                return message.get("content", "")
            
            return ""
            
        except httpx.HTTPStatusError as e:
            error_body = e.response.text[:500]
            error_msg = f"HTTP {e.response.status_code}: {error_body}"
            logger.debug(f"OpenRouter HTTP error: status={e.response.status_code}, body={error_body}")
            
            if e.response.status_code >= 500:
                raise OpenRouterRetryableError(error_msg) from e
            raise RuntimeError(f"OpenRouter API error: {error_msg}") from e
            
        except httpx.ConnectError as e:
            raise OpenRouterRetryableError(f"Connection error: {e}") from e
            
        except httpx.ReadTimeout as e:
            raise OpenRouterRetryableError(f"Timeout: {e}") from e
        
        except OpenRouterRetryableError:
            raise  # Let tenacity handle it

    def get_usage_summary(self) -> str:
        """Get human-readable usage summary."""
        return self.usage_stats.summary()
    
    async def close(self):
        """Закрыть HTTP клиент."""
        if self.usage_stats.total_calls > 0:
            logger.info(self.usage_stats.summary())
        await self.client.aclose()

