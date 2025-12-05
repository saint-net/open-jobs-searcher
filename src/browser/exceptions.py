"""Исключения для модуля браузера."""


class DomainUnreachableError(Exception):
    """Raised when domain cannot be reached (DNS or network issues)."""
    pass


class PlaywrightBrowsersNotInstalledError(Exception):
    """Raised when Playwright browsers are not installed."""
    pass

