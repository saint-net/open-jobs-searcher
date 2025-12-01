"""Модуль поисковиков вакансий."""

from .base import BaseSearcher
from .hh import HeadHunterSearcher
from .website import WebsiteSearcher

__all__ = ["BaseSearcher", "HeadHunterSearcher", "WebsiteSearcher"]

