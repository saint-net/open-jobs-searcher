"""Greenhouse job board parser."""

from bs4 import BeautifulSoup

from src.searchers.job_boards.base import BaseJobBoardParser


class GreenhouseParser(BaseJobBoardParser):
    """Parser for Greenhouse job board."""

    platform_name = "greenhouse"

    def parse(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Parse jobs from Greenhouse HTML."""
        jobs = []
        
        # Greenhouse typically uses .opening or .job-post classes
        for opening in soup.select('.opening, .job-post, [data-mapped="true"]'):
            title_elem = opening.select_one('a, .opening-title, .job-title')
            location_elem = opening.select_one('.location, .job-location')
            
            if not title_elem:
                continue
            
            title = title_elem.get_text(strip=True)
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

