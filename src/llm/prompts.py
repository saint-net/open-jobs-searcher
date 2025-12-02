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

EXTRACT_JOBS_PROMPT = """Extract job listings from this careers page HTML.

URL: {url}

HTML:
{html}

TASK: Find ALL job postings and extract them as JSON.

Look for job titles in:
- Headings (h1, h2, h3, h4) - these often contain job titles
- List items with job names
- Cards or grid items with position titles
- Links to job detail pages (href containing /karriere/, /jobs/, /career/, etc.)
- Accordion/expandable sections with job categories
- Department names that represent open positions
- Repeated structures with job information (data-layout="jobs", class="job-*", etc.)
- Containers with data-entries attribute showing job count

Common HTML patterns for jobs:
- <h2>Software Developer (m/w/d)</h2>
- <h3>Senior Engineer</h3> followed by <h6>Company Name</h6>
- <a href="/karriere/job-title">Weiterlesen</a> or <a href="/jobs/123">Apply</a>
- <div class="job-title">Product Manager</div>
- <div data-layout="jobs">...</div> containing job cards
- Structures with "m/w/d" or "m/f/d" gender notation indicate job listings

For EACH job found, extract:
- title: The job title exactly as written (from h2, h3, or similar heading)
- location: City/region or "Remote" or "Unknown"  
- url: Full URL to job details (combine base URL with href if relative), or page URL if no specific link
- department: Department/company if mentioned (often in h4 or h6), otherwise null

OUTPUT FORMAT - Return ONLY a JSON array:
```json
[
  {{"title": "Job Title Here", "location": "City", "url": "https://...", "department": null}}
]
```

RULES:
1. Extract EVERY job listing you find - even if only 1-3 jobs exist
2. If page shows department/category names (e.g., "Technical Support", "Programming") as hiring areas, treat them as job openings
3. Return valid JSON only, no extra text
4. Empty array [] ONLY if the page has NO job-related content at all
5. Use full URLs (include https://domain)
6. Look for "Weiterlesen" (German for "Read more") links - they often point to job details

JSON:
"""

SYSTEM_PROMPT = """You are a helpful assistant specialized in web scraping and data extraction.
You analyze HTML content and extract structured information accurately.
Always respond with precise, structured data in the requested format.
"""

TRANSLATE_JOB_TITLES_PROMPT = """Translate the following job titles to English.

Job titles (one per line):
{titles}

RULES:
1. Return ONLY a JSON array with translated titles in the same order
2. Keep the translation professional and accurate
3. If a title is already in English, keep it unchanged
4. Preserve any gender notations like (m/w/d) or (m/f/d)

OUTPUT FORMAT - Return ONLY a JSON array:
```json
["Translated Title 1", "Translated Title 2", ...]
```

JSON:
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
