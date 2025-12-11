"""HTML and JSON utilities for LLM processing."""

import json
import logging
import re
from typing import Optional

from bs4 import BeautifulSoup, Comment

logger = logging.getLogger(__name__)

# Tags to completely remove from HTML
REMOVE_TAGS = ['script', 'style', 'svg', 'noscript', 'head', 'meta', 'link', 'iframe']

# Selectors for cookie consent dialogs (can be 5+ MB on some sites)
COOKIE_SELECTORS = [
    '[role="dialog"]',
    '[id*="cookie"]',
    '[id*="consent"]',
    '[class*="cookie"]',
    '[class*="consent"]',
    '[id*="gdpr"]',
    '[class*="gdpr"]',
    '[id*="CookieBot"]',
    '[class*="CookieBot"]',
]

# Attributes to keep when cleaning HTML
KEEP_ATTRS = {'href', 'class', 'id', 'role', 'data-job', 'data-position'}

# Keywords for relevant CSS classes
RELEVANT_CLASS_KEYWORDS = ['job', 'career', 'position', 'vacancy', 'opening', 'title', 'list', 'item']


def clean_html(html: str) -> str:
    """
    Очистить HTML от скриптов, стилей и лишних атрибутов.
    
    Args:
        html: Raw HTML content
        
    Returns:
        Cleaned HTML string optimized for LLM processing
    """
    soup = BeautifulSoup(html, 'lxml')
    
    # Удаляем ненужные теги полностью
    for tag in soup.find_all(REMOVE_TAGS):
        tag.decompose()
    
    # Remove cookie consent dialogs
    for selector in COOKIE_SELECTORS:
        try:
            for element in soup.select(selector):
                element.decompose()
        except Exception:
            pass  # Ignore CSS selector errors
    
    # Удаляем комментарии
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    
    # Фильтруем атрибуты
    for tag in soup.find_all(True):
        new_attrs = {}
        for attr, value in tag.attrs.items():
            if attr in KEEP_ATTRS:
                if attr == 'class' and isinstance(value, list):
                    # Оставляем только релевантные классы
                    relevant = [
                        c for c in value 
                        if any(k in c.lower() for k in RELEVANT_CLASS_KEYWORDS)
                    ]
                    if relevant:
                        new_attrs[attr] = ' '.join(relevant[:3])
                elif attr == 'href':
                    new_attrs[attr] = value
                else:
                    new_attrs[attr] = value
        tag.attrs = new_attrs
    
    # Получаем очищенный HTML
    clean = str(soup)
    
    # Удаляем множественные пробелы и переносы
    clean = re.sub(r'\s+', ' ', clean)
    clean = re.sub(r'>\s+<', '><', clean)
    
    return clean.strip()


def extract_url(response: str, base_url: str) -> Optional[str]:
    """
    Извлечь URL из ответа LLM.
    
    Args:
        response: LLM response text
        base_url: Base URL for resolving relative paths
        
    Returns:
        Extracted URL or None
    """
    # Ищем полный URL
    url_pattern = r'https?://[^\s<>"\'}\])]+'
    urls = re.findall(url_pattern, response)
    
    if urls:
        return urls[0].rstrip('.,;:')
    
    # Если нашли относительный путь
    path_pattern = r'["\'](/[a-zA-Z0-9/_-]+)["\']'
    paths = re.findall(path_pattern, response)
    
    if paths:
        base = base_url.rstrip('/')
        return f"{base}{paths[0]}"
    
    return None


def extract_json(response: str) -> list | dict:
    """
    Извлечь JSON из ответа LLM.
    
    Handles various formats:
    - JSON in markdown code blocks
    - Raw JSON response
    - JSON embedded in text
    
    Args:
        response: LLM response text
        
    Returns:
        Parsed JSON (list or dict), or empty list on failure
    """
    if not response or not response.strip():
        return []
    
    # Пробуем найти JSON в markdown блоке
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Пробуем распарсить весь ответ как JSON
    try:
        return json.loads(response.strip())
    except json.JSONDecodeError as e:
        logger.debug(f"Direct JSON parse failed: {e}")

    # Пробуем найти JSON объект с "jobs" ключом
    try:
        start = response.find('{"jobs"')
        if start == -1:
            start = response.find('{ "jobs"')
        if start == -1:
            start = response.find('{')
        
        if start != -1:
            # Найдем соответствующую закрывающую скобку
            depth = 0
            end = start
            for i, char in enumerate(response[start:], start):
                if char == '{':
                    depth += 1
                elif char == '}':
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            
            if end > start:
                json_str = response[start:end]
                return json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        pass

    # Пробуем найти JSON массив
    array_match = re.search(r'\[[\s\S]*\]', response)
    if array_match:
        try:
            return json.loads(array_match.group(0))
        except json.JSONDecodeError:
            pass

    return []

