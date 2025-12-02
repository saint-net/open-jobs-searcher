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
- Headings (h1, h2, h3, h4)
- List items with job names
- Cards or grid items with position titles
- Links to job detail pages
- Accordion/expandable sections with job categories
- Department names that represent open positions

Common patterns:
- <h3>Software Developer (m/w/d)</h3>
- <a href="/jobs/123">Senior Engineer</a>
- <div class="job-title">Product Manager</div>
- Department/category headings like "Technical Support", "Programming", "Sales"

For EACH job found, extract:
- title: The job title exactly as written
- location: City/region or "Remote" or "Unknown"  
- url: Full URL to job details (combine with {url} if relative), or page URL if no specific link
- department: Department if mentioned, otherwise null

OUTPUT FORMAT - Return ONLY a JSON array:
```json
[
  {{"title": "Job Title Here", "location": "City", "url": "https://...", "department": null}}
]
```

RULES:
1. Extract EVERY job listing you find
2. If page shows department/category names (e.g., "Technical Support", "Programming") as hiring areas, treat them as job openings
3. Return valid JSON only, no extra text
4. Empty array [] ONLY if the page has NO job-related content at all
5. Use full URLs (include https://domain)

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
