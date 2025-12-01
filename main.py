"""Main module for Open Jobs Searcher application."""

import asyncio
import logging
from typing import Optional

import typer
from rich.console import Console
from rich.logging import RichHandler

from src.config import settings
from src.searchers import HeadHunterSearcher, WebsiteSearcher
from src.llm import get_llm_provider
from src.output import display_jobs, save_jobs

# Configure logging
logging.basicConfig(
    level=logging.WARNING,
    format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
)

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
    console.print("  • Любой сайт компании (через LLM)")
    console.print("\nИспользование:")
    console.print("  jobs-searcher search 'Python Developer' --location Moscow")
    console.print("  jobs-searcher website https://example.com")


@app.command()
def website(
    url: str = typer.Argument(
        ...,
        help="URL сайта компании (например, https://company.com)",
    ),
    browser: bool = typer.Option(
        False,
        "--browser",
        "-b",
        help="Использовать браузер для загрузки (для SPA сайтов)",
    ),
    provider: str = typer.Option(
        "ollama",
        "--provider",
        "-p",
        help="LLM провайдер (ollama, openai, claude)",
    ),
    model: str = typer.Option(
        "gpt-oss:20b",
        "--model",
        "-m",
        help="Модель LLM",
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
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Показать отладочную информацию",
    ),
):
    """Поиск вакансий на сайте компании с помощью LLM."""
    # Enable debug logging if verbose
    if verbose:
        logging.getLogger("src").setLevel(logging.DEBUG)
    
    console.print(f"[bold blue]🌐 Сайт:[/bold blue] {url}")
    console.print(f"[bold blue]🤖 LLM:[/bold blue] {provider} ({model})")
    if browser:
        console.print(f"[bold blue]🌐 Режим:[/bold blue] браузер (Playwright)")
    console.print()

    # Run async search
    jobs = asyncio.run(_search_website(url, provider, model, browser))

    # Отображаем результаты
    display_jobs(jobs)

    # Сохраняем если указан путь
    if output:
        save_jobs(jobs, output, format)


async def _search_website(url: str, provider: str, model: str, use_browser: bool) -> list:
    """Асинхронный поиск вакансий на сайте."""
    try:
        llm = get_llm_provider(provider, model=model)
    except Exception as e:
        console.print(f"[red]✗[/red] Ошибка инициализации LLM: {e}")
        return []

    async with WebsiteSearcher(llm, use_browser=use_browser) as searcher:
        try:
            status_msg = "[bold green]Анализирую сайт через браузер..." if use_browser else "[bold green]Анализирую сайт..."
            with console.status(status_msg):
                jobs = await searcher.search(keywords=url)
            
            if jobs:
                console.print(f"[green]✓[/green] Найдено {len(jobs)} вакансий")
            else:
                console.print("[yellow]⚠[/yellow] Вакансии не найдены")
            
            return jobs
        except Exception as e:
            console.print(f"[red]✗[/red] Ошибка: {e}")
            return []


if __name__ == "__main__":
    app()

