"""Модуль для работы с браузером через Playwright."""

from typing import Optional
from contextlib import asynccontextmanager

from playwright.async_api import async_playwright, Browser, Page, Playwright


class DomainUnreachableError(Exception):
    """Raised when domain cannot be reached (DNS or network issues)."""
    pass


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
            
            # Устанавливаем User-Agent
            await page.set_extra_http_headers({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
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
            
            print(f"Browser error for {url}: {e}")
            return None
        finally:
            if page:
                await page.close()

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

