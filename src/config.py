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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

