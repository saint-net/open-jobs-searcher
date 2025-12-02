"""Модуль для работы с браузером через Playwright."""

import logging
import re
from typing import Optional
from contextlib import asynccontextmanager

from playwright.async_api import async_playwright, Browser, Page, Playwright


logger = logging.getLogger(__name__)


class DomainUnreachableError(Exception):
    """Raised when domain cannot be reached (DNS or network issues)."""
    pass


class BrowserLoader:
    """Загрузчик страниц через headless браузер."""

    # Паттерны для поиска ссылок на вакансии в SPA
    JOB_LINK_PATTERNS = [
        # English
        r'current\s*opening',
        r'view\s*all',
        r'see\s*all',
        r'all\s*jobs',
        r'open\s*positions',
        r'job\s*listings',
        r'browse\s*jobs',
        # German
        r'alle\s*stellen',
        r'offene\s*stellen',
        r'stellenangebote',
        r'stellenbörse',
        r'zur\s*stellenbörse',
        # Russian
        r'все\s*вакансии',
        r'открытые\s*позиции',
    ]
    
    # External job board platforms to detect
    EXTERNAL_JOB_BOARD_PATTERNS = [
        r'\.jobs\.personio\.',
        r'boards\.greenhouse\.io',
        r'jobs\.lever\.co',
        r'\.workable\.com',
        r'\.breezy\.hr',
        r'\.recruitee\.com',
        r'\.smartrecruiters\.com',
        r'\.bamboohr\.com/jobs',
        r'\.ashbyhq\.com',
        r'job\.deloitte\.com',
    ]

    def __init__(self, headless: bool = True, timeout: float = 30000):
        """
        Инициализация загрузчика.

        Args:
            headless: Запускать браузер без GUI
            timeout: Таймаут загрузки страницы в мс
        """
        self.headless = headless
        self.timeout = timeout
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None

    async def start(self):
        """Запустить браузер."""
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless,
            )

    async def stop(self):
        """Остановить браузер."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def fetch(self, url: str, wait_for: Optional[str] = None) -> Optional[str]:
        """
        Загрузить страницу и получить HTML после рендеринга JavaScript.

        Args:
            url: URL страницы
            wait_for: CSS селектор для ожидания (опционально)

        Returns:
            HTML содержимое страницы или None при ошибке
        """
        if self._browser is None:
            await self.start()

        page: Optional[Page] = None
        try:
            page = await self._browser.new_page()
            
            # Устанавливаем User-Agent (полный, чтобы избежать блокировок)
            await page.set_extra_http_headers({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            })

            # Загружаем страницу (domcontentloaded быстрее чем networkidle)
            response = await page.goto(url, timeout=self.timeout, wait_until="domcontentloaded")
            
            if response is None or response.status >= 400:
                return None

            # Ждём дополнительный селектор если указан
            if wait_for:
                try:
                    await page.wait_for_selector(wait_for, timeout=5000)
                except Exception:
                    pass  # Продолжаем даже если селектор не найден

            # Даём время на рендеринг динамического контента
            await page.wait_for_timeout(1500)

            # Получаем HTML
            html = await page.content()
            return html

        except Exception as e:
            error_str = str(e)
            # Detect domain/network unreachable errors - fail fast
            if any(err in error_str for err in [
                "ERR_NAME_NOT_RESOLVED",
                "ERR_CONNECTION_REFUSED",
                "ERR_CONNECTION_RESET",
                "ERR_CONNECTION_TIMED_OUT",
                "ERR_NETWORK_CHANGED",
                "ERR_INTERNET_DISCONNECTED",
                "ERR_ADDRESS_UNREACHABLE",
            ]):
                raise DomainUnreachableError(f"Домен недоступен: {url}") from e
            
            logger.warning(f"Browser error for {url}: {e}")
            return None
        finally:
            if page:
                await page.close()

    async def fetch_with_navigation(self, url: str, max_attempts: int = 2) -> tuple[Optional[str], Optional[str]]:
        """
        Загрузить страницу и попытаться найти/перейти на страницу с вакансиями.
        
        Для SPA-сайтов (например, HiBob) вакансии могут находиться на отдельной 
        "странице", доступной через навигацию (Current openings, View all и т.д.).
        
        Args:
            url: URL страницы карьеры
            max_attempts: Максимальное количество попыток навигации
            
        Returns:
            Tuple (HTML содержимое, финальный URL) или (None, None)
        """
        if self._browser is None:
            await self.start()

        page: Optional[Page] = None
        try:
            page = await self._browser.new_page()
            
            await page.set_extra_http_headers({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            })

            response = await page.goto(url, timeout=self.timeout, wait_until="domcontentloaded")
            
            if response is None or response.status >= 400:
                return None, None

            # Ждём начальный рендеринг
            await page.wait_for_timeout(2000)
            
            # Получаем первоначальный HTML
            html = await page.content()
            final_url = url  # Track the final URL after navigation
            
            # Пытаемся найти ссылку на вакансии и кликнуть
            for attempt in range(max_attempts):
                job_link = await self._find_job_navigation_link(page)
                
                if job_link:
                    logger.debug(f"Found job navigation link: {job_link}")
                    try:
                        # Проверяем, открывается ли ссылка в новой вкладке (target="_blank")
                        target = await job_link.get_attribute("target")
                        
                        if target == "_blank":
                            # Обрабатываем клик с открытием новой вкладки
                            async with page.context.expect_page() as new_page_info:
                                await job_link.click()
                            new_page = await new_page_info.value
                            await new_page.wait_for_load_state("domcontentloaded")
                            await new_page.wait_for_timeout(2500)
                            
                            current_url = new_page.url
                            final_url = current_url
                            if self._is_external_job_board(current_url):
                                logger.info(f"Navigated to external job board (new tab): {current_url}")
                                html = await new_page.content()
                                await new_page.close()
                                break
                            
                            html = await new_page.content()
                            await new_page.close()
                            break
                        else:
                            # Обычный клик
                            await job_link.click()
                            # Ждём навигацию или обновление контента
                            await page.wait_for_timeout(2500)
                            
                            # Проверяем, перешли ли на внешний job board
                            current_url = page.url
                            final_url = current_url
                            if self._is_external_job_board(current_url):
                                logger.info(f"Navigated to external job board: {current_url}")
                                html = await page.content()
                                break
                            
                            # Получаем обновлённый HTML
                            new_html = await page.content()
                            
                            # Проверяем, увеличился ли размер HTML (загрузился контент)
                            if len(new_html) > len(html) * 1.2:  # Минимум 20% прирост
                                logger.debug(f"Navigation succeeded, HTML size: {len(html)} -> {len(new_html)}")
                                html = new_html
                                break
                            elif len(new_html) > len(html):
                                html = new_html
                    except Exception as e:
                        logger.debug(f"Click failed: {e}")
                else:
                    break  # Нет ссылок для клика
            
            # Финальная проверка: если открылся iframe с внешним job board, получаем его контент
            external_frame = await self._find_external_job_board_frame(page)
            if external_frame:
                logger.info(f"Found external job board iframe")
                try:
                    frame_html = await external_frame.content()
                    if len(frame_html) > 1000:  # Минимальный размер для валидного контента
                        html = frame_html
                except Exception as e:
                    logger.debug(f"Failed to get iframe content: {e}")
            
            return html, final_url

        except Exception as e:
            error_str = str(e)
            if any(err in error_str for err in [
                "ERR_NAME_NOT_RESOLVED",
                "ERR_CONNECTION_REFUSED",
                "ERR_CONNECTION_RESET",
                "ERR_CONNECTION_TIMED_OUT",
                "ERR_NETWORK_CHANGED",
                "ERR_INTERNET_DISCONNECTED",
                "ERR_ADDRESS_UNREACHABLE",
            ]):
                raise DomainUnreachableError(f"Домен недоступен: {url}") from e
            
            logger.warning(f"Browser error for {url}: {e}")
            return None, None
        finally:
            if page:
                await page.close()

    def _is_external_job_board(self, url: str) -> bool:
        """Check if URL is an external job board platform."""
        for pattern in self.EXTERNAL_JOB_BOARD_PATTERNS:
            if re.search(pattern, url, re.IGNORECASE):
                return True
        return False

    async def _find_external_job_board_frame(self, page: Page):
        """Find iframe containing external job board content."""
        try:
            frames = page.frames
            for frame in frames:
                frame_url = frame.url
                if self._is_external_job_board(frame_url):
                    return frame
        except Exception as e:
            logger.debug(f"Error finding job board frame: {e}")
        return None

    async def _find_job_navigation_link(self, page: Page):
        """
        Найти ссылку для навигации к списку вакансий на странице.
        
        Ищет кликабельные элементы с текстом типа:
        - "Current openings"
        - "View all"
        - "All jobs"
        и т.д.
        
        Returns:
            Элемент для клика или None
        """
        # Ищем все потенциальные ссылки и кнопки
        selectors = [
            'a',
            'button',
            '[role="link"]',
            '[role="button"]',
            '[onclick]',
            'span[class*="link"]',
            'div[class*="nav"]',
        ]
        
        for selector in selectors:
            try:
                elements = await page.query_selector_all(selector)
                
                for element in elements:
                    try:
                        text = await element.inner_text()
                        if not text:
                            continue
                        
                        text_lower = text.lower().strip()
                        
                        # Проверяем текст на соответствие паттернам
                        for pattern in self.JOB_LINK_PATTERNS:
                            if re.search(pattern, text_lower, re.IGNORECASE):
                                # Проверяем, что элемент видим и кликабелен
                                if await element.is_visible():
                                    return element
                    except Exception:
                        continue
            except Exception:
                continue
        
        return None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()


@asynccontextmanager
async def get_browser_loader(headless: bool = True):
    """Контекстный менеджер для BrowserLoader."""
    loader = BrowserLoader(headless=headless)
    try:
        await loader.start()
        yield loader
    finally:
        await loader.stop()

