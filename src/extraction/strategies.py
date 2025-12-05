"""Job extraction strategies."""

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .candidate import (
    JobCandidate,
    ExtractionSource,
    is_likely_job_title,
    JOB_TITLE_KEYWORDS,
)

logger = logging.getLogger(__name__)


class BaseExtractionStrategy(ABC):
    """Base class for extraction strategies."""
    
    name: str = "base"
    source: ExtractionSource = ExtractionSource.KEYWORD_MATCH
    
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


class GenderNotationStrategy(BaseExtractionStrategy):
    """Extract jobs by finding (m/w/d) gender notation patterns."""
    
    name = "gender_notation"
    source = ExtractionSource.GENDER_NOTATION
    
    # All known gender notation variants
    GENDER_PATTERN = re.compile(
        r'\((?:m/w/d|w/m/d|m/f/d|f/m/d|m/w/x|m/d/w|w/d/m|d/m/w|'
        r'gn|d/w/m|w/m/x|m/f/x|f/m/x|all\s*genders?|'
        r'w/m/divers|m/w/divers|divers)\)',
        re.IGNORECASE
    )
    
    def extract(self, html: str, url: str) -> list[JobCandidate]:
        """Extract jobs containing gender notation."""
        soup = BeautifulSoup(html, 'lxml')
        candidates = []
        seen_titles = set()
        
        # Find all text nodes containing gender notation
        for elem in soup.find_all(string=lambda t: t and self.GENDER_PATTERN.search(t)):
            text = str(elem).strip()
            
            # Skip invalid lengths
            if len(text) > 150 or len(text) < 8:
                continue
            
            # Skip standalone notation
            if self.GENDER_PATTERN.fullmatch(text.strip()):
                continue
            
            # Skip duplicates
            normalized = self._normalize(text)
            if normalized in seen_titles:
                continue
            seen_titles.add(normalized)
            
            # Find job URL from parent elements
            job_url = self._find_job_url(elem, url)
            
            # Find location
            location = self._find_location(elem)
            
            signals = {
                "has_gender_notation": True,
                "has_job_url": job_url != url,
                "has_location": location != "Unknown",
            }
            
            candidates.append(JobCandidate(
                title=text,
                url=job_url,
                location=location,
                source=self.source,
                signals=signals,
            ))
        
        logger.debug(f"GenderNotationStrategy found {len(candidates)} candidates")
        return candidates
    
    def _normalize(self, text: str) -> str:
        """Normalize title for deduplication."""
        normalized = self.GENDER_PATTERN.sub('', text.lower())
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        return normalized
    
    def _find_job_url(self, elem, base_url: str) -> str:
        """Find job URL from parent elements."""
        parent = elem.parent
        for _ in range(8):
            if parent and parent.name == 'a' and parent.get('href'):
                href = parent.get('href')
                if href and not href.startswith('#') and not href.startswith('javascript:'):
                    return urljoin(base_url, href)
            if parent:
                # Also check for links inside the parent
                link = parent.find('a', href=True)
                if link:
                    href = link.get('href')
                    if href and not href.startswith('#') and not href.startswith('javascript:'):
                        return urljoin(base_url, href)
                parent = parent.parent
            else:
                break
        return base_url
    
    def _find_location(self, elem) -> str:
        """Extract location from title or nearby text."""
        text = str(elem).strip()
        
        # Check for "Title - Location" pattern
        match = re.search(r'-\s*([A-Za-zäöüÄÖÜß]+(?:\s+[A-Za-zäöüÄÖÜß]+)?)\s*$', text)
        if match:
            location = match.group(1).strip()
            # Common locations
            if location.lower() in ['austria', 'germany', 'schweiz', 'switzerland', 'remote', 'dach']:
                return location.title()
        
        # Check parent elements for location
        parent = elem.parent
        for _ in range(4):
            if not parent:
                break
            
            parent_text = parent.get_text(separator=' ', strip=True).lower()
            
            # Look for location indicators
            if 'remote' in parent_text or 'home office' in parent_text:
                return 'Remote'
            
            location_match = re.search(
                r'(?:standort|location|ort)[:\s]+([A-Za-zäöüÄÖÜß]+)',
                parent_text, re.IGNORECASE
            )
            if location_match:
                return location_match.group(1).title()
            
            parent = parent.parent
        
        return "Unknown"


class ListStructureStrategy(BaseExtractionStrategy):
    """Extract jobs by detecting repeated HTML structures (lists of similar items)."""
    
    name = "list_structure"
    source = ExtractionSource.LIST_STRUCTURE
    
    MIN_ITEMS = 2  # Minimum items to consider a valid job list
    
    def extract(self, html: str, url: str) -> list[JobCandidate]:
        """Extract jobs by analyzing repeated HTML structures."""
        soup = BeautifulSoup(html, 'lxml')
        candidates = []
        seen_titles = set()
        
        # Find potential job list containers
        for container in soup.find_all(['ul', 'ol', 'div', 'section']):
            items = self._find_repeated_structure(container)
            if len(items) >= self.MIN_ITEMS:
                for item in items:
                    candidate = self._extract_from_item(item, url, seen_titles)
                    if candidate:
                        candidates.append(candidate)
        
        logger.debug(f"ListStructureStrategy found {len(candidates)} candidates")
        return candidates
    
    def _find_repeated_structure(self, container: Tag) -> list[Tag]:
        """Find repeated child elements that might be job items."""
        children = [c for c in container.children if isinstance(c, Tag)]
        
        if len(children) < self.MIN_ITEMS:
            return []
        
        # Check if children have similar structure
        tag_names = [c.name for c in children]
        
        # All same tag type (e.g., all <li> or all <div>)
        if len(set(tag_names)) == 1:
            # Additional check: children should have similar class patterns
            class_patterns = []
            for child in children[:5]:  # Check first 5
                classes = child.get('class', [])
                if classes:
                    class_patterns.append(tuple(sorted(classes)))
            
            # If class patterns are similar (or all have no classes)
            if len(set(class_patterns)) <= 2:
                return children
        
        return []
    
    def _extract_from_item(self, item: Tag, base_url: str, seen_titles: set) -> Optional[JobCandidate]:
        """Extract job info from a list item."""
        # Try to find title in heading or link
        title_elem = item.find(['h1', 'h2', 'h3', 'h4', 'a'])
        if not title_elem:
            # Fall back to direct text
            title = item.get_text(strip=True)
        else:
            title = title_elem.get_text(strip=True)
        
        # Validate title
        is_likely, signals = is_likely_job_title(title)
        if not is_likely:
            return None
        
        # Skip duplicates
        normalized = re.sub(r'\s+', ' ', title.lower().strip())
        if normalized in seen_titles:
            return None
        seen_titles.add(normalized)
        
        # Find URL
        job_url = base_url
        link = item.find('a', href=True)
        if link:
            href = link.get('href')
            if href and not href.startswith('#') and not href.startswith('javascript:'):
                job_url = urljoin(base_url, href)
        
        signals["has_job_url"] = job_url != base_url
        signals["from_list_structure"] = True
        
        return JobCandidate(
            title=title,
            url=job_url,
            source=self.source,
            signals=signals,
        )


class KeywordMatchStrategy(BaseExtractionStrategy):
    """Extract jobs by finding text with job-related keywords."""
    
    name = "keyword_match"
    source = ExtractionSource.KEYWORD_MATCH
    
    def extract(self, html: str, url: str) -> list[JobCandidate]:
        """Extract potential jobs based on keyword matching."""
        soup = BeautifulSoup(html, 'lxml')
        candidates = []
        seen_titles = set()
        
        # Look for headings and links that might be job titles
        for elem in soup.find_all(['h1', 'h2', 'h3', 'h4', 'a']):
            text = elem.get_text(strip=True)
            
            is_likely, signals = is_likely_job_title(text)
            if not is_likely:
                continue
            
            # Skip duplicates
            normalized = re.sub(r'\s+', ' ', text.lower().strip())
            if normalized in seen_titles:
                continue
            seen_titles.add(normalized)
            
            # Get URL
            job_url = url
            if elem.name == 'a' and elem.get('href'):
                href = elem.get('href')
                if href and not href.startswith('#') and not href.startswith('javascript:'):
                    job_url = urljoin(url, href)
            
            signals["has_job_url"] = job_url != url
            
            candidates.append(JobCandidate(
                title=text,
                url=job_url,
                source=self.source,
                signals=signals,
            ))
        
        logger.debug(f"KeywordMatchStrategy found {len(candidates)} candidates")
        return candidates
