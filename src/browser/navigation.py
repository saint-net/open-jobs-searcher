"""Навигация и поиск ссылок на вакансии."""

import logging
import re
from typing import Optional

from playwright.async_api import Page, Frame

from .patterns import (
    JOB_LINK_PATTERNS,
    JOB_HREF_PATTERNS,
    EXTERNAL_JOB_BOARD_PATTERNS,
    NAVIGATION_SELECTORS,
)


logger = logging.getLogger(__name__)


def is_external_job_board(url: str) -> bool:
    """Check if URL is an external job board platform."""
    for pattern in EXTERNAL_JOB_BOARD_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return True
    return False


async def find_external_job_board_frame(page: Page) -> Optional[Frame]:
    """Find iframe containing external job board content."""
    try:
        frames = page.frames
        for frame in frames:
            frame_url = frame.url
            if is_external_job_board(frame_url):
                return frame
    except Exception as e:
        logger.debug(f"Error finding job board frame: {e}")
    return None


async def find_job_navigation_link(page: Page):
    """
    Найти ссылку для навигации к списку вакансий на странице.
    
    Ищет кликабельные элементы с текстом типа:
    - "Current openings"
    - "View all"
    - "All jobs"
    и т.д.
    
    Args:
        page: Playwright page object
        
    Returns:
        Элемент для клика или None
    """
    # Patterns to exclude (individual job pages, not listings)
    EXCLUDE_PATTERNS = [
        r'stellenprofil',  # German: job profile (individual job)
        r'bewerbung',  # German: application
        r'bewerben',  # German: apply
        r'job-detail',
        r'/job/[^/]+$',  # Individual job URLs
        r'#apply',
        r'#bewerbung',
    ]
    
    def is_excluded_link(href: str, text: str) -> bool:
        """Check if link should be excluded (job detail page, not listing)."""
        href_lower = href.lower()
        text_lower = text.lower()
        
        for pattern in EXCLUDE_PATTERNS:
            if re.search(pattern, href_lower, re.IGNORECASE):
                return True
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        return False
    
    # First, try to find links by href containing karriere/jobs/career patterns
    try:
        links = await page.query_selector_all('a[href]')
        for link in links:
            try:
                href = await link.get_attribute('href')
                if not href:
                    continue
                
                text = ""
                try:
                    text = await link.inner_text()
                except Exception:
                    pass
                
                # Skip individual job pages
                if is_excluded_link(href, text):
                    continue
                
                for pattern in JOB_HREF_PATTERNS:
                    if re.search(pattern, href, re.IGNORECASE):
                        if await link.is_visible():
                            logger.debug(f"Found job link by href: '{href}' (text: '{text.strip()[:30]}')")
                            return link
            except Exception:
                continue
    except Exception:
        pass
    
    # Then search by text content
    for selector in NAVIGATION_SELECTORS:
        try:
            elements = await page.query_selector_all(selector)
            
            for element in elements:
                try:
                    text = await element.inner_text()
                    if not text:
                        continue
                    
                    text_lower = text.lower().strip()
                    
                    # Проверяем текст на соответствие паттернам
                    for pattern in JOB_LINK_PATTERNS:
                        if re.search(pattern, text_lower, re.IGNORECASE):
                            # Проверяем, что элемент видим и кликабелен
                            if await element.is_visible():
                                logger.debug(f"Found job nav link: '{text.strip()[:50]}' matching pattern '{pattern}'")
                                return element
                except Exception:
                    continue
        except Exception:
            continue
    
    logger.debug("No job navigation link found on page")


