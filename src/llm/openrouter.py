"""OpenRouter LLM провайдер."""

from typing import Optional

import httpx

from .base import BaseLLMProvider


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

    def __init__(
        self,
        api_key: str,
        model: str = "openai/gpt-oss-20b",
        timeout: float = 300.0,
    ):
        """
        Инициализация OpenRouter провайдера.

        Args:
            api_key: API ключ OpenRouter
            model: Название модели (например, openai/gpt-oss-20b)
            timeout: Таймаут запросов в секундах
        """
        if not api_key:
            raise ValueError("OpenRouter API key is required")
        
        self.api_key = api_key
        self.model = model
        self.config = self.MODEL_CONFIGS.get(model, self.DEFAULT_CONFIG)
        self.client = httpx.AsyncClient(timeout=timeout)

    async def complete(self, prompt: str, system: Optional[str] = None) -> str:
        """Generate response via OpenRouter API."""
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

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/open-jobs-searcher",
            "X-Title": "Open Jobs Searcher",
        }

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
                raise RuntimeError(f"OpenRouter API error: {error_msg}")
            
            # Извлекаем ответ
            choices = data.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                return message.get("content", "")
            
            return ""
        except httpx.HTTPStatusError as e:
            error_body = e.response.text
            raise RuntimeError(f"OpenRouter API error: {e.response.status_code} - {error_body}") from e
        except httpx.ConnectError:
            raise RuntimeError("Cannot connect to OpenRouter API. Check your internet connection.")
        except httpx.ReadTimeout:
            return ""

    async def close(self):
        """Закрыть HTTP клиент."""
        await self.client.aclose()

