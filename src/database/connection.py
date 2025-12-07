"""Database connection and initialization."""

import logging
import os
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

# Default database path in project data folder
DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "data" / "jobs.db"


def get_db_path() -> Path:
    """Get database file path.
    
    Can be overridden via JOBS_DB_PATH environment variable.
    """
    env_path = os.environ.get("JOBS_DB_PATH")
    if env_path:
        return Path(env_path)
    return DEFAULT_DB_PATH


async def init_database(db_path: Path | None = None) -> None:
    """Initialize database with schema.
    
    Creates tables if they don't exist.
    
    Args:
        db_path: Path to database file. If None, uses default.
    """
    if db_path is None:
        db_path = get_db_path()
    
    # Ensure data directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.debug(f"Initializing database at {db_path}")
    
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(SCHEMA)
        await db.commit()
        
        # Run migrations for existing databases
        await _run_migrations(db)
    
    logger.debug("Database initialized successfully")


async def _run_migrations(db) -> None:
    """Run database migrations for existing databases."""
    # Migration: Add description column to sites table if it doesn't exist
    cursor = await db.execute("PRAGMA table_info(sites)")
    columns = await cursor.fetchall()
    column_names = [col[1] for col in columns]
    
    if "description" not in column_names:
        logger.debug("Adding 'description' column to sites table")
        await db.execute("ALTER TABLE sites ADD COLUMN description TEXT")
        await db.commit()


SCHEMA = """
-- Sites (company domains)
CREATE TABLE IF NOT EXISTS sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT UNIQUE NOT NULL,
    name TEXT,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_scanned_at TIMESTAMP
);

-- Career page URLs (can be multiple per site)
CREATE TABLE IF NOT EXISTS career_urls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    platform TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    fail_count INTEGER DEFAULT 0,
    last_success_at TIMESTAMP,
    last_fail_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE,
    UNIQUE(site_id, url)
);

-- Cached jobs
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER NOT NULL,
    external_id TEXT,
    title TEXT NOT NULL,
    title_en TEXT,
    company TEXT,
    location TEXT,
    url TEXT,
    description TEXT,
    salary_from INTEGER,
    salary_to INTEGER,
    salary_currency TEXT,
    experience TEXT,
    employment_type TEXT,
    skills TEXT,
    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE
);

-- Unique constraint for job deduplication
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_unique 
ON jobs(site_id, title, location) 
WHERE location IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_unique_no_location 
ON jobs(site_id, title) 
WHERE location IS NULL;

-- Job history (changes log)
CREATE TABLE IF NOT EXISTS job_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    event TEXT NOT NULL,
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    details TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_sites_domain ON sites(domain);
CREATE INDEX IF NOT EXISTS idx_career_urls_site_id ON career_urls(site_id);
CREATE INDEX IF NOT EXISTS idx_jobs_site_id ON jobs(site_id);
CREATE INDEX IF NOT EXISTS idx_jobs_is_active ON jobs(is_active);
CREATE INDEX IF NOT EXISTS idx_job_history_job_id ON job_history(job_id);
"""




