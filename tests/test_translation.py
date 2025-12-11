"""Tests for translation fallback functionality."""

import pytest
from unittest.mock import AsyncMock

from src.llm.base import BaseLLMProvider, TRANSLATION_RULES


class MockLLMProvider(BaseLLMProvider):
    """Mock provider for testing translation methods."""
    
    async def complete(self, prompt: str, system: str = None) -> str:
        return ""


class TestTranslationRulesCompiled:
    """Test that translation rules are pre-compiled."""
    
    def test_rules_are_compiled_regex(self):
        """All rules should be pre-compiled regex patterns."""
        import re
        for pattern, replacement in TRANSLATION_RULES:
            assert isinstance(pattern, re.Pattern), f"Pattern should be compiled: {pattern}"
            assert isinstance(replacement, str), f"Replacement should be string: {replacement}"
    
    def test_rules_cover_common_german_terms(self):
        """Rules should include common German job title terms."""
        patterns_text = ' '.join(p.pattern for p, _ in TRANSLATION_RULES)
        
        # Essential terms
        assert 'entwickler' in patterns_text
        assert 'ingenieur' in patterns_text
        assert 'leiter' in patterns_text
        assert 'für' in patterns_text
        assert 'systemadministrator' in patterns_text


class TestDictionaryTranslation:
    """Test _translate_with_dictionary method."""
    
    @pytest.fixture
    def provider(self):
        return MockLLMProvider()
    
    def test_translates_german_connector_fuer(self, provider):
        """Should translate 'für' to 'for'."""
        titles = ["Manager für IT"]
        result = provider._translate_with_dictionary(titles)
        assert result == ["Manager for IT"]
    
    def test_translates_systemadministrator(self, provider):
        """Should translate compound German words."""
        titles = ["Systemadministrator (m/w/d)"]
        result = provider._translate_with_dictionary(titles)
        assert result == ["System Administrator (m/w/d)"]
    
    def test_translates_teamleitung(self, provider):
        """Should translate Teamleitung to Team Lead."""
        titles = ["Teamleitung Cyber Security"]
        result = provider._translate_with_dictionary(titles)
        assert result == ["Team Lead Cyber Security"]
    
    def test_translates_entwickler(self, provider):
        """Should translate Entwickler to Developer."""
        titles = ["Software Entwickler"]
        result = provider._translate_with_dictionary(titles)
        assert result == ["Software Developer"]
    
    def test_translates_multiple_words_in_title(self, provider):
        """Should translate multiple German words in one title."""
        titles = ["Systemadministrator für interne IT"]
        result = provider._translate_with_dictionary(titles)
        assert result == ["System Administrator for internal IT"]
    
    def test_preserves_english_titles(self, provider):
        """Should not modify already-English titles."""
        titles = ["Software Engineer", "Product Manager", "Chief Operating Officer"]
        result = provider._translate_with_dictionary(titles)
        assert result == titles
    
    def test_preserves_gender_notation(self, provider):
        """Should preserve (m/w/d) notation."""
        titles = ["Entwickler (m/w/d)"]
        result = provider._translate_with_dictionary(titles)
        assert "(m/w/d)" in result[0]
        assert "Developer" in result[0]
    
    def test_handles_empty_list(self, provider):
        """Should handle empty input."""
        result = provider._translate_with_dictionary([])
        assert result == []
    
    def test_handles_special_characters(self, provider):
        """Should handle German special characters."""
        titles = ["Geschäftsführer (m/w/d)"]
        result = provider._translate_with_dictionary(titles)
        assert result == ["Managing Director (m/w/d)"]
    
    def test_case_insensitive(self, provider):
        """Should work regardless of case."""
        titles = ["ENTWICKLER", "entwickler", "Entwickler"]
        result = provider._translate_with_dictionary(titles)
        assert all("Developer" in r for r in result)
    
    def test_translates_kaufmann_kauffrau(self, provider):
        """Should translate Kaufmann/Kauffrau."""
        titles = ["Kaufmann für Büromanagement", "Kauffrau im Einzelhandel"]
        result = provider._translate_with_dictionary(titles)
        assert "Commercial Clerk" in result[0]
        assert "Commercial Clerk" in result[1]
    
    def test_translates_werkstudent(self, provider):
        """Should translate Werkstudent."""
        titles = ["Werkstudent Softwareentwicklung"]
        result = provider._translate_with_dictionary(titles)
        assert "Working Student" in result[0]
    
    def test_translates_employment_type(self, provider):
        """Should translate Vollzeit/Teilzeit."""
        titles = ["Manager (Vollzeit)", "Berater (Teilzeit)"]
        result = provider._translate_with_dictionary(titles)
        assert "Full-time" in result[0]
        assert "Part-time" in result[1]
    
    def test_8com_real_titles(self, provider):
        """Should correctly translate real 8com.de job titles."""
        titles = [
            "Service Manager (m/w/d) für Security Operations Center",
            "Systemadministrator (m/w/d) für interne IT",
            "Teamleitung Cyber Security Automation & SOAR (m/w/d)",
        ]
        result = provider._translate_with_dictionary(titles)
        
        assert result[0] == "Service Manager (m/w/d) for Security Operations Center"
        assert result[1] == "System Administrator (m/w/d) for internal IT"
        assert result[2] == "Team Lead Cyber Security Automation & SOAR (m/w/d)"


class TestTranslationValidation:
    """Test translation response validation."""
    
    @pytest.fixture
    def provider(self):
        return MockLLMProvider()
    
    @pytest.mark.asyncio
    async def test_rejects_garbage_response(self, provider):
        """Should reject responses with encoding garbage."""
        # Simulate garbage LLM response
        provider.complete_json = AsyncMock(return_value={
            "translations": ["Service\xa0?\xa0??", "...", {"error": "Invalid"}]
        })
        
        titles = ["Title 1", "Title 2", "Title 3"]
        result = await provider.translate_job_titles(titles)
        
        # Should use dictionary fallback, not garbage
        assert "\xa0" not in str(result)
        assert "error" not in str(result).lower()
    
    @pytest.mark.asyncio
    async def test_accepts_valid_response(self, provider):
        """Should accept valid LLM response."""
        provider.complete_json = AsyncMock(return_value={
            "translations": ["Developer", "Engineer", "Manager"]
        })
        
        # Need to set cache to None to avoid cache lookup
        provider._cache = None
        
        titles = ["Entwickler", "Ingenieur", "Manager"]
        result = await provider.translate_job_titles(titles)
        
        assert result == ["Developer", "Engineer", "Manager"]
