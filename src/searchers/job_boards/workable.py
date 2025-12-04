"""Workable job board parser."""

import json
import re
from bs4 import BeautifulSoup

from src.searchers.job_boards.base import BaseJobBoardParser


class WorkableParser(BaseJobBoardParser):
    """Parser for Workable job board (apply.workable.com)."""

    platform_name = "workable"

    def parse(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Parse jobs from Workable HTML.
        
        Workable uses React-based SPA with job listings in:
        1. JSON-LD structured data
        2. <ul> lists with job cards
        3. Data attributes with job info
        """
        jobs = []
        
        # Try JSON-LD structured data first
        jobs = self._parse_json_ld(soup, base_url)
        if jobs:
            return jobs
        
        # Try to find job listings in the page structure
        jobs = self._parse_job_cards(soup, base_url)
        if jobs:
            return jobs
        
        # Fallback: parse any links to job postings
        return self._parse_job_links(soup, base_url)
    
    def _parse_json_ld(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Parse jobs from JSON-LD structured data."""
        jobs = []
        
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                
                # Handle single job posting
                if isinstance(data, dict):
                    if data.get('@type') == 'JobPosting':
                        job = self._extract_job_from_jsonld(data, base_url)
                        if job:
                            jobs.append(job)
                    # Handle array of job postings
                    elif '@graph' in data:
                        for item in data['@graph']:
                            if item.get('@type') == 'JobPosting':
                                job = self._extract_job_from_jsonld(item, base_url)
                                if job:
                                    jobs.append(job)
                
                # Handle array at root level
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'JobPosting':
                            job = self._extract_job_from_jsonld(item, base_url)
                            if job:
                                jobs.append(job)
            except (json.JSONDecodeError, TypeError):
                continue
        
        return jobs
    
    def _extract_job_from_jsonld(self, data: dict, base_url: str) -> dict | None:
        """Extract job info from JSON-LD job posting."""
        title = data.get('title') or data.get('name')
        if not title:
            return None
        
        # Get location
        location = "Unknown"
        job_location = data.get('jobLocation')
        if job_location:
            if isinstance(job_location, dict):
                address = job_location.get('address', {})
                if isinstance(address, dict):
                    parts = []
                    if address.get('addressLocality'):
                        parts.append(address['addressLocality'])
                    if address.get('addressRegion'):
                        parts.append(address['addressRegion'])
                    if address.get('addressCountry'):
                        country = address['addressCountry']
                        if isinstance(country, dict):
                            country = country.get('name', '')
                        parts.append(country)
                    location = ', '.join(filter(None, parts)) or "Unknown"
                elif isinstance(address, str):
                    location = address
            elif isinstance(job_location, list) and job_location:
                # Multiple locations - take first
                first_loc = job_location[0]
                if isinstance(first_loc, dict):
                    address = first_loc.get('address', {})
                    if isinstance(address, dict):
                        parts = []
                        if address.get('addressLocality'):
                            parts.append(address['addressLocality'])
                        if address.get('addressCountry'):
                            parts.append(address['addressCountry'])
                        location = ', '.join(filter(None, parts)) or "Unknown"
        
        # Get URL
        url = data.get('url') or base_url
        
        return {
            "title": title,
            "location": location,
            "url": url,
            "department": data.get('occupationalCategory'),
        }
    
    def _parse_job_cards(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Parse job cards from page HTML."""
        jobs = []
        seen_urls = set()
        
        # Workable uses lists with job items
        # Look for lists containing job links
        for item in soup.select('li[class*="job"], li a[href*="/j/"]'):
            # Find the link element
            link = item if item.name == 'a' else item.select_one('a[href*="/j/"]')
            if not link:
                continue
            
            href = link.get('href', '')
            if not href or '/j/' not in href:
                continue
            
            job_url = self._build_full_url(href, base_url)
            
            if job_url in seen_urls:
                continue
            seen_urls.add(job_url)
            
            # Get text from the list item or link
            parent = link.find_parent('li') or link
            full_text = parent.get_text(separator=' ', strip=True)
            
            # Try to extract title and location from text
            title, location, department = self._parse_job_text(full_text)
            
            if title:
                jobs.append({
                    "title": title,
                    "location": location or "Unknown",
                    "url": job_url,
                    "department": department,
                })
        
        return jobs
    
    def _parse_job_links(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Fallback: parse any job links."""
        jobs = []
        seen_urls = set()
        
        # Find all links to job postings (/j/SHORTCODE pattern)
        for link in soup.select('a[href*="/j/"]'):
            href = link.get('href', '')
            if not href or '/j/' not in href:
                continue
            
            # Skip non-job links
            if any(skip in href for skip in ['/gdpr', '/privacy', '/cookie']):
                continue
            
            job_url = self._build_full_url(href, base_url)
            
            if job_url in seen_urls:
                continue
            seen_urls.add(job_url)
            
            # Get text from link or parent
            text = link.get_text(strip=True)
            if not text or len(text) < 3:
                parent = link.find_parent(['li', 'div', 'tr'])
                if parent:
                    text = parent.get_text(separator=' ', strip=True)
            
            title, location, department = self._parse_job_text(text)
            
            if title:
                jobs.append({
                    "title": title,
                    "location": location or "Unknown",
                    "url": job_url,
                    "department": department,
                })
        
        return jobs
    
    def _parse_job_text(self, text: str) -> tuple[str, str, str]:
        """Parse job text to extract title, location, and department.
        
        Workable job cards typically show:
        "Title Type Location Department WorkType"
        e.g., "QA Engineer Hybrid Cluj-Napoca, Romania All, Definition & QA Full time"
        
        Returns (title, location, department) tuple.
        """
        if not text:
            return "", "", ""
        
        # Common work type indicators to remove
        work_types = ['Full time', 'Part time', 'Contract', 'Internship', 
                      'Hybrid', 'Remote', 'On-site', 'On site', 'Onsite']
        
        # Split by work type markers to get components
        parts = text.split()
        
        # Find title (usually first few words until a work type or location)
        title_parts = []
        location = ""
        department = ""
        work_type_found = False
        
        i = 0
        while i < len(parts):
            word = parts[i]
            
            # Check if this is a work type marker
            if word in ['Hybrid', 'Remote', 'On-site', 'Onsite']:
                work_type_found = True
                i += 1
                # Next parts are likely location
                location_parts = []
                while i < len(parts):
                    part = parts[i]
                    # Stop at department or work type
                    if part in ['Full', 'Part'] or part.startswith('All,'):
                        break
                    location_parts.append(part)
                    i += 1
                location = ' '.join(location_parts).strip(' ,')
                
                # Get department
                if i < len(parts) and parts[i].startswith('All,'):
                    dept_parts = []
                    while i < len(parts):
                        part = parts[i]
                        if part in ['Full', 'Part']:
                            break
                        dept_parts.append(part)
                        i += 1
                    department = ' '.join(dept_parts).replace('All, ', '').strip()
                break
            else:
                title_parts.append(word)
            i += 1
        
        title = ' '.join(title_parts).strip()
        
        # If we didn't find structure, return the original text as title
        if not title and text:
            # Try to extract just the main title (usually before first comma or dash)
            match = re.match(r'^([^,\-–—]+)', text)
            if match:
                title = match.group(1).strip()
                # Remove work types from title
                for wt in work_types:
                    title = title.replace(wt, '').strip()
        
        return title, location, department




