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
    
    # Migration: Create llm_cache table if it doesn't exist
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='llm_cache'"
    )
    if not await cursor.fetchone():
        logger.debug("Creating 'llm_cache' table")
        await db.execute("""
            CREATE TABLE llm_cache (
                key TEXT PRIMARY KEY,
                namespace TEXT NOT NULL,
                value TEXT NOT NULL,
                model TEXT,
                ttl_seconds INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                hit_count INTEGER DEFAULT 0,
                tokens_saved INTEGER DEFAULT 0
            )
        """)
        await db.execute("CREATE INDEX idx_llm_cache_namespace ON llm_cache(namespace)")
        await db.execute("CREATE INDEX idx_llm_cache_expiry ON llm_cache(created_at, ttl_seconds)")
        await db.commit()
    
    # Migration: Add extraction_method column to jobs table if it doesn't exist
    cursor = await db.execute("PRAGMA table_info(jobs)")
    columns = await cursor.fetchall()
    job_column_names = [col[1] for col in columns]
    
    if "extraction_method" not in job_column_names:
        logger.debug("Adding 'extraction_method' column to jobs table")
        await db.execute("ALTER TABLE jobs ADD COLUMN extraction_method TEXT")
        await db.commit()
    
    if "extraction_details" not in job_column_names:
        logger.debug("Adding 'extraction_details' column to jobs table")
        await db.execute("ALTER TABLE jobs ADD COLUMN extraction_details TEXT")
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
    extraction_method TEXT,  -- "job_board:platform", "schema_org", "llm", "pdf_link", "api"
    extraction_details TEXT,  -- JSON: {confidence, model, source_url, attempts, ...}
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

-- LLM response cache (with different TTLs per operation type)
CREATE TABLE IF NOT EXISTS llm_cache (
    key TEXT PRIMARY KEY,
    namespace TEXT NOT NULL,
    value TEXT NOT NULL,
    model TEXT,
    ttl_seconds INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    hit_count INTEGER DEFAULT 0,
    tokens_saved INTEGER DEFAULT 0
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_sites_domain ON sites(domain);
CREATE INDEX IF NOT EXISTS idx_career_urls_site_id ON career_urls(site_id);
CREATE INDEX IF NOT EXISTS idx_jobs_site_id ON jobs(site_id);
CREATE INDEX IF NOT EXISTS idx_jobs_is_active ON jobs(is_active);
CREATE INDEX IF NOT EXISTS idx_job_history_job_id ON job_history(job_id);
CREATE INDEX IF NOT EXISTS idx_llm_cache_namespace ON llm_cache(namespace);
CREATE INDEX IF NOT EXISTS idx_llm_cache_expiry ON llm_cache(created_at, ttl_seconds);
"""




