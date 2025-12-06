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

TASK: Find ALL job postings AND the next page link.

=== JOB EXTRACTION ===

What IS a job posting:
- SPECIFIC position titles: "Senior Software Developer (m/w/d)", "Sales Manager - EMEA"
- Anything with "(m/w/d)" or "(m/f/d)" = DEFINITELY a job!
- Has role specifics: level, specialization, department

What is NOT a job (DO NOT EXTRACT):
- Department headers: "IT Department", "Human Resources" (without job title)
- Promotional text: "We're hiring in Sales"

For EACH job, extract:
- title: Job title (keep (m/w/d), remove "Job advert"/"Stellenanzeige" suffixes)
- location: City/region or "Remote" or "Unknown"  
- url: Full URL to job details (https://...)
- department: If mentioned, otherwise null

=== PAGINATION (CRITICAL!) ===

Search the HTML for pagination elements. Look for:

1. PAGE NUMBERS in navigation:
   - <nav class="pager"> or <ul class="pagination">
   - Links like: "1" (current), "2" (next), "3", etc.
   - Current page often has: class="active", class="is-active", aria-current="page"
   - Next page = the number AFTER the current/active one

2. NEXT PAGE LINKS:
   - Text: "Next", "»", "›", "→", "Weiter", "Nächste Seite", "Nächste"
   - Text: "Page 2", "Seite 2"
   - Href patterns: ?page=1, ?page=2, &page=2, /page/2

3. LOAD MORE BUTTONS:
   - "Load more", "Show more", "Mehr laden", "Mehr anzeigen"

HOW TO FIND next_page_url:
1. Find the pagination <nav> or <ul> element
2. Find the CURRENT page (active/highlighted)
3. Get the href of the NEXT page link
4. Return the FULL URL (add domain if href is relative)

EXAMPLES:
- If current page shows "Page 1" and there's a link to "Page 2" with href="?page=1"
  → next_page_url = "{url}?page=1"
- If you see "Nächste Seite ›" with href="/jobs?page=2"  
  → next_page_url = "https://domain.com/jobs?page=2"
- If current page is the LAST page (no next link) → next_page_url = null

=== OUTPUT FORMAT ===

Return ONLY valid JSON:
```json
{{
  "jobs": [
    {{"title": "Job Title (m/w/d)", "location": "City", "url": "https://...", "department": null}}
  ],
  "next_page_url": "https://example.com/jobs?page=2"
}}
```

RULES:
1. Extract EXACT job titles from the page
2. Use FULL URLs (https://domain/path)
3. next_page_url = null ONLY if this is the last page or no pagination
4. Return valid JSON only

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
