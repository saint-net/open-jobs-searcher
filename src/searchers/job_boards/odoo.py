"""Odoo HR Recruitment module parser.

Odoo is a popular CMS/ERP that includes an HR Recruitment module.
Sites running Odoo can be identified by:
- <meta name="generator" content="Odoo">
- CSS classes like o_website_hr_recruitment_*, oe_website_jobs
- Scripts from /web/assets/
"""

import logging
from bs4 import BeautifulSoup

from src.searchers.job_boards.base import BaseJobBoardParser
from src.constants import MIN_VALID_HTML_SIZE, MAX_JOB_SECTION_SIZE


logger = logging.getLogger(__name__)


class OdooParser(BaseJobBoardParser):
    """Parser for Odoo HR Recruitment job listings."""

    platform_name = "odoo"
    
    # Odoo-specific CSS selectors for job containers
    JOB_CONTAINER_SELECTORS = [
        '.o_website_hr_recruitment_jobs_list',
        '.oe_website_jobs',
        '[class*="o_website_hr"]',
        '[class*="oe_website_jobs"]',
    ]
    
    # Selectors for individual job cards
    JOB_CARD_SELECTORS = [
        '.card.card-default',
        '[class*="o_job"]',
        'a[href*="/jobs/detail/"]',
    ]

    @staticmethod
    def is_odoo_site(soup: BeautifulSoup) -> bool:
        """Check if site is running Odoo CMS.
        
        Odoo adds a meta generator tag to all pages.
        This is the most reliable way to detect Odoo sites.
        
        Args:
            soup: BeautifulSoup object of the page
            
        Returns:
            True if Odoo detected
        """
        generator = soup.find('meta', attrs={'name': 'generator'})
        if generator:
            content = generator.get('content', '') or ''
            return 'odoo' in content.lower()
        return False
    
    @staticmethod
    def find_job_section(soup: BeautifulSoup) -> str | None:
        """Find the Odoo job listing section HTML.
        
        Args:
            soup: BeautifulSoup object of the page
            
        Returns:
            HTML string of job section, or None if not found
        """
        for selector in OdooParser.JOB_CONTAINER_SELECTORS:
            try:
                elements = soup.select(selector)
                for el in elements:
                    html = str(el)
                    # Size check: must be substantial but not too large
                    if MIN_VALID_HTML_SIZE < len(html) < MAX_JOB_SECTION_SIZE:
                        return html
            except Exception:
                continue
        return None

    def parse(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Parse jobs from Odoo HR Recruitment HTML.
        
        Args:
            soup: BeautifulSoup object (ideally just the job section)
            base_url: Base URL for building absolute links
            
        Returns:
            List of job dictionaries
        """
        jobs = []
        seen_urls = set()
        
        # Find all job cards
        for selector in self.JOB_CARD_SELECTORS:
            for card in soup.select(selector):
                job = self._parse_job_card(card, base_url)
                if job and job.get('url') not in seen_urls:
                    seen_urls.add(job.get('url'))
                    jobs.append(job)
        
        # Fallback: find all links to /jobs/detail/
        if not jobs:
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                if '/jobs/detail/' in href:
                    job_url = self._build_full_url(href, base_url)
                    if job_url in seen_urls:
                        continue
                    seen_urls.add(job_url)
                    
                    # Try to find title in card structure
                    card = link.find_parent('div', class_='card') or link
                    title_el = card.find(['h3', 'h4', 'h5', '.card-title'])
                    title = title_el.get_text(strip=True) if title_el else link.get_text(strip=True)
                    
                    # Find location
                    location = "Unknown"
                    loc_el = card.find(string=lambda t: t and any(m in t for m in ['Köln', 'Berlin', 'München', 'Hamburg', 'Remote']))
                    if loc_el:
                        location = loc_el.strip()
                    
                    if title:
                        jobs.append({
                            "title": title,
                            "location": location,
                            "url": job_url,
                            "department": None,
                        })
        
        logger.debug(f"Odoo parser found {len(jobs)} jobs")
        return jobs
    
    def _parse_job_card(self, card, base_url: str) -> dict | None:
        """Parse a single Odoo job card element."""
        # Find link
        link = card.find('a', href=True) if card.name != 'a' else card
        if not link:
            return None
        
        href = link.get('href', '')
        if '/jobs/detail/' not in href and '/jobs/' not in href:
            return None
        
        job_url = self._build_full_url(href, base_url)
        
        # Find title (usually in h3 or h4)
        title_el = card.find(['h3', 'h4', 'h5'])
        if not title_el:
            title_el = card.find(class_=lambda c: c and 'title' in c.lower())
        
        title = title_el.get_text(strip=True) if title_el else link.get_text(strip=True)
        if not title:
            return None
        
        # Find location
        location = "Unknown"
        for el in card.find_all(['span', 'p', 'div']):
            text = el.get_text(strip=True)
            # Location often contains city or "Remote"
            if any(marker in text for marker in ['Köln', 'Berlin', 'München', 'Hamburg', 'Frankfurt', 'Remote', 'Deutschland']):
                location = text[:100]  # Limit length
                break
        
        return {
            "title": title,
            "location": location,
            "url": job_url,
            "department": None,
        }
