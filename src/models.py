"""Модели данных для вакансий."""

from datetime import datetime
from typing import Optional, TypedDict

from pydantic import BaseModel, Field, computed_field


class JobDict(TypedDict, total=False):
    """TypedDict для промежуточного формата данных вакансии.
    
    Используется LLM и парсерами до преобразования в Pydantic Job.
    """
    title: str
    company: str
    location: str
    url: str
    department: Optional[str]
    description: Optional[str]
    salary_from: Optional[int]
    salary_to: Optional[int]
    salary_currency: Optional[str]
    experience: Optional[str]
    employment_type: Optional[str]


class JobExtractionResult(TypedDict):
    """Result of job extraction from HTML."""
    jobs: list[JobDict]
    next_page_url: Optional[str]


class Job(BaseModel):
    """Модель вакансии с валидацией через Pydantic."""

    id: str
    title: str
    company: str
    location: str
    url: str
    source: str
    title_en: Optional[str] = None
    description: Optional[str] = None
    salary_from: Optional[int] = Field(default=None, ge=0)
    salary_to: Optional[int] = Field(default=None, ge=0)
    salary_currency: Optional[str] = None
    experience: Optional[str] = None
    employment_type: Optional[str] = None
    skills: list[str] = Field(default_factory=list)
    published_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)

    model_config = {
        "frozen": False,  # Allow mutation
        "extra": "ignore",  # Ignore extra fields during parsing
    }

    def to_dict(self) -> dict:
        """Конвертация в словарь (deprecated, use model_dump())."""
        return self.model_dump(mode="json")

    @computed_field
    @property
    def salary_display(self) -> str:
        """Форматированное отображение зарплаты."""
        if not self.salary_from and not self.salary_to:
            return "Не указана"

        currency = self.salary_currency or "RUB"

        if self.salary_from and self.salary_to:
            return f"{self.salary_from:,} - {self.salary_to:,} {currency}"
        elif self.salary_from:
            return f"от {self.salary_from:,} {currency}"
        else:
            return f"до {self.salary_to:,} {currency}"



