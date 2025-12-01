"""LLM prompts for job parsing and career page discovery."""

FIND_CAREERS_PAGE_PROMPT = """You are analyzing a company website to find their careers/jobs page.

Base URL: {base_url}

Here is the HTML content of the main page:

{html}

Task: Find the URL to the careers/jobs page where job openings are listed.

Look for links containing keywords like:
- English: careers, career, jobs, job, vacancies, vacancy, openings, work with us, join us, join our team, we're hiring
- German: karriere, stellen, stellenangebote, jobangebote, offene stellen, arbeiten bei uns
- Russian: вакансии, карьера, работа у нас

Instructions:
1. Search for <a> tags with href attributes
2. Look at link text and href values
3. Return the FULL URL to the careers page

Return ONLY the URL, nothing else. If you can't find it, return "NOT_FOUND".
"""

EXTRACT_JOBS_PROMPT = """You are extracting job listings from a careers page.

URL: {url}

Here is the HTML content:

{html}

Task: Extract all job openings from this page.

For each job, extract:
- title: Job title/position name
- location: Office location or "Remote" (if not found, use "Unknown")
- url: Direct link to the job posting (full URL)
- department: Department name (if available, otherwise null)

Return a JSON array with the job listings. Example format:
```json
[
  {{
    "title": "Senior Python Developer",
    "location": "Berlin",
    "url": "https://example.com/jobs/123",
    "department": "Engineering"
  }},
  {{
    "title": "Product Manager",
    "location": "Remote",
    "url": "https://example.com/jobs/456",
    "department": "Product"
  }}
]
```

Important:
- Return ONLY valid JSON array
- If no jobs found, return empty array: []
- Make sure URLs are absolute (include domain)
- Extract ALL visible job listings

JSON output:
"""

SYSTEM_PROMPT = """You are a helpful assistant specialized in web scraping and data extraction.
You analyze HTML content and extract structured information accurately.
Always respond with precise, structured data in the requested format.
"""

FIND_CAREERS_FROM_SITEMAP_PROMPT = """You are analyzing a list of URLs from a website's sitemap.xml to find the careers/jobs page.

Base URL: {base_url}

Here are the URLs from the sitemap:

{urls}

Task: Find the URL that leads to the careers/jobs page where job openings are listed.

Look for URLs containing keywords like:
- English: careers, career, jobs, job, vacancies, vacancy, openings, positions, hiring, work-with-us, join-us, join-our-team
- German: karriere, stellen, stellenangebote, jobangebote, offene-stellen
- Russian: вакансии, карьера, работа

Important:
- Choose the MAIN careers page, not individual job postings
- Prefer shorter URLs (e.g., /careers over /careers/senior-developer)
- Look for pages that would list ALL job openings

Return ONLY the URL, nothing else. If you can't find it, return "NOT_FOUND".
"""
