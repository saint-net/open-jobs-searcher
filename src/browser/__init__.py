"""Модуль для работы с браузером через Playwright."""

from .exceptions import DomainUnreachableError
from .loader import BrowserLoader, get_browser_loader
from .navigation import is_external_job_board

__all__ = [
    "BrowserLoader",
    "DomainUnreachableError",
    "get_browser_loader",
    "is_external_job_board",
]

