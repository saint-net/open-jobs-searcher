"""Поисковик вакансий на Karriere.at (Австрия)."""

import logging
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from src.models import Job
from src.searchers.base import BaseSearcher

logger = logging.getLogger(__name__)


class KarriereATSearcher(BaseSearcher):
    """Поисковик вакансий Karriere.at (Австрия)."""

    name = "karriere.at"
    BASE_URL = "https://www.karriere.at"

    # Австрийские города для поиска
    KNOWN_LOCATIONS = {
        "vienna": "wien",
        "wien": "wien",
        "вена": "wien",
        "graz": "graz",
        "грац": "graz",
        "linz": "linz",
        "линц": "linz",
        "salzburg": "salzburg",
        "зальцбург": "salzburg",
        "innsbruck": "innsbruck",
        "инсбрук": "innsbruck",
        "klagenfurt": "klagenfurt",
        "клагенфурт": "klagenfurt",
        "austria": "oesterreich",
        "österreich": "oesterreich",
        "австрия": "oesterreich",
    }

    def __init__(self):
        self.client = httpx.AsyncClient(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "de-AT,de;q=0.9,en;q=0.8",
            },
            follow_redirects=True,
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
        """
        Поиск вакансий на Karriere.at.
        
        Args:
            keywords: Ключевые слова для поиска
            location: Город (на немецком или английском)
            experience: Не используется
            salary_from: Не используется (но парсится из результатов)
            page: Номер страницы (0-based)
            per_page: Не используется
        """
        # Нормализуем location для URL
        location_slug = self._normalize_location(location) if location else None
        
        # Формируем URL
        keywords_slug = self._slugify(keywords)
        if location_slug:
            url = f"{self.BASE_URL}/jobs/{keywords_slug}/{location_slug}"
        else:
            url = f"{self.BASE_URL}/jobs/{keywords_slug}"
        
        # Добавляем страницу если > 0
        if page > 0:
            url += f"?page={page + 1}"  # 1-based pages
        
        logger.debug(f"Karriere.at URL: {url}")
        
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            html = response.text
            
            jobs = self._parse_jobs(html, location)
            logger.info(f"Karriere.at: найдено {len(jobs)} вакансий")
            return jobs
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Karriere.at HTTP error: {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"Karriere.at error: {e}")
            return []

    def _normalize_location(self, location: str) -> str:
        """Нормализовать название города для URL."""
        location_lower = location.lower().strip()
        
        if location_lower in self.KNOWN_LOCATIONS:
            return self.KNOWN_LOCATIONS[location_lower]
        
        return self._slugify(location)

    def _slugify(self, text: str) -> str:
        """Преобразовать текст в URL-slug."""
        # Заменяем немецкие умлауты
        replacements = {
            'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss',
            'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue',
        }
        result = text.lower()
        for char, replacement in replacements.items():
            result = result.replace(char, replacement)
        
        # Заменяем пробелы и спецсимволы на дефисы
        result = re.sub(r'[^a-z0-9]+', '-', result)
        result = result.strip('-')
        
        return result

    def _parse_jobs(self, html: str, default_location: Optional[str]) -> list[Job]:
        """Парсинг вакансий из HTML."""
        soup = BeautifulSoup(html, 'lxml')
        jobs = []
        
        # Karriere.at использует ссылки вида /jobs/7652013 (числовой ID)
        # Ищем все ссылки на конкретные вакансии
        all_links = soup.find_all('a', href=True)
        seen_urls = set()
        
        for link in all_links:
            href = link.get('href', '')
            
            # Проверяем что это ссылка на конкретную вакансию (числовой ID в конце)
            # URL pattern: /jobs/7652013 или https://www.karriere.at/jobs/7652013
            match = re.search(r'/jobs/(\d+)(?:\?|$)', href)
            if not match:
                continue
            
            job_id = match.group(1)
            if job_id in seen_urls:
                continue
            seen_urls.add(job_id)
            
            title = link.get_text(strip=True)
            if not title or len(title) < 5:
                continue
            
            # Пропускаем если это не похоже на название вакансии
            # (например, города, теги типа "Wien", "Vollzeit")
            if title.lower() in self.KNOWN_LOCATIONS or len(title) < 10:
                continue
            
            job_url = href if href.startswith('http') else f"{self.BASE_URL}{href}"
            
            # Пытаемся найти компанию - обычно в родительском элементе
            company = "Unknown"
            parent = link.find_parent(['div', 'li', 'article'])
            if parent:
                # Ищем ссылку на компанию
                company_link = parent.find('a', href=re.compile(r'/firma/'))
                if company_link:
                    company = company_link.get_text(strip=True)
                else:
                    # Ищем элемент с классом company
                    company_elem = parent.find(class_=re.compile(r'company|firma|employer', re.I))
                    if company_elem:
                        company = company_elem.get_text(strip=True)
            
            # Пытаемся найти локацию
            job_location = default_location or "Austria"
            if parent:
                location_elem = parent.find(class_=re.compile(r'location|ort|city', re.I))
                if location_elem:
                    job_location = location_elem.get_text(strip=True)
            
            jobs.append(Job(
                id=f"karriere-{job_id}",
                title=title,
                company=company,
                location=job_location,
                url=job_url,
                source=self.name,
            ))
        
        return jobs[:25]  # Лимит

    async def get_job_details(self, job_id: str) -> Optional[Job]:
        """Получить детальную информацию о вакансии."""
        return None

    async def close(self):
        """Закрыть HTTP клиент."""
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

