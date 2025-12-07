"""Recruitee job board parser."""

import json
import logging
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from src.searchers.job_boards.base import BaseJobBoardParser

logger = logging.getLogger(__name__)


class RecruiteeParser(BaseJobBoardParser):
    """Parser for Recruitee job board.
    
    Recruitee is a SPA that loads job data via API.
    Jobs are available at /api/offers endpoint as JSON.
    """

    platform_name = "recruitee"

    def parse(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Parse jobs from Recruitee HTML.
        
        Note: Recruitee renders jobs via JavaScript, so the HTML itself
        doesn't contain job listings. The data is embedded in the initial
        page state as JSON in a script tag or needs to be fetched from API.
        
        This parser attempts to:
        1. Extract embedded JSON data from script tags
        2. Parse job links from HTML (if rendered server-side)
        """
        jobs = []
        seen_urls = set()
        
        # Strategy 1: Try to extract embedded JSON data from script tags
        # Recruitee embeds initial state in a script tag
        jobs = self._extract_from_embedded_json(soup, base_url)
        if jobs:
            return jobs
        
        # Strategy 2: Parse job links from HTML (fallback)
        jobs = self._extract_from_links(soup, base_url)
        
        return jobs

    def _extract_from_embedded_json(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Extract jobs from embedded JSON in script tags."""
        jobs = []
        seen_urls = set()
        
        # Look for script tags with job data
        for script in soup.find_all('script'):
            text = script.string or ''
            
            # Look for offers array in the script
            if '"offers"' in text or "'offers'" in text:
                # Try to extract the offers JSON
                offers_match = re.search(r'"offers"\s*:\s*(\[.*?\])\s*[,}]', text, re.DOTALL)
                if offers_match:
                    try:
                        offers_json = offers_match.group(1)
                        # Fix common JSON issues
                        offers = json.loads(offers_json)
                        
                        for offer in offers:
                            job_url = offer.get('careers_url') or offer.get('url', '')
                            if job_url in seen_urls:
                                continue
                            seen_urls.add(job_url)
                            
                            title = offer.get('title', '')
                            location = offer.get('location', '')
                            
                            # Try to get city and state for better location
                            if not location:
                                city = offer.get('city', '')
                                state = offer.get('state_name', '')
                                country = offer.get('country', '')
                                location_parts = [p for p in [city, state, country] if p]
                                location = ', '.join(location_parts)
                            
                            department = offer.get('department', '')
                            
                            if title:
                                jobs.append({
                                    "title": title,
                                    "location": location or "Unknown",
                                    "url": job_url if job_url else base_url,
                                    "department": department,
                                })
                                
                        if jobs:
                            logger.debug(f"Extracted {len(jobs)} jobs from embedded JSON")
                            return jobs
                            
                    except json.JSONDecodeError:
                        continue
        
        return jobs

    def _extract_from_links(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Extract jobs from HTML links (fallback method)."""
        jobs = []
        seen_urls = set()
        
        # Recruitee uses /o/ prefix for job pages
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            
            # Check for Recruitee job URL patterns
            if '/o/' not in href:
                continue
            
            # Skip apply/new links
            if '/c/new' in href:
                continue
            
            job_url = self._build_full_url(href, base_url)
            
            if job_url in seen_urls:
                continue
            seen_urls.add(job_url)
            
            # Get job title from link text
            title = link.get_text(separator=' ', strip=True)
            if not title:
                continue
            
            # Try to find location from sibling/parent elements
            location = "Unknown"
            parent = link.find_parent(['article', 'div', 'li'])
            if parent:
                # Look for location patterns
                location_elem = parent.find(string=re.compile(r'(Remote|Hybrid|On-site|vor Ort|Standort)', re.IGNORECASE))
                if location_elem:
                    location = location_elem.strip()
            
            jobs.append({
                "title": title,
                "location": location,
                "url": job_url,
                "department": None,
            })
        
        return jobs

    @staticmethod
    def get_api_url(base_url: str) -> str:
        """Get the API URL for fetching offers.
        
        Recruitee provides a /api/offers endpoint that returns JSON.
        
        Args:
            base_url: The base URL of the Recruitee career site
            
        Returns:
            API URL for fetching offers
        """
        parsed = urlparse(base_url)
        return f"{parsed.scheme}://{parsed.netloc}/api/offers"





