"""Personio job board parser."""

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from src.searchers.job_boards.base import BaseJobBoardParser


class PersonioParser(BaseJobBoardParser):
    """Parser for Personio job board."""

    platform_name = "personio"

    def parse(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Parse jobs from Personio HTML."""
        jobs = []
        seen_urls = set()  # For deduplication
        
        # Personio uses /job/ID links
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            if '/job/' not in href:
                continue
            
            # Build full URL
            job_url = self._build_full_url(href, base_url)
            
            # Skip duplicates
            if job_url in seen_urls:
                continue
            seen_urls.add(job_url)
            
            # Extract link text
            text = link.get_text(separator=' ', strip=True)
            if not text:
                continue
            
            # Parse structure: "Title (all)Employment Type, Full-time·Location·Location"
            title = text
            location = "Unknown"
            
            # Look for employment type patterns
            type_patterns = [
                r'(Permanent employee|Intern / Student|Working student|Freelancer)',
                r'(Full-time|Part-time|Teilzeit|Vollzeit)',
            ]
            
            for pattern in type_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    # Separate title from employment type
                    idx = text.find(match.group(1))
                    if idx > 0:
                        title = text[:idx].strip()
                        remainder = text[idx:].strip()
                        
                        # Extract location (after ·)
                        loc_match = re.search(r'·\s*([^·]+)', remainder)
                        if loc_match:
                            location = loc_match.group(1).strip()
                        break
            
            # Clean up title - remove (all), (m/w/d) suffixes
            title = re.sub(r'\s*\(all\)\s*$', '', title, flags=re.IGNORECASE)
            title = title.strip()
            
            if title:
                jobs.append({
                    "title": title,
                    "location": location,
                    "url": job_url,
                    "department": None,
                })
        
        return jobs

