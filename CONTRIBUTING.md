# Руководство по разработке

## Начало работы

1. Клонируйте репозиторий
2. Создайте виртуальное окружение:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/macOS
   venv\Scripts\activate     # Windows
   ```
3. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```
4. Скопируйте `.env.example` в `.env` и заполните необходимые ключи

## Разработка

### Форматирование кода
```bash
black .
```

### Линтинг
```bash
ruff check .
```

### Запуск тестов
```bash
# Все тесты (~310 штук, ~1 сек)
python -m pytest tests/ -v

# Быстрая проверка
python -m pytest tests/ -q

# После изменений в job board парсерах
python -m pytest tests/test_job_board_parsers.py -v

# После изменений в LLM кэше
python -m pytest tests/test_llm_cache.py -v
```

## Добавление нового функционала

### Новый поисковик
1. Создайте файл в `src/searchers/`
2. Наследуйте `BaseSearcher`
3. Реализуйте метод `search()`
4. Добавьте команду в `main.py`

### Новый LLM провайдер
1. Создайте файл в `src/llm/`
2. Наследуйте `BaseLLMProvider`
3. Реализуйте метод `complete()` - базовый вызов LLM
4. Все остальные методы наследуются от базового класса через Composition:
   - `LLMJobExtractor` - извлечение вакансий
   - `LLMUrlDiscovery` - поиск URL карьеры/job board
5. Добавьте в `get_llm_provider()` factory в `src/llm/__init__.py`

**Архитектура LLM модуля:**
```
BaseLLMProvider (base.py)
├── html_utils.py - clean_html, extract_url, extract_json
├── job_extraction.py - LLMJobExtractor
├── url_discovery.py - LLMUrlDiscovery
└── prompts.py - все промпты
```

### Новый Job Board парсер
1. Создайте файл в `src/searchers/job_boards/`
2. Наследуйте `BaseJobBoardParser`
3. Реализуйте метод `parse()`
4. Для API-based платформ (как Recruitee) реализуйте:
   - `get_api_url()` - формирование URL API
   - `parse_api_json()` - парсинг JSON ответа
5. Зарегистрируйте в `JobBoardParserRegistry._register_defaults()`
6. Добавьте паттерн в `detector.py` (EXTERNAL_JOB_BOARDS)

### Новая стратегия экстракции
1. Создайте класс в `src/extraction/strategies.py`
2. Реализуйте метод `extract(html: str, url: str) -> list[JobCandidate]`
3. При необходимости интегрируйте в `HybridJobExtractor`

**Важно:** Избегайте эвристических стратегий, которые могут давать ложные срабатывания. Текущая архитектура использует только:
- Schema.org (100% точность)
- LLM (основной метод)

### Работа с базой данных

#### Новая таблица
1. Добавьте SQL схему в `src/database/connection.py` (SCHEMA)
2. Создайте dataclass модель в `src/database/models.py`
3. Добавьте методы в `JobRepository` (`src/database/repository.py`)

#### Пример запроса
```python
from src.database import JobRepository

repo = JobRepository()
site = await repo.get_or_create_site("example.com", "Example Company")
jobs = await repo.get_active_jobs(site.id)
await repo.close()
```

### Новая CLI команда
1. Добавьте функцию с декоратором `@app.command()` в `main.py`
2. Используйте Typer для аргументов и опций
3. Обновите команду `info()` с новой командой
4. Обновите документацию в README.md

### Пагинация в LLM экстракции

LLM теперь возвращает не только вакансии, но и `next_page_url`:

```python
# Использование с пагинацией
result = await llm.extract_jobs_with_pagination(html, url)
jobs = result.get("jobs", [])
next_page_url = result.get("next_page_url")

# Обычная экстракция (без пагинации)
jobs = await llm.extract_jobs(html, url)
```

## Стиль кода

- Используйте type hints везде
- Пишите docstrings для всех публичных функций и классов
- Следуйте PEP 8 (проверяется через ruff)
- Комментарии на русском для бизнес-логики
- Используйте async/await для всех I/O операций

## Архитектурные принципы

### Гибридная экстракция
- Предпочитайте точные методы (Schema.org) эвристическим
- LLM используется как основной fallback
- Избегайте эвристик, дающих ложные срабатывания

### Кэширование
- Все данные о сайтах кэшируются в SQLite
- Используйте `JobRepository.sync_jobs()` для синхронизации
- История изменений сохраняется автоматически

### Обработка ошибок
- При ошибке парсинга возвращайте пустой список, не бросайте исключения
- Логируйте все ошибки
- Career URL деактивируется после 3 неудачных попыток

### OpenRouter Provider Routing

Для повышения стабильности можно указать конкретный бэкенд-провайдер:

```python
from src.llm import get_llm_provider

# С явным указанием провайдера
llm = get_llm_provider("openrouter", model="openai/gpt-oss-120b", provider="chutes")

# Через настройки (src/config.py)
# OPENROUTER_PROVIDER=chutes
# OPENROUTER_ALLOW_FALLBACKS=true
```

Доступные провайдеры для `openai/gpt-oss-120b`:
- `chutes` - ~97.6% uptime (рекомендуется)
- `siliconflow` - ~97.7% uptime
- `novitaai`, `gmicloud`, `deepinfra`, `ncompass`

## Коммиты

Используйте понятные сообщения коммитов:
- `feat: добавлен парсер для Workable`
- `fix: исправлена обработка ошибок в HeadHunter API`
- `docs: обновлен README`
- `refactor: рефакторинг LLM провайдеров`
- `db: добавлена миграция для новой таблицы`

## Pull Requests

1. Создайте ветку от `main`
2. Внесите изменения
3. Убедитесь, что код проходит линтинг и тесты
4. Создайте PR с описанием изменений

## Тестирование

### Структура тестов

```
tests/
├── conftest.py                    # Общие фикстуры
├── fixtures/                      # Тестовые HTML файлы (21 файл)
│   │
│   │  # Job Board платформы
│   ├── greenhouse_style.html      # Greenhouse job board
│   ├── hibob_jobs.html            # HiBob job board
│   ├── hrworks_jobs.html          # HRworks job board
│   ├── lever_jobs.html            # Lever job board
│   ├── odoo_jobs.html             # Odoo CMS
│   ├── personio_jobs.html         # Personio job board
│   ├── recruitee_jobs.html        # Recruitee (embedded JSON)
│   ├── talention_jobs.html        # Talention job board
│   ├── workable_jobs.html         # Workable (JSON-LD)
│   │
│   │  # Custom sites (LLM extraction)
│   ├── schema_org_jobs.html       # Schema.org JSON-LD
│   ├── ui_city_jobs.html          # ui.city - Smart City
│   ├── abs_karriere_jobs.html     # abs-karriere.de - lazy loading
│   ├── 1nce_jobs.html             # 1nce.com - IoT
│   ├── 3p_services_jobs.html      # 3p-services.com - Pipeline
│   ├── 3ss_careers.html           # 3ss.tv - Streaming
│   ├── 4dd_werbeagentur_jobs.html # 4dd.de - Advertising
│   ├── 4pipes_jobs.html           # 4pipes
│   ├── 4zero_jobs.html            # 4zero
│   ├── 711media_jobs.html         # 711media.de - Digital
│   ├── 8com_jobs.html             # 8com.de - Security
│   └── pdf_links_jobs.html        # PDF links filtering
├── test_smoke_llm_base.py         # Smoke: LLM/HTML утилиты
├── test_smoke_prompts.py          # Smoke: промпты
├── test_smoke_browser.py          # Smoke: BrowserLoader
├── test_smoke_extraction.py       # Smoke: экстракция
├── test_integration_parsing.py    # Integration: парсинг с реальным HTML
├── test_job_board_parsers.py      # Job Board парсеры
├── test_website_filters.py        # Фильтрация вакансий
├── test_cache_manager.py          # CacheManager тесты
├── test_llm_cache.py              # LLM response cache тесты
├── test_translation.py            # Перевод названий
└── test_lazy_loading.py           # Lazy loading тесты
```

### Когда запускать тесты

| После изменений в | Запустить |
|-------------------|-----------|
| `src/llm/base.py`, `html_utils.py`, `job_extraction.py`, `url_discovery.py` | `pytest tests/test_smoke_llm_base.py tests/test_integration_parsing.py -v` |
| `src/llm/prompts.py` | `pytest tests/test_smoke_prompts.py -v` |
| `src/llm/cache.py` | `pytest tests/test_llm_cache.py -v` |
| `src/browser/loader.py` | `pytest tests/test_smoke_browser.py tests/test_lazy_loading.py -v` |
| `src/extraction/*.py` | `pytest tests/test_smoke_extraction.py tests/test_integration_parsing.py -v` |
| `src/searchers/job_boards/*.py` | `pytest tests/test_job_board_parsers.py -v` |
| `src/searchers/website.py`, `job_extraction.py`, `job_filters.py` | `pytest tests/test_website_filters.py -v` |
| `src/searchers/cache_manager.py` | `pytest tests/test_cache_manager.py -v` |

### Добавление тестового сайта

Если нашли сайт с проблемой парсинга:

1. Сохраните HTML: `curl https://example.com/careers > tests/fixtures/problem_site.html`
2. Добавьте тест в `test_integration_parsing.py`:
```python
def test_parses_problem_site(self):
    html = load_fixture("problem_site.html")
    strategy = SchemaOrgStrategy()
    candidates = strategy.extract(html, "https://example.com")
    assert len(candidates) == 5
```

## Отладка

### Включение debug логов
```bash
python main.py website https://example.com --verbose
```

### Проверка базы данных
```bash
python main.py sites  # Показать все сайты
python main.py history  # Показать историю изменений
```

### Поиск URL вакансий на странице
```bash
python main.py find-job-urls https://company.com/careers --verbose
```

### Отключение кэширования для тестов
```bash
python main.py website https://example.com --nodb
```

### Тестирование с разными OpenRouter провайдерами
```bash
# Тест с chutes (высокий uptime)
python main.py website https://example.com --openrouter-provider chutes

# Тест с siliconflow
python main.py website https://example.com --openrouter-provider siliconflow
```
