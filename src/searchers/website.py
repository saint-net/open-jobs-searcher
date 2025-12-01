"""Universal job searcher for company websites."""

import logging
import re
import xml.etree.ElementTree as ET
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.models import Job
from src.searchers.base import BaseSearcher
from src.llm.base import BaseLLMProvider

logger = logging.getLogger(__name__)


class WebsiteSearcher(BaseSearcher):
    """Универсальный поисковик вакансий с использованием LLM."""

    name = "website"

    # Типичные паттерны URL для страниц с вакансиями
    CAREER_PATTERNS = [
        # English
        r'/career[s]?',
        r'/job[s]?',
        r'/vacanc(?:y|ies)',
        r'/opening[s]?',
        r'/work',
        r'/join',
        r'/hiring',
        r'/positions',
        # German (DE/AT)
        r'/karriere',
        r'/stellen',
        r'/stellenangebote',
        r'/jobangebote',
        r'/arbeiten',
        r'/bewerben',
        r'/offene-stellen',
        # Russian
        r'/вакансии',
        r'/карьера',
        r'/работа',
    ]

    def __init__(
        self,
        llm_provider: BaseLLMProvider,
        use_browser: bool = False,
        headless: bool = True,
    ):
        """
        Инициализация поисковика.

        Args:
            llm_provider: Провайдер LLM для анализа страниц
            use_browser: Использовать Playwright для загрузки страниц (для SPA)
            headless: Запускать браузер без GUI (только если use_browser=True)
        """
        self.llm = llm_provider
        self.use_browser = use_browser
        self.headless = headless
        self._browser_loader = None

        self.client = httpx.AsyncClient(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            },
            follow_redirects=True,
            timeout=30.0,
        )

    async def _get_browser_loader(self):
        """Получить или создать BrowserLoader."""
        if self._browser_loader is None:
            from src.browser import BrowserLoader
            self._browser_loader = BrowserLoader(headless=self.headless)
            await self._browser_loader.start()
        return self._browser_loader

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

        careers_url = None

        # 1. Пробуем найти через sitemap.xml (быстро и надёжно)
        careers_url = await self._find_careers_url_from_sitemap(url)

        # 2. Загружаем главную страницу и ищем эвристически
        if not careers_url:
            html = await self._fetch(url)
            if html:
                careers_url = self._find_careers_url_heuristic(html, url)
                
                # 3. Если не нашли - используем LLM
                if not careers_url:
                    careers_url = await self.llm.find_careers_url(html, url)

        # 4. Пробуем альтернативные URL напрямую
        if not careers_url or careers_url == "NOT_FOUND":
            careers_url = await self._try_alternative_urls(url)
            if not careers_url:
                return []

        # 4. Загружаем страницу вакансий
        careers_html = await self._fetch(careers_url)
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
        """Fetch HTML content from URL."""
        if self.use_browser:
            return await self._fetch_with_browser(url)
        return await self._fetch_with_httpx(url)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.RequestError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _fetch_with_httpx_retry(self, url: str) -> httpx.Response:
        """Fetch with retry logic."""
        response = await self.client.get(url)
        response.raise_for_status()
        return response

    async def _fetch_with_httpx(self, url: str) -> Optional[str]:
        """Fetch HTML via httpx (fast, no JS)."""
        try:
            response = await self._fetch_with_httpx_retry(url)
            return response.text
        except httpx.HTTPStatusError as e:
            logger.debug(f"HTTP error {e.response.status_code} for {url}")
            return None
        except httpx.RequestError as e:
            logger.warning(f"Request failed after retries for {url}: {e}")
            return None

    async def _fetch_with_browser(self, url: str) -> Optional[str]:
        """Fetch HTML via Playwright (slow, with JS)."""
        try:
            loader = await self._get_browser_loader()
            return await loader.fetch(url)
        except Exception as e:
            logger.warning(f"Browser fetch error for {url}: {e}")
            return None

    async def _try_alternative_urls(self, base_url: str) -> Optional[str]:
        """Попробовать альтернативные URL для страницы вакансий."""
        alternatives = self._generate_alternative_urls(base_url)
        for alt_url in alternatives:
            html = await self._fetch(alt_url)
            if html:
                return alt_url
        return None

    async def _find_careers_url_from_sitemap(self, base_url: str) -> Optional[str]:
        """Find careers page URL from sitemap.xml."""
        base = base_url.rstrip('/')
        
        # Possible sitemap locations
        sitemap_urls = [
            f"{base}/sitemap.xml",
            f"{base}/sitemap_index.xml",
            f"{base}/sitemap-index.xml",
        ]
        
        all_urls = []  # Collect URLs for LLM fallback
        
        for sitemap_url in sitemap_urls:
            try:
                # Use retry logic for sitemap fetch
                try:
                    response = await self._fetch_with_httpx_retry(sitemap_url)
                except (httpx.HTTPStatusError, httpx.RequestError):
                    logger.debug(f"Sitemap not found or error: {sitemap_url}")
                    continue
                    
                xml_content = response.text
                
                # Парсим XML
                root = ET.fromstring(xml_content)
                
                # Определяем namespace из корневого тега (может быть http или https)
                root_ns = root.tag.split('}')[0].strip('{') if '}' in root.tag else ''
                ns = {'sm': root_ns} if root_ns else {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
                
                # Ищем URL с карьерными паттернами
                urls = []
                
                # Проверяем, это sitemap index или обычный sitemap
                sitemaps = root.findall('.//sm:sitemap/sm:loc', ns)
                if sitemaps:
                    # Это sitemap index — ищем вложенный sitemap с вакансиями
                    for sitemap in sitemaps:
                        loc = sitemap.text
                        if loc and any(re.search(p, loc, re.IGNORECASE) for p in self.CAREER_PATTERNS):
                            # Загружаем вложенный sitemap
                            nested_url = await self._find_careers_url_from_sitemap(loc)
                            if nested_url:
                                return nested_url
                
                # Ищем URL страниц
                for url_elem in root.findall('.//sm:url/sm:loc', ns):
                    if url_elem.text:
                        urls.append(url_elem.text)
                
                # Также пробуем без namespace (некоторые сайты не используют его)
                if not urls:
                    for url_elem in root.findall('.//url/loc'):
                        if url_elem.text:
                            urls.append(url_elem.text)
                
                # Сохраняем для LLM fallback
                all_urls.extend(urls)
                
                # Search for career patterns (fast regex)
                for page_url in urls:
                    for pattern in self.CAREER_PATTERNS:
                        if re.search(pattern, page_url, re.IGNORECASE):
                            logger.debug(f"Found careers URL in sitemap: {page_url}")
                            return page_url
                            
            except ET.ParseError as e:
                logger.debug(f"XML parse error for {sitemap_url}: {e}")
                continue
        
        # Fallback: use LLM to analyze sitemap URLs
        if all_urls:
            logger.debug(f"Using LLM to analyze {len(all_urls)} URLs from sitemap")
            return await self.llm.find_careers_url_from_sitemap(all_urls, base_url)
        
        return None

    def _find_careers_url_heuristic(self, html: str, base_url: str) -> Optional[str]:
        """Heuristic search for careers page link in HTML."""
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
                # English
                'career', 'careers', 'jobs', 'vacancies', 'openings',
                'join us', 'work with us', 'we\'re hiring',
                # German
                'karriere', 'stellen', 'stellenangebote', 'jobangebote',
                'offene stellen', 'arbeiten bei uns', 'jetzt bewerben',
                # Russian
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
            # English
            f"{base}/careers",
            f"{base}/jobs",
            f"{base}/vacancies",
            f"{base}/career",
            f"{base}/join",
            f"{base}/team",
            f"{base}/about/careers",
            f"{base}/about-us/careers",
            f"{base}/company/careers",
            f"{base}/en/careers",
            # German
            f"{base}/karriere",
            f"{base}/stellen",
            f"{base}/stellenangebote",
            f"{base}/offene-stellen",
            f"{base}/de/karriere",
            f"{base}/ueber-uns/karriere",
            f"{base}/unternehmen/karriere",
            f"{base}/jobs-karriere",
            # Russian
            f"{base}/ru/careers",
            f"{base}/o-kompanii/vakansii",
            f"{base}/company/vacancies",
        ]
        return alternatives

    async def close(self):
        """Закрыть HTTP клиент, браузер и LLM провайдер."""
        await self.client.aclose()
        if self._browser_loader:
            await self._browser_loader.stop()
        await self.llm.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
