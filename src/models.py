"""Модели данных для вакансий."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Job:
    """Модель вакансии."""

    id: str
    title: str
    company: str
    location: str
    url: str
    source: str
    title_en: Optional[str] = None
    description: Optional[str] = None
    salary_from: Optional[int] = None
    salary_to: Optional[int] = None
    salary_currency: Optional[str] = None
    experience: Optional[str] = None
    employment_type: Optional[str] = None
    skills: list[str] = field(default_factory=list)
    published_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Конвертация в словарь."""
        return {
            "id": self.id,
            "title": self.title,
            "title_en": self.title_en,
            "company": self.company,
            "location": self.location,
            "url": self.url,
            "source": self.source,
            "description": self.description,
            "salary_from": self.salary_from,
            "salary_to": self.salary_to,
            "salary_currency": self.salary_currency,
            "experience": self.experience,
            "employment_type": self.employment_type,
            "skills": self.skills,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "created_at": self.created_at.isoformat(),
        }

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



