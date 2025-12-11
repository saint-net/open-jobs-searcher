"""Обработка cookie consent диалогов."""

import logging
import re

from playwright.async_api import Page

from .patterns import COOKIE_ACCEPT_PATTERNS, COOKIE_DIALOG_SELECTORS, EXTERNAL_JOB_BOARD_PATTERNS


logger = logging.getLogger(__name__)


def _is_external_job_board(url: str) -> bool:
    """Check if URL is a known external job board (personio, greenhouse, etc.)."""
    for pattern in EXTERNAL_JOB_BOARD_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return True
    return False


async def handle_cookie_consent(page: Page) -> bool:
    """
    Try to dismiss cookie consent dialogs.
    
    Args:
        page: Playwright page object
        
    Returns:
        True if a cookie dialog was handled, False otherwise
    """
    # Skip cmpbox wait on external job boards (they don't use Consentmanager)
    current_url = page.url
    if _is_external_job_board(current_url):
        cmpbox = None
    else:
        # Handle Consentmanager (cmpbox) specifically - uses <a> not <button>
        # Wait for cmpbox to appear (it may load lazily)
        try:
            cmpbox = await page.wait_for_selector('#cmpbox', timeout=2000)
        except Exception:
            cmpbox = None
    
    try:
        cmpbox_visible = await cmpbox.is_visible() if cmpbox else False
        if cmpbox and cmpbox_visible:
            logger.debug("Found cmpbox (Consentmanager) dialog")
            # Try common accept button selectors for Consentmanager
            accept_selectors = [
                '#cmpbox a.cmpboxbtnyes',  # Primary accept button
                '#cmpbox a[aria-label*="Accept"]',
                '#cmpbox a[aria-label*="accept"]', 
                '#cmpbox a[aria-label*="Akzeptieren"]',
                '#cmpbox .cmpboxbtn.cmpboxbtnyes',
                '#cmpbox a:has-text("Accept")',
                '#cmpbox a:has-text("Akzeptieren")',
                '#cmpbox a:has-text("Alle akzeptieren")',
                '#cmpbox a:has-text("Accept all")',
            ]
            for sel in accept_selectors:
                try:
                    btn = await page.query_selector(sel)
                    if btn and await btn.is_visible():
                        logger.debug(f"Clicking cmpbox accept: {sel}")
                        await btn.click()
                        await page.wait_for_timeout(500)
                        return True
                except Exception:
                    continue
            
            # Fallback: click any visible <a> with accept-like class
            try:
                links = await page.query_selector_all('#cmpbox a')
                for link in links[:5]:
                    cls = await link.get_attribute('class') or ''
                    if 'yes' in cls.lower() or 'accept' in cls.lower():
                        await link.click()
                        await page.wait_for_timeout(500)
                        logger.debug(f"Clicked cmpbox link with class: {cls}")
                        return True
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"cmpbox handling error: {e}")
    
    # Debug: check what buttons exist
    try:
        all_buttons = await page.query_selector_all('button')
        button_texts = []
        for btn in all_buttons[:10]:  # First 10 buttons
            try:
                txt = await btn.inner_text()
                if txt and txt.strip():
                    button_texts.append(txt.strip()[:30])
            except Exception:
                pass
        if button_texts:
            logger.debug(f"Found buttons on page: {button_texts}")
    except Exception as e:
        logger.debug(f"Error listing buttons: {e}")
    
    for selector in COOKIE_DIALOG_SELECTORS:
        try:
            elements = await page.query_selector_all(selector)
            
            for element in elements:
                try:
                    text = await element.inner_text()
                    if not text:
                        continue
                    
                    text_lower = text.lower().strip()
                    
                    for pattern in COOKIE_ACCEPT_PATTERNS:
                        if re.search(pattern, text_lower, re.IGNORECASE):
                            if await element.is_visible():
                                logger.debug(f"Clicking cookie consent: '{text.strip()[:40]}'")
                                try:
                                    await element.click()
                                    await page.wait_for_timeout(1000)
                                    return True
                                except Exception as e:
                                    logger.debug(f"Failed to click cookie button: {e}")
                                    continue
                except Exception:
                    continue
        except Exception:
            continue
    
    logger.debug("No cookie consent dialog found")
    return False



