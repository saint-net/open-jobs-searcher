"""Модуль вывода результатов."""

import json
from pathlib import Path
from typing import Literal

import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.models import Job


console = Console()


def display_execution_time(elapsed_seconds: float) -> None:
    """Отобразить время выполнения в красивом формате."""
    if elapsed_seconds < 60:
        time_str = f"{elapsed_seconds:.2f} сек"
    elif elapsed_seconds < 3600:
        minutes = int(elapsed_seconds // 60)
        seconds = elapsed_seconds % 60
        time_str = f"{minutes} мин {seconds:.1f} сек"
    else:
        hours = int(elapsed_seconds // 3600)
        minutes = int((elapsed_seconds % 3600) // 60)
        seconds = elapsed_seconds % 60
        time_str = f"{hours} ч {minutes} мин {seconds:.0f} сек"
    
    console.print()
    console.print(Panel(
        f"[bold cyan]⏱️  Время выполнения:[/bold cyan] [bold white]{time_str}[/bold white]",
        border_style="dim cyan",
        padding=(0, 2),
    ))


def display_jobs(jobs: list[Job], detailed: bool = False) -> None:
    """Отобразить вакансии в терминале."""
    if not jobs:
        return  # Status message already shown in main.py

    table = Table(title=f"Найдено вакансий: {len(jobs)}", show_lines=True)

    table.add_column("Компания", style="cyan", max_width=25)
    table.add_column("Вакансия", style="green", max_width=35)
    table.add_column("Title (EN)", style="bright_green", max_width=35)
    table.add_column("Локация", style="blue", max_width=15)
    table.add_column("Зарплата", style="yellow", max_width=20)
    table.add_column("Источник", style="magenta", max_width=10)

    for job in jobs:
        table.add_row(
            job.company,
            job.title,
            job.title_en or "—",
            job.location,
            job.salary_display,
            job.source,
        )

    console.print(table)


def save_jobs(
    jobs: list[Job],
    output_path: str,
    format: Literal["json", "csv"] = "json",
) -> Path:
    """
    Сохранить вакансии в файл.

    Args:
        jobs: Список вакансий
        output_path: Путь к файлу
        format: Формат файла (json или csv)

    Returns:
        Путь к сохраненному файлу
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    jobs_data = [job.to_dict() for job in jobs]

    if format == "json":
        if not path.suffix:
            path = path.with_suffix(".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(jobs_data, f, ensure_ascii=False, indent=2)
    elif format == "csv":
        if not path.suffix:
            path = path.with_suffix(".csv")
        df = pd.DataFrame(jobs_data)
        df.to_csv(path, index=False, encoding="utf-8")

    console.print(f"[green]Результаты сохранены в {path}[/green]")
    return path



