"""Job board parser registry."""

import logging
from typing import Optional

from bs4 import BeautifulSoup

from src.searchers.job_boards.base import BaseJobBoardParser
from src.searchers.job_boards.personio import PersonioParser
from src.searchers.job_boards.greenhouse import GreenhouseParser
from src.searchers.job_boards.lever import LeverParser

logger = logging.getLogger(__name__)


class JobBoardParserRegistry:
    """Registry for job board parsers."""

    def __init__(self):
        """Initialize registry with default parsers."""
        self._parsers: dict[str, BaseJobBoardParser] = {}
        self._register_defaults()

    def _register_defaults(self):
        """Register default job board parsers."""
        self.register(PersonioParser())
        self.register(GreenhouseParser())
        self.register(LeverParser())

    def register(self, parser: BaseJobBoardParser):
        """Register a parser for a platform."""
        self._parsers[parser.platform_name] = parser

    def get_parser(self, platform: str) -> Optional[BaseJobBoardParser]:
        """Get parser for platform."""
        return self._parsers.get(platform)

    def parse(self, html: str, base_url: str, platform: str) -> list[dict]:
        """Parse jobs from HTML using appropriate parser.
        
        Args:
            html: HTML content
            base_url: Base URL for resolving links
            platform: Platform name (e.g., 'personio', 'greenhouse')
            
        Returns:
            List of job dictionaries or empty list if parser not found
        """
        parser = self.get_parser(platform)
        if not parser:
            logger.debug(f"No parser registered for platform: {platform}")
            return []
        
        soup = BeautifulSoup(html, 'lxml')
        jobs = parser.parse(soup, base_url)
        
        if jobs:
            logger.info(f"Parsed {len(jobs)} jobs from {platform} directly")
        
        return jobs

