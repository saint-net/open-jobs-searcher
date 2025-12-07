"""Database models (dataclasses)."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


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


