"""Join.com job board parser."""

import json
import logging
import re
from bs4 import BeautifulSoup

from src.searchers.job_boards.base import BaseJobBoardParser

logger = logging.getLogger(__name__)


class JoinParser(BaseJobBoardParser):
    """Parser for Join.com job widget.
    
    Join.com is a popular German job platform that provides
    embeddable job widgets for company career pages.
    
    The widget can be:
    1. Embedded via JavaScript (loads data dynamically)
    2. Rendered as static HTML with job cards
    3. Linked to join.com/companies/... pages
    
    URL patterns:
    - join.com/companies/company-name
    - join.com/companies/company-name/jobs
    - Embedded widget with class "join-jobs-widget"
    
    HTML structure:
    - Widget container: .join-jobs-widget, [data-join], #join-widget
    - Job cards inside widget
    - Links to join.com job detail pages
    """

    platform_name = "join"

    def parse(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Parse jobs from Join.com HTML or widget."""
        jobs = []
        
        # Strategy 1: Parse Join.com company page
        if 'join.com' in base_url:
            jobs = self._parse_join_page(soup, base_url)
            if jobs:
                return jobs
        
        # Strategy 2: Parse embedded widget
        jobs = self._parse_embedded_widget(soup, base_url)
        if jobs:
            return jobs
        
        # Strategy 3: Find all join.com job links
        jobs = self._parse_join_links(soup, base_url)
        
        return jobs
    
    def _parse_join_page(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Parse jobs from join.com company page."""
        jobs = []
        seen_urls = set()
        
        # Join.com uses job cards with links
        # Typical structure: job card -> link to /jobs/job-slug
        job_cards = soup.select(
            '[class*="job-card"], [class*="JobCard"], '
            '[class*="position-card"], [class*="vacancy"], '
            'article[class*="job"], li[class*="job"]'
        )
        
        for card in job_cards:
            link = card.find('a', href=True)
            if not link:
                continue
            
            href = link.get('href', '')
            if '/jobs/' not in href and '/job/' not in href:
                continue
            
            job_url = self._build_full_url(href, base_url)
            if job_url in seen_urls:
                continue
            seen_urls.add(job_url)
            
            # Get title
            title_elem = card.select_one(
                'h2, h3, h4, [class*="title"], [class*="Title"]'
            )
            title = title_elem.get_text(strip=True) if title_elem else link.get_text(strip=True)
            
            # Get location
            location_elem = card.select_one(
                '[class*="location"], [class*="Location"], '
                '[class*="city"], [class*="City"]'
            )
            location = location_elem.get_text(strip=True) if location_elem else "Unknown"
            
            # Get employment type
            type_elem = card.select_one(
                '[class*="type"], [class*="Type"], '
                '[class*="employment"], [class*="Employment"]'
            )
            
            if title:
                jobs.append({
                    "title": self._clean_title(title),
                    "location": location,
                    "url": job_url,
                    "department": None,
                })
        
        # If no cards found, try simpler link extraction
        if not jobs:
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                if '/jobs/' not in href:
                    continue
                if self._is_navigation_link(href):
                    continue
                
                job_url = self._build_full_url(href, base_url)
                if job_url in seen_urls:
                    continue
                seen_urls.add(job_url)
                
                title = link.get_text(strip=True)
                if title and len(title) > 3:
                    jobs.append({
                        "title": self._clean_title(title),
                        "location": "Unknown",
                        "url": job_url,
                        "department": None,
                    })
        
        return jobs
    
    def _parse_embedded_widget(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Parse jobs from embedded Join.com widget."""
        jobs = []
        seen_urls = set()
        
        # Find widget container
        widget_selectors = [
            '.join-jobs-widget',
            '[class*="join-widget"]',
            '[data-join]',
            '#join-widget',
            '[id*="join-jobs"]',
            'iframe[src*="join.com"]',
        ]
        
        widget = None
        for selector in widget_selectors:
            widget = soup.select_one(selector)
            if widget:
                break
        
        if not widget:
            return jobs
        
        # If it's an iframe, we can't parse content (need to fetch iframe src)
        if widget.name == 'iframe':
            src = widget.get('src', '')
            if src:
                logger.debug(f"Join.com widget is an iframe: {src}")
            return jobs
        
        # Parse job links within widget
        for link in widget.find_all('a', href=True):
            href = link.get('href', '')
            if 'join.com' not in href and '/jobs/' not in href:
                continue
            
            job_url = self._build_full_url(href, base_url)
            if job_url in seen_urls:
                continue
            seen_urls.add(job_url)
            
            # Get job data from link and surrounding elements
            title = link.get_text(strip=True)
            location = "Unknown"
            
            # Look for location in parent
            parent = link.find_parent(['div', 'li', 'article'])
            if parent:
                loc_elem = parent.select_one('[class*="location"], [class*="city"]')
                if loc_elem and loc_elem != link:
                    location = loc_elem.get_text(strip=True)
            
            if title and len(title) > 3:
                jobs.append({
                    "title": self._clean_title(title),
                    "location": location,
                    "url": job_url,
                    "department": None,
                })
        
        return jobs
    
    def _parse_join_links(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Find all join.com job links on the page."""
        jobs = []
        seen_urls = set()
        
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            
            # Must be a join.com job link
            if 'join.com' not in href:
                continue
            if '/jobs/' not in href and '/job/' not in href:
                continue
            if self._is_navigation_link(href):
                continue
            
            job_url = href if href.startswith('http') else f"https://join.com{href}"
            
            if job_url in seen_urls:
                continue
            seen_urls.add(job_url)
            
            title = link.get_text(strip=True)
            location = "Unknown"
            
            # Try to get location from parent
            parent = link.find_parent(['div', 'li', 'tr', 'article'])
            if parent:
                loc_elem = parent.select_one('[class*="location"], [class*="ort"]')
                if loc_elem and loc_elem != link:
                    location = loc_elem.get_text(strip=True)
            
            if title and len(title) > 3:
                jobs.append({
                    "title": self._clean_title(title),
                    "location": location,
                    "url": job_url,
                    "department": None,
                })
        
        return jobs
    
    def _is_navigation_link(self, href: str) -> bool:
        """Check if href is a navigation link."""
        skip_patterns = [
            r'\?page=',
            r'\?filter',
            r'/search',
            r'/companies$',
            r'/login',
            r'/register',
            r'/pricing',
            r'/about',
        ]
        return any(re.search(p, href, re.IGNORECASE) for p in skip_patterns)
    
    def _clean_title(self, title: str) -> str:
        """Clean job title."""
        if not title:
            return ""
        
        # Remove badges
        title = re.sub(r'\s*\[?(New|Neu)\]?\s*$', '', title, flags=re.IGNORECASE)
        title = re.sub(r'^\[?(New|Neu)\]?\s*', '', title, flags=re.IGNORECASE)
        
        # Normalize whitespace
        title = re.sub(r'\s+', ' ', title)
        
        return title.strip()
