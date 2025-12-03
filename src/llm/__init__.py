"""Модуль для работы с LLM провайдерами."""

from .base import BaseLLMProvider
from .ollama import OllamaProvider


def get_llm_provider(provider: str = "ollama", **kwargs) -> BaseLLMProvider:
    """
    Фабрика для получения LLM провайдера.

    Args:
        provider: Название провайдера (ollama, openai, claude)
        **kwargs: Дополнительные параметры для провайдера

    Returns:
        Экземпляр LLM провайдера
    """
    match provider.lower():
        case "ollama":
            return OllamaProvider(**kwargs)
        case "openai":
            raise NotImplementedError("OpenAI provider coming soon")
        case "claude" | "anthropic":
            raise NotImplementedError("Claude provider coming soon")
        case _:
            raise ValueError(f"Unknown LLM provider: {provider}")


__all__ = ["BaseLLMProvider", "OllamaProvider", "get_llm_provider"]





