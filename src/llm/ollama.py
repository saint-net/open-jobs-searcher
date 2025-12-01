"""Ollama LLM провайдер."""

from typing import Optional

import httpx

from .base import BaseLLMProvider


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

    async def complete(self, prompt: str, system: Optional[str] = None) -> str:
        """Генерация ответа через Ollama API."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,  # Низкая температура для более точных ответов
                "num_predict": 4000,  # Увеличен лимит токенов
                "num_ctx": 8192,  # Размер контекста
            },
        }

        if system:
            payload["system"] = system

        try:
            response = await self.client.post(
                f"{self.base_url}/api/generate",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            # Проверяем на ошибки в ответе
            if data.get("error"):
                return ""
            
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

    async def close(self):
        """Закрыть HTTP клиент."""
        await self.client.aclose()

