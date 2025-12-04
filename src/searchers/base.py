"""Базовый класс для поисковиков вакансий."""

from abc import ABC, abstractmethod
from typing import Optional

from src.models import Job


class BaseSearcher(ABC):
    """Абстрактный базовый класс для поисковиков."""

    name: str = "base"

    @abstractmethod
    async def search(
        self,
        keywords: str,
        location: Optional[str] = None,
        experience: Optional[str] = None,
        salary_from: Optional[int] = None,
        page: int = 0,
        per_page: int = 20,
    ) -> list[Job]:
        """
        Поиск вакансий.

        Args:
            keywords: Ключевые слова для поиска
            location: Локация/город
            experience: Требуемый опыт
            salary_from: Минимальная зарплата
            page: Номер страницы
            per_page: Количество результатов на странице

        Returns:
            Список найденных вакансий
        """
        pass

    @abstractmethod
    async def get_job_details(self, job_id: str) -> Optional[Job]:
        """
        Получить детальную информацию о вакансии.

        Args:
            job_id: ID вакансии

        Returns:
            Детальная информация о вакансии или None
        """
        pass
