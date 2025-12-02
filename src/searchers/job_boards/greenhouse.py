"""Greenhouse job board parser."""

import re
from bs4 import BeautifulSoup

from src.searchers.job_boards.base import BaseJobBoardParser


class GreenhouseParser(BaseJobBoardParser):
    """Parser for Greenhouse job board."""

    platform_name = "greenhouse"

    def parse(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Parse jobs from Greenhouse HTML."""
        jobs = []
        
        # Try new job-boards.greenhouse.io format first (tables with rows)
        jobs = self._parse_new_format(soup, base_url)
        if jobs:
            return jobs
        
        # Fallback to legacy boards.greenhouse.io format
        return self._parse_legacy_format(soup, base_url)
    
    def _parse_new_format(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Parse new job-boards.greenhouse.io format.
        
        Structure: table rows with links containing title and location spans.
        """
        jobs = []
        seen_urls = set()
        current_department = None
        
        # Find department sections and job tables
        for section in soup.select('section, [class*="section"], div > div'):
            # Check for department heading
            heading = section.select_one('h2, h3, [class*="department"]')
            if heading:
                current_department = heading.get_text(strip=True)
            
            # Find job links in tables or lists
            for link in section.select('a[href*="/jobs/"]'):
                href = link.get('href', '')
                if not href or '/jobs/' not in href:
                    continue
                
                job_url = self._build_full_url(href, base_url)
                
                # Skip duplicates
                if job_url in seen_urls:
                    continue
                seen_urls.add(job_url)
                
                # Get all text children
                children = link.find_all(recursive=False)
                
                if len(children) >= 2:
                    # New format: first child is title, second is location
                    title = self._clean_title(children[0].get_text(strip=True))
                    location = children[1].get_text(strip=True)
                elif len(children) == 1:
                    # Single child - try to extract title and location
                    full_text = link.get_text(strip=True)
                    title, location = self._split_title_location(full_text)
                else:
                    # No children - use link text directly
                    full_text = link.get_text(strip=True)
                    title, location = self._split_title_location(full_text)
                
                if title:
                    jobs.append({
                        "title": title,
                        "location": location or "Unknown",
                        "url": job_url,
                        "department": current_department,
                    })
        
        return jobs
    
    def _parse_legacy_format(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Parse legacy boards.greenhouse.io format."""
        jobs = []
        
        # Greenhouse typically uses .opening or .job-post classes
        for opening in soup.select('.opening, .job-post, [data-mapped="true"]'):
            title_elem = opening.select_one('a, .opening-title, .job-title')
            location_elem = opening.select_one('.location, .job-location')
            
            if not title_elem:
                continue
            
            title = self._clean_title(title_elem.get_text(strip=True))
            href = title_elem.get('href', '')
            job_url = self._build_full_url(href, base_url)
            
            location = location_elem.get_text(strip=True) if location_elem else "Unknown"
            
            if title:
                jobs.append({
                    "title": title,
                    "location": location,
                    "url": job_url,
                    "department": None,
                })
        
        return jobs
    
    def _clean_title(self, title: str) -> str:
        """Remove 'New' badge and other markers from title."""
        # Remove "New" badge (with various formats)
        title = re.sub(r'\s*New\s*$', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\s*\[New\]\s*', ' ', title, flags=re.IGNORECASE)
        return title.strip()
    
    def _split_title_location(self, text: str) -> tuple[str, str]:
        """Try to split combined title+location text.
        
        Returns (title, location) tuple.
        """
        # Common patterns: "Job TitleNew York, NY" or "Job Title - Location"
        # Try to find location pattern (City, State/Country)
        match = re.search(r'(.+?)\s*[-–—]\s*([A-Z][^,]+,\s*[^,]+)$', text)
        if match:
            return self._clean_title(match.group(1)), match.group(2).strip()
        
        # Try to find location at end with comma pattern
        match = re.search(r'(.+?)\s+([A-Z][a-z]+(?:,\s*[A-Z][a-z]+)+(?:,\s*[A-Z][a-z\s]+)?)$', text)
        if match:
            return self._clean_title(match.group(1)), match.group(2).strip()
        
        return self._clean_title(text), ""

