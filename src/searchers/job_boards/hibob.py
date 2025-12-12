"""HiBob job board parser."""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.searchers.job_boards.base import BaseJobBoardParser


class HiBobParser(BaseJobBoardParser):
    """Parser for HiBob careers pages (careers.hibob.com)."""

    platform_name = "hibob"

    def parse(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Parse jobs from HiBob HTML.
        
        HiBob uses Angular with custom components:
        - <b-virtual-scroll-list-item> for each job card
        - Job title in <b-heading> or <b-truncate-tooltip>
        - Metadata in sibling divs (department, location, etc.)
        """
        jobs = []
        seen_titles = set()
        
        # Find all job list items
        job_items = soup.find_all('b-virtual-scroll-list-item')
        
        for item in job_items:
            # Extract title from b-heading or first div with job pattern
            title = None
            
            # Try b-heading first
            heading = item.find('b-heading')
            if heading:
                title = heading.get_text(strip=True)
            
            # Fallback: find div with (f/m or (m/w pattern
            if not title:
                for div in item.find_all('div'):
                    text = div.get_text(strip=True)
                    if re.search(r'\([fmwdx]/[fmwdx]', text, re.IGNORECASE):
                        title = text
                        break
            
            if not title:
                continue
            
            # Skip duplicates
            title_normalized = title.lower().strip()
            if title_normalized in seen_titles:
                continue
            seen_titles.add(title_normalized)
            
            # Extract metadata from the div that contains department/location (has · separator)
            metadata_text = ""
            for div in item.find_all('div'):
                div_text = div.get_text(strip=True)
                if '·' in div_text:  # Metadata div format: "Dept · Location · Type · Remote"
                    metadata_text = div_text
                    break
            
            location = self._extract_location(metadata_text)
            department = self._extract_department(metadata_text)
            
            # Build job URL (HiBob uses SPA, so URL is base + slug)
            job_slug = self._title_to_slug(title)
            job_url = urljoin(base_url.rstrip('/') + '/', job_slug)
            
            jobs.append({
                "title": title,
                "location": location,
                "url": job_url,
                "department": department,
            })
        
        return jobs
    
    def _extract_location(self, text: str) -> str:
        """Extract location from job item text."""
        # HiBob format: "Title | Dept · Location · Type · Remote/Hybrid"
        # Look for location after department marker (·)
        parts = text.split('·')
        
        for part in parts:
            part = part.strip()
            # Skip common non-location parts
            if any(skip in part.lower() for skip in ['permanent', 'full-time', 'part-time', 'posted', 'dev', 'infrastructure', 'marketing', 'operations']):
                continue
            # Check for location keywords
            if any(loc in part.lower() for loc in ['remote', 'hybrid', 'munich', 'berlin', 'germany', 'london', 'amsterdam', 'europe']):
                # Clean up "Remote Germany" -> "Germany" or keep "Remote"
                if 'remote' in part.lower() and len(part.split()) > 1:
                    # "Remote Germany" -> "Germany, Remote"
                    words = part.split()
                    non_remote = [w for w in words if w.lower() != 'remote']
                    if non_remote:
                        return ', '.join(non_remote) + ', Remote'
                return part
        
        return "Remote"  # Default for HiBob (most are remote)
    
    def _extract_department(self, text: str) -> str | None:
        """Extract department from job item text."""
        # HiBob shows department before location: "Dev · Remote"
        parts = text.split('·')
        if len(parts) >= 2:
            dept = parts[0].strip()
            # Filter out job titles
            if not re.search(r'\([fmwdx]/[fmwdx]', dept, re.IGNORECASE):
                return dept if len(dept) < 50 else None
        return None
    
    def _title_to_slug(self, title: str) -> str:
        """Convert job title to URL slug."""
        # Remove gender notation
        slug = re.sub(r'\s*\([fmwdx]/[fmwdx](/[fmwdx])?\)\s*', ' ', title, flags=re.IGNORECASE)
        # Convert to lowercase, replace spaces with hyphens
        slug = slug.lower().strip()
        slug = re.sub(r'[^a-z0-9]+', '-', slug)
        slug = slug.strip('-')
        return slug
