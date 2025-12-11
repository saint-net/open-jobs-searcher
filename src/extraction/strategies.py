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
    
    # Pattern to remove gender notation for deduplication
    GENDER_PATTERN = re.compile(
        r'\s*\([mwfdx/]+\)\s*'  # (m/w/d), (f/d/m), etc.
        r'|\s*[mwfdx]/[mwfdx](/[mwfdx])?\s*$',  # m/w/d at end without parentheses
        re.IGNORECASE
    )
    
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
        
        # Skip duplicates - normalize by removing gender notation
        normalized = self.GENDER_PATTERN.sub('', title.lower())
        normalized = re.sub(r'\s+', ' ', normalized).strip()
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
    
    # Pattern to remove gender notation for deduplication
    GENDER_PATTERN = re.compile(
        r'\s*\([mwfdx/]+\)\s*'  # (m/w/d), (f/d/m), etc.
        r'|\s*[mwfdx]/[mwfdx](/[mwfdx])?\s*$',  # m/w/d at end without parentheses
        re.IGNORECASE
    )
    
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
            
            # Skip duplicates - normalize by removing gender notation
            normalized = self.GENDER_PATTERN.sub('', text.lower())
            normalized = re.sub(r'\s+', ' ', normalized).strip()
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


class AccessibilityTreeStrategy(BaseExtractionStrategy):
    """Extract jobs from browser accessibility tree (a11y snapshot).
    
    Two-stage approach:
    1. Find elements with job-related keywords (any role)
    2. Check context - role type, if we're in a careers section
    
    This handles both link-based job listings and accordion/button structures.
    """
    
    name = "accessibility_tree"
    source = ExtractionSource.ACCESSIBILITY
    
    # Pattern to remove gender notation for deduplication
    GENDER_PATTERN = re.compile(
        r'\s*\([mwfdx/]+\)\s*'  # (m/w/d), (f/d/m), etc.
        r'|\s*[mwfdx]/[mwfdx](/[mwfdx])?\s*$',  # m/w/d at end without parentheses
        re.IGNORECASE
    )
    
    # Keywords that indicate we're in a jobs/careers section
    JOBS_SECTION_KEYWORDS = {
        'careers', 'career', 'jobs', 'job', 'vacancies', 'vacancy',
        'openings', 'positions', 'stellen', 'karriere', 'stellenangebote',
        'offene stellen', 'join us', 'work with us', 'hiring',
    }
    
    # Roles that can contain job titles
    JOB_CANDIDATE_ROLES = {'link', 'heading', 'button', 'listitem'}
    
    # Keywords to filter out (cookie consent, navigation, UI elements, etc.)
    FILTER_KEYWORDS = {
        # Cookie consent
        'cookie', 'cookies', 'datenschutz', 'privacy', 'consent',
        'zulassen', 'erlauben', 'akzeptieren', 'accept', 'allow',
        'notwendig', 'necessary', 'preferences', 'präferenzen',
        'statistik', 'statistics', 'marketing', 'webseite verwendet',
        'website uses', 'this website',
        # Navigation & UI
        'menu', 'navigation', 'home', 'zurück', 'back', 'next', 'previous',
        'mehr erfahren', 'learn more', 'read more', 'view all', 'see all',
        'slider', 'pause', 'play', 'submit', 'send', 'senden',
        'contact', 'kontakt', 'subscribe', 'newsletter',
        # Legal
        'impressum', 'imprint', 'agb', 'terms', 'legal',
        # Marketing/generic phrases
        'certified', 'impact', 'love to hear', 'get in touch',
        'current open', 'open positions', 'our team', 'join us',
        'we are', 'wir sind', 'about us', 'über uns',
    }
    
    async def extract_async(
        self, 
        page, 
        url: str
    ) -> list[JobCandidate]:
        """
        Extract jobs from accessibility tree using two-stage approach.
        
        Args:
            page: Playwright Page object
            url: Base URL for resolving relative links
            
        Returns:
            List of JobCandidate objects
        """
        candidates = []
        seen_titles = set()
        
        try:
            # Get accessibility snapshot
            snapshot = await page.accessibility.snapshot()
            if not snapshot:
                logger.debug("AccessibilityTreeStrategy: empty snapshot")
                return []
            
            # Two-stage extraction:
            # Stage 1 & 2 combined: Walk tree, track context, extract candidates
            await self._walk_snapshot(
                snapshot, page, url, candidates, seen_titles,
                in_jobs_section=False  # Will be detected during walk
            )
            
            logger.debug(f"AccessibilityTreeStrategy found {len(candidates)} candidates")
            return candidates
            
        except Exception as e:
            logger.warning(f"AccessibilityTreeStrategy error: {e}")
            return []
    
    def _is_jobs_section(self, name: str) -> bool:
        """Check if name indicates a jobs/careers section."""
        if not name:
            return False
        name_lower = name.lower()
        return any(kw in name_lower for kw in self.JOBS_SECTION_KEYWORDS)
    
    async def _walk_snapshot(
        self,
        node: dict,
        page,
        url: str,
        candidates: list[JobCandidate],
        seen_titles: set,
        in_jobs_section: bool = False,
    ):
        """Recursively walk accessibility tree and extract jobs with context awareness."""
        role = node.get("role", "")
        a11y_name = node.get("name", "")
        
        # Update context: check if we entered a jobs section
        if self._is_jobs_section(a11y_name):
            in_jobs_section = True
        
        # Stage 1: Check if this element could be a job candidate
        if role in self.JOB_CANDIDATE_ROLES and a11y_name:
            await self._process_potential_job(
                role, a11y_name, page, url, candidates, seen_titles, in_jobs_section
            )
        
        # Recursively process children with updated context
        for child in node.get("children", []):
            await self._walk_snapshot(
                child, page, url, candidates, seen_titles, in_jobs_section
            )
    
    def _should_filter_out(self, text: str) -> bool:
        """Check if text should be filtered out (cookie consent, navigation, etc.)."""
        if not text:
            return True
        text_lower = text.lower()
        return any(kw in text_lower for kw in self.FILTER_KEYWORDS)
    
    async def _process_potential_job(
        self,
        role: str,
        a11y_name: str,
        page,
        url: str,
        candidates: list[JobCandidate],
        seen_titles: set,
        in_jobs_section: bool,
    ):
        """Process a potential job candidate element."""
        
        # Early filter: skip cookie consent, navigation, etc.
        if self._should_filter_out(a11y_name):
            return
        
        # For links: get actual visible text
        if role == "link":
            actual_title, job_url = await self._get_link_text_and_url(page, a11y_name, url)
        else:
            # For headings/buttons: use the a11y name directly
            actual_title = a11y_name.strip()
            job_url = url  # No direct URL for non-link elements
        
        if not actual_title:
            return
        
        # Filter again with actual text (may differ from a11y_name)
        if self._should_filter_out(actual_title):
            return
        
        # Stage 2: Check if it's likely a job title
        is_likely, signals = is_likely_job_title(actual_title)
        
        # For non-link elements (headings/buttons): require STRONG signals
        # Don't accept just because we're "in jobs section" - too many false positives
        if role in ('heading', 'button', 'listitem') and not is_likely:
            # Only accept if has gender notation (m/w/d) - very strong signal
            has_gender = bool(re.search(r'\([mwfdx/]+\)', actual_title, re.IGNORECASE))
            if has_gender:
                is_likely = True
                signals["has_gender_notation"] = True
                signals["accepted_heading_button"] = True
        
        if not is_likely:
            return
        
        # Normalize for deduplication
        normalized = self.GENDER_PATTERN.sub('', actual_title.lower())
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        
        if normalized in seen_titles:
            return
        seen_titles.add(normalized)
        
        # Add signals
        signals["has_job_url"] = job_url != url
        signals["from_accessibility"] = True
        signals["role"] = role
        if in_jobs_section:
            signals["in_jobs_section"] = True
        
        candidates.append(JobCandidate(
            title=actual_title,
            url=job_url,
            source=self.source,
            signals=signals,
        ))
    
    async def _get_link_text_and_url(
        self, page, a11y_name: str, base_url: str
    ) -> tuple[str, str]:
        """Get actual visible text and URL from link.
        
        Args:
            page: Playwright page object
            a11y_name: Accessibility name (may be aria-label, not visible text)
            base_url: Base URL for resolving relative hrefs
            
        Returns:
            Tuple of (actual_text, url) - actual_text may differ from a11y_name
        """
        try:
            # Find link by accessible name
            link = page.get_by_role("link", name=a11y_name, exact=True)
            
            count = await link.count()
            if count > 0:
                first_link = link.first
                
                # Get actual visible text (innerText), not aria-label
                actual_text = await first_link.inner_text()
                actual_text = actual_text.strip() if actual_text else ""
                
                # Fix duplicated lines (innerText may contain repeated text from nested elements)
                if actual_text and '\n' in actual_text:
                    lines = [line.strip() for line in actual_text.split('\n') if line.strip()]
                    unique_lines = list(dict.fromkeys(lines))  # Remove duplicates, keep order
                    actual_text = ' '.join(unique_lines)
                
                # If innerText is empty or very short, the a11y_name might be the real text
                # (some sites have text directly in link without aria-label)
                if not actual_text or len(actual_text) < 3:
                    # Check if a11y_name looks like navigation aria-label
                    if a11y_name.startswith(("Go to ", "Navigate to ", "Link to ", "/")):
                        actual_text = ""  # Skip navigation links
                    else:
                        actual_text = a11y_name  # Use a11y name as fallback
                
                # Get URL
                href = await first_link.get_attribute("href")
                if href:
                    if href.startswith(('http://', 'https://')):
                        job_url = href
                    else:
                        job_url = urljoin(base_url, href)
                else:
                    job_url = base_url
                
                return actual_text, job_url
                
        except Exception as e:
            logger.debug(f"Could not get link info for '{a11y_name}': {e}")
        
        return "", base_url
    
    def extract(self, html: str, url: str) -> list[JobCandidate]:
        """Synchronous extract not supported - use extract_async with page object."""
        logger.warning("AccessibilityTreeStrategy.extract() called - use extract_async() instead")
        return []
