"""Smoke tests for src/llm/prompts.py - LLM prompt templates.

These tests verify that:
- All required prompts are defined
- Prompts can be formatted without errors
- Prompts contain expected placeholders

Run after changes to: src/llm/prompts.py
"""

import pytest

from src.llm import prompts


class TestPromptsExist:
    """Verify all required prompts are defined."""
    
    def test_find_careers_page_prompt_exists(self):
        """FIND_CAREERS_PAGE_PROMPT should be defined."""
        assert hasattr(prompts, 'FIND_CAREERS_PAGE_PROMPT')
        assert isinstance(prompts.FIND_CAREERS_PAGE_PROMPT, str)
        assert len(prompts.FIND_CAREERS_PAGE_PROMPT) > 100
    
    def test_extract_jobs_prompt_exists(self):
        """EXTRACT_JOBS_PROMPT should be defined."""
        assert hasattr(prompts, 'EXTRACT_JOBS_PROMPT')
        assert isinstance(prompts.EXTRACT_JOBS_PROMPT, str)
        assert len(prompts.EXTRACT_JOBS_PROMPT) > 100
    
    def test_system_prompt_exists(self):
        """SYSTEM_PROMPT should be defined."""
        assert hasattr(prompts, 'SYSTEM_PROMPT')
        assert isinstance(prompts.SYSTEM_PROMPT, str)
        assert len(prompts.SYSTEM_PROMPT) > 50
    
    def test_find_job_board_prompt_exists(self):
        """FIND_JOB_BOARD_PROMPT should be defined."""
        assert hasattr(prompts, 'FIND_JOB_BOARD_PROMPT')
        assert isinstance(prompts.FIND_JOB_BOARD_PROMPT, str)
    
    def test_translate_job_titles_prompt_exists(self):
        """TRANSLATE_JOB_TITLES_PROMPT should be defined."""
        assert hasattr(prompts, 'TRANSLATE_JOB_TITLES_PROMPT')
        assert isinstance(prompts.TRANSLATE_JOB_TITLES_PROMPT, str)
    
    def test_find_careers_from_sitemap_prompt_exists(self):
        """FIND_CAREERS_FROM_SITEMAP_PROMPT should be defined."""
        assert hasattr(prompts, 'FIND_CAREERS_FROM_SITEMAP_PROMPT')
        assert isinstance(prompts.FIND_CAREERS_FROM_SITEMAP_PROMPT, str)
    
    def test_find_job_urls_prompt_exists(self):
        """FIND_JOB_URLS_PROMPT should be defined."""
        assert hasattr(prompts, 'FIND_JOB_URLS_PROMPT')
        assert isinstance(prompts.FIND_JOB_URLS_PROMPT, str)
    
    def test_extract_company_info_prompt_exists(self):
        """EXTRACT_COMPANY_INFO_PROMPT should be defined."""
        assert hasattr(prompts, 'EXTRACT_COMPANY_INFO_PROMPT')
        assert isinstance(prompts.EXTRACT_COMPANY_INFO_PROMPT, str)


class TestPromptFormatting:
    """Verify prompts can be formatted without errors."""
    
    def test_find_careers_page_prompt_formats(self):
        """FIND_CAREERS_PAGE_PROMPT should format without errors."""
        result = prompts.FIND_CAREERS_PAGE_PROMPT.format(
            base_url="https://example.com",
            html="<html><body>Test</body></html>",
            sitemap_urls="https://example.com/careers\nhttps://example.com/jobs",
        )
        
        assert "https://example.com" in result
        assert "<html>" in result
    
    def test_extract_jobs_prompt_formats(self):
        """EXTRACT_JOBS_PROMPT should format without errors."""
        result = prompts.EXTRACT_JOBS_PROMPT.format(
            url="https://example.com/careers",
            html="<html><body>Jobs here</body></html>",
        )
        
        assert "https://example.com/careers" in result
        assert "Jobs here" in result
    
    def test_find_job_board_prompt_formats(self):
        """FIND_JOB_BOARD_PROMPT should format without errors."""
        result = prompts.FIND_JOB_BOARD_PROMPT.format(
            url="https://example.com/careers",
            html="Link 1\nLink 2\nLink 3",
        )
        
        assert "https://example.com/careers" in result
        assert "Link 1" in result
    
    def test_translate_job_titles_prompt_formats(self):
        """TRANSLATE_JOB_TITLES_PROMPT should format without errors."""
        result = prompts.TRANSLATE_JOB_TITLES_PROMPT.format(
            titles="Entwickler (m/w/d)\nManager (m/w/d)",
        )
        
        assert "Entwickler" in result
        assert "Manager" in result
    
    def test_find_careers_from_sitemap_prompt_formats(self):
        """FIND_CAREERS_FROM_SITEMAP_PROMPT should format without errors."""
        result = prompts.FIND_CAREERS_FROM_SITEMAP_PROMPT.format(
            base_url="https://example.com",
            urls="https://example.com/page1\nhttps://example.com/careers",
        )
        
        assert "https://example.com" in result
        assert "careers" in result
    
    def test_find_job_urls_prompt_formats(self):
        """FIND_JOB_URLS_PROMPT should format without errors."""
        result = prompts.FIND_JOB_URLS_PROMPT.format(
            url="https://example.com/careers",
            html="<html><body>Job listings</body></html>",
        )
        
        assert "https://example.com/careers" in result
    
    def test_extract_company_info_prompt_formats(self):
        """EXTRACT_COMPANY_INFO_PROMPT should format without errors."""
        result = prompts.EXTRACT_COMPANY_INFO_PROMPT.format(
            url="https://example.com",
            html="<html><body>We are a tech company</body></html>",
        )
        
        assert "https://example.com" in result


class TestPromptContents:
    """Verify prompts contain expected content."""
    
    def test_system_prompt_has_security_rules(self):
        """SYSTEM_PROMPT should contain security rules."""
        prompt = prompts.SYSTEM_PROMPT
        
        assert "SECURITY" in prompt.upper() or "UNTRUSTED" in prompt.upper()
        assert "ignore" in prompt.lower()  # Should mention ignoring injections
    
    def test_extract_jobs_prompt_has_json_format(self):
        """EXTRACT_JOBS_PROMPT should specify JSON output format."""
        prompt = prompts.EXTRACT_JOBS_PROMPT
        
        assert "json" in prompt.lower()
        assert "jobs" in prompt.lower()
        assert "title" in prompt.lower()
    
    def test_extract_jobs_prompt_mentions_pagination(self):
        """EXTRACT_JOBS_PROMPT should mention pagination handling."""
        prompt = prompts.EXTRACT_JOBS_PROMPT
        
        assert "pagination" in prompt.lower() or "next_page" in prompt.lower()
    
    def test_find_careers_prompt_has_keywords(self):
        """FIND_CAREERS_PAGE_PROMPT should list career-related keywords."""
        prompt = prompts.FIND_CAREERS_PAGE_PROMPT
        
        assert "careers" in prompt.lower()
        assert "jobs" in prompt.lower()
        # German keywords
        assert "karriere" in prompt.lower()
        assert "stellen" in prompt.lower()
    
    def test_prompts_have_untrusted_markers(self):
        """Prompts with HTML input should mark content as untrusted."""
        html_prompts = [
            prompts.FIND_CAREERS_PAGE_PROMPT,
            prompts.EXTRACT_JOBS_PROMPT,
            prompts.FIND_JOB_URLS_PROMPT,
            prompts.EXTRACT_COMPANY_INFO_PROMPT,
        ]
        
        for prompt in html_prompts:
            assert "UNTRUSTED" in prompt, f"Prompt should mark HTML as untrusted"


class TestPromptPlaceholders:
    """Verify prompts have correct placeholders."""
    
    def test_find_careers_page_placeholders(self):
        """FIND_CAREERS_PAGE_PROMPT should have required placeholders."""
        prompt = prompts.FIND_CAREERS_PAGE_PROMPT
        
        assert "{base_url}" in prompt
        assert "{html}" in prompt
        assert "{sitemap_urls}" in prompt
    
    def test_extract_jobs_placeholders(self):
        """EXTRACT_JOBS_PROMPT should have required placeholders."""
        prompt = prompts.EXTRACT_JOBS_PROMPT
        
        assert "{url}" in prompt
        assert "{html}" in prompt
    
    def test_find_job_board_placeholders(self):
        """FIND_JOB_BOARD_PROMPT should have required placeholders."""
        prompt = prompts.FIND_JOB_BOARD_PROMPT
        
        assert "{url}" in prompt
        assert "{html}" in prompt
    
    def test_translate_titles_placeholders(self):
        """TRANSLATE_JOB_TITLES_PROMPT should have required placeholders."""
        prompt = prompts.TRANSLATE_JOB_TITLES_PROMPT
        
        assert "{titles}" in prompt


# Run with: pytest tests/test_smoke_prompts.py -v

