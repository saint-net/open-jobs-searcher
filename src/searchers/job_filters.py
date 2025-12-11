"""Job filtering and normalization utilities.

Extracted from WebsiteSearcher for SRP compliance.
"""

import logging
import re
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)


def normalize_title(title: str) -> str:
    """Normalize job title for deduplication.
    
    Removes gender notation and normalizes whitespace.
    """
    result = title.lower().strip()
    
    # Remove gender notation: (m/w/d), (f/d/m), etc.
    result = re.sub(r'\s*\([mwfdx/]+\)\s*', ' ', result)
    result = re.sub(r'\s+[mwfdx]/[mwfdx](/[mwfdx])?\s*$', '', result)
    
    # Normalize whitespace
    result = re.sub(r'\s+', ' ', result).strip()
    
    return result


def normalize_location(location: str) -> str:
    """Normalize location for deduplication.
    
    Removes country suffixes and employment type indicators.
    """
    result = location.lower().strip()
    
    # Remove country suffixes
    countries = [
        r',?\s*deutschland\s*$',
        r',?\s*germany\s*$',
        r',?\s*österreich\s*$',
        r',?\s*austria\s*$',
        r',?\s*schweiz\s*$',
        r',?\s*switzerland\s*$',
    ]
    for pattern in countries:
        result = re.sub(pattern, '', result, flags=re.IGNORECASE)
    
    # Remove employment type suffixes
    employment = [
        r',?\s*vollzeit\s*$',
        r',?\s*teilzeit\s*$',
        r',?\s*inkl\.?\s*home\s*office\s*$',
    ]
    for pattern in employment:
        result = re.sub(pattern, '', result, flags=re.IGNORECASE)
    
    # Normalize whitespace
    result = re.sub(r'\s+', ' ', result).strip()
    result = result.rstrip(',').strip()
    
    return result


def filter_jobs_by_search_query(jobs_data: list[dict], url: str) -> list[dict]:
    """Filter jobs to only those matching the search query in URL.
    
    When navigating to a job board search page (e.g., job.deloitte.com/search?search=27pilots),
    the page may show both search results AND recommended/featured jobs.
    This method filters to keep only jobs that match the search query.
    
    Args:
        jobs_data: List of job dictionaries
        url: Current page URL
        
    Returns:
        Filtered list of jobs matching the search query
    """
    if not jobs_data:
        return jobs_data
    
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    
    # Check for common search parameter names
    search_term = None
    for param_name in ['search', 'q', 'query', 'keyword', 'keywords']:
        if param_name in query_params:
            search_term = query_params[param_name][0].lower()
            break
    
    if not search_term:
        return jobs_data
    
    # Filter jobs that contain the search term in their title
    filtered = []
    for job in jobs_data:
        title = job.get('title', '').lower()
        if search_term in title:
            filtered.append(job)
    
    if filtered:
        logger.debug(f"Filtered jobs by search term '{search_term}': {len(jobs_data)} -> {len(filtered)}")
        return filtered
    
    # If no jobs match, return all (search might be for company name/tag not in title)
    logger.debug(f"No jobs matched search term '{search_term}', keeping all {len(jobs_data)}")
    return jobs_data


def filter_jobs_by_source_company(jobs_data: list[dict], source_url: str) -> list[dict]:
    """Filter jobs to only those related to the source company.
    
    When navigating from a company website (e.g., 2rsoftware.de) to a 
    multi-company career portal (e.g., karriere.synqony.com), filter
    jobs to only show positions from the original company.
    
    Args:
        jobs_data: List of job dictionaries
        source_url: Original company website URL
        
    Returns:
        Filtered list of jobs (or all jobs if no matches found)
    """
    if not jobs_data:
        return jobs_data
    
    # Extract company identifier from source URL
    parsed = urlparse(source_url)
    domain = parsed.netloc.replace('www.', '')
    
    # Get company name variants from domain
    # e.g., "2rsoftware.de" -> ["2rsoftware", "2r software", "2r"]
    company_base = domain.split('.')[0]  # "2rsoftware"
    company_variants = [
        company_base.lower(),  # "2rsoftware"
        company_base.lower().replace('-', ' '),  # for domains like "my-company"
    ]
    
    # Add common variations for company names
    # Split camelCase or numbers: "2rsoftware" -> "2r software", "2r"
    # Also handle "XYZcompany" -> "xyz company", "xyz"
    # Try to split at number-letter boundary: "2rsoftware" -> "2r", "software"
    match = re.match(r'^(\d+[a-z]?)(.*)$', company_base.lower())
    if match:
        prefix = match.group(1)  # "2r"
        suffix = match.group(2)  # "software"
        company_variants.append(f"{prefix} {suffix}")  # "2r software"
        company_variants.append(prefix)  # "2r"
    
    # Filter jobs that mention the source company
    filtered = []
    for job in jobs_data:
        job_text = (
            job.get('title', '') + ' ' + 
            job.get('location', '') + ' ' +
            job.get('description', '') + ' ' +
            job.get('company', '')  # Company name from job card
        ).lower()
        
        # Check if any company variant is mentioned
        for variant in company_variants:
            if variant in job_text:
                filtered.append(job)
                break
    
    if filtered:
        logger.debug(f"Filtered jobs by source company: {len(jobs_data)} -> {len(filtered)}")
        return filtered
    
    # If no matches, return all jobs (company name might not be in job text)
    logger.debug(f"No jobs matched source company variants {company_variants}, keeping all {len(jobs_data)}")
    return jobs_data

