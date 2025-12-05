"""Модуль для работы с браузером через Playwright."""

from .exceptions import DomainUnreachableError, PlaywrightBrowsersNotInstalledError
from .loader import BrowserLoader, get_browser_loader
from .navigation import is_external_job_board

__all__ = [
    "BrowserLoader",
    "DomainUnreachableError",
    "PlaywrightBrowsersNotInstalledError",
    "get_browser_loader",
    "is_external_job_board",
]

