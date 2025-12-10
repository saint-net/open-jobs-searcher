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


# Run with: pytest tests/test_job_board_parsers.py -v

