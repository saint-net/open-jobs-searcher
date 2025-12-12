"""Job board parser registry."""

import logging
from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from src.searchers.job_boards.base import BaseJobBoardParser
from src.searchers.job_boards.personio import PersonioParser
from src.searchers.job_boards.greenhouse import GreenhouseParser
from src.searchers.job_boards.lever import LeverParser
from src.searchers.job_boards.deloitte import DeloitteParser
from src.searchers.job_boards.workable import WorkableParser
from src.searchers.job_boards.recruitee import RecruiteeParser
from src.searchers.job_boards.odoo import OdooParser
from src.searchers.job_boards.hrworks import HRworksParser
from src.searchers.job_boards.hibob import HiBobParser

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
        self.register(DeloitteParser())
        self.register(WorkableParser())
        self.register(RecruiteeParser())
        self.register(OdooParser())
        self.register(HRworksParser())
        self.register(HiBobParser())

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
        jobs = parser.parse_and_filter(soup, base_url)
        
        if jobs:
            logger.info(f"Parsed {len(jobs)} jobs from {platform} directly")
        
        return jobs

    def parse_api_json(self, json_data: dict, base_url: str, platform: str) -> list[dict]:
        """Parse jobs from API JSON response.
        
        Some platforms (like Recruitee) load job data via API instead of 
        embedding it in HTML. This method parses JSON API responses.
        
        Args:
            json_data: JSON response from API
            base_url: Base URL for resolving links
            platform: Platform name (e.g., 'recruitee')
            
        Returns:
            List of job dictionaries or empty list if parser not found
        """
        if platform == 'recruitee':
            return self._parse_recruitee_api(json_data, base_url)
        
        logger.debug(f"No API parser for platform: {platform}")
        return []

    def _parse_recruitee_api(self, json_data: dict, base_url: str) -> list[dict]:
        """Parse jobs from Recruitee API response.
        
        Recruitee API returns: {"offers": [{...}, {...}]}
        """
        jobs = []
        offers = json_data.get('offers', [])
        
        for offer in offers:
            title = offer.get('title', '')
            if not title:
                continue
            
            # Get location
            location = offer.get('location', '')
            if not location:
                city = offer.get('city', '')
                state = offer.get('state_name', '')
                country = offer.get('country', '')
                location_parts = [p for p in [city, state, country] if p]
                location = ', '.join(location_parts) if location_parts else 'Unknown'
            
            # Get URL
            job_url = offer.get('careers_url', '')
            if not job_url:
                # Construct URL from slug
                slug = offer.get('slug', '')
                if slug:
                    parsed = urlparse(base_url)
                    job_url = f"{parsed.scheme}://{parsed.netloc}/o/{slug}"
                else:
                    job_url = base_url
            
            department = offer.get('department', '')
            
            jobs.append({
                "title": title,
                "location": location,
                "url": job_url,
                "department": department,
            })
        
        if jobs:
            logger.info(f"Parsed {len(jobs)} jobs from Recruitee API")
        
        return jobs

    def get_api_url(self, base_url: str, platform: str) -> Optional[str]:
        """Get API URL for platforms that require API calls.
        
        Args:
            base_url: Base URL of the career site
            platform: Platform name
            
        Returns:
            API URL or None if platform doesn't use API
        """
        if platform == 'recruitee':
            parsed = urlparse(base_url)
            return f"{parsed.scheme}://{parsed.netloc}/api/offers"
        
        return None

    def is_api_based(self, platform: str) -> bool:
        """Check if platform requires API calls instead of HTML parsing.
        
        Args:
            platform: Platform name
            
        Returns:
            True if platform is API-based
        """
        return platform in ('recruitee',)

