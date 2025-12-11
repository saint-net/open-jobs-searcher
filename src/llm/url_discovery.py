"""URL discovery logic for LLM providers - finding careers pages, job boards, etc."""

import logging
from typing import Callable, Awaitable, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.constants import MAX_URLS_FOR_LLM

logger = logging.getLogger(__name__)

# Keywords for filtering relevant career URLs
CAREER_KEYWORDS = ['career', 'job', 'karriere', 'stellen', 'vacanc', 'hiring', 'join', 'work']


class LLMUrlDiscovery:
    """Handles URL discovery using LLM - finding careers pages, job boards, etc."""
    
    def __init__(
        self,
        complete_fn: Callable[[str], Awaitable[str]],
        clean_html_fn: Callable[[str], str],
        extract_url_fn: Callable[[str, str], Optional[str]],
        extract_json_fn: Callable[[str], list | dict],
    ):
        """
        Initialize URL discovery with LLM provider functions.
        
        Args:
            complete_fn: Async function to call LLM (prompt -> response)
            clean_html_fn: Function to clean HTML
            extract_url_fn: Function to extract URL from LLM response
            extract_json_fn: Function to extract JSON from LLM response
        """
        self._complete = complete_fn
        self._clean_html = clean_html_fn
        self._extract_url = extract_url_fn
        self._extract_json = extract_json_fn

    async def find_careers_url(
        self, html: str, base_url: str, sitemap_urls: list[str] = None
    ) -> Optional[str]:
        """
        Найти ссылку на страницу с вакансиями.

        Args:
            html: HTML содержимое главной страницы
            base_url: Базовый URL сайта
            sitemap_urls: Список URL из sitemap.xml (опционально)

        Returns:
            URL страницы с вакансиями или None
        """
        from .prompts import FIND_CAREERS_PAGE_PROMPT

        clean_html = self._clean_html(html)
        html_truncated = clean_html[:40000] if len(clean_html) > 40000 else clean_html
        
        # Форматируем sitemap URLs
        sitemap_text = "No sitemap available"
        if sitemap_urls:
            relevant_urls = [
                url for url in sitemap_urls 
                if any(kw in url.lower() for kw in CAREER_KEYWORDS)
            ]
            
            if relevant_urls:
                urls_to_show = relevant_urls[:50]
                logger.debug(f"Found {len(relevant_urls)} career-related URLs in sitemap")
            else:
                urls_to_show = sitemap_urls[:100]
            
            sitemap_text = "\n".join(urls_to_show)
        
        logger.debug(
            f"Searching for careers URL: {len(html_truncated)} chars HTML + "
            f"{len(sitemap_urls or [])} sitemap URLs"
        )

        prompt = FIND_CAREERS_PAGE_PROMPT.format(
            base_url=base_url,
            html=html_truncated,
            sitemap_urls=sitemap_text,
        )

        response = await self._complete(prompt)
        url = self._extract_url(response, base_url)
        
        if url and url != "NOT_FOUND":
            logger.debug(f"LLM found careers URL: {url}")
        else:
            logger.debug("LLM did not find careers URL")
            
        return url

    async def find_job_board_url(self, html: str, url: str) -> Optional[str]:
        """
        Найти ссылку на job board на странице карьеры.
        
        Многие компании имеют landing page про работу, а реальные вакансии
        на внешнем job board (greenhouse, lever, bmwgroup.jobs и т.д.)

        Args:
            html: HTML содержимое страницы карьеры
            url: URL текущей страницы

        Returns:
            URL job board или None если не найден / текущая страница и есть job board
        """
        from .prompts import FIND_JOB_BOARD_PROMPT
        
        links = extract_links_from_html(html, url)
        
        if not links:
            logger.debug("No links found in HTML")
            return None
        
        links_text = "\n".join(links[:200])  # Max 200 links
        
        logger.debug(f"Searching for job board URL among {len(links)} links on {url}")

        prompt = FIND_JOB_BOARD_PROMPT.format(
            url=url,
            html=links_text,
        )

        response = await self._complete(prompt)
        response_clean = response.strip()
        
        if "CURRENT_PAGE" in response_clean:
            logger.debug("Current page is the job board")
            return None
        
        if "NOT_FOUND" in response_clean:
            logger.debug("No job board URL found")
            return None
        
        job_board_url = self._extract_url(response, url)
        
        if job_board_url and job_board_url != url:
            logger.debug(f"Found job board URL: {job_board_url}")
            return job_board_url
        
        return None

    async def find_careers_url_from_sitemap(self, urls: list[str], base_url: str) -> Optional[str]:
        """
        Найти страницу вакансий среди URL из sitemap.xml с помощью LLM.

        Args:
            urls: Список URL из sitemap
            base_url: Базовый URL сайта

        Returns:
            URL страницы с вакансиями или None
        """
        from .prompts import FIND_CAREERS_FROM_SITEMAP_PROMPT

        urls_limited = urls[:MAX_URLS_FOR_LLM]
        urls_text = "\n".join(urls_limited)

        prompt = FIND_CAREERS_FROM_SITEMAP_PROMPT.format(
            base_url=base_url,
            urls=urls_text,
        )

        response = await self._complete(prompt)
        return self._extract_url(response, base_url)

    async def find_job_urls(self, html: str, url: str) -> list[str]:
        """
        Найти URL'ы отдельных вакансий на странице карьеры с помощью LLM.
        
        Этот метод полезен когда:
        - Страница карьеры загружается через JS (SPA)
        - Schema.org отсутствует
        - Нужен список ссылок для дальнейшего парсинга каждой вакансии

        Args:
            html: HTML содержимое страницы карьеры
            url: URL страницы

        Returns:
            Список URL'ов отдельных вакансий
        """
        from .prompts import FIND_JOB_URLS_PROMPT

        clean_html = self._clean_html(html)
        html_truncated = clean_html[:80000] if len(clean_html) > 80000 else clean_html

        prompt = FIND_JOB_URLS_PROMPT.format(
            url=url,
            html=html_truncated,
        )

        response = await self._complete(prompt)
        result = self._extract_json(response)
        
        if not isinstance(result, list):
            logger.warning(f"LLM returned non-list for job URLs: {type(result)}")
            return []
        
        # Валидируем и нормализуем URL'ы
        valid_urls = []
        seen = set()
        
        for item in result:
            if not isinstance(item, str) or not item.strip():
                continue
            
            job_url = item.strip()
            
            # Конвертируем относительные URL в абсолютные
            if job_url.startswith('/'):
                job_url = urljoin(url, job_url)
            elif not job_url.startswith(('http://', 'https://')):
                job_url = urljoin(url, job_url)
            
            # Дедупликация
            if job_url not in seen:
                seen.add(job_url)
                valid_urls.append(job_url)
        
        logger.debug(f"LLM found {len(valid_urls)} unique job URLs on {url}")
        return valid_urls


def extract_links_from_html(html: str, base_url: str) -> list[str]:
    """Извлечь все ссылки из HTML."""
    soup = BeautifulSoup(html, 'lxml')
    links = []
    seen = set()
    
    for a in soup.find_all('a', href=True):
        href = a.get('href', '').strip()
        if not href or href.startswith('#') or href.startswith('javascript:'):
            continue
        
        full_url = urljoin(base_url, href)
        
        if full_url not in seen:
            seen.add(full_url)
            link_text = a.get_text(strip=True)[:50]
            if link_text:
                links.append(f"{full_url} [{link_text}]")
            else:
                links.append(full_url)
    
    return links

