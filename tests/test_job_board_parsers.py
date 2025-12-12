"""Tests for job board parsers.

These tests verify that each job board parser correctly extracts jobs
from platform-specific HTML structures.

Run after changes to: src/searchers/job_boards/*.py
"""

import pytest
from pathlib import Path
from bs4 import BeautifulSoup

from src.searchers.job_boards.lever import LeverParser
from src.searchers.job_boards.personio import PersonioParser
from src.searchers.job_boards.recruitee import RecruiteeParser
from src.searchers.job_boards.workable import WorkableParser
from src.searchers.job_boards.greenhouse import GreenhouseParser
from src.searchers.job_boards.odoo import OdooParser
from src.searchers.job_boards.hrworks import HRworksParser
from src.searchers.job_boards.hibob import HiBobParser


# Path to fixtures
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    """Load HTML fixture file."""
    path = FIXTURES_DIR / name
    return path.read_text(encoding="utf-8")


def make_soup(html: str) -> BeautifulSoup:
    """Create BeautifulSoup from HTML."""
    return BeautifulSoup(html, 'lxml')


class TestLeverParser:
    """Tests for Lever job board parser."""
    
    def test_extracts_all_jobs(self):
        """Should extract all jobs from Lever HTML."""
        html = load_fixture("lever_jobs.html")
        soup = make_soup(html)
        parser = LeverParser()
        
        jobs = parser.parse(soup, "https://jobs.lever.co/levercompany")
        
        assert len(jobs) == 4
    
    def test_extracts_titles_correctly(self):
        """Should extract job titles."""
        html = load_fixture("lever_jobs.html")
        soup = make_soup(html)
        parser = LeverParser()
        
        jobs = parser.parse(soup, "https://jobs.lever.co/levercompany")
        titles = {j["title"] for j in jobs}
        
        assert "Senior Backend Engineer" in titles
        assert "Product Designer (m/w/d)" in titles
        assert "DevOps Engineer" in titles
        assert "Data Scientist" in titles
    
    def test_extracts_locations(self):
        """Should extract job locations."""
        html = load_fixture("lever_jobs.html")
        soup = make_soup(html)
        parser = LeverParser()
        
        jobs = parser.parse(soup, "https://jobs.lever.co/levercompany")
        
        berlin_job = next(j for j in jobs if "Backend" in j["title"])
        assert "Berlin" in berlin_job["location"]
        
        remote_job = next(j for j in jobs if "Designer" in j["title"])
        assert "Remote" in remote_job["location"]
    
    def test_extracts_urls(self):
        """Should extract full job URLs."""
        html = load_fixture("lever_jobs.html")
        soup = make_soup(html)
        parser = LeverParser()
        
        jobs = parser.parse(soup, "https://jobs.lever.co/levercompany")
        
        assert all(j["url"].startswith("https://jobs.lever.co/") for j in jobs)
        assert any("abc123" in j["url"] for j in jobs)


class TestPersonioParser:
    """Tests for Personio job board parser."""
    
    def test_extracts_all_jobs(self):
        """Should extract all jobs from Personio HTML."""
        html = load_fixture("personio_jobs.html")
        soup = make_soup(html)
        parser = PersonioParser()
        
        jobs = parser.parse(soup, "https://personio-company.jobs.personio.de")
        
        assert len(jobs) == 4
    
    def test_extracts_titles(self):
        """Should extract job titles."""
        html = load_fixture("personio_jobs.html")
        soup = make_soup(html)
        parser = PersonioParser()
        
        jobs = parser.parse(soup, "https://personio-company.jobs.personio.de")
        titles = [j["title"] for j in jobs]
        
        # Should have the main titles
        assert any("Software Developer" in t for t in titles)
        assert any("Product Manager" in t for t in titles)
        assert any("Data Engineer" in t for t in titles)
    
    def test_extracts_job_urls(self):
        """Should extract Personio job URLs."""
        html = load_fixture("personio_jobs.html")
        soup = make_soup(html)
        parser = PersonioParser()
        
        jobs = parser.parse(soup, "https://personio-company.jobs.personio.de")
        
        assert all("/job/" in j["url"] for j in jobs)
        assert any("12345" in j["url"] for j in jobs)


class TestRecruiteeParser:
    """Tests for Recruitee job board parser."""
    
    def test_extracts_from_embedded_json(self):
        """Should extract jobs from embedded JSON."""
        html = load_fixture("recruitee_jobs.html")
        soup = make_soup(html)
        parser = RecruiteeParser()
        
        jobs = parser.parse(soup, "https://recruiteecompany.recruitee.com")
        
        assert len(jobs) == 3
    
    def test_extracts_titles(self):
        """Should extract job titles from JSON."""
        html = load_fixture("recruitee_jobs.html")
        soup = make_soup(html)
        parser = RecruiteeParser()
        
        jobs = parser.parse(soup, "https://recruiteecompany.recruitee.com")
        titles = {j["title"] for j in jobs}
        
        assert "Frontend Developer (m/w/d)" in titles
        assert "UX Designer" in titles
        assert "Sales Manager DACH" in titles
    
    def test_extracts_locations_from_json(self):
        """Should extract locations from JSON fields."""
        html = load_fixture("recruitee_jobs.html")
        soup = make_soup(html)
        parser = RecruiteeParser()
        
        jobs = parser.parse(soup, "https://recruiteecompany.recruitee.com")
        
        frontend_job = next(j for j in jobs if "Frontend" in j["title"])
        assert "Berlin" in frontend_job["location"]
        
        ux_job = next(j for j in jobs if "UX" in j["title"])
        assert "Remote" in ux_job["location"]
    
    def test_extracts_departments(self):
        """Should extract department from JSON."""
        html = load_fixture("recruitee_jobs.html")
        soup = make_soup(html)
        parser = RecruiteeParser()
        
        jobs = parser.parse(soup, "https://recruiteecompany.recruitee.com")
        
        frontend_job = next(j for j in jobs if "Frontend" in j["title"])
        assert frontend_job["department"] == "Engineering"
    
    def test_extracts_careers_urls(self):
        """Should extract careers_url from JSON."""
        html = load_fixture("recruitee_jobs.html")
        soup = make_soup(html)
        parser = RecruiteeParser()
        
        jobs = parser.parse(soup, "https://recruiteecompany.recruitee.com")
        
        assert all("/o/" in j["url"] for j in jobs)


class TestWorkableParser:
    """Tests for Workable job board parser."""
    
    def test_extracts_from_json_ld(self):
        """Should extract jobs from JSON-LD."""
        html = load_fixture("workable_jobs.html")
        soup = make_soup(html)
        parser = WorkableParser()
        
        jobs = parser.parse(soup, "https://apply.workable.com/workablecompany")
        
        # JSON-LD has 2 jobs
        assert len(jobs) >= 2
    
    def test_extracts_titles(self):
        """Should extract job titles."""
        html = load_fixture("workable_jobs.html")
        soup = make_soup(html)
        parser = WorkableParser()
        
        jobs = parser.parse(soup, "https://apply.workable.com/workablecompany")
        titles = {j["title"] for j in jobs}
        
        assert "QA Engineer" in titles
        assert "Full Stack Developer (m/w/d)" in titles
    
    def test_extracts_locations_from_json_ld(self):
        """Should extract locations from JSON-LD structure."""
        html = load_fixture("workable_jobs.html")
        soup = make_soup(html)
        parser = WorkableParser()
        
        jobs = parser.parse(soup, "https://apply.workable.com/workablecompany")
        
        qa_job = next(j for j in jobs if "QA" in j["title"])
        assert "Cluj" in qa_job["location"] or "Romania" in qa_job["location"]
    
    def test_extracts_department_from_category(self):
        """Should extract department from occupationalCategory."""
        html = load_fixture("workable_jobs.html")
        soup = make_soup(html)
        parser = WorkableParser()
        
        jobs = parser.parse(soup, "https://apply.workable.com/workablecompany")
        
        qa_job = next(j for j in jobs if "QA" in j["title"])
        assert qa_job["department"] == "Quality Assurance"


class TestGreenhouseParser:
    """Tests for Greenhouse job board parser."""
    
    def test_extracts_from_greenhouse_style(self):
        """Should extract jobs from Greenhouse-style HTML."""
        html = load_fixture("greenhouse_style.html")
        soup = make_soup(html)
        parser = GreenhouseParser()
        
        jobs = parser.parse(soup, "https://boards.greenhouse.io/techcorp")
        
        assert len(jobs) == 5
    
    def test_extracts_titles(self):
        """Should extract job titles."""
        html = load_fixture("greenhouse_style.html")
        soup = make_soup(html)
        parser = GreenhouseParser()
        
        jobs = parser.parse(soup, "https://boards.greenhouse.io/techcorp")
        titles = {j["title"] for j in jobs}
        
        assert "Backend Engineer (m/w/d)" in titles
        assert "Frontend Developer (f/m/d)" in titles
        assert "HR Business Partner (m/w/d)" in titles
    
    def test_extracts_urls(self):
        """Should extract job URLs."""
        html = load_fixture("greenhouse_style.html")
        soup = make_soup(html)
        parser = GreenhouseParser()
        
        jobs = parser.parse(soup, "https://boards.greenhouse.io/techcorp")
        
        assert all("/jobs/" in j["url"] for j in jobs)


class TestOdooParser:
    """Tests for Odoo job board parser."""
    
    def test_extracts_from_odoo_html(self):
        """Should extract jobs from Odoo HTML."""
        html = load_fixture("odoo_jobs.html")
        soup = make_soup(html)
        parser = OdooParser()
        
        jobs = parser.parse(soup, "https://odoo-company.com")
        
        assert len(jobs) == 4
    
    def test_extracts_titles(self):
        """Should extract job titles."""
        html = load_fixture("odoo_jobs.html")
        soup = make_soup(html)
        parser = OdooParser()
        
        jobs = parser.parse(soup, "https://odoo-company.com")
        titles = {j["title"] for j in jobs}
        
        assert "Softwareentwickler Python (m/w/d)" in titles
        assert "Projektmanager (m/w/d)" in titles
        assert "Sales Manager DACH (m/w/d)" in titles
    
    def test_extracts_urls(self):
        """Should extract job detail URLs."""
        html = load_fixture("odoo_jobs.html")
        soup = make_soup(html)
        parser = OdooParser()
        
        jobs = parser.parse(soup, "https://odoo-company.com")
        
        assert all("/jobs/detail/" in j["url"] for j in jobs)


class TestTalentionDetection:
    """Tests for Talention platform detection.
    
    Talention is a pure SPA - jobs are loaded via JavaScript.
    We only detect the platform, no HTML parsing possible.
    """
    
    def test_detects_talention_platform(self):
        """Should detect Talention from HTML markers."""
        from src.searchers.job_boards.detector import detect_job_board_platform
        
        html = load_fixture("talention_jobs.html")
        platform = detect_job_board_platform("https://jobs.4u-at-work.de/jobs", html)
        
        assert platform == "talention"
    
    def test_talention_has_no_static_jobs(self):
        """Talention SPA has no jobs in static HTML (expected behavior).
        
        Jobs are loaded dynamically via JavaScript, so static HTML
        parsing won't find any jobs. This is expected.
        """
        html = load_fixture("talention_jobs.html")
        soup = make_soup(html)
        
        # No job links in static HTML (SPA loads them via JS)
        job_links = [a for a in soup.find_all('a', href=True) 
                     if '/stellenangebote/' in a.get('href', '') 
                     and '/bewerbung' not in a.get('href', '')]
        
        # Only initiativ bewerbung link exists, no actual job listings
        assert len(job_links) == 0


class TestHRworksParser:
    """Tests for HRworks job board parser."""
    
    def test_extracts_all_jobs(self):
        """Should extract all jobs from HRworks HTML."""
        html = load_fixture("hrworks_jobs.html")
        soup = make_soup(html)
        parser = HRworksParser()
        
        jobs = parser.parse(soup, "https://jobs.4sellers.de/de")
        
        # Should have 4 jobs (before filtering)
        assert len(jobs) == 4
    
    def test_extracts_titles(self):
        """Should extract job titles from h2 elements."""
        html = load_fixture("hrworks_jobs.html")
        soup = make_soup(html)
        parser = HRworksParser()
        
        jobs = parser.parse(soup, "https://jobs.4sellers.de/de")
        titles = {j["title"] for j in jobs}
        
        assert "Berufsorientierung" in titles
        assert "Initiativbewerbung" in titles
        assert any("Küchenprofi" in t for t in titles)
        assert any("Finanzbuchhaltung" in t for t in titles)
    
    def test_extracts_locations(self):
        """Should extract locations from icomoon-location elements."""
        html = load_fixture("hrworks_jobs.html")
        soup = make_soup(html)
        parser = HRworksParser()
        
        jobs = parser.parse(soup, "https://jobs.4sellers.de/de")
        
        beruf_job = next(j for j in jobs if "Berufsorientierung" in j["title"])
        assert "Rain" in beruf_job["location"] or "Deutschland" in beruf_job["location"]
    
    def test_extracts_departments(self):
        """Should extract department from metadata div."""
        html = load_fixture("hrworks_jobs.html")
        soup = make_soup(html)
        parser = HRworksParser()
        
        jobs = parser.parse(soup, "https://jobs.4sellers.de/de")
        
        beruf_job = next(j for j in jobs if "Berufsorientierung" in j["title"])
        assert beruf_job["department"] == "IT und Software-Entwicklung"
    
    def test_extracts_urls(self):
        """Should extract job URLs with id parameter."""
        html = load_fixture("hrworks_jobs.html")
        soup = make_soup(html)
        parser = HRworksParser()
        
        jobs = parser.parse(soup, "https://jobs.4sellers.de/de")
        
        assert all("?id=" in j["url"] for j in jobs)
        assert all(j["url"].startswith("https://jobs.4sellers.de/") for j in jobs)
    
    def test_parse_and_filter_removes_initiativbewerbung(self):
        """Should filter out Initiativbewerbung when using parse_and_filter."""
        html = load_fixture("hrworks_jobs.html")
        soup = make_soup(html)
        parser = HRworksParser()
        
        # Raw parse includes Initiativbewerbung
        all_jobs = parser.parse(soup, "https://jobs.4sellers.de/de")
        assert any("Initiativbewerbung" in j["title"] for j in all_jobs)
        
        # Filtered parse removes it
        filtered_jobs = parser.parse_and_filter(soup, "https://jobs.4sellers.de/de")
        assert not any("Initiativbewerbung" in j["title"] for j in filtered_jobs)
        assert len(filtered_jobs) == 3


class TestParserPlatformNames:
    """Test that all parsers have correct platform names."""
    
    def test_lever_platform_name(self):
        assert LeverParser().platform_name == "lever"
    
    def test_personio_platform_name(self):
        assert PersonioParser().platform_name == "personio"
    
    def test_recruitee_platform_name(self):
        assert RecruiteeParser().platform_name == "recruitee"
    
    def test_workable_platform_name(self):
        assert WorkableParser().platform_name == "workable"
    
    def test_greenhouse_platform_name(self):
        assert GreenhouseParser().platform_name == "greenhouse"
    
    def test_odoo_platform_name(self):
        assert OdooParser().platform_name == "odoo"
    
    def test_hrworks_platform_name(self):
        assert HRworksParser().platform_name == "hrworks"


class TestParserEmptyInput:
    """Test parsers handle empty/invalid input gracefully."""
    
    def test_lever_empty_html(self):
        soup = make_soup("<html><body></body></html>")
        jobs = LeverParser().parse(soup, "https://example.com")
        assert jobs == []
    
    def test_personio_empty_html(self):
        soup = make_soup("<html><body></body></html>")
        jobs = PersonioParser().parse(soup, "https://example.com")
        assert jobs == []
    
    def test_recruitee_empty_html(self):
        soup = make_soup("<html><body></body></html>")
        jobs = RecruiteeParser().parse(soup, "https://example.com")
        assert jobs == []
    
    def test_workable_empty_html(self):
        soup = make_soup("<html><body></body></html>")
        jobs = WorkableParser().parse(soup, "https://example.com")
        assert jobs == []
    
    def test_greenhouse_empty_html(self):
        soup = make_soup("<html><body></body></html>")
        jobs = GreenhouseParser().parse(soup, "https://example.com")
        assert jobs == []
    
    def test_odoo_empty_html(self):
        soup = make_soup("<html><body></body></html>")
        jobs = OdooParser().parse(soup, "https://example.com")
        assert jobs == []
    
    def test_hrworks_empty_html(self):
        soup = make_soup("<html><body></body></html>")
        jobs = HRworksParser().parse(soup, "https://example.com")
        assert jobs == []


class TestNonJobFiltering:
    """Tests for filtering non-job entries (Initiativbewerbung, etc.)."""
    
    def test_filters_initiativbewerbung(self):
        """Should filter out Initiativbewerbung entries."""
        parser = PersonioParser()
        assert parser._is_non_job_entry("Initiativbewerbung (d/m/w)") is True
        assert parser._is_non_job_entry("Initiativ Bewerbung") is True
    
    def test_filters_open_application(self):
        """Should filter out Open Application entries."""
        parser = LeverParser()
        assert parser._is_non_job_entry("Open Application") is True
        assert parser._is_non_job_entry("Unsolicited Application") is True
        assert parser._is_non_job_entry("Speculative Application") is True
        assert parser._is_non_job_entry("General Application") is True
    
    def test_filters_spontanbewerbung(self):
        """Should filter out Spontanbewerbung entries."""
        parser = GreenhouseParser()
        assert parser._is_non_job_entry("Spontanbewerbung") is True
        assert parser._is_non_job_entry("Blindbewerbung") is True
    
    def test_keeps_real_jobs(self):
        """Should keep real job titles."""
        parser = PersonioParser()
        assert parser._is_non_job_entry("Software Engineer (m/w/d)") is False
        assert parser._is_non_job_entry("Senior Developer") is False
        assert parser._is_non_job_entry("Product Manager") is False
    
    def test_parse_and_filter_removes_non_jobs(self):
        """parse_and_filter() should remove non-job entries."""
        html = """
        <div class="positions-list">
            <a href="/job/123" class="job-position">
                <span class="job-position__title">Software Engineer (m/w/d)</span>
            </a>
            <a href="/job/124" class="job-position">
                <span class="job-position__title">Initiativbewerbung (d/m/w)</span>
            </a>
            <a href="/job/125" class="job-position">
                <span class="job-position__title">DevOps Engineer (m/w/d)</span>
            </a>
        </div>
        """
        soup = make_soup(html)
        parser = PersonioParser()
        
        # parse() returns all including Initiativbewerbung
        all_jobs = parser.parse(soup, "https://example.personio.de")
        assert len(all_jobs) == 3
        
        # parse_and_filter() removes Initiativbewerbung
        filtered_jobs = parser.parse_and_filter(soup, "https://example.personio.de")
        assert len(filtered_jobs) == 2
        
        titles = {j["title"] for j in filtered_jobs}
        assert "Initiativbewerbung (d/m/w)" not in titles
        assert "Software Engineer (m/w/d)" in titles
        assert "DevOps Engineer (m/w/d)" in titles


class TestPdfLinkStrategy:
    """Tests for PDF link job extraction strategy."""
    
    def test_extracts_jobs_from_pdf_links(self):
        """Should extract jobs from PDF document links."""
        from src.extraction.strategies import PdfLinkStrategy
        
        html = load_fixture("pdf_links_jobs.html")
        strategy = PdfLinkStrategy()
        
        candidates = strategy.extract(html, "https://example.com/jobs")
        
        # Should find 4 job PDFs (not the product brochure, AGB, or datenschutz)
        assert len(candidates) == 4
    
    def test_4pipes_real_site(self):
        """Should extract jobs from real 4pipes.de website."""
        from src.extraction.strategies import PdfLinkStrategy
        
        html = load_fixture("4pipes_jobs.html")
        strategy = PdfLinkStrategy()
        
        candidates = strategy.extract(html, "https://www.4pipes.de/jobs.htm")
        
        # Should find 3 job PDFs
        assert len(candidates) == 3
        
        titles = {c.title for c in candidates}
        assert "IT-Systemadministrator" in titles
        assert "Vertriebsmitarbeiter-Innendienst" in titles
        assert "Vertriebsmitarbeiter-Innendienst-Export" in titles
        
        # All URLs should point to PDFs
        for c in candidates:
            assert c.url.endswith(".pdf")
            assert "4pipes" in c.url.lower() or "stellenausschreibung" in c.url.lower()
    
    def test_extracts_titles_correctly(self):
        """Should extract job titles from PDF filenames."""
        from src.extraction.strategies import PdfLinkStrategy
        
        html = load_fixture("pdf_links_jobs.html")
        strategy = PdfLinkStrategy()
        
        candidates = strategy.extract(html, "https://example.com/jobs")
        titles = {c.title for c in candidates}
        
        assert "IT-Systemadministrator" in titles
        assert "Vertriebsmitarbeiter-Innendienst" in titles
        # Check that Senior-Developer is in one of the titles
        assert any("Senior-Developer" in t for t in titles)
        assert any("Projektmanager" in t for t in titles)
    
    def test_builds_full_urls(self):
        """Should build full URLs from relative paths."""
        from src.extraction.strategies import PdfLinkStrategy
        
        html = load_fixture("pdf_links_jobs.html")
        strategy = PdfLinkStrategy()
        
        candidates = strategy.extract(html, "https://example.com/jobs")
        
        # All URLs should be absolute
        for c in candidates:
            assert c.url.startswith("https://example.com/")
            assert c.url.endswith(".pdf")
    
    def test_ignores_non_job_pdfs(self):
        """Should not extract PDFs without job-related keywords."""
        from src.extraction.strategies import PdfLinkStrategy
        
        html = load_fixture("pdf_links_jobs.html")
        strategy = PdfLinkStrategy()
        
        candidates = strategy.extract(html, "https://example.com/jobs")
        titles = {c.title.lower() for c in candidates}
        
        # These should not be extracted
        assert not any("brochure" in t for t in titles)
        assert not any("agb" in t for t in titles)
        assert not any("datenschutz" in t for t in titles)
    
    def test_capitalizes_acronyms(self):
        """Should properly capitalize known acronyms like IT, HR."""
        from src.extraction.strategies import PdfLinkStrategy
        
        strategy = PdfLinkStrategy()
        
        # Direct test of _extract_title_from_filename
        title = strategy._extract_title_from_filename("stellenausschreibung_it-systemadministrator_v2_20251027.pdf")
        assert "IT-" in title  # IT should be uppercase
    
    def test_deduplicates_jobs(self):
        """Should not return duplicate job titles."""
        from src.extraction.strategies import PdfLinkStrategy
        
        html = '''
        <html><body>
            <a href="job_stellenausschreibung_developer.pdf">Dev</a>
            <a href="karriere_developer.pdf">Dev2</a>
        </body></html>
        '''
        strategy = PdfLinkStrategy()
        
        candidates = strategy.extract(html, "https://example.com")
        titles = [c.title.lower() for c in candidates]
        
        # Should deduplicate "developer"
        assert titles.count("developer") == 1


class Test711mediaPlatformDetection:
    """Test that 711media.de is not detected as a known job board platform."""
    
    def test_711media_not_detected_as_job_board(self):
        """711media.de is a custom TYPO3 site, not a known job board."""
        from src.searchers.job_boards.detector import detect_job_board_platform
        
        html = load_fixture("711media_jobs.html")
        platform = detect_job_board_platform("https://www.711media.de/jobs-in-stuttgart", html)
        
        # Should not match any known platform - returns None or 'unknown'
        assert platform is None or platform == "unknown"
    
    def test_711media_is_typo3_site(self):
        """711media.de is built on TYPO3 CMS."""
        html = load_fixture("711media_jobs.html")
        
        # TYPO3 generator meta tag
        assert 'content="TYPO3 CMS"' in html
        
        # TYPO3 extension paths
        assert "typo3conf/ext/" in html
        assert "typo3temp/" in html


class TestHiBobParser:
    """Tests for HiBob job board parser."""

    def test_extracts_all_jobs(self):
        """Should extract all jobs from HiBob HTML."""
        html = load_fixture("hibob_jobs.html")
        soup = make_soup(html)
        parser = HiBobParser()

        jobs = parser.parse(soup, "https://company.careers.hibob.com/jobs")

        assert len(jobs) == 4

    def test_extracts_titles(self):
        """Should extract job titles correctly."""
        html = load_fixture("hibob_jobs.html")
        soup = make_soup(html)
        parser = HiBobParser()

        jobs = parser.parse(soup, "https://company.careers.hibob.com/jobs")
        titles = [j["title"] for j in jobs]

        assert "Senior Software Engineer (f/m/x)" in titles
        assert "Product Manager (f/m/d)" in titles
        assert "DevOps Engineer (m/w/d)" in titles
        assert "Marketing Lead (f/m/x)" in titles

    def test_extracts_locations(self):
        """Should extract locations from HiBob format."""
        html = load_fixture("hibob_jobs.html")
        soup = make_soup(html)
        parser = HiBobParser()

        jobs = parser.parse(soup, "https://company.careers.hibob.com/jobs")
        locations = [j["location"] for j in jobs]

        # Should extract location keywords
        assert any("Germany" in loc or "Remote" in loc for loc in locations)
        assert any("Munich" in loc for loc in locations)
        assert any("Berlin" in loc for loc in locations)

    def test_extracts_departments(self):
        """Should extract departments from HiBob format."""
        html = load_fixture("hibob_jobs.html")
        soup = make_soup(html)
        parser = HiBobParser()

        jobs = parser.parse(soup, "https://company.careers.hibob.com/jobs")
        departments = [j["department"] for j in jobs if j.get("department")]

        assert "Dev" in departments
        assert "Product" in departments
        assert "Infrastructure" in departments
        assert "Marketing" in departments

    def test_generates_urls(self):
        """Should generate URLs from job titles."""
        html = load_fixture("hibob_jobs.html")
        soup = make_soup(html)
        parser = HiBobParser()

        jobs = parser.parse(soup, "https://company.careers.hibob.com/jobs")

        # All jobs should have URLs
        for job in jobs:
            assert job["url"].startswith("https://company.careers.hibob.com/jobs/")

    def test_platform_name(self):
        """Should have correct platform name."""
        parser = HiBobParser()
        assert parser.platform_name == "hibob"

    def test_empty_html(self):
        """Should handle empty HTML gracefully."""
        soup = make_soup("<html><body></body></html>")
        parser = HiBobParser()

        jobs = parser.parse(soup, "https://company.careers.hibob.com/jobs")

        assert jobs == []


class TestHiBobDetection:
    """Tests for HiBob platform detection."""

    def test_detects_hibob_url(self):
        """Should detect HiBob from URL pattern."""
        from src.searchers.job_boards.detector import detect_job_board_platform

        platform = detect_job_board_platform("https://company.careers.hibob.com/jobs")

        assert platform == "hibob"

    def test_normalizes_hibob_url(self):
        """Should normalize HiBob URL to /jobs."""
        from src.searchers.job_boards.detector import _normalize_job_board_url

        url = _normalize_job_board_url(
            "https://company.careers.hibob.com/",
            platform="hibob"
        )

        assert url == "https://company.careers.hibob.com/jobs"


@pytest.mark.e2e
class TestHiBobLive:
    """E2E tests against real HiBob site.
    
    Run with: pytest -m e2e tests/test_job_board_parsers.py -v
    """

    @pytest.mark.asyncio
    async def test_hibob_live_parsing(self):
        """Smoke test: HiBob parser works on real site."""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            
            await page.goto(
                "https://stakingfacili-62c6a8.careers.hibob.com/jobs",
                wait_until="networkidle",
                timeout=30000
            )
            await page.wait_for_timeout(2000)
            
            html = await page.content()
            await browser.close()
        
        soup = make_soup(html)
        parser = HiBobParser()
        jobs = parser.parse(soup, "https://stakingfacili-62c6a8.careers.hibob.com/jobs")
        
        # Проверяем что парсер находит вакансии (не конкретное число!)
        assert len(jobs) > 0, "HiBob parser should find at least one job"
        
        # Проверяем структуру
        for job in jobs:
            assert job.get("title"), "Job should have title"
            assert job.get("url"), "Job should have URL"
            assert job.get("location"), "Job should have location"


# Run with: pytest tests/test_job_board_parsers.py -v

