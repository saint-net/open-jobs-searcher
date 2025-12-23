"""Модуль для работы с LLM провайдерами."""

from .base import BaseLLMProvider
from .ollama import OllamaProvider
from .openrouter import OpenRouterProvider
from .cache import LLMCache, CacheNamespace

from src.config import settings


def get_llm_provider(provider: str = "ollama", **kwargs) -> BaseLLMProvider:
    """
    Фабрика для получения LLM провайдера.

    Args:
        provider: Название провайдера (ollama, openrouter, openai, claude)
        **kwargs: Дополнительные параметры для провайдера

    Returns:
        Экземпляр LLM провайдера
    """
    match provider.lower():
        case "ollama":
            return OllamaProvider(**kwargs)
        case "openrouter":
            # Используем API ключ из настроек, если не передан явно
            if "api_key" not in kwargs:
                kwargs["api_key"] = settings.openrouter_api_key
            # Provider routing настройки из конфига
            if "provider" not in kwargs and settings.openrouter_provider:
                kwargs["provider"] = settings.openrouter_provider
            if "provider_order" not in kwargs and settings.openrouter_provider_order:
                # Парсим список провайдеров из строки "azure,openai" -> ["azure", "openai"]
                kwargs["provider_order"] = [
                    p.strip() for p in settings.openrouter_provider_order.split(",") if p.strip()
                ]
            if "allow_fallbacks" not in kwargs:
                kwargs["allow_fallbacks"] = settings.openrouter_allow_fallbacks
            if "require_parameters" not in kwargs and settings.openrouter_require_parameters:
                # Парсим список параметров из строки "json_schema,tools" -> ["json_schema", "tools"]
                kwargs["require_parameters"] = [
                    p.strip() for p in settings.openrouter_require_parameters.split(",") if p.strip()
                ]
            return OpenRouterProvider(**kwargs)
        case "openai":
            raise NotImplementedError("OpenAI provider coming soon")
        case "claude" | "anthropic":
            raise NotImplementedError("Claude provider coming soon")
        case _:
            raise ValueError(f"Unknown LLM provider: {provider}")


__all__ = [
    "BaseLLMProvider", 
    "OllamaProvider", 
    "OpenRouterProvider", 
    "get_llm_provider",
    "LLMCache",
    "CacheNamespace",
]





