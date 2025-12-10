"""Smoke tests for src/browser/loader.py - Browser automation.

These tests verify that:
- BrowserLoader can be instantiated
- Context manager works correctly
- Error handling is in place

Run after changes to: src/browser/loader.py, src/browser/navigation.py
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.browser.loader import BrowserLoader, get_browser_loader
from src.browser.exceptions import DomainUnreachableError, PlaywrightBrowsersNotInstalledError


class TestBrowserLoaderInit:
    """Tests for BrowserLoader initialization."""
    
    def test_default_initialization(self):
        """Should initialize with default values."""
        loader = BrowserLoader()
        
        assert loader.headless is True
        assert loader.timeout == 30000
        assert loader._browser is None
        assert loader._playwright is None
    
    def test_custom_initialization(self):
        """Should accept custom parameters."""
        loader = BrowserLoader(headless=False, timeout=60000)
        
        assert loader.headless is False
        assert loader.timeout == 60000
    
    def test_has_required_methods(self):
        """Should have all required methods."""
        loader = BrowserLoader()
        
        assert hasattr(loader, 'start')
        assert hasattr(loader, 'stop')
        assert hasattr(loader, 'fetch')
        assert hasattr(loader, 'fetch_with_navigation')
        assert hasattr(loader, 'fetch_with_page')
        assert hasattr(loader, '__aenter__')
        assert hasattr(loader, '__aexit__')


class TestBrowserLoaderContextManager:
    """Tests for BrowserLoader context manager."""
    
    @pytest.mark.asyncio
    async def test_context_manager_calls_start_and_stop(self):
        """Context manager should call start on entry and stop on exit."""
        loader = BrowserLoader()
        
        with patch.object(loader, 'start', new_callable=AsyncMock) as mock_start:
            with patch.object(loader, 'stop', new_callable=AsyncMock) as mock_stop:
                async with loader:
                    mock_start.assert_called_once()
                
                mock_stop.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_browser_loader_helper(self):
        """get_browser_loader should work as context manager."""
        with patch('src.browser.loader.BrowserLoader') as MockLoader:
            mock_instance = AsyncMock()
            MockLoader.return_value = mock_instance
            mock_instance.start = AsyncMock()
            mock_instance.stop = AsyncMock()
            
            async with get_browser_loader(headless=True) as loader:
                assert loader is mock_instance
                mock_instance.start.assert_called_once()
            
            mock_instance.stop.assert_called_once()


class TestBrowserLoaderFetch:
    """Tests for BrowserLoader.fetch method."""
    
    @pytest.mark.asyncio
    async def test_fetch_returns_none_on_error(self):
        """fetch should return None on general errors."""
        loader = BrowserLoader()
        loader._browser = MagicMock()
        
        # Mock context that raises an error
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(side_effect=Exception("Connection failed"))
        mock_context.new_page = AsyncMock(return_value=mock_page)
        loader._browser.new_context = AsyncMock(return_value=mock_context)
        
        # Mock page.close() to not fail
        mock_page.close = AsyncMock()
        mock_page.context = mock_context
        mock_context.close = AsyncMock()
        
        result = await loader.fetch("https://example.com")
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_fetch_raises_domain_unreachable_on_network_error(self):
        """fetch should raise DomainUnreachableError on network issues."""
        loader = BrowserLoader()
        loader._browser = MagicMock()
        
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(side_effect=Exception("net::ERR_NAME_NOT_RESOLVED"))
        mock_context.new_page = AsyncMock(return_value=mock_page)
        loader._browser.new_context = AsyncMock(return_value=mock_context)
        
        mock_page.close = AsyncMock()
        mock_page.context = mock_context
        mock_context.close = AsyncMock()
        
        with pytest.raises(DomainUnreachableError):
            await loader.fetch("https://nonexistent-domain.invalid")


class TestScrollAndWaitForContent:
    """Tests for _scroll_and_wait_for_content method."""
    
    @pytest.mark.asyncio
    async def test_scroll_executes_without_error(self):
        """_scroll_and_wait_for_content should not raise on success."""
        loader = BrowserLoader()
        
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=None)
        mock_page.wait_for_timeout = AsyncMock(return_value=None)
        mock_page.wait_for_load_state = AsyncMock(return_value=None)
        
        # Should not raise
        await loader._scroll_and_wait_for_content(mock_page, max_scrolls=2)
        
        # Verify scrolling was attempted
        assert mock_page.evaluate.call_count >= 2
    
    @pytest.mark.asyncio
    async def test_scroll_handles_timeout_gracefully(self):
        """_scroll_and_wait_for_content should handle timeouts."""
        loader = BrowserLoader()
        
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=None)
        mock_page.wait_for_timeout = AsyncMock(return_value=None)
        mock_page.wait_for_load_state = AsyncMock(side_effect=Exception("Timeout"))
        
        # Should not raise even on timeout
        await loader._scroll_and_wait_for_content(mock_page, max_scrolls=1)


class TestExceptionsExist:
    """Tests for browser exceptions."""
    
    def test_domain_unreachable_error_exists(self):
        """DomainUnreachableError should be defined and usable."""
        error = DomainUnreachableError("Test domain unreachable")
        
        assert str(error) == "Test domain unreachable"
        assert isinstance(error, Exception)
    
    def test_playwright_not_installed_error_exists(self):
        """PlaywrightBrowsersNotInstalledError should be defined."""
        error = PlaywrightBrowsersNotInstalledError("Browsers not installed")
        
        assert "not installed" in str(error).lower()
        assert isinstance(error, Exception)


class TestPatternsImport:
    """Tests for browser patterns module."""
    
    def test_default_user_agent_exists(self):
        """DEFAULT_USER_AGENT should be defined."""
        from src.browser.patterns import DEFAULT_USER_AGENT
        
        assert isinstance(DEFAULT_USER_AGENT, str)
        assert len(DEFAULT_USER_AGENT) > 20
        assert "Mozilla" in DEFAULT_USER_AGENT
    
    def test_network_error_patterns_exists(self):
        """NETWORK_ERROR_PATTERNS should be defined."""
        from src.browser.patterns import NETWORK_ERROR_PATTERNS
        
        assert isinstance(NETWORK_ERROR_PATTERNS, (list, tuple, set))
        assert len(NETWORK_ERROR_PATTERNS) > 0
        
        # Should contain common network errors
        patterns_str = " ".join(NETWORK_ERROR_PATTERNS)
        assert "ERR_" in patterns_str or "error" in patterns_str.lower()


# Run with: pytest tests/test_smoke_browser.py -v

