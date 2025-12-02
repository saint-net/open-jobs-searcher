"""Job board platform detection utilities."""

import logging
import re
from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


# External job board platforms: (URL pattern, platform name)
EXTERNAL_JOB_BOARDS = [
    (r'\.jobs\.personio\.(?:de|com)', 'personio'),
    (r'boards\.greenhouse\.io', 'greenhouse'),
    (r'jobs\.lever\.co', 'lever'),
    (r'\.workable\.com', 'workable'),
    (r'\.breezy\.hr', 'breezy'),
    (r'\.recruitee\.com', 'recruitee'),
    (r'\.smartrecruiters\.com', 'smartrecruiters'),
    (r'\.bamboohr\.com/jobs', 'bamboohr'),
    (r'\.ashbyhq\.com', 'ashby'),
    (r'\.factorial\.co/job_posting', 'factorial'),
    (r'\.pi-asp\.de/bewerber-web', 'pi-asp'),
]

# URLs to skip when looking for job boards (privacy, imprint, etc.)
SKIP_URL_PATTERNS = [
    r'/privacy[-_]?policy',
    r'/datenschutz',
    r'/imprint',
    r'/impressum',
    r'/terms',
    r'/agb',
    r'/legal',
    r'/cookie',
    r'/contact',
    r'/kontakt',
]


def detect_job_board_platform(url: str) -> Optional[str]:
    """Detect job board platform from URL.
    
    Args:
        url: URL to check
        
    Returns:
        Platform name or None if not detected
    """
    for pattern, platform in EXTERNAL_JOB_BOARDS:
        if re.search(pattern, url, re.IGNORECASE):
            return platform
    return None


def _is_job_board_url_valid(url: str) -> bool:
    """Check if the job board URL is a valid jobs page (not privacy/legal)."""
    for pattern in SKIP_URL_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return False
    return True


def _normalize_job_board_url(url: str) -> str:
    """Normalize job board URL to the main jobs page.
    
    For example:
    - https://company.jobs.personio.com/privacy-policy -> https://company.jobs.personio.com/
    - https://company.jobs.personio.com/job/123 -> https://company.jobs.personio.com/
    """
    parsed = urlparse(url)
    # Keep only language parameter if present
    query_params = parsed.query
    lang_match = re.search(r'language=([a-z]{2})', query_params)
    lang_param = f"?language={lang_match.group(1)}" if lang_match else ""
    
    return f"{parsed.scheme}://{parsed.netloc}/{lang_param}"


def find_external_job_board(html: str) -> Optional[str]:
    """Find external job board URL (Personio, Greenhouse, etc.) in HTML.
    
    Checks for:
    - Links to external job board platforms
    - Iframes loading external job boards
    - Data attributes with external URLs
    - JavaScript variables containing job board URLs
    
    Args:
        html: HTML content of the page
        
    Returns:
        External job board URL if found, None otherwise
    """
    soup = BeautifulSoup(html, 'lxml')
    found_urls = []
    
    # Check all links for external job board URLs
    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        for pattern, platform in EXTERNAL_JOB_BOARDS:
            if re.search(pattern, href, re.IGNORECASE):
                logger.debug(f"Found external job board link: {href}")
                found_urls.append((href, platform))
    
    # Check iframes for external job board sources
    for iframe in soup.find_all('iframe', src=True):
        src = iframe.get('src', '')
        for pattern, platform in EXTERNAL_JOB_BOARDS:
            if re.search(pattern, src, re.IGNORECASE):
                logger.info(f"Found external job board iframe")
                found_urls.append((src, platform))
    
    # Check data attributes that might contain job board URLs
    for elem in soup.find_all(attrs={'data-src': True}):
        data_src = elem.get('data-src', '')
        for pattern, platform in EXTERNAL_JOB_BOARDS:
            if re.search(pattern, data_src, re.IGNORECASE):
                logger.debug(f"Found external job board data-src: {data_src}")
                found_urls.append((data_src, platform))
    
    # Check for JavaScript variables/configs containing job board URLs
    for script in soup.find_all('script'):
        if script.string:
            for pattern, platform in EXTERNAL_JOB_BOARDS:
                match = re.search(
                    rf'["\']?(https?://[^\s"\'<>]*{pattern}[^\s"\'<>]*)["\']?',
                    script.string, re.IGNORECASE
                )
                if match:
                    url = match.group(1)
                    logger.debug(f"Found external job board in script: {url}")
                    found_urls.append((url, platform))
    
    if not found_urls:
        return None
    
    # First, try to find a valid job listing URL (not privacy/legal pages)
    for url, platform in found_urls:
        if _is_job_board_url_valid(url):
            logger.debug(f"Using valid job board URL: {url}")
            return url
    
    # If all URLs are invalid (privacy/legal pages), normalize the first one
    url, platform = found_urls[0]
    normalized_url = _normalize_job_board_url(url)
    logger.info(f"Normalized job board URL: {url} -> {normalized_url}")
    return normalized_url

