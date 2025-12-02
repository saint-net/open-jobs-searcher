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

IMPORTANT: This page may have just 1-2 jobs or many jobs. Extract ALL of them, even if there's only ONE job posting!

Where to look for job titles:
- <li> list items containing job names (very common!)
- <a> links with job titles in text
- Headings (h1, h2, h3, h4) with position names
- Cards, divs with job information
- Text near "Stellen ausgeschrieben" or "open positions"

How to recognize a job title:
- Contains "(m/w/d)" or "(m/f/d)" - DEFINITELY a job title!
- Contains "WerkstudentIn", "PraktikantIn", "Manager", "Developer", "Engineer", etc.
- German titles: "Werkstudent", "Praktikant", "Mitarbeiter", "Leiter", etc.
- Located in list (<ul>/<li>) under text like "Aktuell haben wir folgende Stellen"

Common HTML patterns:
- <li>Werkstudent Sales (m/w/d)</li>
- <a href="/karriere/werkstudent-sales">Werkstudent Sales (m/w/d)</a>
- <h3>Software Developer (m/w/d)</h3>
- Text containing "(m/w/d)" is ALWAYS a job posting

For EACH job found, extract:
- title: The job title exactly as written
- location: City/region or "Remote" or "Unknown"  
- url: Full URL to job details (combine base URL with href if relative), or page URL if no specific link
- department: Department if mentioned, otherwise null

OUTPUT FORMAT - Return ONLY a JSON array:
```json
[
  {{"title": "Job Title Here", "location": "City", "url": "https://...", "department": null}}
]
```

RULES:
1. Extract EVERY job - even if there's only 1 job on the page!
2. Anything with "(m/w/d)" or "(m/f/d)" is a job - extract it!
3. Return valid JSON only, no extra text
4. Empty array [] ONLY if absolutely NO jobs exist
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
