"""Универсальный поисковик вакансий на сайтах компаний."""

from typing import Optional
from urllib.parse import urljoin, urlparse
import re

import httpx
from bs4 import BeautifulSoup

from src.models import Job
from src.searchers.base import BaseSearcher
from src.llm.base import BaseLLMProvider


class WebsiteSearcher(BaseSearcher):
    """Универсальный поисковик вакансий с использованием LLM."""

    name = "website"

    # Типичные паттерны URL для страниц с вакансиями
    CAREER_PATTERNS = [
        r'/career[s]?',
        r'/job[s]?',
        r'/vacanc(?:y|ies)',
        r'/opening[s]?',
        r'/work',
        r'/join',
        r'/hiring',
        r'/positions',
        r'/вакансии',
        r'/карьера',
        r'/работа',
    ]

    def __init__(self, llm_provider: BaseLLMProvider):
        """
        Инициализация поисковика.

        Args:
            llm_provider: Провайдер LLM для анализа страниц
        """
        self.llm = llm_provider
        self.client = httpx.AsyncClient(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            },
            follow_redirects=True,
            timeout=30.0,
        )

    async def search(
        self,
        keywords: str,  # В данном случае это URL сайта
        location: Optional[str] = None,
        experience: Optional[str] = None,
        salary_from: Optional[int] = None,
        page: int = 0,
        per_page: int = 20,
    ) -> list[Job]:
        """
        Поиск вакансий на сайте компании.

        Args:
            keywords: URL главной страницы сайта компании
            location: Не используется (для совместимости)
            experience: Не используется
            salary_from: Не используется
            page: Не используется
            per_page: Не используется

        Returns:
            Список найденных вакансий
        """
        url = keywords  # URL передаётся как keywords для совместимости
        
        # Нормализуем URL
        if not url.startswith(('http://', 'https://')):
            url = f'https://{url}'

        # 1. Загружаем главную страницу
        html = await self._fetch(url)
        if not html:
            return []

        # 2. Пробуем найти страницу вакансий эвристически
        careers_url = self._find_careers_url_heuristic(html, url)

        # 3. Если не нашли - используем LLM
        if not careers_url:
            careers_url = await self.llm.find_careers_url(html, url)

        if not careers_url or careers_url == "NOT_FOUND":
            return []

        # 4. Загружаем страницу вакансий
        careers_html = await self._fetch(careers_url)
        if not careers_html:
            # Пробуем альтернативные URL
            alt_urls = self._generate_alternative_urls(url)
            for alt_url in alt_urls:
                careers_html = await self._fetch(alt_url)
                if careers_html:
                    careers_url = alt_url
                    break
            
            if not careers_html:
                return []

        # 5. Извлекаем вакансии с помощью LLM
        jobs_data = await self.llm.extract_jobs(careers_html, careers_url)

        # 6. Преобразуем в модели Job
        jobs = []
        company_name = self._extract_company_name(url)
        
        for idx, job_data in enumerate(jobs_data):
            job = Job(
                id=f"web-{urlparse(url).netloc}-{idx}",
                title=job_data.get("title", "Unknown Position"),
                company=company_name,
                location=job_data.get("location", "Unknown"),
                url=job_data.get("url", careers_url),
                source=f"website:{urlparse(url).netloc}",
                description=job_data.get("description"),
            )
            jobs.append(job)

        return jobs

    async def get_job_details(self, job_id: str) -> Optional[Job]:
        """Получить детали вакансии (не реализовано для website)."""
        return None

    async def _fetch(self, url: str) -> Optional[str]:
        """Загрузить HTML страницы."""
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.text
        except httpx.HTTPStatusError as e:
            print(f"HTTP error {e.response.status_code} for {url}")
            return None
        except httpx.RequestError as e:
            print(f"Request error for {url}: {e}")
            return None

    def _find_careers_url_heuristic(self, html: str, base_url: str) -> Optional[str]:
        """Эвристический поиск ссылки на страницу вакансий."""
        soup = BeautifulSoup(html, 'lxml')
        
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            text = link.get_text(strip=True).lower()
            
            # Проверяем URL
            for pattern in self.CAREER_PATTERNS:
                if re.search(pattern, href, re.IGNORECASE):
                    return urljoin(base_url, href)
            
            # Проверяем текст ссылки
            career_keywords = [
                'career', 'careers', 'jobs', 'vacancies', 'openings',
                'join us', 'work with us', 'we\'re hiring',
                'вакансии', 'карьера', 'работа у нас', 'присоединяйся',
            ]
            for keyword in career_keywords:
                if keyword in text:
                    return urljoin(base_url, href)
        
        return None

    def _extract_company_name(self, url: str) -> str:
        """Извлечь название компании из URL."""
        parsed = urlparse(url)
        domain = parsed.netloc
        
        # Убираем www и общие домены
        name = domain.replace('www.', '')
        name = re.sub(r'\.(com|ru|org|net|io|co|tech)$', '', name)
        
        # Капитализируем
        return name.title()

    def _generate_alternative_urls(self, base_url: str) -> list[str]:
        """Генерировать альтернативные URL для страницы вакансий."""
        base = base_url.rstrip('/')
        alternatives = [
            f"{base}/careers",
            f"{base}/jobs",
            f"{base}/vacancies",
            f"{base}/career",
            f"{base}/join",
            f"{base}/team",
            f"{base}/about/careers",
            f"{base}/en/careers",
            f"{base}/ru/careers",
        ]
        return alternatives

    async def close(self):
        """Закрыть HTTP клиент и LLM провайдер."""
        await self.client.aclose()
        await self.llm.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

