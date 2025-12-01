"""Базовый класс для LLM провайдеров."""

from abc import ABC, abstractmethod
import json
import re
from typing import Optional


class BaseLLMProvider(ABC):
    """Абстрактный базовый класс для LLM провайдеров."""

    @abstractmethod
    async def complete(self, prompt: str, system: Optional[str] = None) -> str:
        """
        Генерация ответа от LLM.

        Args:
            prompt: Пользовательский промпт
            system: Системный промпт (опционально)

        Returns:
            Ответ модели
        """
        pass

    async def find_careers_url(self, html: str, base_url: str) -> Optional[str]:
        """
        Найти ссылку на страницу с вакансиями.

        Args:
            html: HTML содержимое главной страницы
            base_url: Базовый URL сайта

        Returns:
            URL страницы с вакансиями или None
        """
        from .prompts import FIND_CAREERS_PAGE_PROMPT

        # Ограничиваем размер HTML для LLM
        html_truncated = html[:15000] if len(html) > 15000 else html

        prompt = FIND_CAREERS_PAGE_PROMPT.format(
            base_url=base_url,
            html=html_truncated,
        )

        response = await self.complete(prompt)
        
        # Извлекаем URL из ответа
        url = self._extract_url(response, base_url)
        return url

    async def find_careers_url_from_sitemap(self, urls: list[str], base_url: str) -> Optional[str]:
        """
        Найти страницу вакансий среди URL из sitemap.xml с помощью LLM.

        Args:
            urls: Список URL из sitemap
            base_url: Базовый URL сайта

        Returns:
            URL страницы с вакансиями или None
        """
        from .prompts import FIND_CAREERS_FROM_SITEMAP_PROMPT

        # Ограничиваем количество URL (берём первые 500)
        urls_limited = urls[:500]
        urls_text = "\n".join(urls_limited)

        prompt = FIND_CAREERS_FROM_SITEMAP_PROMPT.format(
            base_url=base_url,
            urls=urls_text,
        )

        response = await self.complete(prompt)
        
        # Извлекаем URL из ответа
        url = self._extract_url(response, base_url)
        return url

    async def extract_jobs(self, html: str, url: str) -> list[dict]:
        """
        Извлечь список вакансий из HTML страницы.

        Args:
            html: HTML содержимое страницы с вакансиями
            url: URL страницы

        Returns:
            Список вакансий в формате dict
        """
        from .prompts import EXTRACT_JOBS_PROMPT
        
        # Сначала пробуем найти JSON данные в script тегах (SSR/schema.org)
        json_jobs = self._extract_json_from_scripts(html)
        if json_jobs:
            return json_jobs
        
        # Очищаем HTML от скриптов и стилей для уменьшения размера
        clean_html = self._clean_html(html)

        # Ограничиваем размер HTML (80000 символов — для страниц с большим количеством контента)
        html_truncated = clean_html[:80000] if len(clean_html) > 80000 else clean_html

        prompt = EXTRACT_JOBS_PROMPT.format(
            url=url,
            html=html_truncated,
        )

        response = await self.complete(prompt)
        
        # Парсим JSON из ответа
        jobs = self._extract_json(response)
        return jobs if isinstance(jobs, list) else []

    def _extract_json_from_scripts(self, html: str) -> list[dict]:
        """Попытка извлечь JSON с вакансиями из script тегов (SSR/hydration)."""
        import re
        import json
        
        # Ищем script теги с JSON данными
        script_pattern = r'<script[^>]*type=["\']application/(?:ld\+)?json["\'][^>]*>([\s\S]*?)</script>'
        scripts = re.findall(script_pattern, html, re.IGNORECASE)
        
        jobs = []
        for script_content in scripts:
            try:
                data = json.loads(script_content)
                # Ищем JobPosting schema.org
                if isinstance(data, dict):
                    if data.get("@type") == "JobPosting":
                        jobs.append(self._parse_schema_job(data))
                    elif data.get("@graph"):
                        for item in data["@graph"]:
                            if item.get("@type") == "JobPosting":
                                jobs.append(self._parse_schema_job(item))
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("@type") == "JobPosting":
                            jobs.append(self._parse_schema_job(item))
            except (json.JSONDecodeError, TypeError):
                continue
        
        return jobs

    def _parse_schema_job(self, data: dict) -> dict:
        """Парсинг вакансии из schema.org JobPosting."""
        location = "Unknown"
        if data.get("jobLocation"):
            loc = data["jobLocation"]
            if isinstance(loc, dict):
                addr = loc.get("address", {})
                if isinstance(addr, dict):
                    location = addr.get("addressLocality", "Unknown")
                elif isinstance(addr, str):
                    location = addr
        
        return {
            "title": data.get("title", "Unknown"),
            "location": location,
            "url": data.get("url", ""),
            "department": data.get("industry", None),
        }

    def _clean_html(self, html: str) -> str:
        """Очистить HTML от скриптов, стилей и лишних пробелов."""
        import re
        
        # Удаляем head секцию
        html = re.sub(r'<head[^>]*>[\s\S]*?</head>', '', html, flags=re.IGNORECASE)
        
        # Удаляем script и style теги
        html = re.sub(r'<script[^>]*>[\s\S]*?</script>', '', html, flags=re.IGNORECASE)
        html = re.sub(r'<style[^>]*>[\s\S]*?</style>', '', html, flags=re.IGNORECASE)
        
        # Удаляем SVG (часто большие)
        html = re.sub(r'<svg[^>]*>[\s\S]*?</svg>', '', html, flags=re.IGNORECASE)
        
        # Удаляем noscript
        html = re.sub(r'<noscript[^>]*>[\s\S]*?</noscript>', '', html, flags=re.IGNORECASE)
        
        # Удаляем комментарии
        html = re.sub(r'<!--[\s\S]*?-->', '', html)
        
        # Удаляем атрибуты data-* и style
        html = re.sub(r'\s+data-[a-z-]+="[^"]*"', '', html, flags=re.IGNORECASE)
        html = re.sub(r'\s+style="[^"]*"', '', html, flags=re.IGNORECASE)
        
        # Удаляем множественные пробелы
        html = re.sub(r'\s+', ' ', html)
        
        return html.strip()

    def _extract_url(self, response: str, base_url: str) -> Optional[str]:
        """Извлечь URL из ответа LLM."""
        # Ищем URL в ответе
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

    def _extract_json(self, response: str) -> list | dict:
        """Извлечь JSON из ответа LLM."""
        # Пробуем найти JSON в markdown блоке
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Пробуем найти JSON массив напрямую
        array_match = re.search(r'\[[\s\S]*\]', response)
        if array_match:
            try:
                return json.loads(array_match.group(0))
            except json.JSONDecodeError:
                pass

        # Пробуем распарсить весь ответ
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return []

    async def close(self):
        """Закрыть соединения."""
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

