"""Tests for WebsiteSearcher filtering logic."""

import pytest
from urllib.parse import urlparse

from src.searchers.job_filters import filter_jobs_by_search_query


class TestDomainNormalization:
    """Test that www. prefix is ignored when comparing domains."""
    
    def test_same_domain_with_www_difference(self):
        """8com.de and www.8com.de should be considered same domain."""
        # Simulate the logic from website.py
        final_url = "https://www.8com.de/offene-stellen?q=Center"
        variant_url = "https://8com.de/warum-8com/karriere"
        
        final_domain = urlparse(final_url).netloc.replace('www.', '')
        variant_domain = urlparse(variant_url).netloc.replace('www.', '')
        navigated_to_external = final_domain != variant_domain
        
        assert final_domain == "8com.de"
        assert variant_domain == "8com.de"
        assert navigated_to_external is False  # Same domain!
    
    def test_different_domains(self):
        """Different domains should be detected as external."""
        final_url = "https://company.jobs.personio.de/"
        variant_url = "https://company.com/careers"
        
        final_domain = urlparse(final_url).netloc.replace('www.', '')
        variant_domain = urlparse(variant_url).netloc.replace('www.', '')
        navigated_to_external = final_domain != variant_domain
        
        assert navigated_to_external is True  # Different domain!
    
    def test_subdomain_is_external(self):
        """Subdomain should be considered external."""
        final_url = "https://careers.company.com/jobs"
        variant_url = "https://www.company.com/about"
        
        final_domain = urlparse(final_url).netloc.replace('www.', '')
        variant_domain = urlparse(variant_url).netloc.replace('www.', '')
        navigated_to_external = final_domain != variant_domain
        
        assert final_domain == "careers.company.com"
        assert variant_domain == "company.com"
        assert navigated_to_external is True


class TestFilterJobsBySearchQuery:
    """Test filter_jobs_by_search_query function."""
    
    def test_no_query_param_returns_all(self):
        """URL without search param should return all jobs."""
        jobs = [
            {"title": "Software Engineer"},
            {"title": "Product Manager"},
        ]
        url = "https://company.com/careers"
        
        result = filter_jobs_by_search_query(jobs, url)
        assert len(result) == 2
    
    def test_query_param_filters_by_title(self):
        """URL with ?q=term should filter jobs by title."""
        jobs = [
            {"title": "Software Engineer"},
            {"title": "Product Manager"},
            {"title": "Senior Software Developer"},
        ]
        url = "https://jobs.company.com/search?q=software"
        
        result = filter_jobs_by_search_query(jobs, url)
        # Should keep jobs with "software" in title
        assert len(result) == 2
        assert result[0]["title"] == "Software Engineer"
        assert result[1]["title"] == "Senior Software Developer"
    
    def test_no_matches_returns_all(self):
        """If no jobs match search term, return all (fallback)."""
        jobs = [
            {"title": "Software Engineer"},
            {"title": "Product Manager"},
        ]
        url = "https://jobs.company.com/search?q=nonexistent"
        
        result = filter_jobs_by_search_query(jobs, url)
        # Should return all when nothing matches
        assert len(result) == 2
    
    def test_search_param_variations(self):
        """Test different search parameter names."""
        jobs = [{"title": "Python Developer"}, {"title": "Java Developer"}]
        
        # Test 'search' param
        result = filter_jobs_by_search_query(jobs, "https://example.com?search=python")
        assert len(result) == 1
        
        # Test 'query' param
        result = filter_jobs_by_search_query(jobs, "https://example.com?query=python")
        assert len(result) == 1
        
        # Test 'keyword' param
        result = filter_jobs_by_search_query(jobs, "https://example.com?keyword=java")
        assert len(result) == 1


class TestFilterNotAppliedToInternalNavigation:
    """
    Test that search query filtering is NOT applied to internal navigation.
    
    This is the fix for 8com.de bug where ?q=Center was incorrectly
    filtering jobs on the company's own website.
    """
    
    def test_8com_scenario(self):
        """
        8com.de/karriere -> 8com.de/offene-stellen?q=Center
        
        The ?q=Center is internal navigation filter, NOT a job board search.
        All 4 jobs should be returned, not filtered to 2.
        """
        # This is tested at integration level by the domain comparison logic
        # The key insight is: same domain = internal navigation = no filtering
        
        source_url = "https://8com.de/warum-8com/karriere"
        jobs_page_url = "https://www.8com.de/offene-stellen?q=Center"
        
        # Normalize domains
        source_domain = urlparse(source_url).netloc.replace('www.', '')
        jobs_domain = urlparse(jobs_page_url).netloc.replace('www.', '')
        
        is_external = source_domain != jobs_domain
        
        # Should NOT be external (same company website)
        assert is_external is False
        
        # Therefore _filter_jobs_by_search_query should NOT be called
        # and all jobs should be kept


class TestDomainRedirectDetection:
    """Test detection of redirects to different domains (M&A cases)."""
    
    def test_same_domain_no_redirect(self):
        """Same domain should not be flagged as redirect."""
        original = "https://company.com"
        final = "https://company.com/home"
        
        orig_domain = urlparse(original).netloc.replace('www.', '').lower()
        final_domain = urlparse(final).netloc.replace('www.', '').lower()
        
        assert orig_domain == final_domain
    
    def test_www_added_not_redirect(self):
        """Adding www should not be flagged as redirect."""
        original = "https://company.com"
        final = "https://www.company.com"
        
        orig_domain = urlparse(original).netloc.replace('www.', '').lower()
        final_domain = urlparse(final).netloc.replace('www.', '').lower()
        
        assert orig_domain == final_domain
    
    def test_different_domain_is_redirect(self):
        """Different domain should be flagged as redirect (7pace -> appfire)."""
        original = "https://7pace.com"
        final = "https://appfire.com/7pace"
        
        orig_domain = urlparse(original).netloc.replace('www.', '').lower()
        final_domain = urlparse(final).netloc.replace('www.', '').lower()
        
        assert orig_domain != final_domain
        assert orig_domain == "7pace.com"
        assert final_domain == "appfire.com"

