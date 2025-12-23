"""Job extraction strategies."""

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .candidate import JobCandidate, ExtractionSource

logger = logging.getLogger(__name__)


class BaseExtractionStrategy(ABC):
    """Base class for extraction strategies."""
    
    name: str = "base"
    source: ExtractionSource = ExtractionSource.LLM
    
    @abstractmethod
    def extract(self, html: str, url: str) -> list[JobCandidate]:
        """Extract job candidates from HTML."""
        pass


class SchemaOrgStrategy(BaseExtractionStrategy):
    """Extract jobs from schema.org JobPosting structured data."""
    
    name = "schema_org"
    source = ExtractionSource.SCHEMA_ORG
    
    def extract(self, html: str, url: str) -> list[JobCandidate]:
        """Extract jobs from JSON-LD script tags."""
        candidates = []
        
        # Find JSON-LD scripts
        script_pattern = r'<script[^>]*type=["\']application/(?:ld\+)?json["\'][^>]*>([\s\S]*?)</script>'
        scripts = re.findall(script_pattern, html, re.IGNORECASE)
        
        for script_content in scripts:
            try:
                data = json.loads(script_content)
                candidates.extend(self._parse_json_ld(data, url))
            except (json.JSONDecodeError, TypeError):
                continue
        
        # Also check for microdata
        soup = BeautifulSoup(html, 'lxml')
        for item in soup.select('[itemtype*="JobPosting"]'):
            candidate = self._parse_microdata(item, url)
            if candidate:
                candidates.append(candidate)
        
        logger.debug(f"SchemaOrgStrategy found {len(candidates)} candidates")
        return candidates
    
    def _parse_json_ld(self, data: dict | list, base_url: str) -> list[JobCandidate]:
        """Parse JSON-LD data for JobPosting."""
        candidates = []
        
        if isinstance(data, dict):
            if data.get("@type") == "JobPosting":
                candidates.append(self._create_candidate(data, base_url))
            elif data.get("@graph"):
                for item in data["@graph"]:
                    if isinstance(item, dict) and item.get("@type") == "JobPosting":
                        candidates.append(self._create_candidate(item, base_url))
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("@type") == "JobPosting":
                    candidates.append(self._create_candidate(item, base_url))
        
        return candidates
    
    def _create_candidate(self, data: dict, base_url: str) -> JobCandidate:
        """Create JobCandidate from schema.org JobPosting data."""
        location = "Unknown"
        if data.get("jobLocation"):
            loc = data["jobLocation"]
            if isinstance(loc, dict):
                addr = loc.get("address", {})
                if isinstance(addr, dict):
                    location = addr.get("addressLocality", "Unknown")
                elif isinstance(addr, str):
                    location = addr
        
        job_url = data.get("url", "")
        if job_url and not job_url.startswith("http"):
            job_url = urljoin(base_url, job_url)
        
        return JobCandidate(
            title=data.get("title", "Unknown"),
            url=job_url or base_url,
            location=location,
            department=data.get("industry"),
            company=data.get("hiringOrganization", {}).get("name") if isinstance(data.get("hiringOrganization"), dict) else None,
            source=self.source,
            signals={"schema_org": True, "has_job_url": bool(job_url)},
        )
    
    def _parse_microdata(self, item: Tag, base_url: str) -> Optional[JobCandidate]:
        """Parse microdata JobPosting."""
        title_elem = item.select_one('[itemprop="title"], [itemprop="name"]')
        if not title_elem:
            return None
        
        title = title_elem.get_text(strip=True)
        
        url_elem = item.select_one('[itemprop="url"]')
        job_url = url_elem.get('href', '') if url_elem else ''
        if job_url and not job_url.startswith("http"):
            job_url = urljoin(base_url, job_url)
        
        location_elem = item.select_one('[itemprop="jobLocation"] [itemprop="addressLocality"]')
        location = location_elem.get_text(strip=True) if location_elem else "Unknown"
        
        return JobCandidate(
            title=title,
            url=job_url or base_url,
            location=location,
            source=self.source,
            signals={"microdata": True},
        )


class PdfLinkStrategy(BaseExtractionStrategy):
    """Extract jobs from PDF/document links by parsing filename patterns.
    
    Many German company websites (especially SMEs) display job listings as PDF flyers.
    These are often links like:
    - stellenausschreibung_IT-Systemadministrator.pdf
    - 4pipes_Stellenausschreibung_Vertriebsmitarbeiter-Innendienst_20251027.pdf
    
    This strategy extracts job titles from such filenames.
    """
    
    name = "pdf_link"
    source = ExtractionSource.PDF_LINK
    
    # File extensions that might contain job postings
    JOB_FILE_EXTENSIONS = {'.pdf', '.doc', '.docx'}
    
    # Keywords in filename that indicate a job posting (German + English)
    JOB_FILENAME_KEYWORDS = {
        'stellenausschreibung', 'stellenangebot', 'stellenanzeige',
        'jobausschreibung', 'jobangebot', 'jobanzeige',
        'karriere', 'career', 'vacancy', 'position',
        'job_posting', 'job-posting', 'jobposting',
    }
    
    # Words to strip from extracted titles
    STRIP_WORDS = {
        'stellenausschreibung', 'stellenangebot', 'stellenanzeige',
        'jobausschreibung', 'jobangebot', 'jobanzeige',
        'karriere', 'career', 'vacancy', 'position',
        'job', 'posting', 'job_posting', 'jobposting',
    }
    
    def extract(self, html: str, url: str) -> list[JobCandidate]:
        """Extract jobs from PDF links in HTML."""
        soup = BeautifulSoup(html, 'lxml')
        candidates = []
        seen_titles = set()
        
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            if not href:
                continue
            
            # Check if it's a document link
            href_lower = href.lower()
            if not any(href_lower.endswith(ext) for ext in self.JOB_FILE_EXTENSIONS):
                continue
            
            # Check if filename contains job-related keywords
            filename = href.split('/')[-1]
            filename_lower = filename.lower()
            
            if not any(kw in filename_lower for kw in self.JOB_FILENAME_KEYWORDS):
                continue
            
            # Extract job title from filename
            title = self._extract_title_from_filename(filename)
            if not title:
                continue
            
            # Deduplicate
            normalized = title.lower()
            if normalized in seen_titles:
                continue
            seen_titles.add(normalized)
            
            # Build full URL
            job_url = urljoin(url, href)
            
            candidates.append(JobCandidate(
                title=title,
                url=job_url,
                source=self.source,
                signals={
                    "from_pdf_link": True,
                    "filename": filename,
                },
            ))
        
        logger.debug(f"PdfLinkStrategy found {len(candidates)} candidates")
        return candidates
    
    def _extract_title_from_filename(self, filename: str) -> str:
        """Extract job title from PDF filename.
        
        Examples:
            4pipes_Stellenausschreibung_Vertriebsmitarbeiter-Innendienst_20251027.pdf
            -> Vertriebsmitarbeiter Innendienst
            
            stellenausschreibung_it-systemadministrator_v2_20251027.pdf
            -> IT-Systemadministrator
        """
        # Remove extension
        name = filename.rsplit('.', 1)[0]
        
        # Replace underscores and hyphens with spaces (but keep hyphens in compound words)
        # First, protect compound words by marking internal hyphens
        name = re.sub(r'([a-zA-ZäöüÄÖÜß])-([a-zA-ZäöüÄÖÜß])', r'\1§HYPHEN§\2', name)
        # Now replace underscores and remaining hyphens with spaces
        name = name.replace('_', ' ').replace('-', ' ')
        # Restore protected hyphens
        name = name.replace('§HYPHEN§', '-')
        
        # Split into parts
        parts = name.split()
        
        # Remove known strip words and filter
        filtered_parts = []
        for part in parts:
            # Skip dates (8 digits like 20251027)
            if re.match(r'^\d{6,8}$', part):
                continue
            # Skip version numbers (v1, v2, etc.)
            if re.match(r'^v\d+$', part.lower()):
                continue
            # Skip company prefixes (like "4pipes")
            if re.match(r'^\d+[a-zA-Z]+$', part):
                continue
            # Skip strip words
            if part.lower() in self.STRIP_WORDS:
                continue
            # Skip very short parts (like "ah" for initials)
            if len(part) <= 2 and part.lower() not in {'it', 'hr', 'qa', 'pr', 'vp'}:
                continue
            
            filtered_parts.append(part)
        
        if not filtered_parts:
            return ""
        
        # Known acronyms that should be uppercase
        known_acronyms = {'it', 'hr', 'qa', 'pr', 'vp', 'ceo', 'cto', 'cfo', 'sap', 'erp', 'crm'}
        
        # Capitalize each part properly
        capitalized_parts = []
        for part in filtered_parts:
            # Keep known acronyms uppercase
            if part.lower() in known_acronyms:
                capitalized_parts.append(part.upper())
            # Keep already-uppercase acronyms (like IT, HR)
            elif part.upper() == part and len(part) <= 4:
                capitalized_parts.append(part.upper())
            # Handle compound words with hyphens (Vertriebsmitarbeiter-Innendienst)
            elif '-' in part:
                subparts = part.split('-')
                capitalized_subparts = []
                for s in subparts:
                    if s.lower() in known_acronyms:
                        capitalized_subparts.append(s.upper())
                    elif s.upper() == s and len(s) <= 4:
                        capitalized_subparts.append(s.upper())
                    else:
                        capitalized_subparts.append(s.capitalize())
                capitalized_parts.append('-'.join(capitalized_subparts))
            else:
                capitalized_parts.append(part.capitalize())
        
        title = ' '.join(capitalized_parts)
        
        # Clean up multiple spaces
        title = re.sub(r'\s+', ' ', title).strip()
        
        return title


