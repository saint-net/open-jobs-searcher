"""Загрузчик страниц через headless браузер."""

import logging
from typing import Optional
from contextlib import asynccontextmanager

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright

try:
    from playwright_stealth import Stealth
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False

from .exceptions import DomainUnreachableError, PlaywrightBrowsersNotInstalledError
from .patterns import DEFAULT_USER_AGENT, NETWORK_ERROR_PATTERNS
from .cookie_handler import handle_cookie_consent, expand_collapsed_content
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
        self._stealth = Stealth() if STEALTH_AVAILABLE else None
        # Max time to wait for Cloudflare in visible mode (user can solve CAPTCHA)
        self._cf_max_wait_visible = 60  # seconds
        self._cf_max_wait_headless = 30  # seconds

    async def start(self):
        """Запустить браузер."""
        if self._browser is None:
            self._playwright = await async_playwright().start()
            # Launch browser with clean context (no cookies from previous sessions)
            # Add Chromium args to allow third-party cookies (needed for HRworks and similar job boards)
            try:
                # Try Chrome first (better anti-bot bypass), fallback to Chromium
                # Anti-detection browser args
                browser_args = [
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=SameSiteByDefaultCookies,CookiesWithoutSameSiteMustBeSecure",
                    "--disable-site-isolation-trials",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-infobars",
                    "--disable-extensions",
                    "--disable-popup-blocking",
                ]
                
                # Try Chrome first, fallback to Chromium
                try:
                    self._browser = await self._playwright.chromium.launch(
                        headless=self.headless,
                        channel="chrome",
                        args=browser_args,
                    )
                    logger.debug("Using Chrome browser")
                except Exception as chrome_err:
                    logger.debug(f"Chrome not available ({chrome_err}), falling back to Chromium")
                    self._browser = await self._playwright.chromium.launch(
                        headless=self.headless,
                        args=browser_args,
                    )
            except Exception as e:
                error_str = str(e)
                # Check if the error is about missing browser executable
                if "Executable doesn't exist" in error_str or "executable doesn't exist" in error_str:
                    # Try to install browsers automatically
                    try:
                        import subprocess
                        import sys
                        logger.info("Браузеры Playwright не установлены. Устанавливаю автоматически...")
                        # Use subprocess to run: python -m playwright install chromium
                        result = subprocess.run(
                            [sys.executable, "-m", "playwright", "install", "chromium"],
                            capture_output=True,
                            text=True,
                            timeout=300,  # 5 minutes timeout
                        )
                        if result.returncode != 0:
                            raise Exception(f"Installation failed: {result.stderr}")
                        logger.info("Браузеры установлены. Повторяю запуск...")
                        # Retry after installation
                        self._browser = await self._playwright.chromium.launch(
                            headless=self.headless,
                            args=[
                                "--disable-features=SameSiteByDefaultCookies,CookiesWithoutSameSiteMustBeSecure",
                                "--disable-site-isolation-trials",
                                "--disable-blink-features=AutomationControlled",
                            ],
                        )
                    except Exception as install_error:
                        raise PlaywrightBrowsersNotInstalledError(
                            "Браузеры Playwright не установлены. "
                            "Установите их вручную командой: python -m playwright install chromium\n"
                            f"Ошибка установки: {install_error}"
                        ) from e
                else:
                    raise

    async def stop(self):
        """Остановить браузер."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def _scroll_and_wait_for_content(self, page: Page, max_scrolls: int = 8) -> None:
        """Scroll page to trigger lazy-loaded content (e.g., external job widgets).
        
        Many sites embed job listings via JS widgets (join.com, personio, etc.)
        that only load when scrolled into view. This method scrolls incrementally
        and waits for network activity to settle.
        
        Args:
            page: Playwright Page object
            max_scrolls: Number of scroll increments (reduced from 15 for speed)
        """
        try:
            # Trigger user interaction events to bypass lazy loading checks
            await page.mouse.move(100, 100)
            await page.wait_for_timeout(200)
            
            # Count elements that might contain job listings (not just article)
            initial_count = await page.evaluate(
                "document.querySelectorAll('article, .job, .vacancy, .position, "
                "[class*=\"job\"], [class*=\"career\"], [class*=\"opening\"], "
                "li[class], tr[class]').length"
            )
            last_count = initial_count
            no_change_count = 0
            
            # Get viewport dimensions
            viewport = await page.evaluate("({ width: window.innerWidth, height: window.innerHeight })")
            scroll_step = viewport.get('height', 800)
            
            # Scroll down incrementally to trigger lazy loading
            for i in range(max_scrolls):
                # Scroll by viewport height
                await page.mouse.wheel(0, scroll_step)
                
                # Shorter wait - 500ms is enough for most lazy loading
                await page.wait_for_timeout(500)
                
                # Quick network check (1.5s timeout, not 3s)
                try:
                    await page.wait_for_load_state("networkidle", timeout=1500)
                except Exception:
                    pass
                
                # Check if new content appeared
                current_count = await page.evaluate(
                    "document.querySelectorAll('article, .job, .vacancy, .position, "
                    "[class*=\"job\"], [class*=\"career\"], [class*=\"opening\"], "
                    "li[class], tr[class]').length"
                )
                if current_count > last_count:
                    logger.debug(f"Scroll {i+1}: elements {last_count} -> {current_count}")
                    last_count = current_count
                    no_change_count = 0
                else:
                    no_change_count += 1
                
                # Check if we've reached the bottom
                at_bottom = await page.evaluate(
                    "(window.innerHeight + window.scrollY) >= document.body.scrollHeight - 100"
                )
                
                # Stop early: at bottom OR no changes for 2 scrolls (was 3)
                if at_bottom or no_change_count >= 2:
                    if at_bottom:
                        # Log element breakdown for debugging
                        breakdown = await page.evaluate("""() => {
                            const counts = {
                                'article': document.querySelectorAll('article').length,
                                '.job': document.querySelectorAll('.job').length,
                                '[class*="job"]': document.querySelectorAll('[class*="job"]').length,
                                '[class*="career"]': document.querySelectorAll('[class*="career"]').length,
                                '[class*="position"]': document.querySelectorAll('[class*="position"]').length,
                            };
                            return Object.entries(counts).filter(([k,v]) => v > 0).map(([k,v]) => `${k}:${v}`).join(', ');
                        }""")
                        logger.debug(f"Reached bottom. Total elements: {current_count} ({breakdown or 'generic li/tr'})")
                    break
            
            # Final scroll to bottom (shorter wait)
            await page.mouse.wheel(0, 1500)
            await page.wait_for_timeout(800)
            
            # Quick network settle
            try:
                await page.wait_for_load_state("networkidle", timeout=2000)
            except Exception:
                pass
            
            # Log if content changed
            final_count = await page.evaluate(
                "document.querySelectorAll('article, .job, .vacancy, .position, "
                "[class*=\"job\"], [class*=\"career\"], [class*=\"opening\"], "
                "li[class], tr[class]').length"
            )
            if final_count != initial_count:
                logger.debug(f"Lazy loading complete: {initial_count} -> {final_count} elements")
            
            # Scroll back to top
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(300)
                
        except Exception as e:
            logger.debug(f"Scroll/wait failed (continuing): {e}")

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
            
            # Apply stealth to bypass bot detection
            if self._stealth:
                await self._stealth.apply_stealth_async(context)
            
            page = await context.new_page()
            
            # Устанавливаем User-Agent (полный, чтобы избежать блокировок)
            await page.set_extra_http_headers({
                "User-Agent": DEFAULT_USER_AGENT
            })

            # Загружаем страницу (domcontentloaded быстрее чем networkidle)
            response = await page.goto(url, timeout=self.timeout, wait_until="domcontentloaded")
            
            if response is None:
                return None
            
            # Check for Cloudflare challenge (403/503 with JS challenge)
            initial_status = response.status
            if initial_status in (403, 503, 520, 521, 522, 523, 524, 525, 526):
                max_wait = self._cf_max_wait_visible if not self.headless else self._cf_max_wait_headless
                max_attempts = max_wait // 5
                
                if not self.headless:
                    logger.info(f"Cloudflare challenge detected. Waiting up to {max_wait}s (solve CAPTCHA if needed)...")
                else:
                    logger.debug(f"Got status {initial_status}, waiting for Cloudflare challenge...")
                
                # Wait for Cloudflare to complete (it reloads the page after JS challenge)
                for attempt in range(max_attempts):
                    await page.wait_for_timeout(5000)
                    html = await page.content()
                    
                    # Check if still on challenge/error page
                    is_cf_challenge = any(x in html for x in [
                        "Checking your browser", "Just a moment", "challenges.cloudflare.com",
                        "403 Forbidden", "Please Wait...", "DDoS protection", "Enable JavaScript"
                    ])
                    
                    if not is_cf_challenge and len(html) > 2000:
                        logger.debug(f"Cloudflare challenge passed after {(attempt+1)*5}s")
                        break
                    
                    logger.debug(f"Still waiting for Cloudflare... ({(attempt+1)*5}/{max_wait}s)")
                else:
                    logger.debug(f"Cloudflare challenge not passed after {max_wait}s")
                    return None
                    
                # Wait for full page load
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
            elif 400 <= initial_status < 500:
                # Real 4xx error (not Cloudflare)
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

    async def fetch_with_page(
        self, url: str, navigate_to_jobs: bool = False, max_attempts: int = 2
    ) -> tuple[Optional[str], Optional[str], Optional[Page], Optional["BrowserContext"]]:
        """
        Загрузить страницу и вернуть HTML + page объект для дальнейшей работы.
        
        ВАЖНО: Вызывающий код должен закрыть page и context после использования!
        
        Args:
            url: URL страницы
            navigate_to_jobs: Попытаться найти и перейти на страницу вакансий
            max_attempts: Максимальное количество попыток навигации
            
        Returns:
            Tuple (HTML, финальный URL, Page объект, BrowserContext) или (None, None, None, None)
        """
        if self._browser is None:
            await self.start()

        page: Optional[Page] = None
        context = None
        try:
            context = await self._browser.new_context(ignore_https_errors=True)
            
            # Apply stealth to bypass bot detection
            if self._stealth:
                await self._stealth.apply_stealth_async(context)
            
            page = await context.new_page()
            
            await page.set_extra_http_headers({
                "User-Agent": DEFAULT_USER_AGENT
            })

            response = await page.goto(url, timeout=self.timeout, wait_until="domcontentloaded")
            
            if response is None:
                if page:
                    await page.close()
                if context:
                    await context.close()
                return None, None, None, None
            
            # Check for Cloudflare challenge
            initial_status = response.status
            if initial_status in (403, 503, 520, 521, 522, 523, 524, 525, 526):
                logger.debug(f"Got status {initial_status}, waiting for Cloudflare challenge...")
                await page.wait_for_timeout(5000)
                
                html = await page.content()
                if "Checking your browser" in html or "Just a moment" in html:
                    logger.debug("Still on Cloudflare challenge, waiting more...")
                    await page.wait_for_timeout(5000)
                    html = await page.content()
                
                if len(html) < 1000 and ("403" in html or "Forbidden" in html):
                    logger.debug("Cloudflare blocked the request")
                    if page:
                        await page.close()
                    if context:
                        await context.close()
                    return None, None, None, None
                
                logger.debug("Cloudflare challenge passed, waiting for content...")
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                await page.wait_for_timeout(2000)
            elif 400 <= initial_status < 500:
                if page:
                    await page.close()
                if context:
                    await context.close()
                return None, None, None, None

            # Ждём начальный рендеринг
            await page.wait_for_timeout(2000)
            
            # Обрабатываем cookie consent (до 3 попыток, диалог может появиться с задержкой)
            cookie_handled = False
            for _ in range(3):
                if await handle_cookie_consent(page):
                    cookie_handled = True
                    await page.wait_for_timeout(500)
                    break
                await page.wait_for_timeout(300)
            
            if not cookie_handled:
                logger.debug("No cookie consent dialog found")
            
            # Раскрываем скрытый контент (кнопки "Mehr Lesen", "Read More" и т.д.)
            await expand_collapsed_content(page)
            
            # NOTE: Don't scroll here - we'll scroll once after final navigation
            # This avoids double scrolling which was causing 80+ second delays
            
            final_url = url
            
            # Навигация к вакансиям если нужно
            if navigate_to_jobs:
                for attempt in range(max_attempts):
                    job_link = await find_job_navigation_link(page)
                    
                    if job_link:
                        logger.debug(f"Found job navigation link: {job_link}")
                        try:
                            target = await job_link.get_attribute("target")
                            
                            if target == "_blank":
                                async with page.context.expect_page() as new_page_info:
                                    try:
                                        await job_link.click(timeout=10000)
                                    except Exception:
                                        await job_link.click(force=True)
                                new_page = await new_page_info.value
                                await new_page.wait_for_load_state("domcontentloaded")
                                await new_page.wait_for_timeout(2500)
                                
                                new_url = new_page.url
                                
                                # Check if navigation failed (chrome-error://)
                                if new_url.startswith("chrome-error://"):
                                    logger.debug(f"Navigation failed, ignoring error page")
                                    await new_page.close()
                                    break
                                
                                final_url = new_url
                                
                                # Закрываем старую страницу, используем новую
                                await page.close()
                                page = new_page
                                
                                # На новой странице тоже ищем навигацию
                                new_job_link = await find_job_navigation_link(page)
                                if new_job_link:
                                    try:
                                        await new_job_link.click(timeout=10000)
                                        await page.wait_for_timeout(1500)
                                        final_url = page.url
                                    except Exception:
                                        try:
                                            await new_job_link.click(force=True)
                                            await page.wait_for_timeout(1500)
                                            final_url = page.url
                                        except Exception:
                                            pass
                                break
                            else:
                                try:
                                    await job_link.click(timeout=10000)
                                except Exception:
                                    # Fallback: force click to bypass overlays (cookie banners)
                                    logger.debug("Normal click failed, trying force click")
                                    await job_link.click(force=True)
                                await page.wait_for_timeout(2500)
                                final_url = page.url
                                # Successfully navigated - no need to retry
                                break
                        except Exception as e:
                            logger.debug(f"Click failed: {e}")
                    else:
                        break
            
            # Scroll again after navigation to trigger lazy content on final page
            await self._scroll_and_wait_for_content(page)
            
            html = await page.content()
            return html, final_url, page, context

        except Exception as e:
            error_str = str(e)
            if any(err in error_str for err in NETWORK_ERROR_PATTERNS):
                if page:
                    await page.close()
                if context:
                    await context.close()
                raise DomainUnreachableError(f"Домен недоступен: {url}") from e
            
            logger.warning(f"Browser error for {url}: {e}")
            if page:
                await page.close()
            if context:
                await context.close()
            return None, None, None, None

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
            
            # Apply stealth to bypass bot detection
            if self._stealth:
                await self._stealth.apply_stealth_async(context)
            
            page = await context.new_page()
            
            await page.set_extra_http_headers({
                "User-Agent": DEFAULT_USER_AGENT
            })

            response = await page.goto(url, timeout=self.timeout, wait_until="domcontentloaded")
            
            if response is None:
                return None, None
            
            # Check for Cloudflare challenge
            initial_status = response.status
            if initial_status in (403, 503, 520, 521, 522, 523, 524, 525, 526):
                logger.debug(f"Got status {initial_status}, waiting for Cloudflare challenge...")
                await page.wait_for_timeout(5000)
                
                html = await page.content()
                if "Checking your browser" in html or "Just a moment" in html:
                    logger.debug("Still on Cloudflare challenge, waiting more...")
                    await page.wait_for_timeout(5000)
                
                content = await page.content()
                if len(content) < 1000 and ("403" in content or "Forbidden" in content):
                    logger.debug("Cloudflare blocked the request")
                    return None, None
                
                logger.debug("Cloudflare challenge passed, waiting for content...")
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                await page.wait_for_timeout(2000)
            elif 400 <= initial_status < 500:
                return None, None

            # Ждём начальный рендеринг
            await page.wait_for_timeout(2000)
            
            # Ждём и обрабатываем cookie consent диалоги (может появиться с задержкой)
            cookie_handled = False
            for _ in range(3):
                if await handle_cookie_consent(page):
                    cookie_handled = True
                    await page.wait_for_timeout(1000)
                    break
                await page.wait_for_timeout(500)
            
            if not cookie_handled:
                logger.debug("No cookie consent dialog found")
            
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
                                try:
                                    await job_link.click(timeout=10000)
                                except Exception:
                                    await job_link.click(force=True)
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
                                    await new_job_link.click(timeout=10000)
                                    await new_page.wait_for_timeout(1500)
                                except Exception:
                                    try:
                                        await new_job_link.click(force=True)
                                        await new_page.wait_for_timeout(1500)
                                    except Exception:
                                        pass
                            
                            if is_external_job_board(current_url):
                                logger.info(f"Navigated to external job board (new tab): {current_url}")
                            
                            html = await new_page.content()
                            await new_page.close()
                            break
                        else:
                            # Обычный клик (с fallback на force при overlay)
                            try:
                                await job_link.click(timeout=10000)
                            except Exception:
                                await job_link.click(force=True)
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

