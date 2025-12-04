"""Lever job board parser."""

from bs4 import BeautifulSoup

from src.searchers.job_boards.base import BaseJobBoardParser


class LeverParser(BaseJobBoardParser):
    """Parser for Lever job board."""

    platform_name = "lever"

    def parse(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Parse jobs from Lever HTML."""
        jobs = []
        
        # Lever uses .posting class
        for posting in soup.select('.posting, .posting-card'):
            title_elem = posting.select_one('.posting-title, h5')
            location_elem = posting.select_one('.location, .posting-categories')
            link_elem = posting.select_one('a.posting-title, a')
            
            if not title_elem:
                continue
            
            title = title_elem.get_text(strip=True)
            href = link_elem.get('href', '') if link_elem else ''
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



