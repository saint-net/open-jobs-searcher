"""Base class for LLM providers."""

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Optional

from src.constants import (
    MAX_LLM_RETRIES,
    MAX_URLS_FOR_LLM,
    MIN_JOB_SECTION_SIZE,
    MAX_JOB_SECTION_SIZE,
    MIN_VALID_HTML_SIZE,
)

logger = logging.getLogger(__name__)


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    # Retry settings for job extraction
    MAX_EXTRACTION_RETRIES = MAX_LLM_RETRIES

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

        # Очищаем HTML
        clean_html = self._clean_html(html)
        html_truncated = clean_html[:40000] if len(clean_html) > 40000 else clean_html
        
        # Форматируем sitemap URLs
        sitemap_text = "No sitemap available"
        if sitemap_urls:
            # Фильтруем только потенциально релевантные URL
            relevant_keywords = ['career', 'job', 'karriere', 'stellen', 'vacanc', 'hiring', 'join', 'work']
            relevant_urls = [
                url for url in sitemap_urls 
                if any(kw in url.lower() for kw in relevant_keywords)
            ]
            
            # Всегда показываем релевантные URL первыми
            # Если их мало - добавляем случайные из остальных
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

        response = await self.complete(prompt)
        
        # Извлекаем URL из ответа
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
        from urllib.parse import urljoin
        
        # Извлекаем только ссылки из HTML (более эффективно чем передавать весь HTML)
        links = self._extract_links_from_html(html, url)
        
        if not links:
            logger.debug("No links found in HTML")
            return None
        
        # Формируем компактный список ссылок для LLM
        links_text = "\n".join(links[:200])  # Max 200 links
        
        logger.debug(f"Searching for job board URL among {len(links)} links on {url}")

        prompt = FIND_JOB_BOARD_PROMPT.format(
            url=url,
            html=links_text,
        )

        response = await self.complete(prompt)
        
        # Обработка ответа
        response_clean = response.strip()
        
        if "CURRENT_PAGE" in response_clean:
            logger.debug("Current page is the job board")
            return None  # Текущая страница уже содержит вакансии
        
        if "NOT_FOUND" in response_clean:
            logger.debug("No job board URL found")
            return None
        
        # Извлекаем URL из ответа
        job_board_url = self._extract_url(response, url)
        
        if job_board_url and job_board_url != url:
            logger.debug(f"Found job board URL: {job_board_url}")
            return job_board_url
        
        return None

    def _extract_links_from_html(self, html: str, base_url: str) -> list[str]:
        """Извлечь все ссылки из HTML."""
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin
        
        soup = BeautifulSoup(html, 'lxml')
        links = []
        seen = set()
        
        for a in soup.find_all('a', href=True):
            href = a.get('href', '').strip()
            if not href or href.startswith('#') or href.startswith('javascript:'):
                continue
            
            # Конвертируем в абсолютный URL
            full_url = urljoin(base_url, href)
            
            # Дедупликация
            if full_url not in seen:
                seen.add(full_url)
                
                # Добавляем с текстом ссылки для контекста
                link_text = a.get_text(strip=True)[:50]  # Max 50 chars
                if link_text:
                    links.append(f"{full_url} [{link_text}]")
                else:
                    links.append(full_url)
        
        return links

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

        # Ограничиваем количество URL
        urls_limited = urls[:MAX_URLS_FOR_LLM]
        urls_text = "\n".join(urls_limited)

        prompt = FIND_CAREERS_FROM_SITEMAP_PROMPT.format(
            base_url=base_url,
            urls=urls_text,
        )

        response = await self.complete(prompt)
        
        # Извлекаем URL из ответа
        url = self._extract_url(response, base_url)
        return url

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
        from urllib.parse import urljoin

        # Очищаем и ограничиваем HTML
        clean_html = self._clean_html(html)
        html_truncated = clean_html[:80000] if len(clean_html) > 80000 else clean_html

        prompt = FIND_JOB_URLS_PROMPT.format(
            url=url,
            html=html_truncated,
        )

        response = await self.complete(prompt)
        
        # Извлекаем JSON массив URL'ов
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

    async def extract_company_info(self, html: str, url: str) -> Optional[str]:
        """
        Extract company description from website HTML.

        Args:
            html: HTML content of the company's main page
            url: URL of the page

        Returns:
            Brief company description or None if extraction failed
        """
        from .prompts import EXTRACT_COMPANY_INFO_PROMPT

        # Clean and truncate HTML
        clean_html = self._clean_html(html)
        html_truncated = clean_html[:40000] if len(clean_html) > 40000 else clean_html

        logger.debug(f"Extracting company info from {url}")

        prompt = EXTRACT_COMPANY_INFO_PROMPT.format(
            url=url,
            html=html_truncated,
        )

        response = await self.complete(prompt)
        
        # Clean up response
        description = response.strip()
        
        # Check for failure indicators
        if not description or description == "UNKNOWN" or len(description) < 10:
            logger.debug(f"Could not extract company info from {url}")
            return None
        
        # Remove quotes if wrapped
        if description.startswith('"') and description.endswith('"'):
            description = description[1:-1]
        
        logger.debug(f"Extracted company info: {description[:100]}...")
        return description

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
    
    async def extract_jobs_with_pagination(self, html: str, url: str) -> dict:
        """
        Extract job listings with pagination info using LLM directly.
        
        This method bypasses Schema.org and uses LLM directly to get
        both jobs and next_page_url in a single request.

        Args:
            html: HTML content of the careers page
            url: URL of the page

        Returns:
            Dict with "jobs" (list) and "next_page_url" (str or None)
        """
        result = await self._llm_extract_jobs_with_pagination(html, url)
        
        jobs = result.get("jobs", [])
        if jobs:
            valid_jobs = self._validate_jobs(jobs)
            result["jobs"] = valid_jobs
        
        return result
    
    async def _llm_extract_jobs(self, html: str, url: str) -> list[dict]:
        """LLM-based job extraction (used as fallback by hybrid extractor)."""
        # Use the new method and return only jobs for backward compatibility
        result = await self._llm_extract_jobs_with_pagination(html, url)
        return result.get("jobs", [])
    
    async def _llm_extract_jobs_with_pagination(self, html: str, url: str) -> dict:
        """LLM-based job extraction with pagination support.
        
        Returns:
            Dict with "jobs" (list) and "next_page_url" (str or None)
        """
        from .prompts import EXTRACT_JOBS_PROMPT
        from bs4 import BeautifulSoup
        
        # Extract body and clean HTML (remove scripts, styles, etc.)
        soup = BeautifulSoup(html, 'lxml')
        body = soup.find('body')
        
        # Try to find job listing sections first (they may be at end of page, outside truncation)
        job_section_html = self._find_job_section(soup)
        
        if job_section_html:
            clean_html = self._clean_html(job_section_html)
            logger.debug(f"Found job section, size: {len(clean_html)} chars")
        else:
            body_html = str(body) if body else html
            clean_html = self._clean_html(body_html)

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
            result = self._extract_json(response)
            
            # Debug: log raw response if no jobs found
            if not result or (isinstance(result, dict) and not result.get("jobs")) or (isinstance(result, list) and len(result) == 0):
                logger.debug(f"LLM response (first 500 chars): {response[:500] if response else 'EMPTY'}")
            
            # Handle new format: {"jobs": [...], "next_page_url": ...}
            if isinstance(result, dict) and "jobs" in result:
                jobs = result.get("jobs", [])
                next_page_url = result.get("next_page_url")
                if isinstance(jobs, list) and len(jobs) > 0:
                    logger.debug(f"LLM extracted {len(jobs)} jobs on attempt {attempt + 1}")
                    return {"jobs": jobs, "next_page_url": next_page_url}
            # Handle old format: [...] (for backward compatibility)
            elif isinstance(result, list) and len(result) > 0:
                logger.debug(f"LLM extracted {len(result)} jobs on attempt {attempt + 1}")
                return {"jobs": result, "next_page_url": None}
            
            if attempt < self.MAX_EXTRACTION_RETRIES - 1:
                logger.debug(f"LLM attempt {attempt + 1} returned no jobs, retrying...")
        
        return {"jobs": [], "next_page_url": None}
    
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
    
    # CSS selectors for common job listing containers/widgets
    JOB_SECTION_SELECTORS = [
        # Odoo job widgets
        '.oe_website_jobs',
        '.o_website_hr_recruitment_jobs_list',
        '[class*="website_jobs"]',
        '[class*="hr_recruitment"]',
        # Join.com widget
        '.join-jobs-widget',
        '[class*="join-jobs"]',
        # Personio
        '.personio-jobs',
        '[class*="personio"]',
        # Generic job containers
        '[class*="job-list"]',
        '[class*="jobs-list"]',
        '[class*="vacancies"]',
        '[class*="career-list"]',
        '[class*="openings"]',
        '[id*="jobs"]',
        '[id*="vacancies"]',
        '[id*="careers"]',
        # Main content with job-related text
        'main',
        'article',
        '.content',
    ]
    
    def _find_job_section(self, soup) -> str | None:
        """Find the HTML section containing job listings.
        
        Many pages have job widgets at the end of large HTML documents.
        This method finds the relevant section to avoid truncation issues.
        
        Args:
            soup: BeautifulSoup object of the page
            
        Returns:
            HTML string of job section, or None if not found
        """
        # Check if this is an Odoo site first (most reliable detection)
        # Import inside method to avoid circular import (base.py -> odoo.py -> searchers -> base.py)
        from src.searchers.job_boards.odoo import OdooParser
        
        if OdooParser.is_odoo_site(soup):
            logger.debug("Detected Odoo site, using Odoo-specific selectors")
            odoo_html = OdooParser.find_job_section(soup)
            if odoo_html:
                return odoo_html
        
        # Try generic selectors for other platforms
        candidates = []
        
        for selector in self.JOB_SECTION_SELECTORS:
            try:
                elements = soup.select(selector)
                valid_elements = []
                for el in elements:
                    el_text = el.get_text().lower()
                    # Check if element contains job-related content
                    if any(marker in el_text for marker in ['(m/w/d)', '(m/f/d)', 'vollzeit', 'teilzeit', 'job', 'position', 'stelle', 'develop', 'engineer', 'manager']):
                        html = str(el)
                        # Size check: must be substantial but not too large
                        # Check size limits for job section
                        if MIN_JOB_SECTION_SIZE < len(html) < MAX_JOB_SECTION_SIZE:
                            valid_elements.append(html)
                
                if valid_elements:
                    # Combine all found elements (e.g. list of job cards)
                    combined_html = "\n<hr>\n".join(valid_elements)
                    # If total size is substantial, consider it a candidate
                    if len(combined_html) > 1000:
                        candidates.append((len(combined_html), combined_html))
            except Exception:
                continue
                
        # Sort candidates by size (descending) to prefer larger collections
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]
            
        return None
    
    def _is_non_job_entry(self, title: str) -> bool:
        """Check if title is a non-job entry (open application, etc.)."""
        title_lower = title.lower()
        for pattern in self.NON_JOB_PATTERNS:
            if re.search(pattern, title_lower, re.IGNORECASE):
                return True
        return False

    def _clean_html(self, html: str) -> str:
        """Очистить HTML от скриптов, стилей и лишних атрибутов."""
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(html, 'lxml')
        
        # Удаляем ненужные теги полностью (но не nav/footer - могут содержать ссылки на вакансии)
        for tag in soup.find_all(['script', 'style', 'svg', 'noscript', 'head', 'meta', 'link', 'iframe']):
            tag.decompose()
        
        # Remove cookie consent dialogs (can be 5+ MB on some sites like Cookiebot)
        # These dialogs significantly inflate HTML size and don't contain job data
        cookie_selectors = [
            '[role="dialog"]',
            '[id*="cookie"]',
            '[id*="consent"]',
            '[class*="cookie"]',
            '[class*="consent"]',
            '[id*="gdpr"]',
            '[class*="gdpr"]',
            '[id*="CookieBot"]',
            '[class*="CookieBot"]',
        ]
        for selector in cookie_selectors:
            try:
                for element in soup.select(selector):
                    element.decompose()
            except Exception:
                pass  # Ignore CSS selector errors
        
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
        if not response or not response.strip():
            return []
        
        # Пробуем найти JSON в markdown блоке
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Пробуем распарсить весь ответ как JSON (если LLM вернул чистый JSON)
        try:
            return json.loads(response.strip())
        except json.JSONDecodeError as e:
            logger.debug(f"Direct JSON parse failed: {e}")

        # Пробуем найти JSON объект с "jobs" ключом
        # Используем нежадный паттерн для вложенных структур
        try:
            # Ищем начало объекта с "jobs"
            start = response.find('{"jobs"')
            if start == -1:
                start = response.find('{ "jobs"')
            if start == -1:
                start = response.find('{')
            
            if start != -1:
                # Найдем соответствующую закрывающую скобку
                depth = 0
                end = start
                for i, char in enumerate(response[start:], start):
                    if char == '{':
                        depth += 1
                    elif char == '}':
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                
                if end > start:
                    json_str = response[start:end]
                    return json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            pass

        # Пробуем найти JSON массив напрямую (старый формат)
        array_match = re.search(r'\[[\s\S]*\]', response)
        if array_match:
            try:
                return json.loads(array_match.group(0))
            except json.JSONDecodeError:
                pass

        return []

    async def close(self):
        """Закрыть соединения."""
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

