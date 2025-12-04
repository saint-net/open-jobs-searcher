"""Обработка cookie consent диалогов."""

import logging
import re

from playwright.async_api import Page

from .patterns import COOKIE_ACCEPT_PATTERNS, COOKIE_DIALOG_SELECTORS


logger = logging.getLogger(__name__)


async def handle_cookie_consent(page: Page) -> bool:
    """
    Try to dismiss cookie consent dialogs.
    
    Args:
        page: Playwright page object
        
    Returns:
        True if a cookie dialog was handled, False otherwise
    """
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

