"""Pytest configuration and fixtures for smoke tests."""

import pytest


# Configure pytest-asyncio
pytest_plugins = ["pytest_asyncio"]


@pytest.fixture
def sample_html_with_jobs():
    """Sample HTML with job listings for testing."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Careers</title></head>
    <body>
        <h1>Open Positions</h1>
        <div class="jobs-list">
            <div class="job-item">
                <a href="/jobs/senior-developer">
                    <h3>Senior Software Developer (m/w/d)</h3>
                </a>
                <span class="location">Berlin</span>
            </div>
            <div class="job-item">
                <a href="/jobs/product-manager">
                    <h3>Product Manager (m/w/d)</h3>
                </a>
                <span class="location">Munich</span>
            </div>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def sample_html_with_schema_org():
    """Sample HTML with Schema.org JobPosting data."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Careers</title>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": "Backend Developer",
            "url": "https://example.com/jobs/backend-dev",
            "jobLocation": {
                "@type": "Place",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": "Hamburg"
                }
            },
            "hiringOrganization": {
                "@type": "Organization",
                "name": "Example Corp"
            }
        }
        </script>
    </head>
    <body>
        <h1>Backend Developer</h1>
        <p>Join our team!</p>
    </body>
    </html>
    """


@pytest.fixture
def sample_html_empty():
    """Empty HTML page without jobs."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>About Us</title></head>
    <body>
        <h1>About Our Company</h1>
        <p>We are a great company.</p>
    </body>
    </html>
    """


@pytest.fixture
def sample_llm_response_jobs():
    """Sample LLM response with job listings."""
    return """
    ```json
    {
        "jobs": [
            {"title": "Senior Developer (m/w/d)", "location": "Berlin", "url": "https://example.com/jobs/1", "department": "Engineering"},
            {"title": "Product Manager", "location": "Munich", "url": "https://example.com/jobs/2", "department": null}
        ],
        "next_page_url": null
    }
    ```
    """


@pytest.fixture
def sample_llm_response_url():
    """Sample LLM response with URL."""
    return "The careers page is at https://example.com/careers"


@pytest.fixture
def sample_dirty_html():
    """HTML with scripts, styles, and noise for cleaning tests."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test</title>
        <script>alert('test');</script>
        <style>.foo { color: red; }</style>
        <link rel="stylesheet" href="style.css">
    </head>
    <body>
        <!-- This is a comment -->
        <nav>Navigation</nav>
        <div class="job-list">
            <h2 class="job-title">Developer (m/w/d)</h2>
            <a href="/jobs/1" class="apply-btn long-class-name-to-remove">Apply</a>
        </div>
        <script>console.log('another script');</script>
        <svg><path d="M0 0"/></svg>
        <noscript>Enable JS</noscript>
    </body>
    </html>
    """

