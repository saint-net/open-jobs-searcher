"""Поисковик вакансий на StepStone.de (Германия)."""

import logging
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from src.models import Job
from src.searchers.base import BaseSearcher

logger = logging.getLogger(__name__)


class StepStoneSearcher(BaseSearcher):
    """Поисковик вакансий StepStone.de (Германия)."""

    name = "stepstone.de"
    BASE_URL = "https://www.stepstone.de"

    # Немецкие города для поиска
    KNOWN_LOCATIONS = {
        "berlin": "berlin",
        "берлин": "berlin",
        "munich": "muenchen",
        "münchen": "muenchen",
        "мюнхен": "muenchen",
        "frankfurt": "frankfurt-am-main",
        "франкфурт": "frankfurt-am-main",
        "hamburg": "hamburg",
        "гамбург": "hamburg",
        "cologne": "koeln",
        "köln": "koeln",
        "кёльн": "koeln",
        "düsseldorf": "duesseldorf",
        "дюссельдорф": "duesseldorf",
        "stuttgart": "stuttgart",
        "штутгарт": "stuttgart",
        "dortmund": "dortmund",
        "essen": "essen",
        "leipzig": "leipzig",
        "bremen": "bremen",
        "dresden": "dresden",
        "hannover": "hannover",
        "nuremberg": "nuernberg",
        "nürnberg": "nuernberg",
    }

    def __init__(self):
        self.client = httpx.AsyncClient(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
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
        Поиск вакансий на StepStone.de.
        
        Args:
            keywords: Ключевые слова для поиска
            location: Город (на немецком или английском)
            experience: Не используется (StepStone не фильтрует по опыту в URL)
            salary_from: Не используется
            page: Номер страницы (0-based)
            per_page: Не используется (StepStone возвращает ~25 вакансий на страницу)
        """
        # Нормализуем location для URL
        location_slug = self._normalize_location(location) if location else None
        
        # Формируем URL
        keywords_slug = self._slugify(keywords)
        if location_slug:
            url = f"{self.BASE_URL}/jobs/{keywords_slug}/in-{location_slug}"
        else:
            url = f"{self.BASE_URL}/jobs/{keywords_slug}"
        
        # Добавляем страницу если > 0
        if page > 0:
            url += f"?page={page + 1}"  # StepStone использует 1-based pages
        
        logger.debug(f"StepStone URL: {url}")
        
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            html = response.text
            
            jobs = self._parse_jobs(html, location)
            logger.info(f"StepStone: найдено {len(jobs)} вакансий")
            return jobs
            
        except httpx.HTTPStatusError as e:
            logger.error(f"StepStone HTTP error: {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"StepStone error: {e}")
            return []

    def _normalize_location(self, location: str) -> str:
        """Нормализовать название города для URL."""
        location_lower = location.lower().strip()
        
        # Проверяем известные города
        if location_lower in self.KNOWN_LOCATIONS:
            return self.KNOWN_LOCATIONS[location_lower]
        
        # Пытаемся автоматически преобразовать
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

    def _parse_jobs(self, html: str, location: Optional[str]) -> list[Job]:
        """Парсинг вакансий из HTML."""
        soup = BeautifulSoup(html, 'lxml')
        jobs = []
        
        # StepStone использует data-at атрибуты для job cards
        # Ищем статьи с вакансиями
        job_cards = soup.find_all('article', {'data-at': 'job-item'})
        
        if not job_cards:
            # Альтернативный селектор - ищем по классам
            job_cards = soup.find_all('article', class_=re.compile(r'res-'))
        
        if not job_cards:
            # Ещё один вариант - ищем ссылки на вакансии
            job_links = soup.find_all('a', href=re.compile(r'/stellenangebote--'))
            for idx, link in enumerate(job_links[:25]):  # Лимит 25
                title = link.get_text(strip=True)
                if title and len(title) > 5:
                    job_url = link.get('href', '')
                    if not job_url.startswith('http'):
                        job_url = f"{self.BASE_URL}{job_url}"
                    
                    jobs.append(Job(
                        id=f"stepstone-{idx}",
                        title=title,
                        company="Unknown",
                        location=location or "Germany",
                        url=job_url,
                        source=self.name,
                    ))
            return jobs
        
        for idx, card in enumerate(job_cards):
            try:
                job = self._parse_job_card(card, idx, location)
                if job:
                    jobs.append(job)
            except Exception as e:
                logger.debug(f"Error parsing job card: {e}")
                continue
        
        return jobs

    def _parse_job_card(self, card, idx: int, default_location: Optional[str]) -> Optional[Job]:
        """Парсинг одной карточки вакансии."""
        # Ищем заголовок
        title_elem = card.find(['h2', 'h3', 'a'], {'data-at': 'job-item-title'})
        if not title_elem:
            title_elem = card.find(['h2', 'h3'])
        
        if not title_elem:
            return None
        
        title = title_elem.get_text(strip=True)
        if not title:
            return None
        
        # Ищем URL
        link = card.find('a', href=True)
        job_url = link.get('href', '') if link else ''
        if job_url and not job_url.startswith('http'):
            job_url = f"{self.BASE_URL}{job_url}"
        
        # Ищем компанию
        company_elem = card.find(['span', 'a'], {'data-at': 'job-item-company-name'})
        if not company_elem:
            company_elem = card.find(class_=re.compile(r'company|employer', re.I))
        company = company_elem.get_text(strip=True) if company_elem else "Unknown"
        
        # Ищем локацию
        location_elem = card.find(['span', 'div'], {'data-at': 'job-item-location'})
        if not location_elem:
            location_elem = card.find(class_=re.compile(r'location', re.I))
        job_location = location_elem.get_text(strip=True) if location_elem else (default_location or "Germany")
        
        # Извлекаем ID из URL или генерируем
        job_id = f"stepstone-{idx}"
        if job_url:
            match = re.search(r'--(\d+)(?:\?|$)', job_url)
            if match:
                job_id = f"stepstone-{match.group(1)}"
        
        return Job(
            id=job_id,
            title=title,
            company=company,
            location=job_location,
            url=job_url,
            source=self.name,
        )

    async def get_job_details(self, job_id: str) -> Optional[Job]:
        """Получить детальную информацию о вакансии."""
        # StepStone требует полный URL для деталей
        return None

    async def close(self):
        """Закрыть HTTP клиент."""
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        