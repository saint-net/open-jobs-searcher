"""Protocols for loose coupling in tests.

These protocols define minimal interfaces for mocking,
avoiding tight coupling to production ABC classes.
"""

from typing import Protocol, Optional, TypeVar, runtime_checkable
from pydantic import BaseModel


T = TypeVar("T", bound=BaseModel)


@runtime_checkable
class LLMProviderProtocol(Protocol):
    """Protocol for LLM providers - minimal interface for testing.
    
    Use this for type hints and mocking instead of inheriting from BaseLLMProvider.
    This enables loose coupling between tests and production code.
    """
    
    async def complete(self, prompt: str, system: Optional[str] = None) -> str:
        """Generate LLM response."""
        ...
    
    async def complete_json(self, prompt: str, system: Optional[str] = None) -> dict | list:
        """Generate JSON response."""
        ...
    
    async def complete_structured(
        self, 
        prompt: str, 
        schema: type[T],
        system: Optional[str] = None
    ) -> T:
        """Generate structured response matching Pydantic schema."""
        ...


@runtime_checkable
class HTMLCleanerProtocol(Protocol):
    """Protocol for HTML cleaning functions."""
    
    def __call__(self, html: str) -> str:
        """Clean HTML, return cleaned version."""
        ...


@runtime_checkable
class JobExtractorProtocol(Protocol):
    """Protocol for job extraction - async function signature."""
    
    async def __call__(self, html: str, url: str) -> list[dict]:
        """Extract jobs from HTML."""
        ...


@runtime_checkable 
class BrowserLoaderProtocol(Protocol):
    """Protocol for browser loader - minimal interface."""
    
    headless: bool
    timeout: float
    
    async def start(self) -> None:
        """Start browser."""
        ...
    
    async def stop(self) -> None:
        """Stop browser."""
        ...
    
    async def fetch(self, url: str, wait_for: Optional[str] = None) -> Optional[str]:
        """Fetch page HTML."""
        ...
    
    async def __aenter__(self) -> "BrowserLoaderProtocol":
        ...
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        ...
