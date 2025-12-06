"""OpenRouter LLM провайдер."""

import asyncio
import logging
from typing import Optional

import httpx
from rich.console import Console

from .base import BaseLLMProvider

logger = logging.getLogger(__name__)
console = Console()


class OpenRouterProvider(BaseLLMProvider):
    """Провайдер для OpenRouter API."""

    BASE_URL = "https://openrouter.ai/api/v1"

    # Настройки для разных моделей
    MODEL_CONFIGS = {
        "openai/gpt-oss-20b": {
            "temperature": 0.0,
            "max_tokens": 4096,
        },
        "openai/gpt-oss-120b": {
            "temperature": 0.0,
            "max_tokens": 4096,
        },
    }

    # Дефолтная конфигурация для неизвестных моделей
    DEFAULT_CONFIG = {
        "temperature": 0.0,
        "max_tokens": 4096,
    }

    # Retry settings for transient API errors
    MAX_RETRIES = 3
    INITIAL_RETRY_DELAY = 2.0  # seconds
    
    # Errors that indicate transient provider issues (should retry)
    TRANSIENT_ERROR_PATTERNS = [
        "provider returned error",
        "rate limit",
        "overloaded",
        "capacity",
        "temporarily unavailable",
        "service unavailable",
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

    async def complete(self, prompt: str, system: Optional[str] = None) -> str:
        """Generate response via OpenRouter API with retry logic for transient errors."""
        from .prompts import SYSTEM_PROMPT

        messages = []
        
        # Добавляем системный промпт
        system_content = system or SYSTEM_PROMPT
        if system_content:
            messages.append({
                "role": "system",
                "content": system_content,
            })
        
        # Добавляем пользовательский промпт
        messages.append({
            "role": "user",
            "content": prompt,
        })

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

        last_error = None
        
        for attempt in range(self.MAX_RETRIES):
            try:
                response = await self.client.post(
                    f"{self.BASE_URL}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()
                
                # Проверяем на ошибки в ответе
                if data.get("error"):
                    error_msg = data["error"].get("message", "Unknown error")
                    
                    # Check if this is a transient error that we should retry
                    if self._is_transient_error(error_msg) and attempt < self.MAX_RETRIES - 1:
                        delay = self.INITIAL_RETRY_DELAY * (2 ** attempt)
                        retry_msg = (
                            f"OpenRouter transient error (attempt {attempt + 1}/{self.MAX_RETRIES}): {error_msg}. "
                            f"Retrying in {delay:.1f}s..."
                        )
                        logger.warning(retry_msg)
                        console.print(f"[bold red]⚠️  {retry_msg}[/bold red]")
                        await asyncio.sleep(delay)
                        last_error = RuntimeError(f"OpenRouter API error: {error_msg}")
                        continue
                    
                    raise RuntimeError(f"OpenRouter API error: {error_msg}")
                
                # Извлекаем ответ
                choices = data.get("choices", [])
                if choices:
                    message = choices[0].get("message", {})
                    return message.get("content", "")
                
                return ""
                
            except httpx.HTTPStatusError as e:
                error_body = e.response.text
                error_msg = f"{e.response.status_code} - {error_body}"
                
                # Retry on 5xx errors
                if e.response.status_code >= 500 and attempt < self.MAX_RETRIES - 1:
                    delay = self.INITIAL_RETRY_DELAY * (2 ** attempt)
                    retry_msg = (
                        f"OpenRouter server error (attempt {attempt + 1}/{self.MAX_RETRIES}): {error_msg}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    logger.warning(retry_msg)
                    console.print(f"[bold red]⚠️  {retry_msg}[/bold red]")
                    await asyncio.sleep(delay)
                    last_error = RuntimeError(f"OpenRouter API error: {error_msg}")
                    continue
                
                raise RuntimeError(f"OpenRouter API error: {error_msg}") from e
                
            except httpx.ConnectError as e:
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.INITIAL_RETRY_DELAY * (2 ** attempt)
                    retry_msg = (
                        f"OpenRouter connection error (attempt {attempt + 1}/{self.MAX_RETRIES}). "
                        f"Retrying in {delay:.1f}s..."
                    )
                    logger.warning(retry_msg)
                    console.print(f"[bold red]⚠️  {retry_msg}[/bold red]")
                    await asyncio.sleep(delay)
                    last_error = e
                    continue
                raise RuntimeError("Cannot connect to OpenRouter API. Check your internet connection.")
                
            except httpx.ReadTimeout:
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.INITIAL_RETRY_DELAY * (2 ** attempt)
                    retry_msg = (
                        f"OpenRouter timeout (attempt {attempt + 1}/{self.MAX_RETRIES}). "
                        f"Retrying in {delay:.1f}s..."
                    )
                    logger.warning(retry_msg)
                    console.print(f"[bold red]⚠️  {retry_msg}[/bold red]")
                    await asyncio.sleep(delay)
                    continue
                return ""
        
        # All retries exhausted
        if last_error:
            raise last_error
        return ""

    async def close(self):
        """Закрыть HTTP клиент."""
        await self.client.aclose()

