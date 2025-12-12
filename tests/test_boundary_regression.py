"""Boundary and regression tests for edge cases and layout changes.

These tests verify:
- Handling of extreme inputs (large HTML, long titles, malformed data)
- Detection of job board layout changes (regression tests)
- Snapshot testing for parser output stability

Run with: pytest tests/test_boundary_regression.py -v
Update snapshots: pytest tests/test_boundary_regression.py -v --snapshot-update
"""

import json
import pytest
from pathlib import Path
from bs4 import BeautifulSoup
from typing import Any
from unittest.mock import AsyncMock

from src.extraction.strategies import SchemaOrgStrategy, PdfLinkStrategy
from src.extraction.extractor import HybridJobExtractor
from src.extraction.candidate import JobCandidate, is_likely_job_title
from src.llm.html_utils import clean_html, extract_json
from src.searchers.job_boards.lever import LeverParser
from src.searchers.job_boards.personio import PersonioParser
from src.searchers.job_boards.greenhouse import GreenhouseParser
from src.searchers.job_boards.workable import WorkableParser
from src.searchers.job_boards.recruitee import RecruiteeParser
from src.searchers.job_boards.hibob import HiBobParser
from src.searchers.job_boards.odoo import OdooParser
from src.searchers.job_boards.hrworks import HRworksParser


FIXTURES_DIR = Path(__file__).parent / "fixtures"
SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"


def load_fixture(name: str) -> str:
    """Load HTML fixture file."""
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


# =============================================================================
# Boundary Tests - Extreme Inputs
# =============================================================================


class TestBoundaryLargeHTML:
    """Tests for handling very large HTML documents."""
    
    def test_handles_1mb_html(self):
        """Should handle HTML > 1MB without crashing or timeout."""
        # Generate 1MB+ HTML with repeated job listings
        job_block = """
        <div class="job-item">
            <h3 class="job-title">Software Developer (m/w/d)</h3>
            <span class="location">Berlin, Germany - Remote possible</span>
            <p class="description">We are looking for a talented developer to join our team.</p>
            <a href="/jobs/12345">Apply Now</a>
        </div>
        """
        # Each block ~300 bytes, need ~3500 for 1MB
        large_html = f"""
        <!DOCTYPE html>
        <html>
        <head><title>Careers</title></head>
        <body>
        <div class="jobs-container">
        {"".join(job_block for _ in range(5000))}
        </div>
        </body>
        </html>
        """
        
        assert len(large_html) > 1_000_000, f"HTML should be > 1MB, got {len(large_html)}"
        
        # clean_html should not crash
        cleaned = clean_html(large_html)
        assert cleaned is not None
        assert len(cleaned) < len(large_html)  # Should reduce size
        
        # SchemaOrgStrategy should handle gracefully (no Schema.org = empty)
        strategy = SchemaOrgStrategy()
        candidates = strategy.extract(large_html, "https://example.com")
        assert candidates == []  # No Schema.org in this HTML
    
    def test_handles_5mb_html(self):
        """Should handle HTML up to 5MB (some corporate sites are huge)."""
        # Generate 5MB HTML - each block ~3KB
        content_block = "<p>" + "Lorem ipsum dolor sit amet consectetur adipiscing elit. " * 100 + "</p>\n"
        large_html = f"""
        <!DOCTYPE html>
        <html>
        <head><title>Huge Page</title></head>
        <body>
        {"".join(content_block for _ in range(1000))}
        </body>
        </html>
        """
        
        assert len(large_html) > 5_000_000, f"HTML should be > 5MB, got {len(large_html)}"
        
        # Should complete without memory error
        cleaned = clean_html(large_html)
        assert cleaned is not None
        
        # clean_html removes scripts/styles/etc, may reduce or keep size
        # Truncation happens at LLM layer, not here
        assert len(cleaned) > 0
    
    def test_handles_deeply_nested_html(self):
        """Should handle deeply nested HTML structures (100+ levels)."""
        # Create deeply nested structure
        depth = 150
        nested_html = "<html><body>"
        nested_html += "<div>" * depth
        nested_html += "<h3>Developer (m/w/d)</h3><a href='/job'>Apply</a>"
        nested_html += "</div>" * depth
        nested_html += "</body></html>"
        
        # Should not cause recursion error
        soup = BeautifulSoup(nested_html, 'lxml')
        assert soup is not None
        
        cleaned = clean_html(nested_html)
        assert "Developer" in cleaned
    
    def test_handles_many_jobs_in_schema_org(self):
        """Should handle Schema.org with 500+ job postings."""
        jobs = [
            {
                "@type": "JobPosting",
                "title": f"Developer {i} (m/w/d)",
                "url": f"/jobs/{i}",
                "jobLocation": {"@type": "Place", "address": "Berlin"}
            }
            for i in range(500)
        ]
        
        html = f"""
        <html>
        <script type="application/ld+json">
        {json.dumps({"@context": "https://schema.org", "@graph": jobs})}
        </script>
        </html>
        """
        
        strategy = SchemaOrgStrategy()
        candidates = strategy.extract(html, "https://example.com")
        
        assert len(candidates) == 500
        assert candidates[0].title == "Developer 0 (m/w/d)"
        assert candidates[499].title == "Developer 499 (m/w/d)"


class TestBoundaryLongStrings:
    """Tests for handling extremely long strings."""
    
    def test_handles_very_long_job_title(self):
        """Should handle job titles > 500 characters."""
        long_title = "Senior " + "Very " * 100 + "Important Developer (m/w/d)"
        assert len(long_title) > 500
        
        html = f"""
        <html>
        <script type="application/ld+json">
        {{"@type": "JobPosting", "title": "{long_title}", "url": "/job"}}
        </script>
        </html>
        """
        
        strategy = SchemaOrgStrategy()
        candidates = strategy.extract(html, "https://example.com")
        
        assert len(candidates) == 1
        # Title should be preserved or truncated, not crash
        assert len(candidates[0].title) > 0
    
    def test_is_likely_job_title_rejects_very_long(self):
        """is_likely_job_title should reject extremely long strings."""
        long_title = "A" * 500
        is_likely, signals = is_likely_job_title(long_title)
        
        assert is_likely is False
        assert "too_long" in signals or signals.get("length_ok") is False
    
    def test_handles_very_long_location(self):
        """Should handle locations > 500 characters."""
        long_location = "Berlin, " * 100 + "Germany"
        
        html = f"""
        <html>
        <script type="application/ld+json">
        {{
            "@type": "JobPosting",
            "title": "Developer",
            "url": "/job",
            "jobLocation": {{"@type": "Place", "address": "{long_location}"}}
        }}
        </script>
        </html>
        """
        
        strategy = SchemaOrgStrategy()
        candidates = strategy.extract(html, "https://example.com")
        
        assert len(candidates) == 1
        # Location should be preserved or truncated
        assert len(candidates[0].location) > 0
    
    def test_handles_very_long_url(self):
        """Should handle URLs > 2000 characters."""
        long_path = "/jobs/" + "a" * 2000
        
        html = f"""
        <html>
        <script type="application/ld+json">
        {{"@type": "JobPosting", "title": "Developer", "url": "{long_path}"}}
        </script>
        </html>
        """
        
        strategy = SchemaOrgStrategy()
        candidates = strategy.extract(html, "https://example.com")
        
        assert len(candidates) == 1
        # URL should be preserved (browsers handle long URLs)
        assert "/jobs/" in candidates[0].url


class TestBoundaryMalformedInput:
    """Tests for handling malformed and corrupt input."""
    
    def test_handles_invalid_utf8(self):
        """Should handle HTML with invalid UTF-8 sequences."""
        # Create HTML with mixed encodings
        html = b"""
        <html>
        <head><title>Karriere</title></head>
        <body>
        <h3>Entwickler (m/w/d) \xff\xfe</h3>
        </body>
        </html>
        """
        
        # Decode with error handling
        html_str = html.decode('utf-8', errors='replace')
        
        cleaned = clean_html(html_str)
        assert "Entwickler" in cleaned
    
    def test_handles_truncated_json_ld(self):
        """Should handle truncated JSON-LD gracefully."""
        html = """
        <html>
        <script type="application/ld+json">
        {"@type": "JobPosting", "title": "Develop
        </script>
        </html>
        """
        
        strategy = SchemaOrgStrategy()
        candidates = strategy.extract(html, "https://example.com")
        
        # Should not crash, return empty
        assert candidates == []
    
    def test_handles_null_bytes(self):
        """Should handle HTML with null bytes."""
        html = "<html><body><h3>Developer\x00 (m/w/d)</h3></body></html>"
        
        cleaned = clean_html(html)
        assert cleaned is not None
        assert "Developer" in cleaned
    
    def test_handles_empty_json_ld(self):
        """Should handle empty JSON-LD blocks."""
        html = """
        <html>
        <script type="application/ld+json"></script>
        <script type="application/ld+json">{}</script>
        <script type="application/ld+json">[]</script>
        <script type="application/ld+json">null</script>
        </html>
        """
        
        strategy = SchemaOrgStrategy()
        candidates = strategy.extract(html, "https://example.com")
        
        assert candidates == []
    
    def test_extract_json_handles_garbage(self):
        """extract_json should handle garbage input without crashing."""
        import math
        
        garbage_inputs = [
            "",
            "not json at all",
            "```json\n{broken\n```",
            "{'single': 'quotes'}",  # Python dict, not JSON
            "undefined",
            "[1, 2, 3,]",  # Trailing comma
        ]
        
        for garbage in garbage_inputs:
            result = extract_json(garbage)
            # Should return empty dict/list, not crash
            assert result == {} or result == [], f"Failed on: {garbage}"
        
        # Special case: "NaN" is valid in some JSON parsers (JavaScript style)
        # Our extract_json may return float('nan') or empty - both are acceptable
        result = extract_json("NaN")
        is_nan = isinstance(result, float) and math.isnan(result)
        is_empty = result == {} or result == []
        assert is_nan or is_empty, f"Unexpected result for 'NaN': {result}"


class TestBoundaryEdgeCases:
    """Edge cases that have caused bugs in production."""
    
    def test_job_with_only_title(self):
        """Should handle job with only title, no other fields."""
        html = """
        <html>
        <script type="application/ld+json">
        {"@type": "JobPosting", "title": "Developer"}
        </script>
        </html>
        """
        
        strategy = SchemaOrgStrategy()
        candidates = strategy.extract(html, "https://example.com")
        
        assert len(candidates) == 1
        assert candidates[0].title == "Developer"
        assert candidates[0].location == "Unknown"  # Default
    
    def test_job_with_empty_strings(self):
        """Should handle job with empty string fields gracefully."""
        html = """
        <html>
        <script type="application/ld+json">
        {"@type": "JobPosting", "title": "", "url": "", "jobLocation": ""}
        </script>
        </html>
        """
        
        strategy = SchemaOrgStrategy()
        candidates = strategy.extract(html, "https://example.com")
        
        # Note: SchemaOrgStrategy extracts even empty titles (Schema.org is trusted)
        # Filtering happens at higher level (HybridJobExtractor or validate_jobs)
        # This test documents current behavior
        if candidates:
            # If returned, title should be empty string
            assert candidates[0].title == ""
        # Or no candidates at all is also acceptable
        assert len(candidates) <= 1
    
    def test_handles_html_in_job_title(self):
        """Should handle HTML tags in job titles without crashing."""
        html = """
        <html>
        <script type="application/ld+json">
        {"@type": "JobPosting", "title": "<b>Developer</b> (m/w/d)", "url": "/job"}
        </script>
        </html>
        """
        
        strategy = SchemaOrgStrategy()
        candidates = strategy.extract(html, "https://example.com")
        
        assert len(candidates) == 1
        # Note: SchemaOrgStrategy preserves title as-is from JSON
        # HTML stripping happens at display/validation layer
        # This documents current behavior
        assert "Developer" in candidates[0].title
    
    def test_handles_special_characters_in_title(self):
        """Should handle special characters in titles."""
        special_titles = [
            "C++ Developer (m/w/d)",
            "C# Engineer (m/w/d)",
            "Node.js Developer (m/w/d)",
            "iOS/Android Developer (m/w/d)",
            "DevOps & SRE Engineer (m/w/d)",
            "Manager – Digital (m/w/d)",  # en-dash
            "Manager — Digital (m/w/d)",  # em-dash
            "Développeur (m/w/d)",  # French accent
            "Müller & Co. Manager (m/w/d)",  # German umlaut
        ]
        
        for title in special_titles:
            html = f"""
            <html>
            <script type="application/ld+json">
            {{"@type": "JobPosting", "title": "{title}", "url": "/job"}}
            </script>
            </html>
            """
            
            strategy = SchemaOrgStrategy()
            candidates = strategy.extract(html, "https://example.com")
            
            assert len(candidates) == 1, f"Failed for title: {title}"
            assert len(candidates[0].title) > 0


# =============================================================================
# Layout Regression Tests - Detect Job Board Changes
# =============================================================================


class TestLayoutRegressionGreenhouse:
    """Detect if Greenhouse changes their HTML structure."""
    
    def test_greenhouse_has_expected_structure(self):
        """Greenhouse HTML should have expected CSS classes and structure."""
        html = load_fixture("greenhouse_style.html")
        soup = BeautifulSoup(html, 'lxml')
        
        # Expected Greenhouse markers (as of Dec 2024)
        # Check key structural elements that GreenhouseParser relies on
        checks = {
            "has_content_div": soup.find('div', id='content') is not None,
            "has_departments_section": soup.find('section', class_='departments') is not None,
            "has_opening_divs": soup.find('div', class_='opening') is not None,
            "has_job_links": len([a for a in soup.find_all('a', href=True) if '/jobs/' in a['href']]) > 0,
        }
        
        failed = [name for name, passed in checks.items() if not passed]
        
        if failed:
            pytest.fail(
                f"Greenhouse layout changed! Failed checks: {failed}\n"
                "Update GreenhouseParser selectors if this is expected."
            )
    
    def test_greenhouse_parser_finds_jobs(self):
        """GreenhouseParser should find jobs in current fixture."""
        html = load_fixture("greenhouse_style.html")
        soup = BeautifulSoup(html, 'lxml')
        parser = GreenhouseParser()
        
        jobs = parser.parse(soup, "https://boards.greenhouse.io/company")
        
        assert len(jobs) >= 5, (
            f"GreenhouseParser found only {len(jobs)} jobs. "
            "Layout may have changed. Expected >= 5."
        )
        
        # Verify job structure
        for job in jobs:
            assert job.get("title"), f"Job missing title: {job}"
            assert job.get("url"), f"Job missing URL: {job}"


class TestLayoutRegressionLever:
    """Detect if Lever changes their HTML structure."""
    
    def test_lever_has_expected_structure(self):
        """Lever HTML should have expected CSS classes."""
        html = load_fixture("lever_jobs.html")
        soup = BeautifulSoup(html, 'lxml')
        
        # Expected Lever markers (as of Dec 2024)
        checks = {
            "has_posting_divs": soup.find('div', class_='posting') is not None,
            "has_posting_title_links": soup.find('a', class_='posting-title') is not None,
            "has_lever_job_urls": len([a for a in soup.find_all('a', href=True) if 'lever.co' in a['href']]) > 0,
        }
        
        failed = [name for name, passed in checks.items() if not passed]
        
        if failed:
            pytest.fail(
                f"Lever layout changed! Failed checks: {failed}\n"
                "Update LeverParser selectors."
            )
    
    def test_lever_parser_finds_jobs(self):
        """LeverParser should find jobs in current fixture."""
        html = load_fixture("lever_jobs.html")
        soup = BeautifulSoup(html, 'lxml')
        parser = LeverParser()
        
        jobs = parser.parse(soup, "https://jobs.lever.co/company")
        
        assert len(jobs) >= 4, f"LeverParser found only {len(jobs)} jobs"


class TestLayoutRegressionPersonio:
    """Detect if Personio changes their HTML structure."""
    
    def test_personio_has_expected_structure(self):
        """Personio HTML should have expected CSS classes."""
        html = load_fixture("personio_jobs.html")
        soup = BeautifulSoup(html, 'lxml')
        
        # Expected Personio markers (as of Dec 2024)
        # Note: Fixture uses simplified structure, real Personio has more markers
        checks = {
            "has_job_list_or_cards": (
                soup.find('div', class_='jobs-list') is not None or
                soup.find('div', class_='job-card') is not None
            ),
            "has_personio_job_urls": len([
                a for a in soup.find_all('a', href=True) 
                if 'personio.de/job/' in a['href']
            ]) > 0,
        }
        
        failed = [name for name, passed in checks.items() if not passed]
        
        if failed:
            pytest.fail(f"Personio layout changed! Failed checks: {failed}")
    
    def test_personio_parser_finds_jobs(self):
        """PersonioParser should find jobs in current fixture."""
        html = load_fixture("personio_jobs.html")
        soup = BeautifulSoup(html, 'lxml')
        parser = PersonioParser()
        
        jobs = parser.parse(soup, "https://company.jobs.personio.de")
        
        assert len(jobs) >= 4, f"PersonioParser found only {len(jobs)} jobs"


class TestLayoutRegressionWorkable:
    """Detect if Workable changes their HTML structure."""
    
    def test_workable_has_json_ld(self):
        """Workable should have JSON-LD with job postings."""
        html = load_fixture("workable_jobs.html")
        soup = BeautifulSoup(html, 'lxml')
        
        json_ld = soup.find('script', type='application/ld+json')
        assert json_ld is not None, "Workable missing JSON-LD. Layout changed?"
        
        try:
            data = json.loads(json_ld.string)
            # Workable uses array format, @graph, or direct JobPosting
            if isinstance(data, list):
                has_jobs = any(item.get('@type') == 'JobPosting' for item in data)
            else:
                has_jobs = (
                    data.get('@type') == 'JobPosting' or
                    any(item.get('@type') == 'JobPosting' for item in data.get('@graph', []))
                )
            assert has_jobs, "Workable JSON-LD has no JobPosting"
        except json.JSONDecodeError:
            pytest.fail("Workable JSON-LD is invalid JSON")
    
    def test_workable_parser_finds_jobs(self):
        """WorkableParser should find jobs in current fixture."""
        html = load_fixture("workable_jobs.html")
        soup = BeautifulSoup(html, 'lxml')
        parser = WorkableParser()
        
        jobs = parser.parse(soup, "https://apply.workable.com/company")
        
        assert len(jobs) >= 2, f"WorkableParser found only {len(jobs)} jobs"


class TestLayoutRegressionHiBob:
    """Detect if HiBob changes their HTML structure."""
    
    def test_hibob_has_expected_structure(self):
        """HiBob HTML should have expected structure."""
        html = load_fixture("hibob_jobs.html")
        soup = BeautifulSoup(html, 'lxml')
        
        # HiBob uses Web Components with b-* prefix and b-heading for titles
        checks = {
            "has_virtual_scroll": soup.find('b-virtual-scroll-list') is not None,
            "has_job_items": soup.find('b-virtual-scroll-list-item') is not None,
            "has_headings": soup.find('b-heading') is not None,
        }
        
        failed = [name for name, passed in checks.items() if not passed]
        
        # At least some structure should exist
        if len(failed) == len(checks):
            pytest.fail(f"HiBob layout changed! All checks failed: {list(checks.keys())}")
    
    def test_hibob_parser_finds_jobs(self):
        """HiBobParser should find jobs in current fixture."""
        html = load_fixture("hibob_jobs.html")
        soup = BeautifulSoup(html, 'lxml')
        parser = HiBobParser()
        
        jobs = parser.parse(soup, "https://company.careers.hibob.com/jobs")
        
        assert len(jobs) >= 4, f"HiBobParser found only {len(jobs)} jobs"


# =============================================================================
# Snapshot Testing - Detect Output Regressions
# =============================================================================


class SnapshotManager:
    """Simple snapshot manager for parser output testing."""
    
    def __init__(self, snapshots_dir: Path):
        self.snapshots_dir = snapshots_dir
        self.snapshots_dir.mkdir(exist_ok=True)
    
    def get_snapshot_path(self, name: str) -> Path:
        return self.snapshots_dir / f"{name}.json"
    
    def load_snapshot(self, name: str) -> dict | None:
        path = self.get_snapshot_path(name)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None
    
    def save_snapshot(self, name: str, data: dict) -> None:
        path = self.get_snapshot_path(name)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    
    def assert_matches(self, name: str, actual: list[dict], update: bool = False) -> None:
        """Assert that actual matches snapshot, or update if requested."""
        snapshot = self.load_snapshot(name)
        
        # Normalize for comparison (sort by title)
        actual_normalized = sorted(actual, key=lambda x: x.get('title', ''))
        actual_data = {"jobs": actual_normalized, "count": len(actual_normalized)}
        
        if snapshot is None or update:
            self.save_snapshot(name, actual_data)
            if snapshot is None:
                pytest.skip(f"Snapshot '{name}' created. Run again to verify.")
            return
        
        # Compare counts first
        expected_count = snapshot.get("count", 0)
        actual_count = len(actual_normalized)
        
        if actual_count != expected_count:
            pytest.fail(
                f"Job count changed for '{name}': {expected_count} → {actual_count}\n"
                f"Run with --snapshot-update to accept new output."
            )
        
        # Compare titles
        expected_titles = {j['title'] for j in snapshot.get("jobs", [])}
        actual_titles = {j['title'] for j in actual_normalized}
        
        missing = expected_titles - actual_titles
        added = actual_titles - expected_titles
        
        if missing or added:
            msg = f"Job titles changed for '{name}':\n"
            if missing:
                msg += f"  Missing: {missing}\n"
            if added:
                msg += f"  Added: {added}\n"
            msg += "Run with --snapshot-update to accept new output."
            pytest.fail(msg)


@pytest.fixture(scope="module")
def snapshot_manager():
    return SnapshotManager(SNAPSHOTS_DIR)


@pytest.fixture
def update_snapshots(request):
    """Check if --snapshot-update flag is passed."""
    return request.config.getoption("--snapshot-update", default=False)




class TestSnapshotParsers:
    """Snapshot tests for parser outputs."""
    
    def test_lever_snapshot(self, snapshot_manager, update_snapshots):
        """Lever parser output should match snapshot."""
        html = load_fixture("lever_jobs.html")
        soup = BeautifulSoup(html, 'lxml')
        parser = LeverParser()
        
        jobs = parser.parse(soup, "https://jobs.lever.co/company")
        
        snapshot_manager.assert_matches("lever_parser", jobs, update=update_snapshots)
    
    def test_personio_snapshot(self, snapshot_manager, update_snapshots):
        """Personio parser output should match snapshot."""
        html = load_fixture("personio_jobs.html")
        soup = BeautifulSoup(html, 'lxml')
        parser = PersonioParser()
        
        jobs = parser.parse(soup, "https://company.jobs.personio.de")
        
        snapshot_manager.assert_matches("personio_parser", jobs, update=update_snapshots)
    
    def test_greenhouse_snapshot(self, snapshot_manager, update_snapshots):
        """Greenhouse parser output should match snapshot."""
        html = load_fixture("greenhouse_style.html")
        soup = BeautifulSoup(html, 'lxml')
        parser = GreenhouseParser()
        
        jobs = parser.parse(soup, "https://boards.greenhouse.io/company")
        
        snapshot_manager.assert_matches("greenhouse_parser", jobs, update=update_snapshots)
    
    def test_workable_snapshot(self, snapshot_manager, update_snapshots):
        """Workable parser output should match snapshot."""
        html = load_fixture("workable_jobs.html")
        soup = BeautifulSoup(html, 'lxml')
        parser = WorkableParser()
        
        jobs = parser.parse(soup, "https://apply.workable.com/company")
        
        snapshot_manager.assert_matches("workable_parser", jobs, update=update_snapshots)
    
    def test_recruitee_snapshot(self, snapshot_manager, update_snapshots):
        """Recruitee parser output should match snapshot."""
        html = load_fixture("recruitee_jobs.html")
        soup = BeautifulSoup(html, 'lxml')
        parser = RecruiteeParser()
        
        jobs = parser.parse(soup, "https://company.recruitee.com")
        
        snapshot_manager.assert_matches("recruitee_parser", jobs, update=update_snapshots)
    
    def test_hibob_snapshot(self, snapshot_manager, update_snapshots):
        """HiBob parser output should match snapshot."""
        html = load_fixture("hibob_jobs.html")
        soup = BeautifulSoup(html, 'lxml')
        parser = HiBobParser()
        
        jobs = parser.parse(soup, "https://company.careers.hibob.com/jobs")
        
        snapshot_manager.assert_matches("hibob_parser", jobs, update=update_snapshots)
    
    def test_odoo_snapshot(self, snapshot_manager, update_snapshots):
        """Odoo parser output should match snapshot."""
        html = load_fixture("odoo_jobs.html")
        soup = BeautifulSoup(html, 'lxml')
        parser = OdooParser()
        
        jobs = parser.parse(soup, "https://company.com/jobs")
        
        snapshot_manager.assert_matches("odoo_parser", jobs, update=update_snapshots)
    
    def test_hrworks_snapshot(self, snapshot_manager, update_snapshots):
        """HRworks parser output should match snapshot."""
        html = load_fixture("hrworks_jobs.html")
        soup = BeautifulSoup(html, 'lxml')
        parser = HRworksParser()
        
        jobs = parser.parse(soup, "https://jobs.company.de/de")
        
        snapshot_manager.assert_matches("hrworks_parser", jobs, update=update_snapshots)


class TestSnapshotSchemaOrg:
    """Snapshot tests for Schema.org extraction."""
    
    def test_schema_org_snapshot(self, snapshot_manager, update_snapshots):
        """Schema.org extraction should match snapshot."""
        html = load_fixture("schema_org_jobs.html")
        strategy = SchemaOrgStrategy()
        
        candidates = strategy.extract(html, "https://example.com")
        jobs = [c.to_dict() for c in candidates]
        
        snapshot_manager.assert_matches("schema_org_extraction", jobs, update=update_snapshots)


# =============================================================================
# Version Detection Tests - Identify Layout Versions
# =============================================================================


class TestLayoutVersionDetection:
    """Tests that identify which version of a job board layout is being used."""
    
    def test_greenhouse_layout_version(self):
        """Identify Greenhouse layout version."""
        html = load_fixture("greenhouse_style.html")
        
        # v1: Uses #content > section.level-0
        # v2 (2024): Uses different structure
        
        v1_markers = ['level-0', 'opening', '#content']
        v2_markers = ['job-board', 'positions-list', 'gh_']  # Hypothetical v2 markers
        
        v1_score = sum(1 for m in v1_markers if m in html)
        v2_score = sum(1 for m in v2_markers if m in html)
        
        if v1_score > v2_score:
            version = "v1 (classic)"
        elif v2_score > v1_score:
            version = "v2 (2024)"
        else:
            version = "unknown"
        
        # For documentation - should be v1 currently
        assert version == "v1 (classic)", f"Greenhouse layout version: {version}"
    
    def test_lever_layout_version(self):
        """Identify Lever layout version."""
        html = load_fixture("lever_jobs.html")
        
        # Current markers
        has_posting_groups = "postings-group" in html
        has_posting_title = "posting-title" in html
        
        if has_posting_groups and has_posting_title:
            version = "v1 (grouped)"
        elif has_posting_title:
            version = "v1 (flat)"
        else:
            version = "unknown"
        
        assert version in ["v1 (grouped)", "v1 (flat)"], f"Lever layout: {version}"


# Run with: pytest tests/test_boundary_regression.py -v
# Update snapshots: pytest tests/test_boundary_regression.py -v --snapshot-update
