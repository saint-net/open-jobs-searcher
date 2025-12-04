"""Job board parsers package."""

from src.searchers.job_boards.base import BaseJobBoardParser
from src.searchers.job_boards.detector import (
    EXTERNAL_JOB_BOARDS,
    detect_job_board_platform,
    find_external_job_board,
)
from src.searchers.job_boards.registry import JobBoardParserRegistry

__all__ = [
    "BaseJobBoardParser",
    "EXTERNAL_JOB_BOARDS",
    "detect_job_board_platform",
    "find_external_job_board",
    "JobBoardParserRegistry",
]




