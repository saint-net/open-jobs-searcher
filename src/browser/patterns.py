"""Паттерны для поиска элементов на страницах."""

# Паттерны для поиска ссылок на вакансии в SPA
JOB_LINK_PATTERNS = [
    # English - specific patterns first
    r'current\s*opening',
    r'open\s*positions?',
    r'job\s*(listings?|openings?)',
    r'all\s*(jobs?|positions?|openings?|vacancies)',
    # "See all" / "View all" - но не highlights, articles, news и т.д.
    r'(view|see)\s*all(?!\s*(highlight|article|news|blog|event|storie|project|client|partner|case))',
    r'browse\s*(jobs?|positions?|openings?)',
    r'career\s*(portal|opportunities)',
    r'job\s*portal',
    # German
    r'alle\s*stellen',
    r'offene\s*stellen',
    r'stellenangebote',
    r'stellenbörse',
    r'zur\s*stellenbörse',
    r'zum?\s*karriereportal',
    r'zu\s*den\s*jobs?',
    r'karriereseite',
    r'jobportal',
    # Russian
    r'все\s*вакансии',
    r'открытые\s*позиции',
    r'карьерный\s*портал',
]

# External job board platforms to detect
EXTERNAL_JOB_BOARD_PATTERNS = [
    r'\.jobs\.personio\.',
    r'boards\.greenhouse\.io',
    r'jobs\.lever\.co',
    r'\.workable\.com',
    r'\.breezy\.hr',
    r'\.recruitee\.com',
    r'\.smartrecruiters\.com',
    r'\.bamboohr\.com/jobs',
    r'\.ashbyhq\.com',
    r'job\.deloitte\.com',
    r'hrworks\.de',  # HRworks job boards
]

# Cookie consent buttons (patterns for button text)
COOKIE_ACCEPT_PATTERNS = [
    # English
    r'accept\s*all',
    r'allow\s*all',
    r'agree\s*all',
    r'i\s*accept',
    r'accept\s*cookies',
    # German
    r'(ich\s+)?akzeptiere?\s*(alle)?',
    r'alle\s*akzeptieren',
    r'alle\s*bestätigen',  # "Alle bestätigen" (confirm all)
    r'zustimmen',
    r'einverstanden',
    r'annehmen',
    # Russian
    r'принять\s*все',
    r'согласен',
]

# Паттерны для поиска ссылок по href
JOB_HREF_PATTERNS = [
    r'karriere\.',  # External karriere subdomain
    r'/jobs/?$',
    r'/careers/?$',
    r'/stellenangebote/?$',
]

# CSS селекторы для cookie диалогов
COOKIE_DIALOG_SELECTORS = [
    '[role="alertdialog"] button',
    '[role="dialog"] button',
    '[class*="consent"] button',
    '[class*="cookie"] button',
    '[id*="consent"] button',
    '[id*="cookie"] button',
    '[class*="modal"] button',
    '[class*="banner"] button',
    'button',
]

# CSS селекторы для навигационных элементов
NAVIGATION_SELECTORS = [
    'a',
    'button',
    '[role="link"]',
    '[role="button"]',
    '[onclick]',
    'span[class*="link"]',
    'div[class*="nav"]',
]

# Network error patterns (domain unreachable)
NETWORK_ERROR_PATTERNS = [
    "ERR_NAME_NOT_RESOLVED",
    "ERR_CONNECTION_REFUSED",
    "ERR_CONNECTION_RESET",
    "ERR_CONNECTION_TIMED_OUT",
    "ERR_NETWORK_CHANGED",
    "ERR_INTERNET_DISCONNECTED",
    "ERR_ADDRESS_UNREACHABLE",
]

# Default User-Agent
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

