"""Tests for CacheManager."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

from src.searchers.cache_manager import CacheManager


@dataclass
class MockSite:
    id: int
    domain: str
    description: str = None


@dataclass
class MockCareerUrl:
    id: int
    url: str
    site_id: int


@dataclass
class MockSyncResult:
    new_jobs: list
    removed_jobs: list
    reactivated_jobs: list
    
    @property
    def has_changes(self):
        return bool(self.new_jobs or self.removed_jobs or self.reactivated_jobs)


@pytest.fixture
def mock_repository():
    """Create mock JobRepository."""
    repo = AsyncMock()
    repo.get_site_by_domain = AsyncMock(return_value=None)
    repo.get_career_urls = AsyncMock(return_value=[])
    repo.mark_url_success = AsyncMock()
    repo.mark_url_failed = AsyncMock(return_value=False)
    repo.get_previous_job_count = AsyncMock(return_value=0)
    repo.sync_jobs = AsyncMock(return_value=MockSyncResult([], [], []))
    repo.update_site_scanned = AsyncMock()
    repo.update_site_description = AsyncMock()
    repo.get_or_create_site = AsyncMock()
    repo.add_career_url = AsyncMock()
    return repo


@pytest.fixture
def cache_manager(mock_repository):
    """Create CacheManager with mocked dependencies."""
    return CacheManager(
        repository=mock_repository,
        extract_jobs=AsyncMock(return_value=[]),
        convert_jobs=AsyncMock(return_value=[]),
        fetch_html=AsyncMock(return_value=None),
        extract_company_info=AsyncMock(return_value=None),
        extract_company_name=MagicMock(return_value="TestCompany"),
    )


class TestSearchWithCache:
    """Tests for search_with_cache method."""
    
    @pytest.mark.asyncio
    async def test_cache_miss_no_site(self, cache_manager, mock_repository):
        """Returns None if site not in database."""
        mock_repository.get_site_by_domain.return_value = None
        
        result = await cache_manager.search_with_cache("https://example.com", "example.com")
        
        assert result is None
        mock_repository.get_site_by_domain.assert_called_once_with("example.com")
    
    @pytest.mark.asyncio
    async def test_cache_miss_no_career_urls(self, cache_manager, mock_repository):
        """Returns None if site exists but no career URLs cached."""
        mock_repository.get_site_by_domain.return_value = MockSite(id=1, domain="example.com")
        mock_repository.get_career_urls.return_value = []
        
        result = await cache_manager.search_with_cache("https://example.com", "example.com")
        
        assert result is None
        mock_repository.get_career_urls.assert_called_once_with(1)
    
    @pytest.mark.asyncio
    async def test_cache_hit_extracts_jobs(self, cache_manager, mock_repository):
        """Uses cached URL to extract jobs."""
        site = MockSite(id=1, domain="example.com")
        career_url = MockCareerUrl(id=10, url="https://example.com/careers", site_id=1)
        jobs_data = [{"title": "Developer", "location": "Berlin", "url": "https://example.com/jobs/1"}]
        mock_jobs = [MagicMock(title="Developer")]
        
        mock_repository.get_site_by_domain.return_value = site
        mock_repository.get_career_urls.return_value = [career_url]
        cache_manager._extract_jobs = AsyncMock(return_value=jobs_data)
        cache_manager._convert_jobs = AsyncMock(return_value=mock_jobs)
        
        result = await cache_manager.search_with_cache("https://example.com", "example.com")
        
        assert result == mock_jobs
        cache_manager._extract_jobs.assert_called_once_with("https://example.com/careers", "https://example.com")
    
    @pytest.mark.asyncio
    async def test_marks_url_success(self, cache_manager, mock_repository):
        """Marks URL as successful after extracting jobs."""
        site = MockSite(id=1, domain="example.com")
        career_url = MockCareerUrl(id=10, url="https://example.com/careers", site_id=1)
        jobs_data = [{"title": "Developer", "location": "Berlin"}]
        
        mock_repository.get_site_by_domain.return_value = site
        mock_repository.get_career_urls.return_value = [career_url]
        cache_manager._extract_jobs = AsyncMock(return_value=jobs_data)
        cache_manager._convert_jobs = AsyncMock(return_value=[MagicMock()])
        
        await cache_manager.search_with_cache("https://example.com", "example.com")
        
        mock_repository.mark_url_success.assert_called_once_with(10)
    
    @pytest.mark.asyncio
    async def test_marks_url_failed_on_error(self, cache_manager, mock_repository):
        """Marks URL as failed when extraction raises exception."""
        site = MockSite(id=1, domain="example.com")
        career_url = MockCareerUrl(id=10, url="https://example.com/careers", site_id=1)
        
        mock_repository.get_site_by_domain.return_value = site
        mock_repository.get_career_urls.return_value = [career_url]
        cache_manager._extract_jobs = AsyncMock(side_effect=Exception("Network error"))
        
        result = await cache_manager.search_with_cache("https://example.com", "example.com")
        
        assert result is None
        mock_repository.mark_url_failed.assert_called_once_with(10)
    
    @pytest.mark.asyncio
    async def test_falls_back_on_all_urls_failed(self, cache_manager, mock_repository):
        """Returns None when all cached URLs fail."""
        site = MockSite(id=1, domain="example.com")
        urls = [
            MockCareerUrl(id=1, url="https://example.com/jobs", site_id=1),
            MockCareerUrl(id=2, url="https://example.com/careers", site_id=1),
        ]
        
        mock_repository.get_site_by_domain.return_value = site
        mock_repository.get_career_urls.return_value = urls
        cache_manager._extract_jobs = AsyncMock(side_effect=Exception("Failed"))
        
        result = await cache_manager.search_with_cache("https://example.com", "example.com")
        
        assert result is None
        assert mock_repository.mark_url_failed.call_count == 2
    
    @pytest.mark.asyncio
    async def test_syncs_jobs_with_database(self, cache_manager, mock_repository):
        """Syncs extracted jobs with database."""
        site = MockSite(id=1, domain="example.com")
        career_url = MockCareerUrl(id=10, url="https://example.com/careers", site_id=1)
        mock_jobs = [MagicMock(title="Developer")]
        sync_result = MockSyncResult(new_jobs=[mock_jobs[0]], removed_jobs=[], reactivated_jobs=[])
        
        mock_repository.get_site_by_domain.return_value = site
        mock_repository.get_career_urls.return_value = [career_url]
        mock_repository.sync_jobs.return_value = sync_result
        cache_manager._extract_jobs = AsyncMock(return_value=[{"title": "Developer"}])
        cache_manager._convert_jobs = AsyncMock(return_value=mock_jobs)
        
        await cache_manager.search_with_cache("https://example.com", "example.com")
        
        mock_repository.sync_jobs.assert_called_once_with(1, mock_jobs)
        assert cache_manager.last_sync_result == sync_result


class TestSaveToCache:
    """Tests for save_to_cache method."""
    
    @pytest.mark.asyncio
    async def test_creates_site(self, cache_manager, mock_repository):
        """Creates site on first save."""
        site = MockSite(id=1, domain="example.com")
        mock_repository.get_or_create_site.return_value = site
        
        await cache_manager.save_to_cache("example.com", "https://example.com/jobs", [])
        
        mock_repository.get_or_create_site.assert_called_once_with("example.com", "TestCompany")
    
    @pytest.mark.asyncio
    async def test_saves_career_url(self, cache_manager, mock_repository):
        """Saves career URL to database."""
        site = MockSite(id=1, domain="example.com")
        mock_repository.get_or_create_site.return_value = site
        
        await cache_manager.save_to_cache("example.com", "https://example.com/jobs", [])
        
        mock_repository.add_career_url.assert_called_once()
        call_args = mock_repository.add_career_url.call_args
        assert call_args[0][0] == 1  # site_id
        assert call_args[0][1] == "https://example.com/jobs"  # url
    
    @pytest.mark.asyncio
    async def test_syncs_jobs(self, cache_manager, mock_repository):
        """Syncs jobs with database."""
        site = MockSite(id=1, domain="example.com")
        mock_jobs = [MagicMock(title="Developer")]
        mock_repository.get_or_create_site.return_value = site
        
        await cache_manager.save_to_cache("example.com", "https://example.com/jobs", mock_jobs)
        
        mock_repository.sync_jobs.assert_called_once_with(1, mock_jobs)
    
    @pytest.mark.asyncio
    async def test_updates_scan_timestamp(self, cache_manager, mock_repository):
        """Updates site scan timestamp."""
        site = MockSite(id=1, domain="example.com")
        mock_repository.get_or_create_site.return_value = site
        
        await cache_manager.save_to_cache("example.com", "https://example.com/jobs", [])
        
        mock_repository.update_site_scanned.assert_called_once_with(1)
    
    @pytest.mark.asyncio
    async def test_handles_save_error_gracefully(self, cache_manager, mock_repository):
        """Handles database errors without raising."""
        mock_repository.get_or_create_site.side_effect = Exception("DB error")
        
        # Should not raise
        await cache_manager.save_to_cache("example.com", "https://example.com/jobs", [])


class TestDeduplicateJobs:
    """Tests for _deduplicate_jobs method."""
    
    def test_deduplicate_by_url(self, cache_manager):
        """Removes duplicate jobs by URL."""
        jobs = [
            {"title": "Developer", "url": "https://example.com/jobs/1"},
            {"title": "Developer Copy", "url": "https://example.com/jobs/1"},  # duplicate
            {"title": "Manager", "url": "https://example.com/jobs/2"},
        ]
        
        result = cache_manager._deduplicate_jobs(jobs, "https://example.com/careers")
        
        assert len(result) == 2
        assert result[0]["title"] == "Developer"
        assert result[1]["title"] == "Manager"
    
    def test_deduplicate_by_title_location(self, cache_manager):
        """Removes duplicates by (title, location) when no URL."""
        jobs = [
            {"title": "Developer", "location": "Berlin"},
            {"title": "Developer", "location": "Berlin"},  # duplicate
            {"title": "Developer", "location": "Munich"},  # different location
        ]
        
        result = cache_manager._deduplicate_jobs(jobs, "https://example.com/careers")
        
        assert len(result) == 2
    
    def test_ignores_self_referencing_urls(self, cache_manager):
        """Treats self-referencing URLs as empty."""
        base_url = "https://example.com/careers"
        jobs = [
            {"title": "Developer", "url": "https://example.com/careers"},  # same as base
            {"title": "Developer", "url": "https://example.com/careers#"},  # anchor
            {"title": "Manager", "url": "https://example.com/jobs/1"},  # different
        ]
        
        result = cache_manager._deduplicate_jobs(jobs, base_url)
        
        # First two have same base URL, should be deduplicated by title+location
        # (both have title "Developer" but no location, so treated as duplicates)
        assert len(result) == 2
    
    def test_handles_none_url(self, cache_manager):
        """Handles None URL values."""
        jobs = [
            {"title": "Developer", "url": None, "location": "Berlin"},
            {"title": "Manager", "url": "None", "location": "Berlin"},  # string "None"
        ]
        
        result = cache_manager._deduplicate_jobs(jobs, "https://example.com/careers")
        
        assert len(result) == 2  # Different titles


class TestMaybeExtractCompanyInfo:
    """Tests for _maybe_extract_company_info method."""
    
    @pytest.mark.asyncio
    async def test_skips_if_description_exists(self, cache_manager, mock_repository):
        """Skips extraction if site already has description."""
        site = MockSite(id=1, domain="example.com", description="Existing description")
        
        await cache_manager._maybe_extract_company_info(site, "example.com")
        
        cache_manager._fetch_html.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_extracts_and_saves_description(self, cache_manager, mock_repository):
        """Extracts and saves company description."""
        site = MockSite(id=1, domain="example.com", description=None)
        cache_manager._fetch_html = AsyncMock(return_value="<html>...</html>")
        cache_manager._extract_company_info = AsyncMock(return_value="Tech company in Berlin")
        
        await cache_manager._maybe_extract_company_info(site, "example.com")
        
        cache_manager._fetch_html.assert_called_once_with("https://example.com")
        mock_repository.update_site_description.assert_called_once_with(1, "Tech company in Berlin")
    
    @pytest.mark.asyncio
    async def test_handles_extraction_error(self, cache_manager, mock_repository):
        """Handles errors during extraction."""
        site = MockSite(id=1, domain="example.com", description=None)
        cache_manager._fetch_html = AsyncMock(side_effect=Exception("Network error"))
        
        # Should not raise
        await cache_manager._maybe_extract_company_info(site, "example.com")

