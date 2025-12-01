"""Поисковик вакансий на HeadHunter."""

from typing import Optional
from datetime import datetime

import httpx

from src.models import Job
from src.searchers.base import BaseSearcher


class HeadHunterSearcher(BaseSearcher):
    """Поисковик вакансий HeadHunter (hh.ru)."""

    name = "hh.ru"
    BASE_URL = "https://api.hh.ru"

    # Маппинг опыта
    EXPERIENCE_MAP = {
        "no_experience": "noExperience",
        "1-3": "between1And3",
        "3-6": "between3And6",
        "6+": "moreThan6",
    }

    # Популярные города (ID регионов HH)
    KNOWN_AREAS = {
        "москва": "1",
        "moscow": "1",
        "санкт-петербург": "2",
        "saint-petersburg": "2",
        "spb": "2",
        "новосибирск": "4",
        "екатеринбург": "3",
        "казань": "88",
        "нижний новгород": "66",
        "россия": "113",
        "russia": "113",
    }

    def __init__(self):
        self.client = httpx.AsyncClient(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
            timeout=30.0,
        )

    async def search(
        self,
        keywords: str,
        location: Optional[str] = None,
        experience: Optional[str] = None,
        salary_from: Optional[int] = None,
        page: int = 0,
        per_page: int = 20,
    ) -> list[Job]:
        """Поиск вакансий на HeadHunter."""
        params: dict[str, str] = {
            "text": keywords,
            "page": str(page),
            "per_page": str(min(per_page, 100)),  # HH ограничивает до 100
        }

        # Добавляем локацию (area)
        if location:
            area_id = await self._get_area_id(location)
            if area_id:
                params["area"] = area_id

        # Добавляем опыт
        if experience and experience in self.EXPERIENCE_MAP:
            params["experience"] = self.EXPERIENCE_MAP[experience]

        # Добавляем зарплату
        if salary_from:
            params["salary"] = str(salary_from)
            params["only_with_salary"] = "true"

        response = await self.client.get(f"{self.BASE_URL}/vacancies", params=params)
        response.raise_for_status()
        data = response.json()

        jobs = []
        for item in data.get("items", []):
            job = self._parse_vacancy(item)
            jobs.append(job)

        return jobs

    async def get_job_details(self, job_id: str) -> Optional[Job]:
        """Получить детальную информацию о вакансии."""
        try:
            response = await self.client.get(f"{self.BASE_URL}/vacancies/{job_id}")
            response.raise_for_status()
            data = response.json()
            return self._parse_vacancy(data, detailed=True)
        except httpx.HTTPStatusError:
            return None

    async def _get_area_id(self, location: str) -> Optional[str]:
        """Получить ID региона по названию."""
        # Сначала проверяем известные города
        location_lower = location.lower().strip()
        if location_lower in self.KNOWN_AREAS:
            return self.KNOWN_AREAS[location_lower]

        # Пробуем найти через API
        try:
            response = await self.client.get(
                f"{self.BASE_URL}/suggests/area_leaves",
                params={"text": location},
            )
            response.raise_for_status()
            data = response.json()

            if data.get("items"):
                return data["items"][0]["id"]
        except httpx.HTTPStatusError:
            pass

        return None

    def _parse_vacancy(self, data: dict, detailed: bool = False) -> Job:
        """Парсинг данных вакансии."""
        salary = data.get("salary") or {}

        # Парсим дату публикации
        published_at = None
        if data.get("published_at"):
            try:
                published_at = datetime.fromisoformat(
                    data["published_at"].replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass

        # Извлекаем навыки
        skills = []
        if detailed and data.get("key_skills"):
            skills = [skill["name"] for skill in data["key_skills"]]

        return Job(
            id=str(data["id"]),
            title=data["name"],
            company=data.get("employer", {}).get("name", "Unknown"),
            location=data.get("area", {}).get("name", ""),
            url=data["alternate_url"],
            source=self.name,
            description=data.get("description") if detailed else None,
            salary_from=salary.get("from"),
            salary_to=salary.get("to"),
            salary_currency=salary.get("currency"),
            experience=data.get("experience", {}).get("name"),
            employment_type=data.get("employment", {}).get("name"),
            skills=skills,
            published_at=published_at,
        )

    async def close(self):
        """Закрыть HTTP клиент."""
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

