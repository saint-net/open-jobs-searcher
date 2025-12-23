"""Конфигурация приложения."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Поиск
    default_location: str = Field(default="Moscow", description="Локация по умолчанию")
    default_keywords: str = Field(
        default="Python Developer", description="Ключевые слова по умолчанию"
    )

    # Вывод
    output_format: str = Field(default="json", description="Формат вывода (json/csv)")
    output_dir: str = Field(default="./data", description="Директория для результатов")

    # LLM настройки
    llm_provider: str = Field(default="openrouter", description="LLM провайдер")
    llm_model: str = Field(default="openai/gpt-4o-mini", description="Модель LLM")
    ollama_url: str = Field(
        default="http://localhost:11434", description="URL Ollama сервера"
    )

    # OpenRouter provider routing
    # https://openrouter.ai/docs/features/provider-routing
    # Для gpt-4o-mini OpenRouter автоматически выбирает лучших провайдеров
    # Для других моделей можно указать провайдеров вручную
    openrouter_provider: str = Field(
        default="", description="Конкретный провайдер OpenRouter (например: 'azure')"
    )
    openrouter_provider_order: str = Field(
        default="",
        description="Список провайдеров через запятую в порядке приоритета (например: 'azure,openai')"
    )
    openrouter_allow_fallbacks: bool = Field(
        default=True, description="Разрешать fallback на другие провайдеры при ошибках"
    )
    openrouter_require_parameters: str = Field(
        default="",
        description="Требуемые параметры через запятую (например: 'json_schema,tools')"
    )

    # OpenAI (для будущего использования)
    openai_api_key: str = Field(default="", description="OpenAI API ключ")

    # OpenRouter
    openrouter_api_key: str = Field(default="", description="OpenRouter API ключ")


settings = Settings()

