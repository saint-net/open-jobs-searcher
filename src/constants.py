"""Global constants for the application.

Centralizes magic numbers and configuration values.
"""

# =============================================================================
# Pagination
# =============================================================================

MAX_PAGINATION_PAGES = 3  # Maximum pages to scan for jobs
MAX_SITEMAP_URLS = 300  # Maximum URLs to fetch from sitemap


# =============================================================================
# LLM
# =============================================================================

MAX_LLM_RETRIES = 3  # Maximum retries for LLM calls
MAX_URLS_FOR_LLM = 500  # Maximum URLs to send to LLM for analysis
LLM_TIMEOUT = 300.0  # Default timeout for LLM calls (seconds)


# =============================================================================
# HTML Size Limits
# =============================================================================

MIN_JOB_SECTION_SIZE = 300  # Minimum size for job section HTML (bytes)
MAX_JOB_SECTION_SIZE = 200_000  # Maximum size for job section HTML (bytes)
MIN_VALID_HTML_SIZE = 1000  # Minimum size for valid HTML content (bytes)


# =============================================================================
# Browser Timeouts (milliseconds)
# =============================================================================

BROWSER_DEFAULT_TIMEOUT = 30_000  # Default page timeout (30s)
BROWSER_NAVIGATION_TIMEOUT = 10_000  # Network idle timeout (10s)
BROWSER_WAIT_SHORT = 500  # Short wait for DOM updates
BROWSER_WAIT_MEDIUM = 1_000  # Medium wait
BROWSER_WAIT_LONG = 2_000  # Wait after page load
BROWSER_WAIT_CF_CHALLENGE = 5_000  # Wait for Cloudflare challenge
IFRAME_FETCH_TIMEOUT = 5 * 60  # Iframe fetch timeout (5 minutes, in seconds)


# =============================================================================
# HTTP Status Codes
# =============================================================================

HTTP_CLIENT_ERROR_MIN = 400
HTTP_CLIENT_ERROR_MAX = 499
HTTP_SERVER_ERROR_MIN = 500

