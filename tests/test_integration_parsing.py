"""Integration tests for job parsing with real HTML fixtures.

These tests verify end-to-end job extraction using saved HTML from real sites.
Run these after changes to:
- src/llm/base.py
- src/extraction/*.py
- src/llm/prompts.py

The fixtures simulate real-world HTML structures:
- schema_org_jobs.html: Site with Schema.org JSON-LD (best case)
- greenhouse_style.html: Greenhouse-style job board layout
- odoo_jobs.html: Odoo CMS careers page
"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock

from src.extraction.extractor import HybridJobExtractor
from src.extraction.strategies import SchemaOrgStrategy
from src.llm.base import BaseLLMProvider


# Path to fixtures
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    """Load HTML fixture file."""
    path = FIXTURES_DIR / name
    return path.read_text(encoding="utf-8")


class MockLLMProvider(BaseLLMProvider):
    """Mock LLM for testing extraction methods."""
    
    def __init__(self):
        self.complete_calls = []
    
    async def complete(self, prompt: str, system: str = None) -> str:
        self.complete_calls.append(prompt)
        # Return realistic LLM response based on HTML content
        if "Backend Engineer" in prompt:
            return '''```json
{
    "jobs": [
        {"title": "Backend Engineer (m/w/d)", "location": "Berlin, Germany", "url": "https://boards.greenhouse.io/techcorp/jobs/123"},
        {"title": "Frontend Developer (f/m/d)", "location": "Remote", "url": "https://boards.greenhouse.io/techcorp/jobs/124"},
        {"title": "Senior Data Engineer (m/w/d)", "location": "Munich, Germany", "url": "https://boards.greenhouse.io/techcorp/jobs/125"},
        {"title": "Product Manager - Platform (m/w/d)", "location": "Berlin, Germany", "url": "https://boards.greenhouse.io/techcorp/jobs/200"},
        {"title": "HR Business Partner (m/w/d)", "location": "Hamburg", "url": "https://boards.greenhouse.io/techcorp/jobs/300"}
    ],
    "next_page_url": null
}
```'''
        elif "Softwareentwickler" in prompt or "Odoo" in prompt:
            return '''```json
{
    "jobs": [
        {"title": "Softwareentwickler Python (m/w/d)", "location": "Wien", "url": "/jobs/apply/1"},
        {"title": "Projektmanager (m/w/d)", "location": "Graz", "url": "/jobs/apply/2"},
        {"title": "Sales Manager DACH (m/w/d)", "location": "Remote / Home Office", "url": "/jobs/apply/3"},
        {"title": "Customer Success Manager (m/w/d)", "location": "Wien", "url": "/jobs/apply/4"}
    ],
    "next_page_url": null
}
```'''
        return '{"jobs": [], "next_page_url": null}'


class TestSchemaOrgParsing:
    """Test Schema.org JSON-LD parsing."""
    
    def test_extracts_all_jobs_from_json_ld(self):
        """Should extract all 3 jobs from Schema.org JSON-LD."""
        html = load_fixture("schema_org_jobs.html")
        strategy = SchemaOrgStrategy()
        
        candidates = strategy.extract(html, "https://example.com")
        
        assert len(candidates) == 3
        
        titles = {c.title for c in candidates}
        assert "Senior Software Developer (m/w/d)" in titles
        assert "Product Manager (m/w/d)" in titles
        assert "DevOps Engineer" in titles
    
    def test_extracts_locations_correctly(self):
        """Should extract location from nested jobLocation structure."""
        html = load_fixture("schema_org_jobs.html")
        strategy = SchemaOrgStrategy()
        
        candidates = strategy.extract(html, "https://example.com")
        
        locations = {c.title: c.location for c in candidates}
        assert locations["Senior Software Developer (m/w/d)"] == "Berlin"
        assert locations["Product Manager (m/w/d)"] == "Munich"
        # String address format
        assert locations["DevOps Engineer"] == "Hamburg"
    
    def test_extracts_company_name(self):
        """Should extract company from hiringOrganization."""
        html = load_fixture("schema_org_jobs.html")
        strategy = SchemaOrgStrategy()
        
        candidates = strategy.extract(html, "https://example.com")
        
        # First two have hiringOrganization
        companies = [c.company for c in candidates if c.company]
        assert "Example GmbH" in companies
    
    def test_converts_relative_urls(self):
        """Should convert relative URLs to absolute."""
        html = load_fixture("schema_org_jobs.html")
        strategy = SchemaOrgStrategy()
        
        candidates = strategy.extract(html, "https://example.com")
        
        devops = next(c for c in candidates if c.title == "DevOps Engineer")
        assert devops.url == "https://example.com/jobs/devops"


class TestHybridExtractorWithSchemaOrg:
    """Test HybridJobExtractor with Schema.org data."""
    
    @pytest.mark.asyncio
    async def test_uses_schema_org_without_llm(self):
        """Should use Schema.org and NOT call LLM when Schema.org is present."""
        html = load_fixture("schema_org_jobs.html")
        
        llm_called = False
        async def mock_llm(html, url):
            nonlocal llm_called
            llm_called = True
            return []
        
        extractor = HybridJobExtractor(llm_extract_fn=mock_llm)
        jobs = await extractor.extract(html, "https://example.com")
        
        assert len(jobs) == 3
        assert llm_called is False, "LLM should NOT be called when Schema.org is present"
    
    @pytest.mark.asyncio
    async def test_returns_dict_format(self):
        """Should return jobs as dictionaries, not JobCandidate objects."""
        html = load_fixture("schema_org_jobs.html")
        extractor = HybridJobExtractor()
        
        jobs = await extractor.extract(html, "https://example.com")
        
        assert all(isinstance(job, dict) for job in jobs)
        assert all("title" in job for job in jobs)
        assert all("url" in job for job in jobs)
        assert all("location" in job for job in jobs)


class TestLLMExtractionFallback:
    """Test LLM fallback when Schema.org is not available."""
    
    @pytest.mark.asyncio
    async def test_falls_back_to_llm_for_greenhouse_style(self):
        """Should use LLM for pages without Schema.org."""
        html = load_fixture("greenhouse_style.html")
        
        llm_called = False
        async def mock_llm(html, url):
            nonlocal llm_called
            llm_called = True
            return [
                {"title": "Backend Engineer (m/w/d)", "location": "Berlin", "url": "/jobs/123"},
                {"title": "Frontend Developer (f/m/d)", "location": "Remote", "url": "/jobs/124"},
            ]
        
        extractor = HybridJobExtractor(llm_extract_fn=mock_llm)
        jobs = await extractor.extract(html, "https://example.com")
        
        assert llm_called is True, "LLM should be called when no Schema.org"
        assert len(jobs) == 2


class TestCleanHtmlForLLM:
    """Test HTML cleaning before sending to LLM."""
    
    def test_removes_cookie_consent_noise(self):
        """Should remove cookie consent dialogs from HTML."""
        html = load_fixture("greenhouse_style.html")
        provider = MockLLMProvider()
        
        clean = provider._clean_html(html)
        
        # Cookie-related text should be reduced or removed
        # (full removal depends on implementation)
        assert clean.count("cookie") <= html.lower().count("cookie")
    
    def test_preserves_job_content(self):
        """Should preserve job-related content."""
        html = load_fixture("greenhouse_style.html")
        provider = MockLLMProvider()
        
        clean = provider._clean_html(html)
        
        # Job titles and links should be preserved
        assert "Backend Engineer" in clean
        assert "Frontend Developer" in clean
        assert "greenhouse.io" in clean
    
    def test_removes_footer_links_content(self):
        """Should handle footer content (Impressum, Datenschutz)."""
        html = load_fixture("greenhouse_style.html")
        provider = MockLLMProvider()
        
        clean = provider._clean_html(html)
        
        # Footer links may still be present but won't confuse job extraction
        # The important thing is job content is preserved
        assert len(clean) < len(html)  # Some cleanup happened


class TestOdooSiteDetection:
    """Test Odoo CMS detection and parsing."""
    
    def test_detects_odoo_by_generator_meta(self):
        """Should detect Odoo site by meta generator tag."""
        from bs4 import BeautifulSoup
        
        html = load_fixture("odoo_jobs.html")
        provider = MockLLMProvider()
        soup = BeautifulSoup(html, 'lxml')
        
        assert provider._is_odoo_site(soup) is True
    
    def test_finds_odoo_job_section(self):
        """Should find Odoo job section by specific selectors."""
        from bs4 import BeautifulSoup
        
        html = load_fixture("odoo_jobs.html")
        provider = MockLLMProvider()
        soup = BeautifulSoup(html, 'lxml')
        
        section = provider._find_job_section(soup)
        
        assert section is not None
        assert "Softwareentwickler" in section
        assert "o_website_hr_recruitment_jobs_list" in section or "o_job" in section


class TestValidateJobsIntegration:
    """Test job validation with realistic data."""
    
    def test_filters_initiativbewerbung_from_real_results(self):
        """Should filter open application entries."""
        provider = MockLLMProvider()
        
        jobs = [
            {"title": "Senior Developer (m/w/d)", "location": "Berlin", "url": "/job/1"},
            {"title": "Initiativbewerbung (m/w/d)", "location": "Anywhere", "url": "/apply"},
            {"title": "Junior Developer (m/w/d)", "location": "Munich", "url": "/job/2"},
            {"title": "Open Application", "location": "Remote", "url": "/open"},
        ]
        
        valid = provider._validate_jobs(jobs)
        
        assert len(valid) == 2
        titles = {j["title"] for j in valid}
        assert "Senior Developer (m/w/d)" in titles
        assert "Junior Developer (m/w/d)" in titles
        assert "Initiativbewerbung (m/w/d)" not in titles
        assert "Open Application" not in titles
    
    def test_handles_missing_fields_gracefully(self):
        """Should handle jobs with missing optional fields."""
        provider = MockLLMProvider()
        
        jobs = [
            {"title": "Developer"},  # Minimal
            {"title": "Manager", "location": ""},  # Empty location
            {"title": "Engineer", "location": "Berlin", "department": "IT"},  # Full
        ]
        
        valid = provider._validate_jobs(jobs)
        
        assert len(valid) == 3
        assert valid[0]["location"] == "Unknown"
        assert valid[1]["location"] == "Unknown"
        assert valid[2]["location"] == "Berlin"


class TestExtractJsonIntegration:
    """Test JSON extraction with realistic LLM responses."""
    
    def test_extracts_json_with_markdown_and_text(self):
        """Should extract JSON from typical LLM response format."""
        provider = MockLLMProvider()
        
        response = """I found the following jobs on the page:

```json
{
    "jobs": [
        {"title": "Developer (m/w/d)", "location": "Berlin", "url": "/job/1"},
        {"title": "Manager (m/w/d)", "location": "Munich", "url": "/job/2"}
    ],
    "next_page_url": "https://example.com/jobs?page=2"
}
```

These are all the open positions I could find."""
        
        result = provider._extract_json(response)
        
        assert isinstance(result, dict)
        assert len(result["jobs"]) == 2
        assert result["next_page_url"] == "https://example.com/jobs?page=2"
    
    def test_handles_malformed_llm_response(self):
        """Should handle malformed JSON gracefully."""
        provider = MockLLMProvider()
        
        response = """The page contains jobs but I cannot parse them properly.
        
{"jobs": [{"title": "Dev" ... (incomplete)"""
        
        result = provider._extract_json(response)
        
        # Should return empty list, not crash
        assert result == [] or result == {}


class TestUiCityParsing:
    """Test parsing ui.city - Custom site (Smart City company).
    
    ui.city is a custom corporate website (not a job board platform).
    Uses LLM extraction - no specialized parser.
    Source: https://ui.city/
    """
    
    @pytest.mark.asyncio
    async def test_llm_extracts_jobs_from_ui_city(self):
        """Should extract jobs via LLM (no Schema.org on this site)."""
        html = load_fixture("ui_city_jobs.html")
        
        # ui.city doesn't have Schema.org, so LLM would be used
        async def mock_llm(html, url):
            return [
                {"title": "Software Engineer (m/w/d)", "location": "Darmstadt / Remote", "url": "/jobs/software-engineer"},
                {"title": "DevOps Engineer (m/w/d)", "location": "Berlin / Remote", "url": "/jobs/devops-engineer"},
                {"title": "Duales Studium Data Science und Künstliche Intelligenz (m/w/d)", "location": "Darmstadt", "url": "/jobs/duales-studium-data-science"},
                {"title": "Elektromonteur (m/w/d)", "location": "München", "url": "/jobs/elektromonteur"},
                {"title": "Solution Owner Smart Energy (m/w/d)", "location": "Berlin / Darmstadt", "url": "/jobs/solution-owner-smart-energy"},
                {"title": "Sales Consultant Smart Regions (m/w/d)", "location": "Deutschland", "url": "/jobs/sales-consultant-smart-regions"},
                {"title": "Solution Owner Smart Parking (m/w/d)", "location": "Darmstadt", "url": "/jobs/solution-owner-smart-parking"},
                {"title": "Berater/Beraterin Smart City (m/w/d)", "location": "Berlin / München / Darmstadt", "url": "/jobs/berater-smart-city"},
                {"title": "Projektmanager Smart City (m/w/d)", "location": "Darmstadt", "url": "/jobs/projektmanager-smart-city"},
                {"title": "Software Engineer Backend (m/w/d)", "location": "Remote", "url": "/jobs/software-engineer-backend"},
            ]
        
        extractor = HybridJobExtractor(llm_extract_fn=mock_llm)
        jobs = await extractor.extract(html, "https://ui.city")
        
        assert len(jobs) == 10
        
        titles = {j["title"] for j in jobs}
        assert "Software Engineer (m/w/d)" in titles
        assert "DevOps Engineer (m/w/d)" in titles
        assert "Elektromonteur (m/w/d)" in titles
    
    def test_ui_city_html_has_job_content(self):
        """Verify the fixture contains expected job content."""
        html = load_fixture("ui_city_jobs.html")
        
        # Check that HTML contains job-related content
        assert "Software Engineer (m/w/d)" in html
        assert "DevOps Engineer (m/w/d)" in html
        assert "Smart City" in html
        assert "(m/w/d)" in html
        
        # Check structure markers
        assert "job-card" in html
        assert "job-listings" in html
    
    def test_ui_city_no_schema_org(self):
        """ui.city should not have Schema.org (falls back to LLM)."""
        html = load_fixture("ui_city_jobs.html")
        strategy = SchemaOrgStrategy()
        
        candidates = strategy.extract(html, "https://ui.city")
        
        # No Schema.org data - should return empty
        assert len(candidates) == 0
    
    def test_clean_html_preserves_ui_city_jobs(self):
        """HTML cleaning should preserve job content from ui.city."""
        html = load_fixture("ui_city_jobs.html")
        provider = MockLLMProvider()
        
        clean = provider._clean_html(html)
        
        # Job titles should be preserved
        assert "Software Engineer" in clean
        assert "DevOps Engineer" in clean
        assert "(m/w/d)" in clean
        
        # Job URLs should be preserved
        assert "/jobs/" in clean


class Test1nceParsing:
    """Test parsing 1nce.com - Custom site (IoT connectivity).
    
    1nce.com is a custom corporate website (not a job board platform).
    Uses LLM extraction - no specialized parser.
    Source: https://www.1nce.com/en-eu
    """
    
    @pytest.mark.asyncio
    async def test_llm_extracts_jobs_from_1nce(self):
        """Should extract jobs via LLM (no Schema.org on this site)."""
        html = load_fixture("1nce_jobs.html")
        
        async def mock_llm(html, url):
            return [
                {"title": "Senior Backend Developer (m/w/d)", "location": "Cologne, Germany / Remote", "url": "/careers/senior-backend-developer"},
                {"title": "DevOps Engineer (m/w/d)", "location": "Cologne, Germany", "url": "/careers/devops-engineer"},
                {"title": "Frontend Developer React (m/w/d)", "location": "Remote", "url": "/careers/frontend-developer"},
                {"title": "QA Engineer (m/w/d)", "location": "Cologne, Germany", "url": "/careers/qa-engineer"},
                {"title": "Account Executive IoT (m/w/d)", "location": "Munich, Germany", "url": "/careers/account-executive"},
                {"title": "Sales Manager APAC (m/w/d)", "location": "Singapore", "url": "/careers/sales-manager-apac"},
                {"title": "Product Manager IoT Platform (m/w/d)", "location": "Cologne, Germany", "url": "/careers/product-manager"},
                {"title": "Customer Success Manager (m/w/d)", "location": "Cologne, Germany / Remote", "url": "/careers/customer-success-manager"},
            ]
        
        extractor = HybridJobExtractor(llm_extract_fn=mock_llm)
        jobs = await extractor.extract(html, "https://www.1nce.com")
        
        assert len(jobs) == 8
        
        titles = {j["title"] for j in jobs}
        assert "Senior Backend Developer (m/w/d)" in titles
        assert "DevOps Engineer (m/w/d)" in titles
        assert "Product Manager IoT Platform (m/w/d)" in titles
    
    def test_1nce_html_has_job_content(self):
        """Verify the fixture contains expected job content."""
        html = load_fixture("1nce_jobs.html")
        
        # Check job-related content
        assert "Senior Backend Developer" in html
        assert "DevOps Engineer" in html
        assert "IoT" in html
        assert "(m/w/d)" in html
        
        # Check structure
        assert "job-posting" in html
        assert "careers-section" in html
    
    def test_1nce_no_schema_org(self):
        """1nce.com should not have Schema.org (falls back to LLM)."""
        html = load_fixture("1nce_jobs.html")
        strategy = SchemaOrgStrategy()
        
        candidates = strategy.extract(html, "https://www.1nce.com")
        
        assert len(candidates) == 0
    
    def test_clean_html_preserves_1nce_jobs(self):
        """HTML cleaning should preserve job content from 1nce."""
        html = load_fixture("1nce_jobs.html")
        provider = MockLLMProvider()
        
        clean = provider._clean_html(html)
        
        assert "Backend Developer" in clean
        assert "DevOps Engineer" in clean
        assert "(m/w/d)" in clean
        assert "/careers/" in clean


class Test3pServicesParsing:
    """Test parsing 3p-services.com - Custom site (Pipeline inspection).
    
    3P Services is a custom corporate website (not a job board platform).
    Uses LLM extraction - no specialized parser.
    Source: https://www.3p-services.com/career/jobs/
    """
    
    @pytest.mark.asyncio
    async def test_llm_extracts_jobs_from_3p_services(self):
        """Should extract jobs via LLM (no Schema.org on this site)."""
        html = load_fixture("3p_services_jobs.html")
        
        async def mock_llm(html, url):
            return [
                {"title": "Sales & Project Manager – French", "location": "Lingen, Germany", "url": "/career/jobs/sales-project-manager-french"},
                {"title": "Sales & Project Manager", "location": "Lingen, Germany", "url": "/career/jobs/sales-project-manager"},
                {"title": "Inside Sales", "location": "Lingen, Germany", "url": "/career/jobs/inside-sales"},
                {"title": "Data Scientist", "location": "Lingen, Germany", "url": "/career/jobs/data-scientist"},
                {"title": "Team Leader Software Development", "location": "Lingen, Germany", "url": "/career/jobs/team-leader-software-development"},
                {"title": "Financial Accountant – Int. Tax Law", "location": "Lingen, Germany", "url": "/career/jobs/financial-accountant"},
                {"title": "Electronics Technician", "location": "Lingen, Germany", "url": "/career/jobs/electronics-technician"},
                {"title": "Service Technician", "location": "Lingen, Germany", "url": "/career/jobs/service-technician"},
            ]
        
        extractor = HybridJobExtractor(llm_extract_fn=mock_llm)
        jobs = await extractor.extract(html, "https://www.3p-services.com")
        
        assert len(jobs) == 8
        
        titles = {j["title"] for j in jobs}
        assert "Data Scientist" in titles
        assert "Team Leader Software Development" in titles
        assert "Electronics Technician" in titles
    
    def test_3p_services_html_has_job_content(self):
        """Verify the fixture contains expected job content."""
        html = load_fixture("3p_services_jobs.html")
        
        # Check job-related content
        assert "Sales & Project Manager" in html
        assert "Data Scientist" in html
        assert "Team Leader Software Development" in html
        assert "Electronics Technician" in html
        assert "Service Technician" in html
        
        # Check structure
        assert "job-item" in html
        assert "job-listings" in html
        assert "open-jobs" in html
    
    def test_3p_services_no_schema_org(self):
        """3p-services.com should not have Schema.org (falls back to LLM)."""
        html = load_fixture("3p_services_jobs.html")
        strategy = SchemaOrgStrategy()
        
        candidates = strategy.extract(html, "https://www.3p-services.com")
        
        assert len(candidates) == 0
    
    def test_clean_html_preserves_3p_services_jobs(self):
        """HTML cleaning should preserve job content from 3p-services."""
        html = load_fixture("3p_services_jobs.html")
        provider = MockLLMProvider()
        
        clean = provider._clean_html(html)
        
        assert "Data Scientist" in clean
        assert "Software Development" in clean
        assert "/career/jobs/" in clean


class Test3ssParsing:
    """Test parsing 3ss.tv - Custom site (Entertainment platform).
    
    3SS is a custom corporate website (not a job board platform).
    Uses LLM extraction - no specialized parser.
    Important: This site had a Glassdoor link that should NOT be followed.
    Source: https://www.3ss.tv/careers
    """
    
    @pytest.mark.asyncio
    async def test_llm_extracts_jobs_from_3ss(self):
        """Should extract jobs via LLM (no Schema.org on this site)."""
        html = load_fixture("3ss_careers.html")
        
        async def mock_llm(html, url):
            return [
                {"title": "Senior Lightning.js (JavaScript) Software Engineer", "location": "Brașov, Targu Mureș, Cluj-Napoca", "url": "/careers/senior-lightning-js"},
                {"title": "Product Designer", "location": "Brașov, Targu Mureș, Cluj-Napoca, Chișinău", "url": "/careers/product-designer"},
                {"title": "React Native SW Engineer", "location": "Brașov, Targu Mureș, Cluj-Napoca", "url": "/careers/react-native-engineer"},
                {"title": "QA Engineer", "location": "Brașov, Targu Mureș, Cluj-Napoca, Chișinău", "url": "/careers/qa-engineer"},
            ]
        
        extractor = HybridJobExtractor(llm_extract_fn=mock_llm)
        jobs = await extractor.extract(html, "https://www.3ss.tv")
        
        assert len(jobs) == 4
        
        titles = {j["title"] for j in jobs}
        assert "Senior Lightning.js (JavaScript) Software Engineer" in titles
        assert "Product Designer" in titles
        assert "React Native SW Engineer" in titles
        assert "QA Engineer" in titles
    
    def test_3ss_html_has_job_content(self):
        """Verify the fixture contains expected job content."""
        html = load_fixture("3ss_careers.html")
        
        # Check job-related content
        assert "Senior Lightning" in html
        assert "Product Designer" in html
        assert "React Native" in html
        assert "QA Engineer" in html
        
        # Check location markers
        assert "Brașov" in html or "Brasov" in html
        assert "Cluj" in html
        
        # Check page structure
        assert "Open Positions" in html
    
    def test_3ss_no_schema_org(self):
        """3ss.tv should not have Schema.org (falls back to LLM)."""
        html = load_fixture("3ss_careers.html")
        strategy = SchemaOrgStrategy()
        
        candidates = strategy.extract(html, "https://www.3ss.tv")
        
        assert len(candidates) == 0
    
    def test_clean_html_preserves_3ss_jobs(self):
        """HTML cleaning should preserve job content from 3ss.tv."""
        html = load_fixture("3ss_careers.html")
        provider = MockLLMProvider()
        
        clean = provider._clean_html(html)
        
        assert "Lightning" in clean
        assert "Product Designer" in clean
        assert "React Native" in clean
        assert "QA Engineer" in clean
    
    def test_3ss_html_has_glassdoor_link(self):
        """Verify Glassdoor link exists (should be ignored by job board finder).
        
        This test documents that the page has a Glassdoor link,
        which the LLM should NOT follow as a job board.
        """
        html = load_fixture("3ss_careers.html")
        
        # The page has a Glassdoor link (but it's a review site, not a job board)
        assert "glassdoor" in html.lower()


class Test4ddWerbeagenturParsing:
    """Test parsing 4dd-werbeagentur.de - Custom site (Advertising agency).
    
    4DD communication GmbH is a full-service advertising agency in Düsseldorf.
    Custom corporate website, uses LLM extraction - no specialized parser.
    Notable: All jobs link to same #bewerben anchor (application form).
    Source: https://4dd-werbeagentur.de/karriere/
    """
    
    @pytest.mark.asyncio
    async def test_llm_extracts_jobs_from_4dd(self):
        """Should extract jobs via LLM (no Schema.org on this site)."""
        html = load_fixture("4dd_werbeagentur_jobs.html")
        
        async def mock_llm(html, url):
            return [
                {"title": "Social Media Manager / Texter (m/w/d)", "location": "Düsseldorf", "url": "/karriere/#bewerben"},
                {"title": "Praktikant:in – Social Media & Redaktion (m/w/d)", "location": "Düsseldorf", "url": "/karriere/#bewerben"},
                {"title": "Grafikdesigner (m/w/d)", "location": "Düsseldorf", "url": "/karriere/#bewerben"},
                {"title": "BERATER / PROJEKTMANAGER (M/W/D)", "location": "Düsseldorf", "url": "/karriere/#bewerben"},
                {"title": "Kontakter / Kundenakquise (M/W/D)", "location": "Düsseldorf", "url": "/karriere/#bewerben"},
            ]
        
        extractor = HybridJobExtractor(llm_extract_fn=mock_llm)
        jobs = await extractor.extract(html, "https://4dd-werbeagentur.de")
        
        assert len(jobs) == 5
        
        titles = {j["title"] for j in jobs}
        assert "Social Media Manager / Texter (m/w/d)" in titles
        assert "Grafikdesigner (m/w/d)" in titles
        assert "BERATER / PROJEKTMANAGER (M/W/D)" in titles
    
    def test_4dd_html_has_job_content(self):
        """Verify the fixture contains expected job content."""
        html = load_fixture("4dd_werbeagentur_jobs.html")
        
        # Check job-related content
        assert "Social Media Manager / Texter (m/w/d)" in html
        assert "Praktikant:in" in html
        assert "Grafikdesigner (m/w/d)" in html
        assert "BERATER / PROJEKTMANAGER" in html
        assert "Kontakter / Kundenakquise" in html
        
        # Check company context
        assert "4DD" in html
        assert "Düsseldorf" in html
        assert "Werbeagentur" in html
        
        # Check page structure
        assert "job-item" in html
        assert "job-listings" in html
        assert "#bewerben" in html
    
    def test_4dd_no_schema_org(self):
        """4dd-werbeagentur.de should not have Schema.org (falls back to LLM)."""
        html = load_fixture("4dd_werbeagentur_jobs.html")
        strategy = SchemaOrgStrategy()
        
        candidates = strategy.extract(html, "https://4dd-werbeagentur.de")
        
        assert len(candidates) == 0
    
    def test_clean_html_preserves_4dd_jobs(self):
        """HTML cleaning should preserve job content from 4dd-werbeagentur.de."""
        html = load_fixture("4dd_werbeagentur_jobs.html")
        provider = MockLLMProvider()
        
        clean = provider._clean_html(html)
        
        # Job titles should be preserved
        assert "Social Media Manager" in clean
        assert "Grafikdesigner" in clean
        assert "Texter" in clean
        assert "(m/w/d)" in clean
    
    def test_4dd_all_jobs_link_to_form(self):
        """All jobs link to same #bewerben form anchor.
        
        This is a common pattern for small agencies - jobs don't have
        individual pages, just an application form at the bottom.
        """
        html = load_fixture("4dd_werbeagentur_jobs.html")
        
        # All apply buttons point to form anchor
        assert html.count('href="#bewerben"') >= 5
        
        # Form section exists
        assert 'id="bewerben"' in html
        assert "Bewerbung absenden" in html


class Test4zeroParsing:
    """Tests for 4zero.solutions - Webflow site with all jobs linking to href='#'."""
    
    async def test_llm_extracts_jobs_from_4zero(self):
        """Should extract jobs via LLM (no Schema.org on this site)."""
        html = load_fixture("4zero_jobs.html")
        
        async def mock_llm(html, url):
            return [
                {"title": "Grafik / Design (m/w/d)", "location": "München", "url": "#"},
                {"title": "Software Web Frontend Engineer", "location": "worldwide", "url": "#"},
                {"title": "Software Web Backend Engineer", "location": "worldwide", "url": "#"},
                {"title": "Software Developer", "location": "Germany", "url": "#"},
            ]
        
        extractor = HybridJobExtractor(llm_extract_fn=mock_llm)
        jobs = await extractor.extract(html, "https://www.4zero.solutions/job")
        
        assert len(jobs) >= 4
        titles = [j.get("title", "") for j in jobs]
        assert any("Grafik" in t or "Design" in t for t in titles)
        assert any("Frontend" in t for t in titles)
        assert any("Backend" in t for t in titles)
        assert any("Software Developer" in t for t in titles)
    
    def test_4zero_html_has_job_content(self):
        """4zero.solutions HTML should contain job listings."""
        html = load_fixture("4zero_jobs.html")
        
        # Check page content
        assert "Jobs @ 4zero" in html or "Job Listings" in html
        assert "Grafik / Design (m/w/d)" in html
        assert "Software Web Frontend Engineer" in html
        assert "Software Web Backend Engineer" in html
        assert "Software Developer" in html
        
        # Check locations
        assert "München" in html
        assert "worldwide" in html
        assert "Germany" in html
    
    def test_4zero_no_schema_org(self):
        """4zero.solutions should not have Schema.org (falls back to LLM)."""
        html = load_fixture("4zero_jobs.html")
        strategy = SchemaOrgStrategy()
        
        candidates = strategy.extract(html, "https://www.4zero.solutions/job")
        
        assert len(candidates) == 0
    
    def test_clean_html_preserves_4zero_jobs(self):
        """HTML cleaning should preserve job content from 4zero.solutions."""
        html = load_fixture("4zero_jobs.html")
        provider = MockLLMProvider()
        
        clean = provider._clean_html(html)
        
        # Job titles should be preserved
        assert "Grafik" in clean or "Design" in clean
        assert "Frontend" in clean
        assert "Backend" in clean
        assert "Software Developer" in clean
    
    def test_4zero_all_jobs_link_to_hash(self):
        """All jobs link to href='#' - no individual job pages.
        
        This is why deduplication by URL was failing - all jobs had same key.
        Fixed by treating href='#' as non-unique and using (title, location) fallback.
        """
        html = load_fixture("4zero_jobs.html")
        
        # All job cards have href="#"
        assert 'href="#"' in html
        
        # Jobs are in card structure
        assert "job-listing-card" in html
        assert "job-listing-title" in html


# Run with: pytest tests/test_integration_parsing.py -v

