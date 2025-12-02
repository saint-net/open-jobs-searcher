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
from src.browser import DomainUnreachableError

logger = logging.getLogger(__name__)


class WebsiteSearcher(BaseSearcher):
    """Универсальный поисковик вакансий с использованием LLM."""

    name = "website"

    # URL patterns for career pages
    CAREER_PATTERNS = [
        # English
        r'/career[s]?',
        r'/job[s]?',
        r'/vacanc(?:y|ies)',
        r'/opening[s]?',
        r'/work[-_]?with[-_]?us',
        r'/join[-_]?us',
        r'/join[-_]?our[-_]?team',
        r'/hiring',
        r'/positions',
        r'/people[-_]?(?:and[-_]?)?jobs',
        # German (DE/AT)
        r'/karriere',
        r'/stellen',
        r'/stellenangebote',
        r'/jobangebote',
        r'/arbeiten',
        r'/bewerben',
        r'/offene[-_]?stellen',
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

        try:
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

            # 5. Загружаем страницу вакансий (пробуем варианты URL: plural/singular)
            jobs_data = []
            careers_html = None
            
            for variant_url in self._generate_url_variants(careers_url):
                # Для браузерного режима пробуем с навигацией к вакансиям (для SPA)
                if self.use_browser:
                    careers_html = await self._fetch_with_browser(variant_url, navigate_to_jobs=True)
                else:
                    careers_html = await self._fetch(variant_url)
                
                if not careers_html:
                    continue
                
                # 6. Извлекаем вакансии с помощью LLM
                jobs_data = await self.llm.extract_jobs(careers_html, variant_url)
                
                if jobs_data:
                    careers_url = variant_url  # Update to the working URL
                    logger.debug(f"Found {len(jobs_data)} jobs at {variant_url}")
                    break
                else:
                    logger.debug(f"No jobs found at {variant_url}, trying next variant...")
            
            if not careers_html:
                return []

            # 7. Переводим названия вакансий на английский
            titles = [job_data.get("title", "Unknown Position") for job_data in jobs_data]
            titles_en = await self.llm.translate_job_titles(titles)

            # 8. Преобразуем в модели Job
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
                    title_en=titles_en[idx] if idx < len(titles_en) else None,
                    description=job_data.get("description"),
                )
                jobs.append(job)

            return jobs
            
        except DomainUnreachableError as e:
            logger.error(f"Домен недоступен: {url} - {e}")
            return []

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
        except httpx.ConnectError as e:
            error_str = str(e).lower()
            # Detect DNS resolution errors
            if any(err in error_str for err in [
                "name or service not known",
                "nodename nor servname provided",
                "getaddrinfo failed",
                "no address associated",
                "name resolution failed",
                "temporary failure in name resolution",
            ]):
                raise DomainUnreachableError(f"Домен недоступен: {url}") from e
            logger.warning(f"Connection error for {url}: {e}")
            return None
        except httpx.RequestError as e:
            logger.warning(f"Request failed after retries for {url}: {e}")
            return None

    async def _fetch_with_browser(self, url: str, navigate_to_jobs: bool = False) -> Optional[str]:
        """Fetch HTML via Playwright (slow, with JS).
        
        Args:
            url: URL страницы
            navigate_to_jobs: Попытаться найти и перейти на страницу вакансий (для SPA)
        """
        try:
            loader = await self._get_browser_loader()
            if navigate_to_jobs:
                return await loader.fetch_with_navigation(url)
            return await loader.fetch(url)
        except DomainUnreachableError:
            raise  # Re-raise to handle at caller level
        except Exception as e:
            logger.warning(f"Browser fetch error for {url}: {e}")
            return None

    async def _try_alternative_urls(self, base_url: str) -> Optional[str]:
        """Попробовать альтернативные URL для страницы вакансий."""
        alternatives = self._generate_alternative_urls(base_url)
        for alt_url in alternatives:
            try:
                html = await self._fetch(alt_url)
                if html:
                    return alt_url
            except DomainUnreachableError:
                # Domain is unreachable, no point trying other URLs
                logger.info("Домен недоступен, прекращаем перебор URL")
                raise
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
                
                # Check if this is a sitemap index
                sitemaps = root.findall('.//sm:sitemap/sm:loc', ns)
                if sitemaps:
                    # Prioritize sitemaps: career-related first, then page/general
                    priority_sitemaps = []
                    page_sitemaps = []
                    other_sitemaps = []
                    
                    for sitemap in sitemaps:
                        loc = sitemap.text
                        if not loc:
                            continue
                        if any(re.search(p, loc, re.IGNORECASE) for p in self.CAREER_PATTERNS):
                            priority_sitemaps.append(loc)
                        elif 'page' in loc.lower():
                            page_sitemaps.append(loc)
                        else:
                            other_sitemaps.append(loc)
                    
                    # Load priority sitemaps (career-related + page sitemap)
                    for sitemap_loc in priority_sitemaps + page_sitemaps:
                        nested_urls = await self._parse_sitemap_urls(sitemap_loc)
                        all_urls.extend(nested_urls)
                
                # Ищем URL страниц
                for url_elem in root.findall('.//sm:url/sm:loc', ns):
                    if url_elem.text:
                        urls.append(url_elem.text)
                
                # Также пробуем без namespace (некоторые сайты не используют его)
                if not urls:
                    for url_elem in root.findall('.//url/loc'):
                        if url_elem.text:
                            urls.append(url_elem.text)
                
                # Save for LLM fallback
                all_urls.extend(urls)
                            
            except ET.ParseError as e:
                logger.debug(f"XML parse error for {sitemap_url}: {e}")
                continue
        
        # Find all URLs matching career patterns
        matching_urls = []
        for page_url in all_urls:
            for pattern in self.CAREER_PATTERNS:
                if re.search(pattern, page_url, re.IGNORECASE):
                    matching_urls.append(page_url)
                    break
        
        if matching_urls:
            # Score URLs to find the best careers page (not individual job pages)
            best_url = self._select_best_careers_url(matching_urls)
            logger.debug(f"Found careers URL in sitemap: {best_url} (from {len(matching_urls)} matches)")
            return best_url
        
        # Fallback: use LLM to analyze sitemap URLs
        if all_urls:
            logger.debug(f"Using LLM to analyze {len(all_urls)} URLs from sitemap")
            return await self.llm.find_careers_url_from_sitemap(all_urls, base_url)
        
        return None

    def _select_best_careers_url(self, urls: list[str]) -> str:
        """Select the best careers page URL from a list of candidates."""
        # Job listing page endings (most specific - actual job lists)
        # Plural forms first (jobs > job), then with .html extension
        job_listing_endings = [
            '/jobs', '/jobs.html', '/job', '/job.html',
            '/vacancies', '/vacancies.html', '/vacancy', '/vacancy.html',
            '/openings', '/openings.html', '/opening', '/opening.html',
            '/careers', '/careers.html',
            '/stellenangebote', '/stellenangebote.html',
            '/offene-stellen', '/offene-stellen.html',
            '/stellen', '/stellen.html',
            '/вакансии', '/вакансии.html',
        ]
        
        # General careers section endings (parent pages)
        general_careers_endings = [
            '/career', '/career.html',
            '/karriere', '/karriere.html',
            '/people-jobs', '/people-jobs.html',
            '/people-and-jobs', '/people-and-jobs.html',
            '/карьера', '/карьера.html',
            '/работа', '/работа.html',
        ]
        
        def score_url(url: str) -> tuple:
            """Score URL: lower is better. Returns (priority, ending_index, path_depth, length)."""
            path = urlparse(url).path.rstrip('/')
            # Also handle .html extension for path matching
            path_normalized = path.replace('.html', '')
            segments = [s for s in path.split('/') if s]
            
            # Priority 0: URL ends with job listing pattern (most specific)
            # Earlier in list = better (plural forms first)
            for idx, ending in enumerate(job_listing_endings):
                ending_normalized = ending.replace('.html', '')
                if path.endswith(ending) or path_normalized.endswith(ending_normalized):
                    return (0, idx, len(segments), len(url))
            
            # Priority 1: URL ends with general careers pattern
            for idx, ending in enumerate(general_careers_endings):
                ending_normalized = ending.replace('.html', '')
                if path.endswith(ending) or path_normalized.endswith(ending_normalized):
                    return (1, idx, len(segments), len(url))
            
            # Priority 2: URL contains career pattern with short slug (category)
            last_segment = segments[-1] if segments else ''
            if len(last_segment) < 30:
                return (2, 0, len(segments), len(url))
            
            # Priority 3: Long slugs (specific job pages)
            return (3, 0, len(segments), len(url))
        
        return min(urls, key=score_url)

    def _generate_url_variants(self, url: str) -> list[str]:
        """Generate plural/singular variants of a careers URL.
        
        If sitemap contains job.html, also try jobs.html and vice versa.
        """
        variants = [url]  # Original URL first
        
        # Singular -> plural mappings
        singular_to_plural = {
            '/job.html': '/jobs.html',
            '/job': '/jobs',
            '/vacancy.html': '/vacancies.html',
            '/vacancy': '/vacancies',
            '/opening.html': '/openings.html',
            '/opening': '/openings',
            '/career.html': '/careers.html',
            '/career': '/careers',
            '/stelle.html': '/stellen.html',
            '/stelle': '/stellen',
        }
        
        parsed = urlparse(url)
        path = parsed.path
        
        # Try singular -> plural
        for singular, plural in singular_to_plural.items():
            if path.endswith(singular):
                new_path = path[:-len(singular)] + plural
                new_url = f"{parsed.scheme}://{parsed.netloc}{new_path}"
                variants.append(new_url)
                break
        
        # Try plural -> singular (less common but possible)
        for singular, plural in singular_to_plural.items():
            if path.endswith(plural):
                new_path = path[:-len(plural)] + singular
                new_url = f"{parsed.scheme}://{parsed.netloc}{new_path}"
                variants.append(new_url)
                break
        
        return variants

    async def _parse_sitemap_urls(self, sitemap_url: str) -> list[str]:
        """Parse URLs from a single sitemap file."""
        urls = []
        try:
            response = await self._fetch_with_httpx_retry(sitemap_url)
            root = ET.fromstring(response.text)
            
            # Detect namespace
            root_ns = root.tag.split('}')[0].strip('{') if '}' in root.tag else ''
            ns = {'sm': root_ns} if root_ns else {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
            
            # Extract URLs
            for url_elem in root.findall('.//sm:url/sm:loc', ns):
                if url_elem.text:
                    urls.append(url_elem.text)
            
            # Try without namespace
            if not urls:
                for url_elem in root.findall('.//url/loc'):
                    if url_elem.text:
                        urls.append(url_elem.text)
                        
        except (httpx.HTTPStatusError, httpx.RequestError, ET.ParseError) as e:
            logger.debug(f"Failed to parse sitemap {sitemap_url}: {e}")
        
        return urls

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
            # English (with .html variants for static sites)
            f"{base}/careers",
            f"{base}/careers.html",
            f"{base}/jobs",
            f"{base}/jobs.html",
            f"{base}/vacancies",
            f"{base}/vacancies.html",
            f"{base}/career",
            f"{base}/career.html",
            f"{base}/join",
            f"{base}/team",
            f"{base}/about/careers",
            f"{base}/about-us/careers",
            f"{base}/company/careers",
            f"{base}/en/careers",
            # German (with .html variants)
            f"{base}/karriere",
            f"{base}/karriere.html",
            f"{base}/stellen",
            f"{base}/stellen.html",
            f"{base}/stellenangebote",
            f"{base}/stellenangebote.html",
            f"{base}/offene-stellen",
            f"{base}/offene-stellen.html",
            f"{base}/de/karriere",
            f"{base}/ueber-uns/karriere",
            f"{base}/unternehmen/karriere",
            f"{base}/jobs-karriere",
            f"{base}/people-jobs",
            f"{base}/people-jobs/offene-stellen",
            f"{base}/people-and-jobs",
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
