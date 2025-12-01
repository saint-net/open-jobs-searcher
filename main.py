"""Главный модуль приложения Open Jobs Searcher."""

import asyncio
from typing import Optional

import typer
from rich.console import Console

from src.config import settings
from src.searchers import HeadHunterSearcher
from src.output import display_jobs, save_jobs


app = typer.Typer(
    name="jobs-searcher",
    help="🔍 Поиск вакансий с различных платформ",
    add_completion=False,
)
console = Console()


@app.command()
def search(
    keywords: str = typer.Argument(
        default=None,
        help="Ключевые слова для поиска",
    ),
    location: Optional[str] = typer.Option(
        None,
        "--location",
        "-l",
        help="Город/локация",
    ),
    experience: Optional[str] = typer.Option(
        None,
        "--experience",
        "-e",
        help="Опыт работы (no_experience, 1-3, 3-6, 6+)",
    ),
    salary: Optional[int] = typer.Option(
        None,
        "--salary",
        "-s",
        help="Минимальная зарплата",
    ),
    output: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help="Сохранить результаты в файл",
    ),
    format: str = typer.Option(
        "json",
        "--format",
        "-f",
        help="Формат вывода (json/csv)",
    ),
    limit: int = typer.Option(
        20,
        "--limit",
        "-n",
        help="Количество результатов",
    ),
):
    """Поиск вакансий по ключевым словам."""
    # Используем значения по умолчанию из настроек
    if not keywords:
        keywords = settings.default_keywords
    if not location:
        location = settings.default_location

    console.print(f"[bold blue]🔍 Поиск:[/bold blue] {keywords}")
    console.print(f"[bold blue]📍 Локация:[/bold blue] {location}")
    console.print()

    # Запускаем асинхронный поиск
    jobs = asyncio.run(_search_jobs(keywords, location, experience, salary, limit))

    # Отображаем результаты
    display_jobs(jobs)

    # Сохраняем если указан путь
    if output:
        save_jobs(jobs, output, format)


async def _search_jobs(
    keywords: str,
    location: Optional[str],
    experience: Optional[str],
    salary: Optional[int],
    limit: int,
) -> list:
    """Асинхронный поиск вакансий."""
    all_jobs = []

    async with HeadHunterSearcher() as searcher:
        try:
            jobs = await searcher.search(
                keywords=keywords,
                location=location,
                experience=experience,
                salary_from=salary,
                per_page=limit,
            )
            all_jobs.extend(jobs)
            console.print(f"[green]✓[/green] {searcher.name}: найдено {len(jobs)} вакансий")
        except Exception as e:
            console.print(f"[red]✗[/red] {searcher.name}: ошибка - {e}")

    return all_jobs


@app.command()
def info():
    """Информация о приложении."""
    console.print("[bold]Open Jobs Searcher[/bold]")
    console.print("Версия: 0.1.0")
    console.print("\nПоддерживаемые источники:")
    console.print("  • HeadHunter (hh.ru)")
    console.print("\nИспользование:")
    console.print("  jobs-searcher search 'Python Developer' --location Moscow")


if __name__ == "__main__":
    app()

