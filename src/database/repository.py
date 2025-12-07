"""Database repository for CRUD operations."""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

from src.database.connection import get_db_path, init_database
from src.database.models import Site, CareerUrl, CachedJob, JobHistoryEvent, SyncResult
from src.models import Job

logger = logging.getLogger(__name__)


class JobRepository:
    """Repository for job-related database operations."""
    
    def __init__(self, db_path: Path | None = None):
        """Initialize repository.
        
        Args:
            db_path: Path to database file. If None, uses default.
        """
        self.db_path = db_path or get_db_path()
        self._initialized = False
        self._connection: Optional[aiosqlite.Connection] = None
    
    async def _ensure_initialized(self) -> None:
        """Ensure database is initialized."""
        if not self._initialized:
            await init_database(self.db_path)
            self._initialized = True
    
    async def _get_connection(self) -> aiosqlite.Connection:
        """Get or create database connection.
        
        Reuses single connection for the lifetime of the repository.
        """
        await self._ensure_initialized()
        if self._connection is None:
            self._connection = await aiosqlite.connect(self.db_path)
            self._connection.row_factory = aiosqlite.Row
        return self._connection
    
    async def close(self) -> None:
        """Close database connection."""
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
    
    # ==================== Sites ====================
    
    async def get_site_by_domain(self, domain: str) -> Optional[Site]:
        """Get site by domain.
        
        Args:
            domain: Site domain (e.g., "company.com")
            
        Returns:
            Site object or None if not found
        """
        db = await self._get_connection()
        cursor = await db.execute(
            "SELECT * FROM sites WHERE domain = ?",
            (domain,)
        )
        row = await cursor.fetchone()
        
        if row:
            return Site(
                id=row["id"],
                domain=row["domain"],
                name=row["name"],
                created_at=self._parse_datetime(row["created_at"]),
                last_scanned_at=self._parse_datetime(row["last_scanned_at"]),
            )
        return None
    
    async def create_site(self, domain: str, name: Optional[str] = None) -> Site:
        """Create new site record.
        
        Args:
            domain: Site domain
            name: Company name (optional)
            
        Returns:
            Created Site object
        """
        db = await self._get_connection()
        cursor = await db.execute(
            "INSERT INTO sites (domain, name) VALUES (?, ?)",
            (domain, name)
        )
        await db.commit()
        site_id = cursor.lastrowid
        
        return Site(
            id=site_id,
            domain=domain,
            name=name,
            created_at=datetime.now(),
            last_scanned_at=None,
        )
    
    async def get_or_create_site(self, domain: str, name: Optional[str] = None) -> Site:
        """Get existing site or create new one.
        
        Args:
            domain: Site domain
            name: Company name (used only if creating)
            
        Returns:
            Site object
        """
        site = await self.get_site_by_domain(domain)
        if site:
            return site
        return await self.create_site(domain, name)
    
    async def update_site_scanned(self, site_id: int) -> None:
        """Update site's last_scanned_at timestamp."""
        db = await self._get_connection()
        await db.execute(
            "UPDATE sites SET last_scanned_at = CURRENT_TIMESTAMP WHERE id = ?",
            (site_id,)
        )
        await db.commit()
    
    # ==================== Career URLs ====================
    
    async def get_career_urls(self, site_id: int, active_only: bool = True) -> list[CareerUrl]:
        """Get career URLs for a site.
        
        Args:
            site_id: Site ID
            active_only: Return only active URLs
            
        Returns:
            List of CareerUrl objects
        """
        db = await self._get_connection()
        query = "SELECT * FROM career_urls WHERE site_id = ?"
        if active_only:
            query += " AND is_active = TRUE"
        query += " ORDER BY last_success_at DESC NULLS LAST"
        
        cursor = await db.execute(query, (site_id,))
        rows = await cursor.fetchall()
        
        return [
            CareerUrl(
                id=row["id"],
                site_id=row["site_id"],
                url=row["url"],
                platform=row["platform"],
                is_active=bool(row["is_active"]),
                fail_count=row["fail_count"],
                last_success_at=self._parse_datetime(row["last_success_at"]),
                last_fail_at=self._parse_datetime(row["last_fail_at"]),
                created_at=self._parse_datetime(row["created_at"]),
            )
            for row in rows
        ]
    
    async def add_career_url(
        self, 
        site_id: int, 
        url: str, 
        platform: Optional[str] = None
    ) -> CareerUrl:
        """Add career URL for a site.
        
        Args:
            site_id: Site ID
            url: Career page URL
            platform: Job board platform (e.g., "greenhouse", "lever")
            
        Returns:
            Created CareerUrl object
        """
        db = await self._get_connection()
        # Try to insert, if exists - update to active
        cursor = await db.execute(
            """
            INSERT INTO career_urls (site_id, url, platform)
            VALUES (?, ?, ?)
            ON CONFLICT(site_id, url) DO UPDATE SET
                is_active = TRUE,
                fail_count = 0,
                platform = COALESCE(excluded.platform, platform)
            RETURNING *
            """,
            (site_id, url, platform)
        )
        row = await cursor.fetchone()
        await db.commit()
        
        return CareerUrl(
            id=row["id"],
            site_id=row["site_id"],
            url=row["url"],
            platform=row["platform"],
            is_active=True,
            fail_count=0,
            last_success_at=self._parse_datetime(row["last_success_at"]),
            last_fail_at=self._parse_datetime(row["last_fail_at"]),
            created_at=self._parse_datetime(row["created_at"]),
        )
    
    async def mark_url_success(self, url_id: int) -> None:
        """Mark career URL as successful."""
        db = await self._get_connection()
        await db.execute(
            """
            UPDATE career_urls 
            SET last_success_at = CURRENT_TIMESTAMP, 
                fail_count = 0,
                is_active = TRUE
            WHERE id = ?
            """,
            (url_id,)
        )
        await db.commit()
    
    async def mark_url_failed(self, url_id: int, max_failures: int = 3) -> bool:
        """Mark career URL as failed.
        
        Args:
            url_id: Career URL ID
            max_failures: Max failures before marking inactive
            
        Returns:
            True if URL is now inactive (exceeded max failures)
        """
        db = await self._get_connection()
        # Increment fail count
        await db.execute(
            """
            UPDATE career_urls 
            SET fail_count = fail_count + 1,
                last_fail_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (url_id,)
        )
        
        # Check if exceeded max failures
        cursor = await db.execute(
            "SELECT fail_count FROM career_urls WHERE id = ?",
            (url_id,)
        )
        row = await cursor.fetchone()
        
        if row and row["fail_count"] >= max_failures:
            await db.execute(
                "UPDATE career_urls SET is_active = FALSE WHERE id = ?",
                (url_id,)
            )
            await db.commit()
            logger.warning(f"Career URL {url_id} marked as inactive after {max_failures} failures")
            return True
        
        await db.commit()
        return False
    
    # ==================== Jobs ====================
    
    async def get_active_jobs(self, site_id: int) -> list[CachedJob]:
        """Get all active jobs for a site.
        
        Args:
            site_id: Site ID
            
        Returns:
            List of CachedJob objects
        """
        db = await self._get_connection()
        cursor = await db.execute(
            "SELECT * FROM jobs WHERE site_id = ? AND is_active = TRUE",
            (site_id,)
        )
        rows = await cursor.fetchall()
        
        return [self._row_to_cached_job(row) for row in rows]
    
    async def get_previous_job_count(self, site_id: int) -> int:
        """Get count of previously active jobs (including currently inactive).
        
        Used to detect suspicious situations where all jobs disappear.
        
        Args:
            site_id: Site ID
            
        Returns:
            Total job count ever seen for this site
        """
        db = await self._get_connection()
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM jobs WHERE site_id = ?",
            (site_id,)
        )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0
    
    async def sync_jobs(self, site_id: int, current_jobs: list[Job]) -> SyncResult:
        """Synchronize jobs with database.
        
        Compares current jobs with stored ones:
        - Marks missing jobs as inactive (removed)
        - Adds new jobs
        - Reactivates jobs that reappeared
        - Records history for all changes
        
        Args:
            site_id: Site ID
            current_jobs: List of currently found jobs
            
        Returns:
            SyncResult with new, removed, and reactivated jobs
        """
        result = SyncResult(total_jobs=len(current_jobs))
        
        db = await self._get_connection()
        # Get all jobs for site (including inactive)
        cursor = await db.execute(
            "SELECT * FROM jobs WHERE site_id = ?",
            (site_id,)
        )
        existing_rows = await cursor.fetchall()
        
        # Check if this is the first scan (no existing jobs)
        result.is_first_scan = len(existing_rows) == 0
        
        # Build lookup by (title, location)
        existing_jobs = {}
        for row in existing_rows:
            key = self._job_key(row["title"], row["location"])
            existing_jobs[key] = self._row_to_cached_job(row)
        
        # Track which existing jobs we've seen
        seen_keys = set()
        
        for job in current_jobs:
            key = self._job_key(job.title, job.location)
            seen_keys.add(key)
            
            if key in existing_jobs:
                existing = existing_jobs[key]
                
                # Update last_seen_at
                await db.execute(
                    "UPDATE jobs SET last_seen_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (existing.id,)
                )
                
                if not existing.is_active:
                    # Job reappeared - reactivate
                    await db.execute(
                        "UPDATE jobs SET is_active = TRUE WHERE id = ?",
                        (existing.id,)
                    )
                    await self._add_history_event(
                        db, existing.id, "reactivated", 
                        f"Job reappeared after being removed"
                    )
                    result.reactivated_jobs.append(job)
                    logger.debug(f"Reactivated job: {job.title}")
            else:
                # New job - insert
                job_id = await self._insert_job(db, site_id, job)
                await self._add_history_event(db, job_id, "added")
                result.new_jobs.append(job)
                logger.debug(f"New job: {job.title}")
        
        # Mark unseen active jobs as removed
        for key, existing in existing_jobs.items():
            if key not in seen_keys and existing.is_active:
                await db.execute(
                    "UPDATE jobs SET is_active = FALSE WHERE id = ?",
                    (existing.id,)
                )
                await self._add_history_event(
                    db, existing.id, "removed",
                    f"Job no longer found on site"
                )
                # Convert to Job for result
                removed_job = Job(
                    id=f"cached-{existing.id}",
                    title=existing.title,
                    company=existing.company or "",
                    location=existing.location or "Unknown",
                    url=existing.url or "",
                    source=f"cached:{site_id}",
                    title_en=existing.title_en,
                )
                result.removed_jobs.append(removed_job)
                logger.debug(f"Removed job: {existing.title}")
        
        await db.commit()
        
        return result
    
    async def _insert_job(self, db: aiosqlite.Connection, site_id: int, job: Job) -> int:
        """Insert new job into database."""
        skills_json = json.dumps(job.skills) if job.skills else None
        
        cursor = await db.execute(
            """
            INSERT INTO jobs (
                site_id, external_id, title, title_en, company, location,
                url, description, salary_from, salary_to, salary_currency,
                experience, employment_type, skills
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                site_id, job.id, job.title, job.title_en, job.company, job.location,
                job.url, job.description, job.salary_from, job.salary_to,
                job.salary_currency, job.experience, job.employment_type, skills_json
            )
        )
        return cursor.lastrowid
    
    async def _add_history_event(
        self, 
        db: aiosqlite.Connection, 
        job_id: int, 
        event: str,
        details: Optional[str] = None
    ) -> None:
        """Add job history event."""
        await db.execute(
            "INSERT INTO job_history (job_id, event, details) VALUES (?, ?, ?)",
            (job_id, event, details)
        )
    
    # ==================== History ====================
    
    async def get_job_history(
        self, 
        site_id: Optional[int] = None,
        limit: int = 100
    ) -> list[dict]:
        """Get job history events.
        
        Args:
            site_id: Filter by site (optional)
            limit: Max events to return
            
        Returns:
            List of history events with job details
        """
        db = await self._get_connection()
        if site_id:
            cursor = await db.execute(
                """
                SELECT jh.*, j.title, j.company, j.location, s.domain
                FROM job_history jh
                JOIN jobs j ON jh.job_id = j.id
                JOIN sites s ON j.site_id = s.id
                WHERE j.site_id = ?
                ORDER BY jh.changed_at DESC
                LIMIT ?
                """,
                (site_id, limit)
            )
        else:
            cursor = await db.execute(
                """
                SELECT jh.*, j.title, j.company, j.location, s.domain
                FROM job_history jh
                JOIN jobs j ON jh.job_id = j.id
                JOIN sites s ON j.site_id = s.id
                ORDER BY jh.changed_at DESC
                LIMIT ?
                """,
                (limit,)
            )
        
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    
    # ==================== Utilities ====================
    
    def _job_key(self, title: str, location: Optional[str]) -> tuple:
        """Create unique key for job comparison.
        
        Uses separate normalization for title and location:
        - Title: removes job posting suffixes, gender notation
        - Location: removes country suffixes, employment type indicators
        """
        title_norm = self._normalize_string(title)
        location_norm = self._normalize_location(location) if location else ""
        return (title_norm, location_norm)
    
    def _normalize_string(self, s: str) -> str:
        """Normalize string for comparison.
        
        Performs robust normalization to avoid false positives in job comparison:
        - Lowercases and strips whitespace
        - Removes common suffixes like "Job advert", "Stellenanzeige"
        - Removes gender notation (m/w/d), (f/d/m), etc.
        - Normalizes whitespace
        """
        result = s.lower().strip()
        
        # Remove common job posting suffixes that cause false positives
        # These are often added by job boards but aren't part of the actual title
        suffixes_to_remove = [
            r'\s*job\s*advert\s*$',
            r'\s*job\s*posting\s*$',
            r'\s*stellenanzeige\s*$',
            r'\s*job\s*offer\s*$',
            r'\s*vacancy\s*$',
            r'\s*apply\s*now\s*$',
        ]
        for pattern in suffixes_to_remove:
            result = re.sub(pattern, '', result, flags=re.IGNORECASE)
        
        # Remove gender notation: (m/w/d), (f/d/m), etc.
        result = re.sub(r'\s*\([mwfdx/]+\)\s*', ' ', result)
        # Also without parentheses at end: "Title m/w/d"
        result = re.sub(r'\s+[mwfdx]/[mwfdx](/[mwfdx])?\s*$', '', result)
        
        # Normalize whitespace
        result = re.sub(r'\s+', ' ', result).strip()
        
        return result
    
    def _normalize_location(self, location: str) -> str:
        """Normalize location for comparison.
        
        Handles variations like:
        - "Erftstadt, Deutschland" vs "Erftstadt"
        - "Berlin, Germany" vs "Berlin"
        - "Remote, Deutschland" vs "Remote"
        """
        result = location.lower().strip()
        
        # Remove country suffixes (with comma or space)
        countries_to_remove = [
            r',?\s*deutschland\s*$',
            r',?\s*germany\s*$',
            r',?\s*österreich\s*$',
            r',?\s*austria\s*$',
            r',?\s*schweiz\s*$',
            r',?\s*switzerland\s*$',
            r',?\s*united\s*kingdom\s*$',
            r',?\s*uk\s*$',
            r',?\s*usa\s*$',
            r',?\s*united\s*states\s*$',
            r',?\s*netherlands\s*$',
            r',?\s*france\s*$',
            r',?\s*spain\s*$',
            r',?\s*italy\s*$',
            r',?\s*poland\s*$',
        ]
        for pattern in countries_to_remove:
            result = re.sub(pattern, '', result, flags=re.IGNORECASE)
        
        # Remove employment type suffixes often mixed with location
        employment_suffixes = [
            r',?\s*vollzeit\s*$',
            r',?\s*teilzeit\s*$',
            r',?\s*full[\s-]*time\s*$',
            r',?\s*part[\s-]*time\s*$',
            r',?\s*remote\s*$',  # If at end after city
            r',?\s*hybrid\s*$',
            r',?\s*inkl\.?\s*home\s*office\s*$',
        ]
        for pattern in employment_suffixes:
            result = re.sub(pattern, '', result, flags=re.IGNORECASE)
        
        # Normalize whitespace and remove trailing commas
        result = re.sub(r'\s+', ' ', result).strip()
        result = result.rstrip(',').strip()
        
        return result
    
    def _parse_datetime(self, value) -> Optional[datetime]:
        """Parse datetime from database value."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None
    
    def _row_to_cached_job(self, row) -> CachedJob:
        """Convert database row to CachedJob."""
        return CachedJob(
            id=row["id"],
            site_id=row["site_id"],
            external_id=row["external_id"],
            title=row["title"],
            title_en=row["title_en"],
            company=row["company"],
            location=row["location"],
            url=row["url"],
            description=row["description"],
            salary_from=row["salary_from"],
            salary_to=row["salary_to"],
            salary_currency=row["salary_currency"],
            experience=row["experience"],
            employment_type=row["employment_type"],
            skills=row["skills"],
            first_seen_at=self._parse_datetime(row["first_seen_at"]),
            last_seen_at=self._parse_datetime(row["last_seen_at"]),
            is_active=bool(row["is_active"]),
        )


