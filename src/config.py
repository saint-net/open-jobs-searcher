"""Конфигурация приложения."""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Настройки приложения."""

    # Поиск
    default_location: str = Field(default="Moscow", description="Локация по умолчанию")
    default_keywords: str = Field(
        default="Python Developer", description="Ключевые слова по умолчанию"
    )

    # Вывод
    output_format: str = Field(default="json", description="Формат вывода (json/csv)")
    output_dir: str = Field(default="./data", description="Директория для результатов")

    # LLM настройки
    llm_provider: str = Field(default="ollama", description="LLM провайдер")
    llm_model: str = Field(default="gpt-oss:20b", description="Модель LLM")
    ollama_url: str = Field(
        default="http://localhost:11434", description="URL Ollama сервера"
    )

    # OpenAI (для будущего использования)
    openai_api_key: str = Field(default="", description="OpenAI API ключ")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

