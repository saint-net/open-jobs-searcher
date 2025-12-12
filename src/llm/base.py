"""Base class for LLM providers."""

import logging
import re
from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING, TypeVar

from pydantic import BaseModel

from src.models import JobDict, JobExtractionResult
from .html_utils import clean_html, extract_url, extract_json, html_to_markdown

if TYPE_CHECKING:
    from .cache import LLMCache

logger = logging.getLogger(__name__)

# Generic type for structured output
T = TypeVar("T", bound=BaseModel)


# Pre-compiled translation patterns for German → English job titles
# Order matters: longer/more specific patterns first
TRANSLATION_RULES = [
    # Full compound words (longest first)
    (re.compile(r'systemadministrator', re.IGNORECASE), 'System Administrator'),
    (re.compile(r'teamleitung', re.IGNORECASE), 'Team Lead'),
    (re.compile(r'teamleiter', re.IGNORECASE), 'Team Lead'),
    (re.compile(r'abteilungsleiter', re.IGNORECASE), 'Department Head'),
    (re.compile(r'geschäftsführer', re.IGNORECASE), 'Managing Director'),
    (re.compile(r'projektleiter', re.IGNORECASE), 'Project Manager'),
    (re.compile(r'produktmanager', re.IGNORECASE), 'Product Manager'),
    (re.compile(r'kundenservice', re.IGNORECASE), 'Customer Service'),
    (re.compile(r'kundendienst', re.IGNORECASE), 'Customer Service'),
    (re.compile(r'werkstudent', re.IGNORECASE), 'Working Student'),
    (re.compile(r'auszubildende[r]?', re.IGNORECASE), 'Apprentice'),
    (re.compile(r'praktikantin', re.IGNORECASE), 'Intern'),
    (re.compile(r'praktikant', re.IGNORECASE), 'Intern'),
    (re.compile(r'stellvertretender?', re.IGNORECASE), 'Deputy'),
    (re.compile(r'kauffrau', re.IGNORECASE), 'Commercial Clerk'),
    (re.compile(r'kaufmann', re.IGNORECASE), 'Commercial Clerk'),
    # Role words
    (re.compile(r'entwickler', re.IGNORECASE), 'Developer'),
    (re.compile(r'ingenieur', re.IGNORECASE), 'Engineer'),
    (re.compile(r'referent', re.IGNORECASE), 'Specialist'),
    (re.compile(r'berater', re.IGNORECASE), 'Consultant'),
    (re.compile(r'analyst', re.IGNORECASE), 'Analyst'),
    (re.compile(r'architekt', re.IGNORECASE), 'Architect'),
    (re.compile(r'spezialist', re.IGNORECASE), 'Specialist'),
    (re.compile(r'fachkraft', re.IGNORECASE), 'Specialist'),
    (re.compile(r'experte', re.IGNORECASE), 'Expert'),
    (re.compile(r'meister', re.IGNORECASE), 'Master'),
    (re.compile(r'techniker', re.IGNORECASE), 'Technician'),
    (re.compile(r'assistentin', re.IGNORECASE), 'Assistant'),
    (re.compile(r'assistent', re.IGNORECASE), 'Assistant'),
    (re.compile(r'sachbearbeiter', re.IGNORECASE), 'Clerk'),
    (re.compile(r'mitarbeiter', re.IGNORECASE), 'Employee'),
    (re.compile(r'leiter', re.IGNORECASE), 'Lead'),
    # Connectors (with word boundaries via spaces)
    (re.compile(r' für ', re.IGNORECASE), ' for '),
    (re.compile(r' und ', re.IGNORECASE), ' and '),
    (re.compile(r' oder ', re.IGNORECASE), ' or '),
    (re.compile(r' im ', re.IGNORECASE), ' in '),
    (re.compile(r' bei ', re.IGNORECASE), ' at '),
    (re.compile(r' interne ', re.IGNORECASE), ' internal '),
    # Employment type
    (re.compile(r'vollzeit', re.IGNORECASE), 'Full-time'),
    (re.compile(r'teilzeit', re.IGNORECASE), 'Part-time'),
]


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    _job_extractor = None  # Lazy-initialized LLMJobExtractor
    _url_discovery = None  # Lazy-initialized LLMUrlDiscovery
    _cache: Optional["LLMCache"] = None  # Optional LLM response cache
    
    def _get_job_extractor(self):
        """Get or create job extractor instance."""
        if self._job_extractor is None:
            from .job_extraction import LLMJobExtractor
            self._job_extractor = LLMJobExtractor(
                complete_fn=self.complete,
                clean_html_fn=clean_html,
                extract_json_fn=extract_json,
                complete_json_fn=self.complete_json,
                complete_structured_fn=self.complete_structured,
                html_to_markdown_fn=html_to_markdown,
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
                complete_json_fn=self.complete_json,
            )
        return self._url_discovery
    
    def set_cache(self, cache: "LLMCache") -> None:
        """Set LLM response cache.
        
        Args:
            cache: LLMCache instance for caching responses
        """
        self._cache = cache

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

    async def complete_json(self, prompt: str, system: Optional[str] = None) -> dict | list:
        """
        Генерация JSON ответа от LLM с использованием structured output.

        Использует response_format={"type": "json_object"} для гарантированного
        валидного JSON без необходимости парсить markdown блоки.

        Args:
            prompt: Пользовательский промпт (должен явно просить JSON)
            system: Системный промпт (опционально)

        Returns:
            Распарсенный JSON (dict или list)
        """
        # Дефолтная реализация — fallback на complete() + extract_json()
        # Провайдеры могут переопределить для использования native structured output
        response = await self.complete(prompt, system)
        return extract_json(response)

    async def complete_structured(
        self, 
        prompt: str, 
        schema: type[T],
        system: Optional[str] = None
    ) -> T:
        """
        Генерация ответа от LLM с гарантированным соответствием Pydantic схеме.

        Использует response_format={"type": "json_schema"} для строгой типизации.
        Провайдеры должны переопределить для native поддержки.

        Args:
            prompt: Пользовательский промпт
            schema: Pydantic модель, определяющая структуру ответа
            system: Системный промпт (опционально)

        Returns:
            Инстанс Pydantic модели с валидированными данными
        """
        # Дефолтная реализация — fallback на complete_json() + Pydantic validation
        # Провайдеры с поддержкой json_schema должны переопределить
        response = await self.complete_json(prompt, system)
        
        # Try to validate response with Pydantic
        if isinstance(response, dict):
            return schema.model_validate(response)
        elif isinstance(response, list):
            # If schema expects a wrapper, try to wrap
            return schema.model_validate({"items": response})
        
        # Return empty instance as fallback
        return schema()

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
        from src.models import TranslationSchema

        if not titles:
            return []

        # Skip translation if titles already look English (ASCII-only or common English words)
        if self._titles_look_english(titles):
            logger.debug("Titles already in English, skipping translation")
            return titles

        titles_text = "\n".join(titles)
        
        # Try cache first (translations are very stable, 30 day TTL)
        if self._cache:
            from .cache import CacheNamespace, estimate_tokens
            cached = await self._cache.get(CacheNamespace.TRANSLATION, titles_text)
            if cached is not None and isinstance(cached, list) and len(cached) == len(titles):
                logger.debug(f"Translation cache hit for {len(titles)} titles")
                return [str(t) for t in cached]
        
        prompt = TRANSLATE_JOB_TITLES_PROMPT.format(titles=titles_text)

        # Try structured output first (guaranteed schema)
        try:
            result = await self.complete_structured(prompt, TranslationSchema)
            translated = result.translations
            
            if len(translated) == len(titles):
                # Validate each translation
                valid_translations = []
                for t in translated:
                    if '\xa0?' in t or '\\xa0' in t or t == '...' or 'error' in t.lower():
                        break
                    valid_translations.append(t.strip())
                else:
                    # All valid - cache and return
                    if self._cache:
                        from .cache import CacheNamespace, estimate_tokens
                        await self._cache.set(
                            CacheNamespace.TRANSLATION, 
                            titles_text, 
                            valid_translations,
                            tokens_estimate=estimate_tokens(titles_text)
                        )
                    return valid_translations
                
                logger.warning("Translation response contained invalid data, using fallback")
            else:
                logger.warning(f"Translation count mismatch: expected {len(titles)}, got {len(translated)}")
                
        except Exception as e:
            logger.warning(f"Structured translation failed: {e}, falling back to legacy")

        # Fallback to legacy complete_json
        translated = await self.complete_json(prompt)

        # Handle both array and object responses
        if isinstance(translated, dict):
            for key in ("translations", "titles", "translated_titles", "result"):
                if key in translated and isinstance(translated[key], list):
                    translated = translated[key]
                    break
            else:
                values = list(translated.values())
                if len(values) == 1 and isinstance(values[0], list):
                    translated = values[0]

        if isinstance(translated, list) and len(translated) == len(titles):
            result = []
            valid = True
            for t in translated:
                if not isinstance(t, str):
                    valid = False
                    break
                if '\xa0?' in t or '\\xa0' in t or t == '...' or 'error' in t.lower():
                    valid = False
                    break
                result.append(t.strip())
            
            if valid and len(result) == len(titles):
                if self._cache:
                    from .cache import CacheNamespace, estimate_tokens
                    await self._cache.set(
                        CacheNamespace.TRANSLATION, 
                        titles_text, 
                        result,
                        tokens_estimate=estimate_tokens(titles_text)
                    )
                return result
            
            logger.warning("Translation response contained invalid data, using fallback")
        
        # Fallback: use dictionary-based translation for common German words
        logger.debug("Using dictionary fallback for translation")
        return self._translate_with_dictionary(titles)
    
    def _translate_with_dictionary(self, titles: list[str]) -> list[str]:
        """Fallback translation using pre-compiled patterns for German job terms.
        
        Uses TRANSLATION_RULES defined at module level for performance.
        """
        result = []
        for title in titles:
            translated = title
            for pattern, replacement in TRANSLATION_RULES:
                translated = pattern.sub(replacement, translated)
            result.append(translated)
        return result

    def _titles_look_english(self, titles: list[str]) -> bool:
        """Check if titles are likely already in English."""
        # Common non-English characters in German job titles
        non_english_chars = set('äöüßÄÖÜ')
        # Common German/other language job title words
        non_english_words = {
            'entwickler', 'ingenieur', 'leiter', 'berater', 'kaufmann', 'kauffrau',
            'sachbearbeiter', 'mitarbeiter', 'fachkraft', 'meister', 'techniker',
            'stellvertretender', 'geschäftsführer', 'abteilungsleiter', 'werkstudent',
            'практикант', 'разработчик', 'инженер', 'менеджер',  # Russian
        }
        
        for title in titles:
            title_lower = title.lower()
            # Check for non-English characters
            if any(c in title for c in non_english_chars):
                return False
            # Check for non-English words
            if any(word in title_lower for word in non_english_words):
                return False
        
        return True

    async def extract_company_info(self, html: str, url: str) -> Optional[str]:
        """Extract company description from website HTML."""
        from .prompts import EXTRACT_COMPANY_INFO_PROMPT
        from urllib.parse import urlparse

        # Use domain as cache key (company info is very stable)
        domain = urlparse(url).netloc
        
        # Try cache first (company info rarely changes, 30 day TTL)
        if self._cache:
            from .cache import CacheNamespace
            cached = await self._cache.get(CacheNamespace.COMPANY_INFO, domain)
            if cached is not None and isinstance(cached, str):
                logger.debug(f"Company info cache hit for {domain}")
                return cached

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
        
        # Cache successful extraction
        if self._cache:
            from .cache import CacheNamespace, estimate_tokens
            await self._cache.set(
                CacheNamespace.COMPANY_INFO,
                domain,
                description,
                tokens_estimate=estimate_tokens(html_truncated)
            )
        
        logger.debug(f"Extracted company info: {description[:100]}...")
        return description

    async def extract_jobs(self, html: str, url: str, page=None) -> list[JobDict]:
        """Extract job listings from HTML page using hybrid approach."""
        # Try cache first (job listings change frequently, 6 hour TTL)
        if self._cache:
            from .cache import CacheNamespace, estimate_tokens
            # Use markdown for cache key (normalized content)
            content_for_key = html_to_markdown(html)
            cached = await self._cache.get(CacheNamespace.JOBS, content_for_key)
            if cached is not None and isinstance(cached, list):
                logger.debug(f"Job extraction cache hit for {url}")
                return cached
        
        result = await self._get_job_extractor().extract_jobs(html, url, page)
        
        # Cache successful extraction (only if we have jobs)
        if self._cache and result:
            from .cache import CacheNamespace, estimate_tokens
            content_for_key = html_to_markdown(html)
            await self._cache.set(
                CacheNamespace.JOBS,
                content_for_key,
                result,
                tokens_estimate=estimate_tokens(content_for_key)
            )
        
        return result
    
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
        """Закрыть соединения и залогировать статистику кэша."""
        if self._cache:
            self._cache.log_session_stats()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

