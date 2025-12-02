"""Base class for LLM providers."""

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    # Retry settings for job extraction
    MAX_EXTRACTION_RETRIES = 3

    @abstractmethod
    async def complete(self, prompt: str, system: Optional[str] = None) -> str:
        """
        Генерация ответа от LLM.

        Args:
            prompt: Пользовательский промпт
            system: Системный промпт (опционально)

        Returns:
            Ответ модели
        """
        pass

    async def find_careers_url(self, html: str, base_url: str) -> Optional[str]:
        """
        Найти ссылку на страницу с вакансиями.

        Args:
            html: HTML содержимое главной страницы
            base_url: Базовый URL сайта

        Returns:
            URL страницы с вакансиями или None
        """
        from .prompts import FIND_CAREERS_PAGE_PROMPT

        # Ограничиваем размер HTML для LLM
        html_truncated = html[:15000] if len(html) > 15000 else html

        prompt = FIND_CAREERS_PAGE_PROMPT.format(
            base_url=base_url,
            html=html_truncated,
        )

        response = await self.complete(prompt)
        
        # Извлекаем URL из ответа
        url = self._extract_url(response, base_url)
        return url

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

        # Ограничиваем количество URL (берём первые 500)
        urls_limited = urls[:500]
        urls_text = "\n".join(urls_limited)

        prompt = FIND_CAREERS_FROM_SITEMAP_PROMPT.format(
            base_url=base_url,
            urls=urls_text,
        )

        response = await self.complete(prompt)
        
        # Извлекаем URL из ответа
        url = self._extract_url(response, base_url)
        return url

    async def translate_job_titles(self, titles: list[str]) -> list[str]:
        """
        Translate job titles to English.

        Args:
            titles: List of job titles in any language

        Returns:
            List of translated titles in English
        """
        from .prompts import TRANSLATE_JOB_TITLES_PROMPT

        if not titles:
            return []

        titles_text = "\n".join(titles)
        prompt = TRANSLATE_JOB_TITLES_PROMPT.format(titles=titles_text)

        response = await self.complete(prompt)
        translated = self._extract_json(response)

        if isinstance(translated, list) and len(translated) == len(titles):
            return [str(t) for t in translated]
        
        # Fallback: return original titles if translation failed
        logger.warning(f"Translation failed, returning original titles")
        return titles

    async def extract_jobs(self, html: str, url: str) -> list[dict]:
        """
        Extract job listings from HTML page with retry logic.

        Args:
            html: HTML content of the careers page
            url: URL of the page

        Returns:
            List of job dictionaries
        """
        from .prompts import EXTRACT_JOBS_PROMPT
        
        # First try to find JSON data in script tags (SSR/schema.org)
        json_jobs = self._extract_json_from_scripts(html)
        if json_jobs:
            logger.debug(f"Found {len(json_jobs)} jobs from schema.org data")
            return json_jobs
        
        # Clean HTML from scripts and styles
        clean_html = self._clean_html(html)

        # Limit HTML size (80000 chars for large pages)
        html_truncated = clean_html[:80000] if len(clean_html) > 80000 else clean_html
        
        logger.debug(f"Extracting jobs from {url}, HTML size: {len(html_truncated)} chars")

        prompt = EXTRACT_JOBS_PROMPT.format(
            url=url,
            html=html_truncated,
        )

        # Retry extraction if result is empty (LLM can be inconsistent)
        for attempt in range(self.MAX_EXTRACTION_RETRIES):
            response = await self.complete(prompt)
            jobs = self._extract_json(response)
            
            if isinstance(jobs, list) and len(jobs) > 0:
                # Validate job structure
                valid_jobs = self._validate_jobs(jobs)
                if valid_jobs:
                    logger.debug(f"Extracted {len(valid_jobs)} jobs on attempt {attempt + 1}")
                    return valid_jobs
            
            if attempt < self.MAX_EXTRACTION_RETRIES - 1:
                logger.debug(f"Extraction attempt {attempt + 1} returned no jobs, retrying...")
        
        logger.warning(f"Failed to extract jobs from {url} after {self.MAX_EXTRACTION_RETRIES} attempts")
        return []
    
    def _validate_jobs(self, jobs: list) -> list[dict]:
        """Validate and filter job entries."""
        valid_jobs = []
        for job in jobs:
            if not isinstance(job, dict):
                continue
            # Must have at least a title
            if not job.get("title"):
                continue
            # Clean up and normalize
            valid_job = {
                "title": str(job.get("title", "")).strip(),
                "location": str(job.get("location", "Unknown")).strip() or "Unknown",
                "url": str(job.get("url", "")).strip(),
                "department": job.get("department"),
            }
            valid_jobs.append(valid_job)
        return valid_jobs

    def _extract_json_from_scripts(self, html: str) -> list[dict]:
        """Попытка извлечь JSON с вакансиями из script тегов (SSR/hydration)."""
        import re
        import json
        
        # Ищем script теги с JSON данными
        script_pattern = r'<script[^>]*type=["\']application/(?:ld\+)?json["\'][^>]*>([\s\S]*?)</script>'
        scripts = re.findall(script_pattern, html, re.IGNORECASE)
        
        jobs = []
        for script_content in scripts:
            try:
                data = json.loads(script_content)
                # Ищем JobPosting schema.org
                if isinstance(data, dict):
                    if data.get("@type") == "JobPosting":
                        jobs.append(self._parse_schema_job(data))
                    elif data.get("@graph"):
                        for item in data["@graph"]:
                            if item.get("@type") == "JobPosting":
                                jobs.append(self._parse_schema_job(item))
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("@type") == "JobPosting":
                            jobs.append(self._parse_schema_job(item))
            except (json.JSONDecodeError, TypeError):
                continue
        
        return jobs

    def _parse_schema_job(self, data: dict) -> dict:
        """Парсинг вакансии из schema.org JobPosting."""
        location = "Unknown"
        if data.get("jobLocation"):
            loc = data["jobLocation"]
            if isinstance(loc, dict):
                addr = loc.get("address", {})
                if isinstance(addr, dict):
                    location = addr.get("addressLocality", "Unknown")
                elif isinstance(addr, str):
                    location = addr
        
        return {
            "title": data.get("title", "Unknown"),
            "location": location,
            "url": data.get("url", ""),
            "department": data.get("industry", None),
        }

    def _clean_html(self, html: str) -> str:
        """Очистить HTML от скриптов, стилей и лишних атрибутов."""
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(html, 'lxml')
        
        # Удаляем ненужные теги полностью
        for tag in soup.find_all(['script', 'style', 'svg', 'noscript', 'head', 'meta', 'link', 'iframe', 'nav', 'footer']):
            tag.decompose()
        
        # Удаляем комментарии
        from bs4 import Comment
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()
        
        # Оставляем только важные атрибуты (href для ссылок)
        for tag in soup.find_all(True):
            # Сохраняем только href для ссылок
            href = tag.get('href') if tag.name == 'a' else None
            tag.attrs = {}
            if href:
                tag['href'] = href
        
        # Получаем очищенный HTML
        clean = str(soup)
        
        # Удаляем множественные пробелы и переносы
        import re
        clean = re.sub(r'\s+', ' ', clean)
        clean = re.sub(r'>\s+<', '><', clean)
        
        return clean.strip()

    def _extract_url(self, response: str, base_url: str) -> Optional[str]:
        """Извлечь URL из ответа LLM."""
        # Ищем URL в ответе
        url_pattern = r'https?://[^\s<>"\'}\])]+'
        urls = re.findall(url_pattern, response)
        
        if urls:
            return urls[0].rstrip('.,;:')
        
        # Если нашли относительный путь
        path_pattern = r'["\'](/[a-zA-Z0-9/_-]+)["\']'
        paths = re.findall(path_pattern, response)
        
        if paths:
            base = base_url.rstrip('/')
            return f"{base}{paths[0]}"
        
        return None

    def _extract_json(self, response: str) -> list | dict:
        """Извлечь JSON из ответа LLM."""
        # Пробуем найти JSON в markdown блоке
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Пробуем найти JSON массив напрямую
        array_match = re.search(r'\[[\s\S]*\]', response)
        if array_match:
            try:
                return json.loads(array_match.group(0))
            except json.JSONDecodeError:
                pass

        # Пробуем распарсить весь ответ
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return []

    async def close(self):
        """Закрыть соединения."""
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

