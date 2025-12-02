"""Модуль поисковиков вакансий."""

from .base import BaseSearcher
from .hh import HeadHunterSearcher
from .website import WebsiteSearcher
from .stepstone import StepStoneSearcher
from .karriere import KarriereATSearcher

__all__ = [
    "BaseSearcher",
    "HeadHunterSearcher",
    "WebsiteSearcher",
    "StepStoneSearcher",
    "KarriereATSearcher",
]

