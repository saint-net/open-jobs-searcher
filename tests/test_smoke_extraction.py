"""Smoke tests for src/extraction/ - Job extraction module.

These tests verify that:
- SchemaOrgStrategy correctly parses JSON-LD and microdata
- HybridJobExtractor integrates strategies correctly
- JobCandidate model works properly

Run after changes to: src/extraction/*.py
"""

import pytest
from unittest.mock import AsyncMock

from src.extraction.strategies import SchemaOrgStrategy
from src.extraction.extractor import HybridJobExtractor
from src.extraction.candidate import JobCandidate, ExtractionSource, is_likely_job_title


class TestSchemaOrgStrategy:
    """Tests for SchemaOrgStrategy."""
    
    def test_extracts_json_ld_job_posting(self, sample_html_with_schema_org):
        """Should extract job from JSON-LD JobPosting."""
        strategy = SchemaOrgStrategy()
        candidates = strategy.extract(sample_html_with_schema_org, "https://example.com")
        
        assert len(candidates) == 1
        assert candidates[0].title == "Backend Developer"
        assert candidates[0].location == "Hamburg"
        assert "example.com/jobs/backend-dev" in candidates[0].url
    
    def test_extracts_multiple_jobs_from_graph(self):
        """Should extract multiple jobs from @graph."""
        html = """
        <html>
        <head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "JobPosting",
                    "title": "Developer",
                    "url": "/jobs/dev"
                },
                {
                    "@type": "JobPosting",
                    "title": "Designer",
                    "url": "/jobs/designer"
                }
            ]
        }
        </script>
        </head>
        </html>
        """
        strategy = SchemaOrgStrategy()
        candidates = strategy.extract(html, "https://example.com")
        
        assert len(candidates) == 2
        titles = {c.title for c in candidates}
        assert "Developer" in titles
        assert "Designer" in titles
    
    def test_extracts_from_array_format(self):
        """Should extract jobs from JSON-LD array format."""
        html = """
        <html>
        <script type="application/ld+json">
        [
            {"@type": "JobPosting", "title": "Job 1"},
            {"@type": "JobPosting", "title": "Job 2"}
        ]
        </script>
        </html>
        """
        strategy = SchemaOrgStrategy()
        candidates = strategy.extract(html, "https://example.com")
        
        assert len(candidates) == 2
    
    def test_handles_invalid_json(self):
        """Should handle invalid JSON gracefully."""
        html = """
        <html>
        <script type="application/ld+json">
        {invalid json here}
        </script>
        </html>
        """
        strategy = SchemaOrgStrategy()
        candidates = strategy.extract(html, "https://example.com")
        
        assert candidates == []
    
    def test_returns_empty_for_no_schema_org(self, sample_html_empty):
        """Should return empty list if no Schema.org data."""
        strategy = SchemaOrgStrategy()
        candidates = strategy.extract(sample_html_empty, "https://example.com")
        
        assert candidates == []
    
    def test_extracts_company_from_hiring_organization(self):
        """Should extract company name from hiringOrganization."""
        html = """
        <html>
        <script type="application/ld+json">
        {
            "@type": "JobPosting",
            "title": "Developer",
            "hiringOrganization": {
                "@type": "Organization",
                "name": "Acme Corp"
            }
        }
        </script>
        </html>
        """
        strategy = SchemaOrgStrategy()
        candidates = strategy.extract(html, "https://example.com")
        
        assert len(candidates) == 1
        assert candidates[0].company == "Acme Corp"


class TestHybridJobExtractor:
    """Tests for HybridJobExtractor."""
    
    def test_initialization_without_llm(self):
        """Should initialize without LLM function."""
        extractor = HybridJobExtractor()
        
        assert extractor.llm_extract_fn is None
        assert extractor.schema_strategy is not None
    
    def test_initialization_with_llm(self):
        """Should accept LLM extraction function."""
        async def mock_llm(html, url):
            return []
        
        extractor = HybridJobExtractor(llm_extract_fn=mock_llm)
        
        assert extractor.llm_extract_fn is mock_llm
    
    @pytest.mark.asyncio
    async def test_uses_schema_org_when_available(self, sample_html_with_schema_org):
        """Should use Schema.org data when available (no LLM call)."""
        llm_called = False
        
        async def mock_llm(html, url):
            nonlocal llm_called
            llm_called = True
            return []
        
        extractor = HybridJobExtractor(llm_extract_fn=mock_llm)
        jobs = await extractor.extract(sample_html_with_schema_org, "https://example.com")
        
        assert len(jobs) == 1
        assert jobs[0]["title"] == "Backend Developer"
        assert llm_called is False  # LLM should not be called
    
    @pytest.mark.asyncio
    async def test_falls_back_to_llm(self, sample_html_empty):
        """Should fall back to LLM when no Schema.org data."""
        async def mock_llm(html, url):
            return [{"title": "LLM Job", "location": "Berlin", "url": url}]
        
        extractor = HybridJobExtractor(llm_extract_fn=mock_llm)
        jobs = await extractor.extract(sample_html_empty, "https://example.com")
        
        assert len(jobs) == 1
        assert jobs[0]["title"] == "LLM Job"
    
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_llm_and_no_schema(self, sample_html_empty):
        """Should return empty list when no LLM and no Schema.org."""
        extractor = HybridJobExtractor()  # No LLM
        jobs = await extractor.extract(sample_html_empty, "https://example.com")
        
        assert jobs == []
    
    def test_extract_sync_uses_schema_org_only(self, sample_html_with_schema_org):
        """extract_sync should only use Schema.org (no LLM)."""
        extractor = HybridJobExtractor()
        jobs = extractor.extract_sync(sample_html_with_schema_org, "https://example.com")
        
        assert len(jobs) == 1
        assert jobs[0]["title"] == "Backend Developer"
    
    @pytest.mark.asyncio
    async def test_deduplicates_llm_jobs(self):
        """Should deduplicate jobs from LLM."""
        async def mock_llm(html, url):
            return [
                {"title": "Developer (m/w/d)", "url": "/job/1"},
                {"title": "Developer (m/w/d)", "url": "/job/2"},  # Duplicate title
            ]
        
        extractor = HybridJobExtractor(llm_extract_fn=mock_llm)
        jobs = await extractor.extract("<html></html>", "https://example.com")
        
        # Should deduplicate by normalized title
        assert len(jobs) == 1


class TestJobCandidate:
    """Tests for JobCandidate model."""
    
    def test_creates_with_required_fields(self):
        """Should create with required fields."""
        candidate = JobCandidate(
            title="Developer (m/w/d)",
            url="https://example.com/job/1",
        )
        
        assert candidate.title == "Developer (m/w/d)"
        assert candidate.url == "https://example.com/job/1"
        assert candidate.location == "Unknown"  # Default
        assert candidate.source == ExtractionSource.KEYWORD_MATCH  # Default
    
    def test_creates_with_all_fields(self):
        """Should create with all optional fields."""
        candidate = JobCandidate(
            title="Manager",
            url="https://example.com/job/2",
            location="Berlin",
            department="Sales",
            company="Acme Corp",
            source=ExtractionSource.SCHEMA_ORG,
            signals={"test": True},
        )
        
        assert candidate.location == "Berlin"
        assert candidate.department == "Sales"
        assert candidate.company == "Acme Corp"
        assert candidate.source == ExtractionSource.SCHEMA_ORG
        assert candidate.signals["test"] is True
    
    def test_normalized_title_removes_gender_notation(self):
        """normalized_title should remove (m/w/d) variants."""
        candidate = JobCandidate(
            title="Developer (m/w/d)",
            url="https://example.com/job",
        )
        
        normalized = candidate.normalized_title
        
        assert "(m/w/d)" not in normalized
        assert "developer" in normalized.lower()
    
    def test_to_dict_returns_correct_structure(self):
        """to_dict should return expected dictionary structure."""
        candidate = JobCandidate(
            title="Developer",
            url="https://example.com/job",
            location="Berlin",
            department="IT",
            company="Test Corp",
        )
        
        result = candidate.to_dict()
        
        assert isinstance(result, dict)
        assert result["title"] == "Developer"
        assert result["url"] == "https://example.com/job"
        assert result["location"] == "Berlin"
        assert "department" in result
        assert "company" in result


class TestExtractionSource:
    """Tests for ExtractionSource enum."""
    
    def test_all_sources_defined(self):
        """All expected sources should be defined."""
        assert hasattr(ExtractionSource, 'SCHEMA_ORG')
        assert hasattr(ExtractionSource, 'LLM')
        assert hasattr(ExtractionSource, 'KEYWORD_MATCH')
        assert hasattr(ExtractionSource, 'GENDER_NOTATION')
        assert hasattr(ExtractionSource, 'LIST_STRUCTURE')
        assert hasattr(ExtractionSource, 'ACCESSIBILITY')


class TestIsLikelyJobTitle:
    """Tests for is_likely_job_title helper function."""
    
    def test_accepts_job_titles_with_gender_notation(self):
        """Should accept titles with (m/w/d)."""
        is_likely, signals = is_likely_job_title("Senior Developer (m/w/d)")
        
        assert is_likely is True
        assert "has_gender_notation" in signals or signals.get("has_gender_notation")
    
    def test_accepts_common_job_keywords(self):
        """Should accept titles with common job keywords."""
        # These titles contain keywords from JOB_TITLE_KEYWORDS
        titles = [
            "Software Engineer",
            "Product Manager", 
            "Marketing Specialist",
            "Senior Developer",
        ]
        
        for title in titles:
            is_likely, signals = is_likely_job_title(title)
            assert is_likely is True, f"Should accept '{title}', signals: {signals}"
    
    def test_rejects_too_short_titles(self):
        """Should reject very short strings."""
        is_likely, _ = is_likely_job_title("Dev")
        
        assert is_likely is False
    
    def test_rejects_too_long_titles(self):
        """Should reject very long strings."""
        long_title = "A" * 200
        is_likely, _ = is_likely_job_title(long_title)
        
        assert is_likely is False
    
    def test_rejects_navigation_items(self):
        """Should reject navigation-like items."""
        nav_items = ["Home", "About", "Contact", "Menu"]
        
        for item in nav_items:
            is_likely, _ = is_likely_job_title(item)
            assert is_likely is False, f"Should reject navigation item '{item}'"


# Run with: pytest tests/test_smoke_extraction.py -v

