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

    async def extract_jobs(self, html: str, url: str, page=None) -> list[dict]:
        """
        Extract job listings from HTML page using hybrid approach.

        Args:
            html: HTML content of the careers page
            url: URL of the page
            page: Optional Playwright Page object (enables accessibility tree extraction)

        Returns:
            List of job dictionaries
        """
        from src.extraction import HybridJobExtractor
        
        # Create hybrid extractor with LLM fallback
        extractor = HybridJobExtractor(
            llm_extract_fn=self._llm_extract_jobs
        )
        
        # Use hybrid extraction (with browser if page is provided)
        jobs = await extractor.extract(html, url, page=page)
        
        if jobs:
            logger.debug(f"Hybrid extraction found {len(jobs)} jobs from {url}")
            # Validate job structure
            valid_jobs = self._validate_jobs(jobs)
            return valid_jobs
        
        logger.warning(f"Failed to extract jobs from {url}")
        return []
    
    async def _llm_extract_jobs(self, html: str, url: str) -> list[dict]:
        """LLM-based job extraction (used as fallback by hybrid extractor)."""
        from .prompts import EXTRACT_JOBS_PROMPT
        
        # Try to extract only the main content (where jobs usually are)
        main_html = self._extract_main_content(html)
        
        # Clean HTML from scripts and styles
        clean_html = self._clean_html(main_html)

        # Limit HTML size (80000 chars for large pages)
        html_truncated = clean_html[:80000] if len(clean_html) > 80000 else clean_html
        
        logger.debug(f"LLM extracting jobs from {url}, HTML size: {len(html_truncated)} chars")

        prompt = EXTRACT_JOBS_PROMPT.format(
            url=url,
            html=html_truncated,
        )

        # Retry extraction if result is empty (LLM can be inconsistent)
        for attempt in range(self.MAX_EXTRACTION_RETRIES):
            response = await self.complete(prompt)
            jobs = self._extract_json(response)
            
            if isinstance(jobs, list) and len(jobs) > 0:
                logger.debug(f"LLM extracted {len(jobs)} jobs on attempt {attempt + 1}")
                return jobs
            
            if attempt < self.MAX_EXTRACTION_RETRIES - 1:
                logger.debug(f"LLM attempt {attempt + 1} returned no jobs, retrying...")
        
        return []
    
    # Non-job titles to filter out (open applications, general inquiries, etc.)
    NON_JOB_PATTERNS = [
        r'initiativbewerbung',  # German: Open/unsolicited application
        r'initiativ\s*bewerbung',
        r'spontanbewerbung',  # German: Spontaneous application
        r'open\s*application',  # English variants
        r'unsolicited\s*application',
        r'speculative\s*application',
        r'general\s*application',
        r'blindbewerbung',  # German: Blind application
    ]
    
    def _validate_jobs(self, jobs: list) -> list[dict]:
        """Validate and filter job entries."""
        valid_jobs = []
        for job in jobs:
            if not isinstance(job, dict):
                continue
            # Must have at least a title
            if not job.get("title"):
                continue
            
            title = str(job.get("title", "")).strip()
            
            # Filter out non-job entries (open applications, etc.)
            if self._is_non_job_entry(title):
                logger.debug(f"Filtered non-job entry: {title}")
                continue
            
            # Clean up and normalize
            valid_job = {
                "title": title,
                "location": str(job.get("location", "Unknown")).strip() or "Unknown",
                "url": str(job.get("url", "")).strip(),
                "department": job.get("department"),
            }
            valid_jobs.append(valid_job)
        return valid_jobs
    
    def _is_non_job_entry(self, title: str) -> bool:
        """Check if title is a non-job entry (open application, etc.)."""
        title_lower = title.lower()
        for pattern in self.NON_JOB_PATTERNS:
            if re.search(pattern, title_lower, re.IGNORECASE):
                return True
        return False
    
    def _extract_main_content(self, html: str) -> str:
        """Extract main content area from HTML (where jobs are usually located)."""
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(html, 'lxml')
        
        # Try to find main content container
        main_selectors = [
            'main',
            '[role="main"]',
            '#main',
            '#content',
            '.content',
            'article',
            '.main-content',
            '.page-content',
        ]
        
        for selector in main_selectors:
            main = soup.select_one(selector)
            if main and len(str(main)) > 500:  # Ensure it has meaningful content
                logger.debug(f"Found main content via '{selector}', size: {len(str(main))} chars")
                return str(main)
        
        # Fallback: return body or full HTML
        body = soup.find('body')
        if body:
            return str(body)
        return html

    def _clean_html(self, html: str) -> str:
        """Очистить HTML от скриптов, стилей и лишних атрибутов."""
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(html, 'lxml')
        
        # Удаляем ненужные теги полностью (но не nav/footer - могут содержать ссылки на вакансии)
        for tag in soup.find_all(['script', 'style', 'svg', 'noscript', 'head', 'meta', 'link', 'iframe']):
            tag.decompose()
        
        # Удаляем комментарии
        from bs4 import Comment
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()
        
        # Сохраняем важные атрибуты, которые помогают понять структуру
        keep_attrs = {'href', 'class', 'id', 'role', 'data-job', 'data-position'}
        for tag in soup.find_all(True):
            # Фильтруем атрибуты
            new_attrs = {}
            for attr, value in tag.attrs.items():
                if attr in keep_attrs:
                    # Укорачиваем длинные классы
                    if attr == 'class' and isinstance(value, list):
                        # Оставляем только классы, связанные с job/career/position
                        relevant = [c for c in value if any(k in c.lower() for k in ['job', 'career', 'position', 'vacancy', 'opening', 'title', 'list', 'item'])]
                        if relevant:
                            new_attrs[attr] = ' '.join(relevant[:3])  # Максимум 3 класса
                    elif attr == 'href':
                        new_attrs[attr] = value
                    else:
                        new_attrs[attr] = value
            tag.attrs = new_attrs
        
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

