"""Deloitte job board parser.

Deloitte uses a complex SPA job portal (job.deloitte.com).
This parser attempts to extract jobs from search results pages.
Falls back to LLM extraction if direct parsing fails.
"""

import re
from urllib.parse import urlparse, parse_qs

from bs4 import BeautifulSoup

from src.searchers.job_boards.base import BaseJobBoardParser


class DeloitteParser(BaseJobBoardParser):
    """Parser for Deloitte job board (job.deloitte.com)."""

    platform_name = "deloitte"

    def parse(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Parse jobs from Deloitte search results HTML.
        
        Deloitte's job portal is a complex SPA. This parser attempts to extract
        job listings from the rendered HTML. If no jobs are found, the system
        falls back to LLM-based extraction.
        """
        jobs = []
        seen_urls = set()
        
        # Extract search term from URL for filtering
        search_term = self._extract_search_term(base_url)
        
        # Deloitte job links typically contain /job/ or /stelle/ in the path
        # and have job titles in the link text
        job_link_patterns = [
            r'/job/',
            r'/stelle/',
            r'/position/',
            r'jobdetail',
        ]
        
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            
            # Check if this looks like a job link
            is_job_link = any(pattern in href.lower() for pattern in job_link_patterns)
            if not is_job_link:
                continue
            
            # Build full URL
            job_url = self._build_full_url(href, base_url)
            
            # Skip duplicates
            if job_url in seen_urls:
                continue
            seen_urls.add(job_url)
            
            # Extract job title from link text
            title = link.get_text(separator=' ', strip=True)
            if not title or len(title) < 5:
                continue
            
            # Skip navigation/UI links
            if title.lower() in ['zurück', 'back', 'weiter', 'next', 'details', 'mehr']:
                continue
            
            # If we have a search term, filter by it
            if search_term and search_term.lower() not in title.lower():
                continue
            
            # Try to extract location from nearby elements
            location = self._extract_location(link)
            
            jobs.append({
                "title": title,
                "location": location,
                "url": job_url,
            })
        
        return jobs

    def _extract_search_term(self, url: str) -> str | None:
        """Extract search term from URL query parameters."""
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        
        for param_name in ['search', 'q', 'query', 'keyword']:
            if param_name in params:
                return params[param_name][0]
        
        return None

    def _extract_location(self, link_element) -> str:
        """Try to extract location from the job listing element."""
        # Check parent elements for location info
        parent = link_element.parent
        for _ in range(3):  # Check up to 3 levels up
            if parent is None:
                break
            
            # Look for location patterns in text
            text = parent.get_text(separator=' ', strip=True)
            
            # Common German cities
            cities = [
                'Berlin', 'München', 'Hamburg', 'Frankfurt', 'Köln',
                'Düsseldorf', 'Stuttgart', 'Dresden', 'Leipzig', 'Hannover',
                'Nürnberg', 'Mannheim', 'Walldorf', 'Magdeburg', 'Görlitz',
                'Halle', 'Remote', 'Deutschlandweit',
            ]
            
            for city in cities:
                if city in text:
                    return city
            
            parent = parent.parent
        
        return "Germany"




