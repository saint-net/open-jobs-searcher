"""Integration tests for lazy loading handling in BrowserLoader.

These tests verify that:
- BrowserLoader correctly scrolls to trigger lazy-loaded content
- Intersection Observer patterns are handled
- Article count increases after scrolling

Run with: pytest tests/test_lazy_loading.py -v
"""

import pytest
import threading
import tempfile
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from functools import partial

from bs4 import BeautifulSoup

from src.browser.loader import BrowserLoader


# HTML with lazy loading via Intersection Observer
# Simulates a job board that loads 3 jobs initially, then 3 more on each scroll
# Total: 9 jobs after 2 lazy load triggers
# Uses scroll-based loading that triggers on scroll position, not intersection
LAZY_LOADING_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>Jobs - Lazy Loading Test</title>
    <style>
        article { padding: 20px; margin: 10px; border: 1px solid #ccc; min-height: 50px; }
        #loader { height: 100px; background: #f0f0f0; text-align: center; padding: 40px; }
        body { min-height: 200vh; }
    </style>
</head>
<body>
<h1>Open Positions</h1>
<div id="jobs">
    <article class="job"><h3>Software Developer (m/w/d)</h3><span>Berlin</span></article>
    <article class="job"><h3>Product Manager (m/w/d)</h3><span>Munich</span></article>
    <article class="job"><h3>DevOps Engineer (m/w/d)</h3><span>Hamburg</span></article>
</div>
<div id="loader">Loading more jobs...</div>
<script>
let page = 1;
const maxPages = 3;
const jobTitles = [
    ['Data Scientist (m/w/d)', 'Frontend Developer (m/w/d)', 'Backend Developer (m/w/d)'],
    ['QA Engineer (m/w/d)', 'UX Designer (m/w/d)', 'Sales Manager (m/w/d)']
];
const locations = ['Berlin', 'Munich', 'Hamburg', 'Frankfurt', 'Remote'];

// Scroll-based loading - more reliable than IntersectionObserver for testing
let loading = false;
window.addEventListener('scroll', function() {
    if (loading || page >= maxPages) return;
    
    // Trigger when scrolled past 20% of page
    const scrollPercent = window.scrollY / (document.body.scrollHeight - window.innerHeight);
    const threshold = (page - 1) * 0.3 + 0.2; // 20% for first load, 50% for second
    
    if (scrollPercent >= threshold) {
        loading = true;
        setTimeout(() => {
            const jobs = document.getElementById('jobs');
            const titles = jobTitles[page - 1] || [];
            
            titles.forEach((title, i) => {
                const article = document.createElement('article');
                article.className = 'job';
                article.innerHTML = '<h3>' + title + '</h3><span>' + locations[i % locations.length] + '</span>';
                jobs.appendChild(article);
            });
            
            page++;
            loading = false;
            
            if (page >= maxPages) {
                document.getElementById('loader').style.display = 'none';
            }
        }, 100); // Short delay
    }
});
</script>
</body>
</html>
"""

# HTML without lazy loading (static content)
STATIC_HTML = """<!DOCTYPE html>
<html>
<head><title>Jobs - Static</title></head>
<body>
<h1>Open Positions</h1>
<div id="jobs">
    <article class="job"><h3>Software Developer (m/w/d)</h3></article>
    <article class="job"><h3>Product Manager (m/w/d)</h3></article>
    <article class="job"><h3>DevOps Engineer (m/w/d)</h3></article>
</div>
</body>
</html>
"""

# HTML with mouse-wheel triggered lazy loading
WHEEL_TRIGGERED_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>Jobs - Wheel Trigger</title>
    <style>
        article { padding: 20px; margin: 10px; border: 1px solid #ccc; }
        body { min-height: 300vh; }
    </style>
</head>
<body>
<h1>Open Positions</h1>
<div id="jobs">
    <article class="job"><h3>Initial Job 1</h3></article>
    <article class="job"><h3>Initial Job 2</h3></article>
</div>
<script>
let loaded = false;
// Only load more jobs after wheel event (simulates sites that detect real user interaction)
document.addEventListener('wheel', function onWheel() {
    if (loaded) return;
    loaded = true;
    
    setTimeout(() => {
        const jobs = document.getElementById('jobs');
        for (let i = 3; i <= 6; i++) {
            const article = document.createElement('article');
            article.className = 'job';
            article.innerHTML = '<h3>Lazy Job ' + i + '</h3>';
            jobs.appendChild(article);
        }
    }, 150);
    
    document.removeEventListener('wheel', onWheel);
});
</script>
</body>
</html>
"""


class _MockServerHandler(SimpleHTTPRequestHandler):
    """Custom handler that serves test HTML files (prefixed with _ to avoid pytest collection)."""
    
    def __init__(self, *args, directory=None, **kwargs):
        self.test_dir = directory
        super().__init__(*args, directory=directory, **kwargs)
    
    def log_message(self, format, *args):
        """Suppress server logs during tests."""
        pass


@pytest.fixture(scope="module")
def mock_server():
    """Start local HTTP server with lazy loading test pages.
    
    Serves:
    - /lazy.html - Intersection Observer lazy loading (9 jobs total)
    - /static.html - Static page (3 jobs)
    - /wheel.html - Wheel-event triggered loading (6 jobs total)
    """
    # Create temp directory with test HTML files
    tmpdir = tempfile.mkdtemp()
    
    (Path(tmpdir) / "lazy.html").write_text(LAZY_LOADING_HTML, encoding="utf-8")
    (Path(tmpdir) / "static.html").write_text(STATIC_HTML, encoding="utf-8")
    (Path(tmpdir) / "wheel.html").write_text(WHEEL_TRIGGERED_HTML, encoding="utf-8")
    
    # Create handler with custom directory
    handler = partial(_MockServerHandler, directory=tmpdir)
    
    # Start server on random available port
    server = HTTPServer(('127.0.0.1', 0), handler)
    port = server.server_address[1]
    
    # Run server in background thread
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    
    yield f"http://127.0.0.1:{port}"
    
    server.shutdown()


class TestLazyLoadingWithMockServer:
    """Integration tests for lazy loading using local mock server."""
    
    @pytest.mark.asyncio
    async def test_scroll_loads_all_lazy_articles(self, mock_server):
        """Should load all 9 articles after scrolling (3 initial + 6 lazy).
        
        This tests Intersection Observer pattern commonly used by job boards.
        """
        async with BrowserLoader(headless=True) as loader:
            html, final_url, page, context = await loader.fetch_with_page(f"{mock_server}/lazy.html")
            if page:
                await page.close()
            if context:
                await context.close()
        
        assert html is not None
        article_count = html.count('<article')
        
        # 3 initial + 3 (page 2) + 3 (page 3) = 9 total
        assert article_count >= 9, f"Expected ≥9 articles after lazy loading, got {article_count}"
        
        # Verify specific job titles from lazy-loaded content
        assert "Data Scientist" in html, "Lazy-loaded job 'Data Scientist' not found"
        assert "UX Designer" in html, "Lazy-loaded job 'UX Designer' not found"
    
    @pytest.mark.asyncio
    async def test_static_page_returns_all_content(self, mock_server):
        """Static pages should return all content without scrolling."""
        async with BrowserLoader(headless=True) as loader:
            html, final_url, page, context = await loader.fetch_with_page(f"{mock_server}/static.html")
            if page:
                await page.close()
            if context:
                await context.close()
        
        assert html is not None
        article_count = html.count('<article')
        
        assert article_count == 3, f"Expected exactly 3 articles on static page, got {article_count}"
    
    @pytest.mark.asyncio
    async def test_wheel_event_triggers_loading(self, mock_server):
        """Should trigger lazy loading via mouse wheel events.
        
        Some sites only load content after detecting real user interaction
        (wheel events, not just scroll position changes).
        """
        async with BrowserLoader(headless=True) as loader:
            html, final_url, page, context = await loader.fetch_with_page(f"{mock_server}/wheel.html")
            if page:
                await page.close()
            if context:
                await context.close()
        
        assert html is not None
        article_count = html.count('<article')
        
        # 2 initial + 4 lazy = 6 total
        assert article_count >= 6, f"Expected ≥6 articles after wheel trigger, got {article_count}"
        
        # Verify lazy-loaded content
        assert "Lazy Job" in html, "Wheel-triggered lazy content not loaded"
    
    @pytest.mark.asyncio
    async def test_fetch_without_scroll_gets_initial_only(self, mock_server):
        """Regular fetch (without scroll) should only get initial content.
        
        Note: We check article count in DOM, not text presence, because
        the job titles exist as string literals in the JS code.
        """
        async with BrowserLoader(headless=True) as loader:
            # Use regular fetch, not fetch_with_page
            html = await loader.fetch(f"{mock_server}/lazy.html")
        
        assert html is not None
        
        # Count actual article elements rendered in DOM (class="job")
        # Initial 3 are in HTML, lazy-loaded ones would be added by JS
        soup = BeautifulSoup(html, 'lxml')
        articles = soup.find_all('article', class_='job')
        
        # Should have only initial 3 articles (no scrolling triggered lazy load)
        assert len(articles) == 3, f"Expected 3 initial articles without scroll, got {len(articles)}"


class TestScrollBehavior:
    """Tests for scroll mechanism specifics."""
    
    @pytest.mark.asyncio
    async def test_scroll_returns_to_top(self, mock_server):
        """After scrolling, page should be scrolled back to top for consistent extraction."""
        async with BrowserLoader(headless=True) as loader:
            # Access page directly to check scroll position
            loader._browser = None
            await loader.start()
            
            context = await loader._browser.new_context()
            page = await context.new_page()
            
            await page.goto(f"{mock_server}/lazy.html", wait_until="domcontentloaded")
            
            # Perform scroll
            await loader._scroll_and_wait_for_content(page, max_scrolls=5)
            
            # Check scroll position is at top
            scroll_y = await page.evaluate("window.scrollY")
            
            await page.close()
            await context.close()
        
        assert scroll_y == 0, f"Page should be scrolled to top, but scrollY={scroll_y}"
    
    @pytest.mark.asyncio
    async def test_article_count_tracking(self, mock_server):
        """Scroll should detect when new articles appear."""
        async with BrowserLoader(headless=True) as loader:
            await loader.start()
            
            context = await loader._browser.new_context()
            page = await context.new_page()
            
            await page.goto(f"{mock_server}/lazy.html", wait_until="domcontentloaded")
            
            # Get initial count
            initial_count = await page.evaluate("document.querySelectorAll('article').length")
            
            # Scroll with more attempts to get past the 2000px spacer
            await loader._scroll_and_wait_for_content(page, max_scrolls=15)
            
            # Get final count
            final_count = await page.evaluate("document.querySelectorAll('article').length")
            
            await page.close()
            await context.close()
        
        assert initial_count == 3, f"Initial article count should be 3, got {initial_count}"
        # With 2000px spacer, we expect at least some lazy loading (>3)
        # Full 9 may require more scrolls depending on viewport
        assert final_count > initial_count, f"Article count should increase after scrolling (was {initial_count}, now {final_count})"
        assert final_count >= 6, f"Final article count should be ≥6, got {final_count}"


class TestEdgeCases:
    """Tests for edge cases in lazy loading."""
    
    @pytest.mark.asyncio
    async def test_handles_no_loader_element(self, mock_server):
        """Should handle pages without loader/spinner elements gracefully."""
        async with BrowserLoader(headless=True) as loader:
            html, final_url, page, context = await loader.fetch_with_page(f"{mock_server}/static.html")
            if page:
                await page.close()
            if context:
                await context.close()
        
        # Should complete without errors
        assert html is not None
        assert "Software Developer" in html
    
    @pytest.mark.asyncio
    async def test_handles_fast_loading(self, mock_server):
        """Should handle pages where content loads instantly."""
        async with BrowserLoader(headless=True) as loader:
            html, final_url, page, context = await loader.fetch_with_page(f"{mock_server}/static.html")
            if page:
                await page.close()
            if context:
                await context.close()
        
        # Should complete quickly without unnecessary waiting
        assert html is not None


# Marker for real site tests (slow, requires network)
pytest_plugins = ["pytest_asyncio"]


class TestRealSitesLazyLoading:
    """E2E tests against real sites with known lazy loading.
    
    These tests are slow and require network access.
    Run with: pytest tests/test_lazy_loading.py -v -m e2e
    Skip with: pytest tests/test_lazy_loading.py -v -m "not e2e"
    """
    
    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_abs_karriere_lazy_loading(self):
        """abs-karriere.de/jobs/ loads jobs via lazy loading (Intersection Observer).
        
        This site shows jobs in article elements. The number of jobs varies
        depending on company hiring activity.
        
        This was the original bug report that led to fixing _scroll_and_wait_for_content.
        """
        async with BrowserLoader(headless=True) as loader:
            html, final_url, page, context = await loader.fetch_with_page(
                "https://abs-karriere.de/jobs/"
            )
            if page:
                await page.close()
            if context:
                await context.close()
        
        assert html is not None, "Failed to load abs-karriere.de/jobs/"
        
        # Count article elements (each job is in an <article>)
        soup = BeautifulSoup(html, 'lxml')
        articles = soup.find_all('article')
        
        # Site should have at least 1 job (actual count varies with hiring activity)
        assert len(articles) >= 1, (
            f"Expected ≥1 jobs on abs-karriere.de/jobs/, got {len(articles)}. "
            "Site may be down or page structure changed."
        )
        
        # Verify some expected job content
        html_lower = html.lower()
        assert "softwareentwickler" in html_lower or "developer" in html_lower or "manager" in html_lower, (
            "Expected to find job listing on abs-karriere.de"
        )


# Run with: pytest tests/test_lazy_loading.py -v
# Skip E2E tests: pytest tests/test_lazy_loading.py -v -m "not e2e"
# Run only E2E: pytest tests/test_lazy_loading.py -v -m e2e
