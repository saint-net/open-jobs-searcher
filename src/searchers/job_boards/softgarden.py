"""Softgarden job board parser."""

import re
from bs4 import BeautifulSoup

from src.searchers.job_boards.base import BaseJobBoardParser


class SoftgardenParser(BaseJobBoardParser):
    """Parser for Softgarden job board (*.softgarden.io).
    
    Softgarden is a popular German ATS platform used by many
    Mittelstand and enterprise companies.
    
    URL patterns:
    - company.softgarden.io
    - jobdb.softgarden.de/...
    
    HTML structure typically includes:
    - Job cards/rows with links to /job/ID or /vacancies/ID
    - Title in link text or h2/h3 elements
    - Location often in separate span/div
    """

    platform_name = "softgarden"

    def parse(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Parse jobs from Softgarden HTML."""
        jobs = []
        seen_urls = set()
        
        # Strategy 1: Find job links with /job/ or /vacancies/ in href
        job_patterns = ['/job/', '/vacancies/', '/vacancy/', '/stelle/']
        
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            
            # Check if this is a job link
            if not any(pattern in href.lower() for pattern in job_patterns):
                continue
            
            # Skip navigation/filter links
            if self._is_navigation_link(href):
                continue
            
            job_url = self._build_full_url(href, base_url)
            
            # Skip duplicates
            if job_url in seen_urls:
                continue
            seen_urls.add(job_url)
            
            # Extract job info from link and surrounding context
            job_data = self._extract_job_from_link(link, job_url)
            if job_data:
                jobs.append(job_data)
        
        # Strategy 2: If no jobs found, try job-card/job-listing classes
        if not jobs:
            jobs = self._parse_job_cards(soup, base_url)
        
        return jobs
    
    def _is_navigation_link(self, href: str) -> bool:
        """Check if href is a navigation/filter link, not a job."""
        skip_patterns = [
            r'\?page=',
            r'\?filter',
            r'\?sort',
            r'#',
            r'/search',
            r'/login',
            r'/register',
        ]
        return any(re.search(p, href, re.IGNORECASE) for p in skip_patterns)
    
    def _extract_job_from_link(self, link, job_url: str) -> dict | None:
        """Extract job data from a link element and its context."""
        # Get text from link
        title = link.get_text(separator=' ', strip=True)
        
        if not title or len(title) < 3:
            return None
        
        location = "Unknown"
        department = None
        
        # Try to find location in sibling/parent elements
        parent = link.find_parent(['div', 'li', 'article', 'tr'])
        if parent:
            # Look for location in common patterns
            location_elem = parent.select_one(
                '[class*="location"], [class*="ort"], [class*="city"], '
                '[class*="standort"], .job-location, .location'
            )
            if location_elem and location_elem != link:
                location = location_elem.get_text(strip=True)
            
            # Look for department
            dept_elem = parent.select_one(
                '[class*="department"], [class*="abteilung"], [class*="bereich"], '
                '[class*="category"], .department'
            )
            if dept_elem and dept_elem != link:
                department = dept_elem.get_text(strip=True)
            
            # If title contains location pattern, split it
            if location == "Unknown":
                title, location = self._split_title_location(title)
        
        # Clean title
        title = self._clean_title(title)
        
        if not title:
            return None
        
        return {
            "title": title,
            "location": location,
            "url": job_url,
            "department": department,
        }
    
    def _parse_job_cards(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Parse jobs from card/listing elements."""
        jobs = []
        seen_urls = set()
        
        # Try common card selectors
        card_selectors = [
            '[class*="job-card"]',
            '[class*="job-listing"]',
            '[class*="job-item"]',
            '[class*="vacancy-card"]',
            '[class*="position-card"]',
            'article[class*="job"]',
            '.job-row',
            'li[class*="job"]',
        ]
        
        for selector in card_selectors:
            cards = soup.select(selector)
            for card in cards:
                link = card.find('a', href=True)
                if not link:
                    continue
                
                href = link.get('href', '')
                job_url = self._build_full_url(href, base_url)
                
                if job_url in seen_urls:
                    continue
                seen_urls.add(job_url)
                
                # Get title from heading or link
                title_elem = card.select_one('h2, h3, h4, [class*="title"]')
                title = title_elem.get_text(strip=True) if title_elem else link.get_text(strip=True)
                
                # Get location
                location_elem = card.select_one('[class*="location"], [class*="ort"]')
                location = location_elem.get_text(strip=True) if location_elem else "Unknown"
                
                # Get department
                dept_elem = card.select_one('[class*="department"], [class*="category"]')
                department = dept_elem.get_text(strip=True) if dept_elem else None
                
                if title:
                    jobs.append({
                        "title": self._clean_title(title),
                        "location": location,
                        "url": job_url,
                        "department": department,
                    })
            
            if jobs:
                break  # Found jobs with this selector
        
        return jobs
    
    def _clean_title(self, title: str) -> str:
        """Clean job title."""
        if not title:
            return ""
        
        # Remove common suffixes/prefixes
        title = re.sub(r'\s*\(all genders?\)\s*', ' ', title, flags=re.IGNORECASE)
        title = re.sub(r'\s*–\s*Jetzt bewerben!?\s*$', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\s*-\s*Apply now!?\s*$', '', title, flags=re.IGNORECASE)
        
        # Normalize whitespace
        title = re.sub(r'\s+', ' ', title)
        
        return title.strip()
    
    def _split_title_location(self, text: str) -> tuple[str, str]:
        """Try to split title and location from combined text."""
        # Pattern: "Job Title | Location" or "Job Title - Location"
        match = re.search(r'(.+?)\s*[|–—-]\s*([A-Z][^|–—-]+)$', text)
        if match:
            return match.group(1).strip(), match.group(2).strip()
        
        # Pattern: "Job Title, City" at end
        match = re.search(r'(.+?),\s+([A-Z][a-zäöüß]+(?:\s*,\s*[A-Za-zäöüß]+)?)$', text)
        if match:
            return match.group(1).strip(), match.group(2).strip()
        
        return text, "Unknown"
