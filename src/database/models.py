"""Database models (dataclasses)."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ExtractionMethod(str, Enum):
    """Method used to extract job from page.
    
    Stored in DB to track extraction quality and enable analytics.
    """
    JOB_BOARD = "job_board"      # Known platform parser (Greenhouse, Lever, etc.)
    SCHEMA_ORG = "schema_org"    # schema.org/JobPosting structured data
    LLM = "llm"                  # LLM-based extraction
    PDF_LINK = "pdf_link"        # Extracted from PDF/document link
    API = "api"                  # Direct API (HeadHunter, StepStone, etc.)


@dataclass
class Site:
    """Company site record."""
    
    id: int
    domain: str
    name: Optional[str] = None
    description: Optional[str] = None
    created_at: Optional[datetime] = None
    last_scanned_at: Optional[datetime] = None


@dataclass
class CareerUrl:
    """Career page URL record."""
    
    id: int
    site_id: int
    url: str
    platform: Optional[str] = None
    is_active: bool = True
    fail_count: int = 0
    last_success_at: Optional[datetime] = None
    last_fail_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


@dataclass
class CachedJob:
    """Cached job record from database."""
    
    id: int
    site_id: int
    title: str
    external_id: Optional[str] = None
    title_en: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    url: Optional[str] = None
    description: Optional[str] = None
    salary_from: Optional[int] = None
    salary_to: Optional[int] = None
    salary_currency: Optional[str] = None
    experience: Optional[str] = None
    employment_type: Optional[str] = None
    skills: Optional[str] = None  # JSON string
    extraction_method: Optional[str] = None  # ExtractionMethod value or "job_board:platform"
    extraction_details: Optional[str] = None  # JSON: {confidence, model, source_url, attempts, ...}
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    is_active: bool = True


@dataclass
class JobHistoryEvent:
    """Job history event record."""
    
    id: int
    job_id: int
    event: str  # "added", "removed", "updated", "reactivated"
    changed_at: Optional[datetime] = None
    details: Optional[str] = None  # JSON string


@dataclass
class SyncResult:
    """Result of job synchronization."""
    
    total_jobs: int = 0
    new_jobs: list = field(default_factory=list)
    removed_jobs: list = field(default_factory=list)
    reactivated_jobs: list = field(default_factory=list)
    is_first_scan: bool = False  # True if this is the first scan for this site
    
    @property
    def has_changes(self) -> bool:
        """Check if there are any changes."""
        return bool(self.new_jobs or self.removed_jobs or self.reactivated_jobs)


@dataclass
class LLMCacheEntry:
    """LLM response cache entry."""
    
    key: str
    namespace: str
    value: str
    ttl_seconds: int
    model: Optional[str] = None
    created_at: Optional[datetime] = None
    hit_count: int = 0
    tokens_saved: int = 0
    
    def is_expired(self) -> bool:
        """Check if cache entry has expired."""
        if not self.created_at:
            return True
        from datetime import timedelta
        expiry = self.created_at + timedelta(seconds=self.ttl_seconds)
        return datetime.now() > expiry


@dataclass
class LLMCacheStats:
    """Statistics for LLM cache usage."""
    
    hits: int = 0
    misses: int = 0
    total_tokens_saved: int = 0
    
    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0
    
    @property
    def estimated_cost_saved(self) -> float:
        """Estimate cost saved (rough approximation: $0.01 per 1K tokens)."""
        return self.total_tokens_saved * 0.00001


