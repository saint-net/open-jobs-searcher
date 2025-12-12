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
    
    return False


# Patterns for "expand/read more" buttons that hide job content
EXPAND_BUTTON_PATTERNS = [
    r'mehr\s*lesen',      # German: Read more
    r'weiterlesen',       # German: Continue reading
    r'mehr\s*anzeigen',   # German: Show more
    r'alle\s*anzeigen',   # German: Show all
    r'read\s*more',       # English
    r'show\s*more',       # English
    r'view\s*more',       # English
    r'expand',            # English
    r'see\s*all',         # English
    r'load\s*more',       # English
]


async def expand_collapsed_content(page: Page, max_clicks: int = 5) -> int:
    """
    Click "expand" / "read more" buttons to reveal hidden content.
    
    Args:
        page: Playwright page object
        max_clicks: Maximum number of expand buttons to click
        
    Returns:
        Number of buttons clicked
    """
    clicked = 0
    
    try:
        # Find all buttons and clickable elements
        # Include span/div with onclick or clickable styling
        selectors = [
            'button', 'a', '[role="button"]', '.btn', 
            '[class*="expand"]', '[class*="more"]', '[class*="toggle"]',
            'span[onclick]', 'div[onclick]', '[class*="read-more"]', '[class*="readmore"]',
        ]
        
        candidates_found = []
        
        for selector in selectors:
            if clicked >= max_clicks:
                break
                
            try:
                elements = await page.query_selector_all(selector)
                
                for element in elements:
                    if clicked >= max_clicks:
                        break
                        
                    try:
                        text = await element.inner_text()
                        if not text:
                            continue
                        
                        text_clean = text.strip()
                        text_lower = text_clean.lower()
                        
                        # Check if it matches expand patterns
                        for pattern in EXPAND_BUTTON_PATTERNS:
                            if re.search(pattern, text_lower, re.IGNORECASE):
                                candidates_found.append(text_clean[:30])
                                try:
                                    # Quick check: skip if element is detached or not actionable
                                    tag = await element.evaluate("el => el.tagName.toLowerCase()")
                                    if tag not in ('button', 'a', 'input', 'div', 'span'):
                                        continue
                                    
                                    # For <a> tags, check if it has href (real link vs fake button)
                                    if tag == 'a':
                                        href = await element.get_attribute('href')
                                        # If it's a real navigation link, skip (we don't want to navigate)
                                        if href and not href.startswith('#') and not href.startswith('javascript:'):
                                            continue
                                    
                                    # Use JS click - bypasses all Playwright actionability checks
                                    # dispatchEvent ensures React/Vue state updates trigger
                                    await element.evaluate("""el => {
                                        try {
                                            el.click();
                                            el.dispatchEvent(new Event('click', {bubbles: true}));
                                        } catch(e) {}
                                    }""")
                                    
                                    await page.wait_for_timeout(400)
                                    clicked += 1
                                    logger.debug(f"Expanded content: '{text_clean[:40]}'")
                                    break  # Move to next element
                                except Exception:
                                    continue
                    except Exception:
                        continue
            except Exception:
                continue
    except Exception as e:
        logger.debug(f"Error expanding content: {e}")
    
    if clicked > 0:
        logger.debug(f"Expanded {clicked} collapsed section(s)")
    elif candidates_found:
        logger.debug(f"Found expand candidates but none clickable: {candidates_found[:5]}")
    else:
        logger.debug("No expandable content found")
    
    return clicked


