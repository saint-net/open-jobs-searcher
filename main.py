"""Main module for Open Jobs Searcher application."""

import asyncio
import logging
import time
from typing import Optional

import typer
from rich.console import Console
from rich.logging import RichHandler

from src.config import settings
from src.searchers import HeadHunterSearcher, WebsiteSearcher, StepStoneSearcher, KarriereATSearcher
from src.llm import get_llm_provider
from src.output import display_jobs, save_jobs, display_execution_time
from src.browser import PlaywrightBrowsersNotInstalledError

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
    start_time = time.perf_counter()
    
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
    
    display_execution_time(time.perf_counter() - start_time)


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
def stepstone(
    keywords: str = typer.Argument(
        ...,
        help="Ключевые слова для поиска (например, 'Python Developer')",
    ),
    location: Optional[str] = typer.Option(
        None,
        "--location",
        "-l",
        help="Город в Германии (например, Berlin, Munich, Frankfurt)",
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
    page: int = typer.Option(
        0,
        "--page",
        "-p",
        help="Номер страницы (начиная с 0)",
    ),
):
    """🇩🇪 Поиск вакансий на StepStone.de (Германия)."""
    start_time = time.perf_counter()
    
    console.print(f"[bold blue]🔍 Поиск:[/bold blue] {keywords}")
    if location:
        console.print(f"[bold blue]📍 Локация:[/bold blue] {location}")
    console.print(f"[bold blue]🌐 Источник:[/bold blue] StepStone.de")
    console.print()

    jobs = asyncio.run(_search_stepstone(keywords, location, page))
    display_jobs(jobs)

    if output:
        save_jobs(jobs, output, format)
    
    display_execution_time(time.perf_counter() - start_time)


async def _search_stepstone(keywords: str, location: Optional[str], page: int) -> list:
    """Асинхронный поиск на StepStone.de."""
    async with StepStoneSearcher() as searcher:
        try:
            with console.status("[bold green]Ищу вакансии на StepStone.de..."):
                jobs = await searcher.search(keywords=keywords, location=location, page=page)
            
            if jobs:
                console.print(f"[green]✓[/green] Найдено {len(jobs)} вакансий")
            else:
                console.print("[yellow]⚠[/yellow] Вакансии не найдены")
            
            return jobs
        except Exception as e:
            console.print(f"[red]✗[/red] Ошибка: {e}")
            return []


@app.command()
def karriere(
    keywords: str = typer.Argument(
        ...,
        help="Ключевые слова для поиска (например, 'Python Developer')",
    ),
    location: Optional[str] = typer.Option(
        None,
        "--location",
        "-l",
        help="Город в Австрии (например, Wien, Graz, Salzburg)",
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
    page: int = typer.Option(
        0,
        "--page",
        "-p",
        help="Номер страницы (начиная с 0)",
    ),
):
    """🇦🇹 Поиск вакансий на Karriere.at (Австрия)."""
    start_time = time.perf_counter()
    
    console.print(f"[bold blue]🔍 Поиск:[/bold blue] {keywords}")
    if location:
        console.print(f"[bold blue]📍 Локация:[/bold blue] {location}")
    console.print(f"[bold blue]🌐 Источник:[/bold blue] Karriere.at")
    console.print()

    jobs = asyncio.run(_search_karriere(keywords, location, page))
    display_jobs(jobs)

    if output:
        save_jobs(jobs, output, format)
    
    display_execution_time(time.perf_counter() - start_time)


async def _search_karriere(keywords: str, location: Optional[str], page: int) -> list:
    """Асинхронный поиск на Karriere.at."""
    async with KarriereATSearcher() as searcher:
        try:
            with console.status("[bold green]Ищу вакансии на Karriere.at..."):
                jobs = await searcher.search(keywords=keywords, location=location, page=page)
            
            if jobs:
                console.print(f"[green]✓[/green] Найдено {len(jobs)} вакансий")
            else:
                console.print("[yellow]⚠[/yellow] Вакансии не найдены")
            
            return jobs
        except Exception as e:
            console.print(f"[red]✗[/red] Ошибка: {e}")
            return []


@app.command()
def info():
    """Информация о приложении."""
    console.print("[bold]Open Jobs Searcher[/bold]")
    console.print("Версия: 0.1.0")
    console.print("\nПоддерживаемые источники:")
    console.print("  • HeadHunter (hh.ru) - Россия")
    console.print("  • StepStone.de - Германия 🇩🇪")
    console.print("  • Karriere.at - Австрия 🇦🇹")
    console.print("  • Любой сайт компании (через LLM: Ollama, OpenRouter)")
    console.print("\nИспользование:")
    console.print("  jobs-searcher search 'Python Developer' --location Moscow")
    console.print("  jobs-searcher stepstone 'Python Developer' --location Berlin")
    console.print("  jobs-searcher karriere 'Python Developer' --location Wien")
    console.print("  jobs-searcher website https://example.com")
    console.print("  jobs-searcher history  # Показать историю изменений")


@app.command()
def history(
    domain: Optional[str] = typer.Argument(
        None,
        help="Домен сайта для фильтрации (например, company.com)",
    ),
    limit: int = typer.Option(
        50,
        "--limit",
        "-n",
        help="Количество записей",
    ),
):
    """📜 Показать историю изменений вакансий."""
    asyncio.run(_show_history(domain, limit))


async def _show_history(domain: Optional[str], limit: int) -> None:
    """Асинхронное отображение истории."""
    from src.database import JobRepository
    
    repo = JobRepository()
    
    # Get site_id if domain specified
    site_id = None
    if domain:
        site = await repo.get_site_by_domain(domain)
        if site:
            site_id = site.id
            console.print(f"[bold blue]📜 История для:[/bold blue] {domain}")
        else:
            console.print(f"[yellow]⚠[/yellow] Сайт {domain} не найден в базе")
            return
    else:
        console.print("[bold blue]📜 История всех сайтов[/bold blue]")
    
    console.print()
    
    events = await repo.get_job_history(site_id=site_id, limit=limit)
    
    if not events:
        console.print("[dim]История пуста[/dim]")
        return
    
    # Group by date
    from datetime import datetime
    
    current_date = None
    for event in events:
        event_date = event.get("changed_at", "")
        if isinstance(event_date, str) and event_date:
            try:
                dt = datetime.fromisoformat(event_date)
                date_str = dt.strftime("%Y-%m-%d")
                time_str = dt.strftime("%H:%M")
            except ValueError:
                date_str = event_date[:10]
                time_str = ""
        else:
            date_str = "Unknown"
            time_str = ""
        
        if date_str != current_date:
            current_date = date_str
            console.print(f"\n[bold]{date_str}[/bold]")
        
        # Format event
        event_type = event.get("event", "unknown")
        title = event.get("title", "Unknown")
        location = event.get("location", "")
        site_domain = event.get("domain", "")
        
        if event_type == "added":
            icon = "[green]✅[/green]"
            action = "добавлена"
        elif event_type == "removed":
            icon = "[red]❌[/red]"
            action = "закрыта"
        elif event_type == "reactivated":
            icon = "[yellow]↻[/yellow]"
            action = "вернулась"
        else:
            icon = "•"
            action = event_type
        
        location_str = f" ({location})" if location else ""
        site_str = f" [{site_domain}]" if site_domain and not domain else ""
        
        console.print(f"  {time_str} {icon} {title}{location_str}{site_str} — {action}")


@app.command()
def sites():
    """📋 Показать кэшированные сайты."""
    asyncio.run(_show_sites())


async def _show_sites() -> None:
    """Асинхронное отображение кэшированных сайтов."""
    from src.database import JobRepository
    from src.database.connection import get_db_path
    import aiosqlite
    
    db_path = get_db_path()
    
    if not db_path.exists():
        console.print("[yellow]⚠[/yellow] База данных ещё не создана")
        console.print("[dim]Запустите поиск на сайте, чтобы создать кэш[/dim]")
        return
    
    console.print(f"[bold blue]📋 Кэшированные сайты[/bold blue]")
    console.print(f"[dim]База данных: {db_path}[/dim]")
    console.print()
    
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        
        # Get sites with job counts
        cursor = await db.execute("""
            SELECT 
                s.domain,
                s.name,
                s.last_scanned_at,
                COUNT(DISTINCT CASE WHEN j.is_active = 1 THEN j.id END) as active_jobs,
                COUNT(DISTINCT j.id) as total_jobs,
                COUNT(DISTINCT cu.id) as career_urls
            FROM sites s
            LEFT JOIN jobs j ON j.site_id = s.id
            LEFT JOIN career_urls cu ON cu.site_id = s.id AND cu.is_active = 1
            GROUP BY s.id
            ORDER BY s.last_scanned_at DESC
        """)
        rows = await cursor.fetchall()
        
        if not rows:
            console.print("[dim]Нет кэшированных сайтов[/dim]")
            return
        
        for row in rows:
            domain = row["domain"]
            name = row["name"] or domain
            active_jobs = row["active_jobs"]
            total_jobs = row["total_jobs"]
            career_urls = row["career_urls"]
            last_scan = row["last_scanned_at"]
            
            # Format last scan time
            if last_scan:
                from datetime import datetime
                try:
                    dt = datetime.fromisoformat(last_scan)
                    scan_str = dt.strftime("%Y-%m-%d %H:%M")
                except ValueError:
                    scan_str = last_scan[:16]
            else:
                scan_str = "никогда"
            
            removed = total_jobs - active_jobs
            removed_str = f" [dim](-{removed} закрыто)[/dim]" if removed > 0 else ""
            
            console.print(f"  [bold]{name}[/bold] ({domain})")
            console.print(f"    Вакансий: {active_jobs}{removed_str}")
            console.print(f"    URL-ов: {career_urls}")
            console.print(f"    Последнее сканирование: {scan_str}")
            console.print()


@app.command()
def website(
    url: str = typer.Argument(
        ...,
        help="URL сайта компании (например, https://company.com)",
    ),
    browser: bool = typer.Option(
        True,
        "--browser",
        "-b",
        help="Использовать браузер для загрузки (для SPA сайтов)",
    ),
    provider: str = typer.Option(
        "openrouter",
        "--provider",
        "-p",
        help="LLM провайдер (openrouter, ollama)",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        "-m",
        help="Модель LLM (по умолчанию: gpt-oss:20b для ollama, openai/gpt-oss-20b для openrouter)",
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
        True,
        "--verbose",
        "-v",
        help="Показать отладочную информацию",
    ),
    nodb: bool = typer.Option(
        False,
        "--nodb",
        help="Не использовать базу данных (без кэширования и истории)",
    ),
):
    """Поиск вакансий на сайте компании с помощью LLM."""
    start_time = time.perf_counter()
    
    # Enable debug logging if verbose
    if verbose:
        logging.getLogger("src").setLevel(logging.DEBUG)
    
    # Определяем модель для отображения
    display_model = model
    if display_model is None:
        display_model = "gpt-oss:20b" if provider == "ollama" else "openai/gpt-oss-120b"
    
    console.print(f"[bold blue]🌐 Сайт:[/bold blue] {url}")
    console.print(f"[bold blue]🤖 LLM:[/bold blue] {provider} ({display_model})")
    if browser:
        console.print(f"[bold blue]🌐 Режим:[/bold blue] браузер (Playwright)")
    if nodb:
        console.print(f"[bold blue]💾 База:[/bold blue] отключена")
    console.print()

    # Run async search
    jobs, sync_result = asyncio.run(_search_website(url, provider, model, browser, use_cache=not nodb))
    
    # Отображаем результаты синхронизации (новые/удалённые)
    if not nodb:
        _display_sync_result(sync_result)

    # Отображаем результаты
    display_jobs(jobs)

    # Сохраняем если указан путь
    if output:
        save_jobs(jobs, output, format)
    
    display_execution_time(time.perf_counter() - start_time)


async def _search_website(
    url: str, 
    provider: str, 
    model: Optional[str], 
    use_browser: bool,
    use_cache: bool = True
) -> tuple:
    """Асинхронный поиск вакансий на сайте.
    
    Args:
        url: URL сайта
        provider: LLM провайдер
        model: Модель LLM
        use_browser: Использовать браузер
        use_cache: Использовать кэширование в SQLite
    
    Returns:
        Tuple (jobs, sync_result) - sync_result может быть None при первом запуске или если use_cache=False
    """
    # Определяем модель по умолчанию в зависимости от провайдера
    if model is None:
        if provider == "ollama":
            model = "gpt-oss:20b"
        else:
            model = "openai/gpt-oss-120b"
    
    try:
        llm = get_llm_provider(provider, model=model)
    except Exception as e:
        console.print(f"[red]✗[/red] Ошибка инициализации LLM: {e}")
        return [], None

    async with WebsiteSearcher(llm, use_browser=use_browser, use_cache=use_cache) as searcher:
        try:
            status_msg = "[bold green]Анализирую сайт через браузер..." if use_browser else "[bold green]Анализирую сайт..."
            with console.status(status_msg):
                jobs = await searcher.search(keywords=url)
            
            if jobs:
                console.print(f"[green]✓[/green] Найдено {len(jobs)} вакансий")
            else:
                console.print("[yellow]⚠[/yellow] Вакансии не найдены")
            
            # Get sync result for showing new/removed jobs
            sync_result = searcher.last_sync_result
            
            return jobs, sync_result
        except PlaywrightBrowsersNotInstalledError as e:
            console.print(f"[red]✗[/red] {e}")
            console.print("[yellow]💡[/yellow] Попробуйте установить браузеры вручную: [bold]playwright install chromium[/bold]")
            return [], None
        except Exception as e:
            console.print(f"[red]✗[/red] Ошибка: {e}")
            return [], None


def _display_sync_result(sync_result) -> None:
    """Отображает результаты синхронизации (новые/удалённые вакансии)."""
    if sync_result is None:
        return
    
    # Первое сканирование сайта
    if sync_result.is_first_scan:
        console.print(f"[green]📊 Первое сканирование: добавлено {sync_result.total_jobs} вакансий в базу[/green]")
        console.print()
        return
    
    if not sync_result.has_changes:
        console.print("[dim]📊 Изменений с прошлого сканирования нет[/dim]")
        console.print()
        return
    
    console.print()
    console.print("[bold]📊 Изменения с прошлого сканирования:[/bold]")
    
    # Новые вакансии
    if sync_result.new_jobs:
        console.print(f"  [green]✅ Новых: {len(sync_result.new_jobs)}[/green]")
        for job in sync_result.new_jobs[:5]:  # Show max 5
            console.print(f"     • {job.title} ({job.location})")
        if len(sync_result.new_jobs) > 5:
            console.print(f"     [dim]... и ещё {len(sync_result.new_jobs) - 5}[/dim]")
    
    # Удалённые вакансии
    if sync_result.removed_jobs:
        console.print(f"  [red]❌ Закрыто: {len(sync_result.removed_jobs)}[/red]")
        for job in sync_result.removed_jobs[:5]:  # Show max 5
            console.print(f"     • {job.title} ({job.location})")
        if len(sync_result.removed_jobs) > 5:
            console.print(f"     [dim]... и ещё {len(sync_result.removed_jobs) - 5}[/dim]")
    
    # Вернувшиеся вакансии
    if sync_result.reactivated_jobs:
        console.print(f"  [yellow]↻ Вернулись: {len(sync_result.reactivated_jobs)}[/yellow]")
        for job in sync_result.reactivated_jobs[:3]:
            console.print(f"     • {job.title} ({job.location})")
        if len(sync_result.reactivated_jobs) > 3:
            console.print(f"     [dim]... и ещё {len(sync_result.reactivated_jobs) - 3}[/dim]")
    
    console.print()


@app.command("find-job-urls")
def find_job_urls(
    url: str = typer.Argument(
        ...,
        help="URL страницы карьеры с вакансиями",
    ),
    provider: str = typer.Option(
        "openrouter",
        "--provider",
        "-p",
        help="LLM провайдер (openrouter, ollama)",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        "-m",
        help="Модель LLM",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Показать отладочную информацию",
    ),
):
    """🔗 Найти URL'ы отдельных вакансий на странице через LLM."""
    start_time = time.perf_counter()
    
    # Enable debug logging if verbose
    if verbose:
        logging.getLogger("src").setLevel(logging.DEBUG)
    
    display_model = model
    if display_model is None:
        display_model = "gpt-oss:20b" if provider == "ollama" else "openai/gpt-oss-120b"
    
    console.print(f"[bold blue]🌐 Страница:[/bold blue] {url}")
    console.print(f"[bold blue]🤖 LLM:[/bold blue] {provider} ({display_model})")
    console.print()

    job_urls = asyncio.run(_find_job_urls(url, provider, model))
    
    if job_urls:
        console.print(f"[green]✓[/green] Найдено {len(job_urls)} URL'ов вакансий:")
        console.print()
        for i, job_url in enumerate(job_urls, 1):
            console.print(f"  {i}. {job_url}")
    else:
        console.print("[yellow]⚠[/yellow] URL'ы вакансий не найдены")
    
    display_execution_time(time.perf_counter() - start_time)


async def _find_job_urls(url: str, provider: str, model: Optional[str]) -> list[str]:
    """Асинхронный поиск URL'ов вакансий через LLM."""
    from src.browser import BrowserLoader
    
    # Определяем модель по умолчанию
    if model is None:
        if provider == "ollama":
            model = "gpt-oss:20b"
        else:
            model = "openai/gpt-oss-120b"
    
    try:
        llm = get_llm_provider(provider, model=model)
    except Exception as e:
        console.print(f"[red]✗[/red] Ошибка инициализации LLM: {e}")
        return []
    
    # Загружаем страницу через браузер (для SPA сайтов)
    async with llm:
        try:
            loader = BrowserLoader(headless=True)
            await loader.start()
            
            with console.status("[bold green]Загружаю страницу..."):
                html = await loader.fetch(url)
            
            await loader.stop()
            
            if not html:
                console.print("[red]✗[/red] Не удалось загрузить страницу")
                return []
            
            with console.status("[bold green]Анализирую страницу через LLM..."):
                job_urls = await llm.find_job_urls(html, url)
            
            return job_urls
            
        except PlaywrightBrowsersNotInstalledError as e:
            console.print(f"[red]✗[/red] {e}")
            return []
        except Exception as e:
            console.print(f"[red]✗[/red] Ошибка: {e}")
            return []


if __name__ == "__main__":
    app()

