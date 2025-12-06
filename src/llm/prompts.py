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

TASK: Find ALL SPECIFIC job postings and extract them as JSON.

CRITICAL - What IS a job posting:
- SPECIFIC position titles: "Senior Software Developer (m/w/d)", "Sales Manager - EMEA", "Marketing Specialist"
- Contains role specifics: level (Junior/Senior), specialization, department
- Usually has: title + location + link to apply/details
- Examples of REAL job postings:
  * "Werkstudent Sales (m/w/d)" - specific role with gender notation
  * "Senior Backend Developer" - specific position
  * "Customer Success Manager - DACH Region" - role with region

CRITICAL - What is NOT a job posting (DO NOT EXTRACT):
- Standalone categories WITHOUT any job details: just text like "Sales", "Engineering" as menu items
- DEPARTMENT NAMES without context: "IT Department", "Human Resources" as section headers only
- AREAS OF WORK as promotional text: "We're hiring in Sales", "Join our Engineering team"
- Pages that ONLY say "Send resume to jobs@company.com" with NO position listings at all

IMPORTANT: Generic names CAN be real jobs if they have context:
- "Technical Support" with experience requirements (e.g. "0-6 years") = REAL JOB
- "Programming" in expandable card with job details = REAL JOB
- "Sales" with location (e.g. "Bangalore") = REAL JOB
- If position has ANY details (experience, location, description) = extract it!

Where to look for job titles:
- <li> list items containing SPECIFIC job names
- <a> links with job titles in text
- Headings (h1, h2, h3, h4) with SPECIFIC position names
- Cards, divs with job information
- Text near "Stellen ausgeschrieben" or "open positions"

How to recognize a SPECIFIC job title:
- Contains "(m/w/d)" or "(m/f/d)" - DEFINITELY a job title!
- Has role specifics: "Software Developer", "Sales Manager", "Support Engineer"
- German titles: "Werkstudent Marketing", "Praktikant Entwicklung", "Mitarbeiter Vertrieb"
- More than just one word category

For EACH job found, extract:
- title: The EXACT job title as written on the page (DO NOT invent or modify!)
- location: City/region or "Remote" or "Unknown"  
- url: Full URL to job details, or page URL if no specific link
- department: Department if mentioned, otherwise null

OUTPUT FORMAT - Return ONLY a JSON array:
```json
[
  {{"title": "Job Title Here", "location": "City", "url": "https://...", "department": null}}
]
```

RULES:
1. Extract job positions - even generic names if they have details (experience, location)!
2. DO NOT invent job titles - use EXACT text from the page!
3. If position has context (experience, location, description) = it's a real job
4. Anything with "(m/w/d)" or "(m/f/d)" is a job - extract it!
5. Return valid JSON only, no extra text
6. Empty array [] ONLY if page has NO job listings at all (just "email us")
7. Use full URLs (include https://domain)

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
