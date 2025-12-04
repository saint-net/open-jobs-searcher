"""Загрузчик страниц через headless браузер."""

import logging
from typing import Optional
from contextlib import asynccontextmanager

from playwright.async_api import async_playwright, Browser, Page, Playwright

from .exceptions import DomainUnreachableError
from .patterns import DEFAULT_USER_AGENT, NETWORK_ERROR_PATTERNS
from .cookie_handler import handle_cookie_consent
from .navigation import (
    is_external_job_board,
    find_external_job_board_frame,
    find_job_navigation_link,
)


logger = logging.getLogger(__name__)


class BrowserLoader:
    """Загрузчик страниц через headless браузер."""

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
            # Launch browser with clean context (no cookies from previous sessions)
            # Add Chromium args to allow third-party cookies (needed for HRworks and similar job boards)
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-features=SameSiteByDefaultCookies,CookiesWithoutSameSiteMustBeSecure",
                    "--disable-site-isolation-trials",
                ],
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
            # Create page with HTTPS errors ignored (for sites with certificate issues)
            context = await self._browser.new_context(ignore_https_errors=True)
            page = await context.new_page()
            
            # Устанавливаем User-Agent (полный, чтобы избежать блокировок)
            await page.set_extra_http_headers({
                "User-Agent": DEFAULT_USER_AGENT
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
            if any(err in error_str for err in NETWORK_ERROR_PATTERNS):
                raise DomainUnreachableError(f"Домен недоступен: {url}") from e
            
            logger.warning(f"Browser error for {url}: {e}")
            return None
        finally:
            if page:
                context = page.context
                await page.close()
                await context.close()

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
        context = None
        try:
            # Create page with HTTPS errors ignored (for sites with certificate issues)
            context = await self._browser.new_context(ignore_https_errors=True)
            page = await context.new_page()
            
            await page.set_extra_http_headers({
                "User-Agent": DEFAULT_USER_AGENT
            })

            response = await page.goto(url, timeout=self.timeout, wait_until="domcontentloaded")
            
            if response is None or response.status >= 400:
                return None, None

            # Ждём начальный рендеринг
            await page.wait_for_timeout(2000)
            
            # Ждём и обрабатываем cookie consent диалоги (может появиться с задержкой)
            for _ in range(3):
                if await handle_cookie_consent(page):
                    await page.wait_for_timeout(1000)
                    break
                # Ждём появления диалога
                await page.wait_for_timeout(500)
            
            # Получаем первоначальный HTML
            html = await page.content()
            final_url = url  # Track the final URL after navigation
            
            # Пытаемся найти ссылку на вакансии и кликнуть
            for attempt in range(max_attempts):
                job_link = await find_job_navigation_link(page)
                
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
                            
                            # На новой странице тоже ищем навигацию к вакансиям
                            # (например, "Zu den Jobs" на karriere.synqony.com)
                            new_job_link = await find_job_navigation_link(new_page)
                            if new_job_link:
                                logger.debug(f"Found job nav link on external site, clicking...")
                                try:
                                    await new_job_link.click()
                                    await new_page.wait_for_timeout(1500)
                                except Exception:
                                    pass
                            
                            if is_external_job_board(current_url):
                                logger.info(f"Navigated to external job board (new tab): {current_url}")
                            
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
                            if is_external_job_board(current_url):
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
            external_frame = await find_external_job_board_frame(page)
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
            if any(err in error_str for err in NETWORK_ERROR_PATTERNS):
                raise DomainUnreachableError(f"Домен недоступен: {url}") from e
            
            logger.warning(f"Browser error for {url}: {e}")
            return None, None
        finally:
            if page:
                await page.close()
            if context:
                await context.close()

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

