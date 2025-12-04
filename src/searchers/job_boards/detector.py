"""Job board platform detection utilities."""

import logging
import re
from typing import Optional
from urllib.parse import urlparse

import httpx
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
    (r'job\.deloitte\.com', 'deloitte'),
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


def detect_job_board_platform(url: str, html: Optional[str] = None) -> Optional[str]:
    """Detect job board platform from URL and optionally HTML.
    
    Args:
        url: URL to check
        html: Optional HTML content to analyze for platform signatures
        
    Returns:
        Platform name or None if not detected
    """
    # First check URL patterns
    for pattern, platform in EXTERNAL_JOB_BOARDS:
        if re.search(pattern, url, re.IGNORECASE):
            return platform
    
    # If HTML is provided, check for platform signatures
    if html:
        # Check for Recruitee (uses custom domains)
        if detect_recruitee_from_html(html):
            return 'recruitee'
    
    return None


def _is_job_board_url_valid(url: str) -> bool:
    """Check if the job board URL is a valid jobs page (not privacy/legal)."""
    for pattern in SKIP_URL_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return False
    return True


def _normalize_job_board_url(url: str, platform: str = None) -> str:
    """Normalize job board URL to the main jobs page.
    
    For example:
    - https://company.jobs.personio.com/privacy-policy -> https://company.jobs.personio.com/
    - https://company.jobs.personio.com/job/123 -> https://company.jobs.personio.com/
    - https://job-boards.greenhouse.io/company/jobs/123 -> https://job-boards.greenhouse.io/company
    - https://boards.greenhouse.io/company/jobs/123 -> https://boards.greenhouse.io/company
    - https://apply.workable.com/company/gdpr_policy -> https://apply.workable.com/company/
    - https://job.deloitte.com/search?search=27pilots -> https://job.deloitte.com/search?search=27pilots (keep as-is)
    """
    parsed = urlparse(url)
    
    # Handle Greenhouse URLs - keep company slug
    if platform == 'greenhouse' or 'greenhouse.io' in parsed.netloc:
        # Path like /company/jobs/123 -> /company
        path_parts = parsed.path.strip('/').split('/')
        if path_parts and path_parts[0]:
            company_slug = path_parts[0]
            return f"{parsed.scheme}://{parsed.netloc}/{company_slug}"
        return f"{parsed.scheme}://{parsed.netloc}/"
    
    # Handle Workable URLs - keep company slug, strip everything else
    if platform == 'workable' or 'workable.com' in parsed.netloc:
        # Path like /company/gdpr_policy -> /company/
        # Path like /company/j/ABC123 -> /company/
        path_parts = parsed.path.strip('/').split('/')
        if path_parts and path_parts[0]:
            company_slug = path_parts[0]
            return f"{parsed.scheme}://{parsed.netloc}/{company_slug}/"
        return f"{parsed.scheme}://{parsed.netloc}/"
    
    # Handle Deloitte URLs - keep search parameters intact
    if platform == 'deloitte' or 'deloitte.com' in parsed.netloc:
        # Keep the full URL with search parameters
        return url
    
    # For other platforms, keep only language parameter if present
    query_params = parsed.query
    lang_match = re.search(r'language=([a-z]{2})', query_params)
    lang_param = f"?language={lang_match.group(1)}" if lang_match else ""
    
    return f"{parsed.scheme}://{parsed.netloc}/{lang_param}"


def detect_recruitee_from_html(html: str) -> bool:
    """Detect if a page is powered by Recruitee.
    
    Recruitee sites can use custom domains but have telltale signs:
    - "Hiring with Recruitee" or "recruitee" links in footer
    - recruiteecdn.com images
    - careers-analytics.recruitee.com tracking
    - Specific data attributes or script patterns
    
    Args:
        html: HTML content of the page
        
    Returns:
        True if page is powered by Recruitee
    """
    soup = BeautifulSoup(html, 'lxml')
    
    # Check for Recruitee footer link
    for link in soup.find_all('a', href=True):
        href = link.get('href', '').lower()
        text = link.get_text(strip=True).lower()
        if 'recruitee' in href or 'recruitee' in text:
            logger.debug(f"Detected Recruitee from link: {href or text}")
            return True
    
    # Check for Recruitee CDN images
    for img in soup.find_all('img', src=True):
        if 'recruiteecdn.com' in img.get('src', ''):
            logger.debug("Detected Recruitee from CDN image")
            return True
    
    # Check for Recruitee scripts or tracking
    for script in soup.find_all('script'):
        src = script.get('src', '')
        text = script.string or ''
        if 'recruitee' in src.lower() or 'recruitee' in text.lower():
            logger.debug("Detected Recruitee from script")
            return True
    
    # Check raw HTML for recruitee patterns
    if 'recruitee' in html.lower() or 'recruiteecdn.com' in html.lower():
        logger.debug("Detected Recruitee from raw HTML")
        return True
    
    return False


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
    
    # For platforms where individual job URLs should be normalized to main board
    # (e.g., Greenhouse /company/jobs/123 -> /company)
    # (e.g., Personio /job/123 -> /)
    # (e.g., Workable /company/gdpr_policy -> /company)
    normalize_platforms = {'greenhouse', 'personio', 'workable'}
    
    # Collect unique normalized URLs per platform
    seen_normalized = set()
    best_url = None
    
    for url, platform in found_urls:
        if not _is_job_board_url_valid(url):
            continue
            
        # Normalize URL for platforms that need it
        if platform in normalize_platforms:
            normalized = _normalize_job_board_url(url, platform)
            if normalized not in seen_normalized:
                seen_normalized.add(normalized)
                if best_url is None:
                    best_url = normalized
                    logger.debug(f"Normalized job board URL: {url} -> {normalized}")
        else:
            # For other platforms, use as-is
            if best_url is None:
                best_url = url
                logger.debug(f"Using valid job board URL: {url}")
    
    if best_url:
        return best_url
    
    # If all URLs are invalid (privacy/legal pages), normalize the first one
    url, platform = found_urls[0]
    normalized_url = _normalize_job_board_url(url, platform)
    logger.info(f"Normalized job board URL: {url} -> {normalized_url}")
    return normalized_url

