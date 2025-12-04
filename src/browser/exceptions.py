"""Исключения для модуля браузера."""


class DomainUnreachableError(Exception):
    """Raised when domain cannot be reached (DNS or network issues)."""
    pass

