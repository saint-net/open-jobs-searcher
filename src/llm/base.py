"""Base class for LLM providers."""

import logging
from abc import ABC, abstractmethod
from typing import Optional

from src.models import JobDict, JobExtractionResult
from .html_utils import clean_html, extract_url, extract_json

logger = logging.getLogger(__name__)


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    _job_extractor = None  # Lazy-initialized LLMJobExtractor
    _url_discovery = None  # Lazy-initialized LLMUrlDiscovery
    
    def _get_job_extractor(self):
        """Get or create job extractor instance."""
        if self._job_extractor is None:
            from .job_extraction import LLMJobExtractor
            self._job_extractor = LLMJobExtractor(
                complete_fn=self.complete,
                clean_html_fn=clean_html,
                extract_json_fn=extract_json,
            )
        return self._job_extractor
    
    def _get_url_discovery(self):
        """Get or create URL discovery instance."""
        if self._url_discovery is None:
            from .url_discovery import LLMUrlDiscovery
            self._url_discovery = LLMUrlDiscovery(
                complete_fn=self.complete,
                clean_html_fn=clean_html,
                extract_url_fn=extract_url,
                extract_json_fn=extract_json,
            )
        return self._url_discovery

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

    async def find_careers_url(
        self, html: str, base_url: str, sitemap_urls: list[str] = None
    ) -> Optional[str]:
        """Найти ссылку на страницу с вакансиями."""
        return await self._get_url_discovery().find_careers_url(html, base_url, sitemap_urls)

    async def find_job_board_url(self, html: str, url: str) -> Optional[str]:
        """Найти ссылку на job board на странице карьеры."""
        return await self._get_url_discovery().find_job_board_url(html, url)

    async def find_careers_url_from_sitemap(self, urls: list[str], base_url: str) -> Optional[str]:
        """Найти страницу вакансий среди URL из sitemap.xml."""
        return await self._get_url_discovery().find_careers_url_from_sitemap(urls, base_url)

    async def find_job_urls(self, html: str, url: str) -> list[str]:
        """Найти URL'ы отдельных вакансий на странице карьеры."""
        return await self._get_url_discovery().find_job_urls(html, url)

    async def translate_job_titles(self, titles: list[str]) -> list[str]:
        """Translate job titles to English."""
        from .prompts import TRANSLATE_JOB_TITLES_PROMPT

        if not titles:
            return []

        titles_text = "\n".join(titles)
        prompt = TRANSLATE_JOB_TITLES_PROMPT.format(titles=titles_text)

        response = await self.complete(prompt)
        translated = extract_json(response)

        if isinstance(translated, list) and len(translated) == len(titles):
            return [str(t) for t in translated]
        
        logger.warning("Translation failed, returning original titles")
        return titles

    async def extract_company_info(self, html: str, url: str) -> Optional[str]:
        """Extract company description from website HTML."""
        from .prompts import EXTRACT_COMPANY_INFO_PROMPT

        cleaned = clean_html(html)
        html_truncated = cleaned[:40000] if len(cleaned) > 40000 else cleaned

        logger.debug(f"Extracting company info from {url}")

        prompt = EXTRACT_COMPANY_INFO_PROMPT.format(url=url, html=html_truncated)
        response = await self.complete(prompt)
        
        description = response.strip()
        
        if not description or description == "UNKNOWN" or len(description) < 10:
            logger.debug(f"Could not extract company info from {url}")
            return None
        
        if description.startswith('"') and description.endswith('"'):
            description = description[1:-1]
        
        logger.debug(f"Extracted company info: {description[:100]}...")
        return description

    async def extract_jobs(self, html: str, url: str, page=None) -> list[JobDict]:
        """Extract job listings from HTML page using hybrid approach."""
        return await self._get_job_extractor().extract_jobs(html, url, page)
    
    async def extract_jobs_with_pagination(self, html: str, url: str) -> JobExtractionResult:
        """Extract job listings with pagination info using LLM directly."""
        return await self._get_job_extractor().extract_jobs_with_pagination(html, url)

    # Expose utility functions as methods for backward compatibility
    def _clean_html(self, html: str) -> str:
        """Очистить HTML от скриптов, стилей и лишних атрибутов."""
        return clean_html(html)

    def _extract_url(self, response: str, base_url: str) -> Optional[str]:
        """Извлечь URL из ответа LLM."""
        return extract_url(response, base_url)

    def _extract_json(self, response: str) -> list | dict:
        """Извлечь JSON из ответа LLM."""
        return extract_json(response)

    async def close(self):
        """Закрыть соединения."""
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

