"""Модуль поисковиков вакансий."""

from .base import BaseSearcher
from .hh import HeadHunterSearcher

__all__ = ["BaseSearcher", "HeadHunterSearcher"]

