"""Career page URL discovery utilities."""

import logging
import re
import xml.etree.ElementTree as ET
from typing import Optional
from urllib.parse import urljoin, urlparse
import tldextract

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


# Career-related subdomains to check
CAREER_SUBDOMAINS = [
    'jobs',
    'careers',
    'karriere',
    'career',
    'stellen',
    'join',
    'work',
    'hiring',
]

# URL patterns for career pages
CAREER_PATTERNS = [
    # English
    r'/career[s]?',
    r'/job[s]?',
    r'/vacanc(?:y|ies)',
    r'/opening[s]?',
    r'/work[-_]?with[-_]?us',
    r'/join[-_]?us',
    r'/join[-_]?our[-_]?team',
    r'/hiring',
    r'/positions',
    r'/people[-_]?(?:and[-_]?)?jobs',
    # German (DE/AT)
    r'/karriere',
    r'/stellen',
    r'/stellenangebote',
    r'/jobangebote',
    r'/arbeiten',
    r'/bewerben',
    r'/offene[-_]?stellen',
    # Russian
    r'/вакансии',
    r'/карьера',
    r'/работа',
]


class CareerUrlDiscovery:
    """Discovers career page URLs from websites."""

    def __init__(self, http_client):
        """
        Initialize URL discovery.
        
        Args:
            http_client: HTTP client with fetch method
        """
        self.http_client = http_client

    async def discover_career_subdomain(self, base_url: str) -> Optional[str]:
        """Discover career-related subdomains (e.g., jobs.example.com).
        
        Many companies host their job portal on a separate subdomain like:
        - jobs.example.com
        - careers.example.com
        - karriere.example.com
        
        Args:
            base_url: Base URL of the website
            
        Returns:
            Career subdomain URL if found and reachable
        """
        # Extract domain parts
        extracted = tldextract.extract(base_url)
        domain = extracted.domain
        suffix = extracted.suffix
        
        if not domain or not suffix:
            return None
        
        # Determine protocol from original URL
        parsed = urlparse(base_url)
        protocol = parsed.scheme or 'https'
        
        # Build base domain without subdomain (e.g., "3spin-learning.com")
        base_domain = f"{domain}.{suffix}"
        
        # Try each career subdomain
        for subdomain in CAREER_SUBDOMAINS:
            subdomain_url = f"{protocol}://{subdomain}.{base_domain}"
            try:
                # check_domain_available returns None on success, raises on failure
                await self.http_client.check_domain_available(subdomain_url)
                logger.debug(f"Found career subdomain: {subdomain_url}")
                return subdomain_url
            except Exception as e:
                logger.debug(f"Subdomain {subdomain_url} not available: {e}")
                continue
        
        return None

    async def find_from_sitemap(self, base_url: str, llm_fallback=None) -> Optional[str]:
        """Find careers page URL from sitemap.xml.
        
        Args:
            base_url: Base URL of the website
            llm_fallback: Optional LLM provider for analyzing sitemap URLs
            
        Returns:
            Career page URL if found
        """
        base = base_url.rstrip('/')
        
        # Possible sitemap locations
        sitemap_urls = [
            f"{base}/sitemap.xml",
            f"{base}/sitemap_index.xml",
            f"{base}/sitemap-index.xml",
        ]
        
        all_urls = []  # Collect URLs for LLM fallback
        
        for sitemap_url in sitemap_urls:
            try:
                response = await self.http_client.fetch_response(sitemap_url)
                if response is None:
                    continue
                    
                xml_content = response.text.strip()
                
                # Quick check if content looks like XML (not HTML)
                if not xml_content or not xml_content.startswith('<?xml') and not xml_content.startswith('<urlset') and not xml_content.startswith('<sitemapindex'):
                    logger.debug(f"Sitemap {sitemap_url} returned non-XML content (likely HTML 404 page)")
                    continue
                
                # Parse XML
                root = ET.fromstring(xml_content)
                
                # Detect namespace from root tag
                root_ns = root.tag.split('}')[0].strip('{') if '}' in root.tag else ''
                ns = {'sm': root_ns} if root_ns else {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
                
                urls = []
                
                # Check if this is a sitemap index
                sitemaps = root.findall('.//sm:sitemap/sm:loc', ns)
                if sitemaps:
                    # Prioritize sitemaps: career-related first, then page/general
                    priority_sitemaps = []
                    page_sitemaps = []
                    
                    for sitemap in sitemaps:
                        loc = sitemap.text
                        if not loc:
                            continue
                        if any(re.search(p, loc, re.IGNORECASE) for p in CAREER_PATTERNS):
                            priority_sitemaps.append(loc)
                        elif 'page' in loc.lower():
                            page_sitemaps.append(loc)
                    
                    # Load priority sitemaps
                    for sitemap_loc in priority_sitemaps + page_sitemaps:
                        nested_urls = await self._parse_sitemap_urls(sitemap_loc)
                        all_urls.extend(nested_urls)
                
                # Find page URLs
                for url_elem in root.findall('.//sm:url/sm:loc', ns):
                    if url_elem.text:
                        urls.append(url_elem.text)
                
                # Try without namespace
                if not urls:
                    for url_elem in root.findall('.//url/loc'):
                        if url_elem.text:
                            urls.append(url_elem.text)
                
                all_urls.extend(urls)
                            
            except ET.ParseError as e:
                logger.debug(f"XML parse error for {sitemap_url}: {e}")
                continue
        
        # Find all URLs matching career patterns
        matching_urls = []
        for page_url in all_urls:
            for pattern in CAREER_PATTERNS:
                if re.search(pattern, page_url, re.IGNORECASE):
                    matching_urls.append(page_url)
                    break
        
        if matching_urls:
            best_url = self._select_best_careers_url(matching_urls)
            logger.debug(f"Found careers URL in sitemap: {best_url} (from {len(matching_urls)} matches)")
            return best_url
        
        # Fallback: use LLM to analyze sitemap URLs
        if all_urls and llm_fallback:
            logger.debug(f"Using LLM to analyze {len(all_urls)} URLs from sitemap")
            return await llm_fallback.find_careers_url_from_sitemap(all_urls, base_url)
        
        return None

    async def _parse_sitemap_urls(self, sitemap_url: str) -> list[str]:
        """Parse URLs from a single sitemap file."""
        urls = []
        try:
            response = await self.http_client.fetch_response(sitemap_url)
            if response is None:
                return urls
            
            xml_content = response.text.strip()
            
            # Quick check if content looks like XML (not HTML)
            if not xml_content or not xml_content.startswith('<?xml') and not xml_content.startswith('<urlset') and not xml_content.startswith('<sitemapindex'):
                logger.debug(f"Nested sitemap {sitemap_url} returned non-XML content")
                return urls
                
            root = ET.fromstring(xml_content)
            
            # Detect namespace
            root_ns = root.tag.split('}')[0].strip('{') if '}' in root.tag else ''
            ns = {'sm': root_ns} if root_ns else {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
            
            # Extract URLs
            for url_elem in root.findall('.//sm:url/sm:loc', ns):
                if url_elem.text:
                    urls.append(url_elem.text)
            
            # Try without namespace
            if not urls:
                for url_elem in root.findall('.//url/loc'):
                    if url_elem.text:
                        urls.append(url_elem.text)
                        
        except (ET.ParseError, Exception) as e:
            logger.debug(f"Failed to parse sitemap {sitemap_url}: {e}")
        
        return urls

    def _select_best_careers_url(self, urls: list[str]) -> str:
        """Select the best careers page URL from a list of candidates."""
        # Job listing page endings (most specific - actual job lists)
        job_listing_endings = [
            '/jobs', '/jobs.html', '/job', '/job.html',
            '/vacancies', '/vacancies.html', '/vacancy', '/vacancy.html',
            '/openings', '/openings.html', '/opening', '/opening.html',
            '/careers', '/careers.html',
            '/stellenangebote', '/stellenangebote.html',
            '/offene-stellen', '/offene-stellen.html',
            '/stellen', '/stellen.html',
            '/вакансии', '/вакансии.html',
        ]
        
        # General careers section endings (parent pages)
        general_careers_endings = [
            '/career', '/career.html',
            '/karriere', '/karriere.html',
            '/people-jobs', '/people-jobs.html',
            '/people-and-jobs', '/people-and-jobs.html',
            '/карьера', '/карьера.html',
            '/работа', '/работа.html',
        ]
        
        def score_url(url: str) -> tuple:
            """Score URL: lower is better."""
            path = urlparse(url).path.rstrip('/')
            path_normalized = path.replace('.html', '')
            segments = [s for s in path.split('/') if s]
            
            # Priority 0: URL ends with job listing pattern
            for idx, ending in enumerate(job_listing_endings):
                ending_normalized = ending.replace('.html', '')
                if path.endswith(ending) or path_normalized.endswith(ending_normalized):
                    return (0, idx, len(segments), len(url))
            
            # Priority 1: URL ends with general careers pattern
            for idx, ending in enumerate(general_careers_endings):
                ending_normalized = ending.replace('.html', '')
                if path.endswith(ending) or path_normalized.endswith(ending_normalized):
                    return (1, idx, len(segments), len(url))
            
            # Priority 2: URL contains career pattern with short slug
            last_segment = segments[-1] if segments else ''
            if len(last_segment) < 30:
                return (2, 0, len(segments), len(url))
            
            # Priority 3: Long slugs (specific job pages)
            return (3, 0, len(segments), len(url))
        
        return min(urls, key=score_url)

    def find_from_html_heuristic(self, html: str, base_url: str) -> Optional[str]:
        """Heuristic search for careers page link in HTML."""
        soup = BeautifulSoup(html, 'lxml')
        
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            text = link.get_text(strip=True).lower()
            
            # Check URL
            for pattern in CAREER_PATTERNS:
                if re.search(pattern, href, re.IGNORECASE):
                    return urljoin(base_url, href)
            
            # Check link text
            career_keywords = [
                # English
                'career', 'careers', 'jobs', 'vacancies', 'openings',
                'join us', 'work with us', 'we\'re hiring',
                # German
                'karriere', 'stellen', 'stellenangebote', 'jobangebote',
                'offene stellen', 'arbeiten bei uns', 'jetzt bewerben',
                # Russian
                'вакансии', 'карьера', 'работа у нас', 'присоединяйся',
            ]
            for keyword in career_keywords:
                if keyword in text:
                    return urljoin(base_url, href)
        
        return None

    def generate_alternative_urls(self, base_url: str) -> list[str]:
        """Generate alternative URLs for careers page."""
        base = base_url.rstrip('/')
        return [
            # English (with .html variants for static sites)
            f"{base}/careers",
            f"{base}/careers.html",
            f"{base}/jobs",
            f"{base}/jobs.html",
            f"{base}/vacancies",
            f"{base}/vacancies.html",
            f"{base}/career",
            f"{base}/career.html",
            f"{base}/join",
            f"{base}/team",
            f"{base}/about/careers",
            f"{base}/about-us/careers",
            f"{base}/company/careers",
            f"{base}/en/careers",
            # German (with .html variants)
            f"{base}/karriere",
            f"{base}/karriere.html",
            f"{base}/stellen",
            f"{base}/stellen.html",
            f"{base}/stellenangebote",
            f"{base}/stellenangebote.html",
            f"{base}/offene-stellen",
            f"{base}/offene-stellen.html",
            f"{base}/de/karriere",
            f"{base}/ueber-uns/karriere",
            f"{base}/unternehmen/karriere",
            f"{base}/jobs-karriere",
            f"{base}/people-jobs",
            f"{base}/people-jobs/offene-stellen",
            f"{base}/people-and-jobs",
            # Russian
            f"{base}/ru/careers",
            f"{base}/o-kompanii/vakansii",
            f"{base}/company/vacancies",
        ]

    async def fetch_all_sitemap_urls(self, base_url: str, max_urls: int = 300) -> list[str]:
        """Fetch all URLs from sitemap.xml (checking robots.txt first).
        
        Unlike find_from_sitemap, this returns ALL URLs without filtering.
        Useful for LLM analysis of the entire sitemap.
        
        Args:
            base_url: Base URL of the website
            max_urls: Maximum number of URLs to return
            
        Returns:
            List of all URLs from sitemap
        """
        base = base_url.rstrip('/')
        all_urls = []
        
        # 1. Try to find sitemap location in robots.txt
        sitemap_locations = []
        try:
            robots_txt = await self.http_client.fetch(f"{base}/robots.txt")
            if robots_txt:
                for line in robots_txt.split('\n'):
                    line = line.strip()
                    if line.lower().startswith('sitemap:'):
                        sitemap_url = line.split(':', 1)[1].strip()
                        sitemap_locations.append(sitemap_url)
                        logger.debug(f"Found sitemap in robots.txt: {sitemap_url}")
        except Exception as e:
            logger.debug(f"robots.txt check failed: {e}")
        
        # 2. Add standard locations as fallback
        standard_locations = [
            f"{base}/sitemap.xml",
            f"{base}/sitemap_index.xml",
        ]
        for loc in standard_locations:
            if loc not in sitemap_locations:
                sitemap_locations.append(loc)
        
        # 3. Parse sitemaps (try each location)
        for sitemap_url in sitemap_locations[:3]:  # Limit to 3 sitemaps
            try:
                response = await self.http_client.fetch(sitemap_url)
                if not response:
                    continue
                
                content = response.strip()
                if not content.startswith('<?xml') and not content.startswith('<'):
                    logger.debug(f"Sitemap {sitemap_url} is not XML")
                    continue
                
                root = ET.fromstring(content)
                
                # Check if this is a sitemap index
                ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
                nested_sitemaps = root.findall('.//sm:sitemap/sm:loc', ns)
                if not nested_sitemaps:
                    nested_sitemaps = root.findall('.//sitemap/loc')
                
                if nested_sitemaps:
                    # Parse nested sitemaps
                    for nested in nested_sitemaps[:2]:
                        if nested.text:
                            nested_urls = await self._parse_sitemap_urls(nested.text)
                            all_urls.extend(nested_urls)
                            if len(all_urls) >= max_urls:
                                break
                else:
                    # Direct sitemap with URLs
                    for elem in root.iter():
                        if elem.tag.endswith('loc') and elem.text:
                            all_urls.append(elem.text)
                
                if all_urls:
                    logger.debug(f"Found {len(all_urls)} URLs from sitemap(s)")
                    break
                    
            except ET.ParseError as e:
                logger.debug(f"XML parse error for {sitemap_url}: {e}")
            except Exception as e:
                logger.debug(f"Sitemap {sitemap_url} failed: {e}")
        
        return all_urls[:max_urls]

    def generate_url_variants(self, url: str) -> list[str]:
        """Generate plural/singular variants of a careers URL.
        
        If sitemap contains job.html, also try jobs.html and vice versa.
        """
        variants = [url]  # Original URL first
        
        # Singular -> plural mappings
        singular_to_plural = {
            '/job.html': '/jobs.html',
            '/job': '/jobs',
            '/vacancy.html': '/vacancies.html',
            '/vacancy': '/vacancies',
            '/opening.html': '/openings.html',
            '/opening': '/openings',
            '/career.html': '/careers.html',
            '/career': '/careers',
            '/stelle.html': '/stellen.html',
            '/stelle': '/stellen',
        }
        
        parsed = urlparse(url)
        path = parsed.path
        
        # Try singular -> plural
        for singular, plural in singular_to_plural.items():
            if path.endswith(singular):
                new_path = path[:-len(singular)] + plural
                new_url = f"{parsed.scheme}://{parsed.netloc}{new_path}"
                variants.append(new_url)
                break
        
        # Try plural -> singular
        for singular, plural in singular_to_plural.items():
            if path.endswith(plural):
                new_path = path[:-len(plural)] + singular
                new_url = f"{parsed.scheme}://{parsed.netloc}{new_path}"
                variants.append(new_url)
                break
        
        return variants


