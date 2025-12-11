"""HRworks job board parser."""

import logging

from bs4 import BeautifulSoup

from src.searchers.job_boards.base import BaseJobBoardParser

logger = logging.getLogger(__name__)


class HRworksParser(BaseJobBoardParser):
    """Parser for HRworks job board (hrworks.de).
    
    HRworks is a German HR/Payroll platform with a recruitment module.
    Career pages are typically hosted on jobs.companyname.de subdomains.
    
    Structure:
    - Jobs are in .portlet.light.bordered containers
    - Title: a.job-offer-content with h2 inside
    - URL: href attribute of a.job-offer-content (format: /de?id=XXXXX)
    - Metadata: div.margin-top-10 contains "Department - Level - Contract - WorkTime"
    - Location: span after i.icomoon-location or link to Google Maps
    """

    platform_name = "hrworks"

    def parse(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Parse jobs from HRworks HTML."""
        jobs = []
        seen_urls = set()
        
        # Find all job offer links
        for link in soup.find_all('a', class_='job-offer-content'):
            href = link.get('href', '')
            if not href or '?id=' not in href:
                continue
            
            job_url = self._build_full_url(href, base_url)
            
            # Skip duplicates (each job has 2 links - title and description)
            if job_url in seen_urls:
                continue
            seen_urls.add(job_url)
            
            # Get title from h2 or title attribute
            title = None
            h2 = link.find('h2')
            if h2:
                title = h2.get_text(strip=True)
            if not title:
                title = link.get('title', '').strip()
            if not title:
                title = link.get_text(strip=True)
            
            if not title:
                continue
            
            # Find parent portlet container for metadata
            portlet = link.find_parent('div', class_='portlet')
            
            location = "Unknown"
            department = None
            
            if portlet:
                # Extract metadata from colored div (department - level - contract - time)
                meta_div = portlet.find('div', class_='margin-top-10')
                if meta_div:
                    meta_text = meta_div.get_text(strip=True)
                    # Format: "IT und Software-Entwicklung - Studium/Praktikum - Praktikum - Vollzeit"
                    parts = [p.strip() for p in meta_text.split(' - ') if p.strip()]
                    if parts:
                        department = parts[0]  # First part is usually department
                
                # Extract location from icomoon-location icon's sibling span
                loc_icon = portlet.find('i', class_='icomoon-location')
                if loc_icon:
                    parent_a = loc_icon.find_parent('a')
                    if parent_a:
                        loc_span = parent_a.find('span')
                        if loc_span:
                            location = loc_span.get_text(strip=True)
                
                # Alternative: look for icomoon-home (remote/hybrid work)
                if location == "Unknown":
                    home_icon = portlet.find('i', class_='icomoon-home')
                    if home_icon:
                        parent_a = home_icon.find_parent('a')
                        if parent_a:
                            loc_span = parent_a.find('span')
                            if loc_span:
                                location = loc_span.get_text(strip=True)
            
            jobs.append({
                "title": title,
                "location": location,
                "url": job_url,
                "department": department,
            })
        
        if jobs:
            logger.debug(f"HRworks parser found {len(jobs)} jobs")
        
        return jobs

