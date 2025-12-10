"""Job candidate model with confidence scoring."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import re


class ExtractionSource(Enum):
    """Source of job extraction."""
    SCHEMA_ORG = "schema_org"          # schema.org/JobPosting - highest confidence
    PDF_LINK = "pdf_link"              # Job from PDF/document link filename
    ACCESSIBILITY = "accessibility"     # Browser accessibility tree - high confidence
    GENDER_NOTATION = "gender_notation" # (m/w/d) pattern
    LIST_STRUCTURE = "list_structure"   # Detected from repeated HTML structure
    KEYWORD_MATCH = "keyword_match"     # Job title keywords
    LLM = "llm"                         # LLM extraction - fallback


# Base confidence scores by source
SOURCE_CONFIDENCE = {
    ExtractionSource.SCHEMA_ORG: 0.95,
    ExtractionSource.PDF_LINK: 0.90,  # High confidence - explicit job document links
    ExtractionSource.ACCESSIBILITY: 0.90,  # High confidence - clean text from browser
    ExtractionSource.GENDER_NOTATION: 0.85,
    ExtractionSource.LIST_STRUCTURE: 0.60,
    ExtractionSource.KEYWORD_MATCH: 0.50,
    ExtractionSource.LLM: 0.70,
}


@dataclass
class JobCandidate:
    """A job candidate with confidence score."""
    
    title: str
    url: str = ""
    location: str = "Unknown"
    department: Optional[str] = None
    company: Optional[str] = None
    source: ExtractionSource = ExtractionSource.KEYWORD_MATCH
    confidence: float = 0.5
    
    # Signals that contributed to confidence
    signals: dict = field(default_factory=dict)
    
    def __post_init__(self):
        """Calculate confidence based on signals."""
        if not self.signals:
            self.confidence = SOURCE_CONFIDENCE.get(self.source, 0.5)
        else:
            self._calculate_confidence()
    
    def _calculate_confidence(self):
        """Calculate confidence score based on multiple signals."""
        base = SOURCE_CONFIDENCE.get(self.source, 0.5)
        bonus = 0.0
        
        # Signal bonuses
        if self.signals.get("has_gender_notation"):
            bonus += 0.15
        if self.signals.get("has_job_url"):
            bonus += 0.10
        if self.signals.get("has_location"):
            bonus += 0.05
        if self.signals.get("title_has_keywords"):
            bonus += 0.10
        if self.signals.get("in_job_container"):
            bonus += 0.08
        if self.signals.get("proper_length"):
            bonus += 0.05
            
        # Penalties
        if self.signals.get("too_long"):
            bonus -= 0.20
        if self.signals.get("too_short"):
            bonus -= 0.15
        if self.signals.get("looks_like_nav"):
            bonus -= 0.30
        if self.signals.get("has_non_job_words"):
            bonus -= 0.25
            
        self.confidence = min(max(base + bonus, 0.0), 1.0)
    
    def to_dict(self) -> dict:
        """Convert to dictionary format."""
        return {
            "title": self.title,
            "url": self.url,
            "location": self.location,
            "department": self.department,
            "company": self.company,
        }
    
    def _fix_concatenated_title(self, title: str) -> str:
        """
        Fix concatenated/repeated titles.
        
        Examples:
            "Full-Stack Engineer (f/d/m)Full-Stack Engineer (f/d/m)" -> "Full-Stack Engineer (f/d/m)"
            "Frontend Engineer\nFrontend Engineer" -> "Frontend Engineer"
        """
        if not title or len(title) < 10:
            return title
        
        # First check for newline-separated duplicates (from innerText)
        lines = [line.strip() for line in title.split('\n') if line.strip()]
        if len(lines) >= 2:
            # Remove duplicate lines, keep order
            unique_lines = list(dict.fromkeys(lines))
            if len(unique_lines) < len(lines):
                # Had duplicates - join unique lines
                return ' '.join(unique_lines)
            # Check if first and second lines are the same (normalized)
            first_norm = re.sub(r'\s+', ' ', lines[0].lower())
            second_norm = re.sub(r'\s+', ' ', lines[1].lower())
            if first_norm == second_norm:
                return lines[0]
        
        # Then check for directly concatenated duplicates
        title_len = len(title)
        for half_len in range(title_len // 4, title_len // 2 + 1):
            first_part = title[:half_len]
            rest = title[half_len:]
            
            if rest == first_part or rest.lstrip() == first_part:
                return first_part.strip()
            
            first_normalized = re.sub(r'\s+', ' ', first_part.strip().lower())
            rest_normalized = re.sub(r'\s+', ' ', rest.strip().lower())
            
            if first_normalized == rest_normalized and first_normalized:
                return first_part.strip()
        
        return title
    
    @property
    def normalized_title(self) -> str:
        """Get normalized title for comparison (keeps location for uniqueness)."""
        if not self.title:
            return ""
        
        # First, detect and fix concatenated/repeated titles
        # e.g., "Full-Stack Engineer (f/d/m)Full-Stack Engineer (f/d/m)" -> "Full-Stack Engineer (f/d/m)"
        title = self._fix_concatenated_title(self.title)
        
        # Remove gender notation and normalize whitespace
        # BUT keep location suffix - different locations = different jobs
        # Pattern 1: with parentheses (m/w/d), (f/d/m), etc.
        normalized = re.sub(r'\s*\([mwfdx/]+\)\s*', '', title.lower())
        # Pattern 2: without parentheses at end of title: "Senior DeveloperM/W/D" or "Senior Developer m/w/d"
        normalized = re.sub(r'\s*[mwfdx]/[mwfdx](/[mwfdx])?\s*$', '', normalized, flags=re.IGNORECASE)
        
        # Remove salary/employment type suffixes that create duplicates
        # Pattern: "– Vollzeit: 30.000 - 40.000 Euro Jahresgehalt."
        # Also handles: "- Vollzeit/Teilzeit: ..."
        normalized = re.sub(
            r'\s*[–-]\s*(vollzeit|teilzeit|full-?time|part-?time)[:/]?\s*[\d.,\s-]*(euro|eur|€)?.*$',
            '',
            normalized,
            flags=re.IGNORECASE
        )
        
        # Remove trailing salary info without employment type
        # Pattern: "30.000 - 40.000 Euro Jahresgehalt" at the end
        normalized = re.sub(
            r'\s*[\d.,]+\s*[-–]\s*[\d.,]+\s*(euro|eur|€)\s*(jahresgehalt|annual|salary)?\.?\s*$',
            '',
            normalized,
            flags=re.IGNORECASE
        )
        
        # Remove "in vollzeit/teilzeit" from title
        normalized = re.sub(r'\s+in\s+(vollzeit|teilzeit)\b', '', normalized)
        
        # Remove department/context suffixes like "im Vertrieb"
        normalized = re.sub(r'\s+(im|in der|in den|für)\s+\w+$', '', normalized)
        
        # Normalize German singular/plural forms for common job words
        # Telefonisten -> Telefonist, Mitarbeiter/Mitarbeiterin -> Mitarbeiter
        german_singular_map = {
            r'\btelefonisten\b': 'telefonist',
            r'\bmitarbeiterin\b': 'mitarbeiter',
            r'\bmitarbeiterinnen\b': 'mitarbeiter',
            r'\bassistentin\b': 'assistent',
            r'\bassistentinnen\b': 'assistent',
            r'\bberaterinnen\b': 'berater',
            r'\bberaterin\b': 'berater',
            r'\bkundenbetreuerin\b': 'kundenbetreuer',
            r'\bkundenbetreuerinnen\b': 'kundenbetreuer',
        }
        for pattern, replacement in german_singular_map.items():
            normalized = re.sub(pattern, replacement, normalized)
        
        # Normalize "Geschäftsführers" -> "Geschäftsführung" (genitive -> base)
        # "des Geschäftsführers" and "der Geschäftsführung" are same position
        normalized = re.sub(r'\bdes\s+geschäftsführers\b', 'der geschäftsführung', normalized)
        normalized = re.sub(r'\bgeschäftsführers\b', 'geschäftsführung', normalized)
        
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        return normalized
    
    def __eq__(self, other):
        if not isinstance(other, JobCandidate):
            return False
        return self.normalized_title == other.normalized_title
    
    def __hash__(self):
        return hash(self.normalized_title)


# Job title keywords for scoring
JOB_TITLE_KEYWORDS = {
    # English
    'manager', 'developer', 'engineer', 'consultant', 'analyst', 'designer',
    'director', 'specialist', 'coordinator', 'assistant', 'administrator',
    'architect', 'lead', 'senior', 'junior', 'intern', 'trainee',
    'head', 'chief', 'officer', 'president', 'vice',
    # German
    'leiter', 'leiterin', 'berater', 'beraterin', 'entwickler', 'entwicklerin',
    'ingenieur', 'ingenieurin', 'fachkraft', 'mitarbeiter', 'mitarbeiterin',
    'werkstudent', 'werkstudentin', 'praktikant', 'praktikantin',
    'geschäftsführer', 'geschäftsführerin', 'projektmanager', 'projektmanagerin',
    'produktmanager', 'produktmanagerin', 'teamleiter', 'teamleiterin',
    'sachbearbeiter', 'sachbearbeiterin', 'referent', 'referentin',
    'kaufmann', 'kauffrau', 'techniker', 'technikerin',
}

# Words that indicate NOT a job title
NON_JOB_WORDS = {
    # Legal/footer
    'impressum', 'datenschutz', 'privacy', 'cookie', 'agb', 'terms',
    'copyright', 'all rights reserved', 'alle rechte vorbehalten',
    # Navigation/UI
    'kontakt', 'contact', 'über uns', 'about', 'home', 'startseite',
    'login', 'register', 'anmelden', 'registrieren', 'suche', 'search',
    'newsletter', 'blog', 'news', 'presse', 'press', 'mehr erfahren',
    'learn more', 'read more', 'weiterlesen', 'zurück', 'back',
    'filter', 'sort', 'alle', 'all', 'reset', 'clear',
    'download anfordern', 'entdecken sie',
    # Cookie consent / tracking
    'consent', 'storage duration', 'pixel tracker', 'local storage',
    'persistent', 'preferences', 'statistics',
    'cross-domain', 'necessary', 'tracking',
    # Legal forms
    'data subject', 'rights form', 'speakup', 'do not sell', 'share my personal',
    # German menu/category items (not job titles) - specific phrases
    'dokumentenverwaltung', 'finanzen & controlling', 'finanzen und controlling',
    'geräte- und maschinenverwaltung', 'service und wartung',
    'vertrieb und crm', 'wohnbau-management', 'einkauf, lager',
}

# Patterns that indicate company names (not job titles)
# These need word boundaries to avoid false positives
COMPANY_NAME_PATTERNS = [
    r'\blimited\b',              # "Thomas Armstrong Limited"
    r'\bgmbh\b',                 # German company suffix
    r'\b[A-Z][a-z]+\s+AG\b',     # "Company AG" - requires capital letter before
    r'\bbv\b',                   # Dutch company suffix
    r'\bbuilding\s+services\b',  # "Building Services Engineers"
    r'^[A-Z]{2,}\s+International$',  # "BAM International", "ABC International"
]

# Regex patterns that indicate NOT a job title
NON_JOB_PATTERNS = [
    r'^type:\s*',                      # "Type: Pixel Tracker"
    r'^maximum storage',               # "Maximum Storage Duration:"
    r'\.com\d*$',                       # URLs like "marketing.4psgroup.com1"
    r'^©',                             # Copyright symbol at start
    r'©',                              # Copyright symbol anywhere
    r'^\s*$',                          # Empty or whitespace only
    r'^[a-z0-9.-]+\.[a-z]{2,4}$',      # Domain names
    r'^(html\s+)?local\s+storage$',    # "HTML Local Storage"
    r'^\d+\s*(year|month|day)s?$',     # "1 year", "180 days"
    r'^session$',                      # Just "Session"
]


def is_likely_job_title(text: str) -> tuple[bool, dict]:
    """
    Check if text is likely a job title.
    
    Returns:
        Tuple of (is_likely, signals_dict)
    """
    if not text or not text.strip():
        return False, {"empty": True}
    
    text_lower = text.lower().strip()
    signals = {}
    
    # Length checks
    if len(text) < 5:
        signals["too_short"] = True
        return False, signals
    if len(text) > 150:
        signals["too_long"] = True
        return False, signals
    
    signals["proper_length"] = 15 < len(text) < 100
    
    # Check non-job patterns first (high priority rejection)
    for pattern in NON_JOB_PATTERNS:
        if re.search(pattern, text_lower):
            signals["matches_non_job_pattern"] = True
            return False, signals
    
    # Gender notation - strong positive signal
    if re.search(r'\([mwfdx/]+\)', text_lower):
        signals["has_gender_notation"] = True
    
    # Job keywords - use word boundaries to avoid false positives
    # (e.g., 'intern' matching inside 'International')
    found_keywords = [
        kw for kw in JOB_TITLE_KEYWORDS 
        if re.search(rf'\b{re.escape(kw)}\b', text_lower)
    ]
    if found_keywords:
        signals["title_has_keywords"] = True
        signals["matched_keywords"] = found_keywords[:3]
    
    # Non-job words - negative signal
    found_non_job = [w for w in NON_JOB_WORDS if w in text_lower]
    if found_non_job:
        signals["has_non_job_words"] = True
        signals["non_job_words"] = found_non_job[:3]
        return False, signals
    
    # Company name patterns (with word boundaries)
    for pattern in COMPANY_NAME_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            signals["looks_like_company_name"] = True
            return False, signals
    
    # Looks like navigation
    if text_lower in ['home', 'back', 'next', 'previous', 'menu']:
        signals["looks_like_nav"] = True
        return False, signals
    
    # Final decision - require at least one strong signal
    # (proper_length alone is not enough)
    is_likely = (
        signals.get("has_gender_notation") or 
        signals.get("title_has_keywords")
    )
    
    return is_likely, signals
