# Архитектура проекта Open Jobs Searcher

## Обзор

Open Jobs Searcher - это инструмент для поиска вакансий с различных платформ, использующий комбинацию API запросов, веб-скрапинга и LLM для парсинга сайтов компаний. Система поддерживает кэширование вакансий и отслеживание изменений.

## Основные компоненты

### 1. CLI интерфейс (`main.py`)

Точка входа приложения, использующая Typer для создания CLI команд:
- `search` - поиск на HeadHunter
- `stepstone` - поиск на StepStone.de
- `karriere` - поиск на Karriere.at
- `website` - универсальный поиск на сайте компании
- `find-job-urls` - поиск URL вакансий на странице через LLM
- `history` - просмотр истории изменений вакансий
- `sites` - просмотр кэшированных сайтов
- `info` - информация о приложении

### 2. Поисковики (`src/searchers/`)

#### BaseSearcher
Базовый абстрактный класс для всех поисковиков:
- Асинхронный context manager
- Единый интерфейс `search()`
- Обработка ошибок и логирование

#### Специализированные поисковики
- **HeadHunterSearcher** (`hh.py`) - использует официальный API HeadHunter
- **StepStoneSearcher** (`stepstone.py`) - парсинг HTML StepStone.de
- **KarriereATSearcher** (`karriere.py`) - парсинг HTML Karriere.at
- **WebsiteSearcher** (`website.py`) - оркестратор для универсального парсинга

#### Вспомогательные модули
- **PageFetcher** (`page_fetcher.py`) - унифицированная загрузка страниц (HTTP + Browser)
- **JobConverter** (`job_converter.py`) - конвертация raw job data → Job модели + перевод
- **CompanyInfoExtractor** (`company_info.py`) - извлечение и сохранение информации о компании

### 3. Job Board парсеры (`src/searchers/job_boards/`)

Автоматическое определение и парсинг популярных платформ:

#### Архитектура
- **BaseJobBoardParser** - абстрактный класс для парсеров
- **JobBoardParserRegistry** - реестр всех парсеров
- **detector.py** - автоматическое определение платформы по URL/HTML

#### Поддерживаемые платформы
- Personio, Greenhouse, Lever - HTML парсинг
- Workable, Deloitte - HTML парсинг
- HRworks, HiBob - HTML парсинг
- Odoo - CMS парсинг
- Recruitee - API-based парсинг
- SmartRecruiters, Ashby, Breezy HR - HTML парсинг
- BambooHR, Factorial - HTML парсинг

### 4. База данных (`src/database/`)

SQLite для кэширования вакансий и отслеживания изменений:

#### Компоненты
- **connection.py** - подключение к БД, схема таблиц
- **models.py** - dataclass модели (Site, CareerUrl, CachedJob, JobHistoryEvent, SyncResult)
- **repository.py** - JobRepository для CRUD операций

#### Схема базы данных
```
sites (id, domain, name, created_at, last_scanned_at)
  ↓
career_urls (id, site_id, url, platform, is_active, fail_count, ...)
  ↓
jobs (id, site_id, title, title_en, location, url, is_active, ...)
  ↓
job_history (id, job_id, event, changed_at, details)
```

#### События истории
- `added` - вакансия появилась впервые
- `removed` - вакансия больше не найдена
- `reactivated` - вакансия вернулась после удаления

### 5. Гибридная экстракция (`src/extraction/`)

Упрощённая система извлечения вакансий без ложных срабатываний:

#### Компоненты
- **extractor.py** - HybridJobExtractor (основной класс)
- **candidate.py** - JobCandidate с системой scoring
- **strategies.py** - SchemaOrgStrategy (единственная эвристическая стратегия)

#### Стратегия извлечения
1. **Schema.org** (100% точность, ~20-30% сайтов) - структурированные данные JobPosting
2. **LLM** (основной метод) - GPT-модель анализирует HTML

#### JobCandidate scoring
Система оценки уверенности с сигналами:
- Позитивные: `has_gender_notation`, `has_job_url`, `title_has_keywords`
- Негативные: `too_long`, `looks_like_nav`, `has_non_job_words`

### 6. LLM провайдеры (`src/llm/`)

#### BaseLLMProvider (`base.py`)
Абстрактный класс для всех LLM провайдеров:
- `complete()` - генерация ответа (абстрактный)
- `find_careers_url()` - поиск страницы вакансий (HTML + sitemap)
- `find_job_board_url()` - поиск внешнего job board на странице карьеры
- `find_job_urls()` - поиск URL отдельных вакансий на странице
- `extract_jobs()` - извлечение вакансий через HybridJobExtractor
- `extract_jobs_with_pagination()` - извлечение с поддержкой пагинации
- `translate_job_titles()` - перевод названий на английский
- `extract_company_info()` - извлечение описания компании

Использует Composition для делегирования:
- `LLMJobExtractor` - извлечение вакансий
- `LLMUrlDiscovery` - поиск URL карьеры/job board

#### HTML утилиты (`html_utils.py`)
- `clean_html()` - очистка HTML от скриптов, стилей, cookie dialogs
- `html_to_markdown()` - конвертация HTML в Markdown для уменьшения токенов (до 70% экономии)
- `extract_url()` - извлечение URL из ответа LLM
- `extract_json()` - парсинг JSON из ответа LLM (markdown блоки, raw JSON)

#### LLM Cache (`cache.py`)
Кэширование LLM ответов с разными TTL по типам операций:
- `LLMCache` - основной класс кэша
- `CacheNamespace` - пространства имён:
  - `JOBS` - 6 часов (вакансии часто меняются)
  - `TRANSLATION` - 30 дней (переводы стабильны)
  - `URL_DISCOVERY` - 7 дней (career URLs редко меняются)
  - `COMPANY_INFO` - 30 дней (описания компаний стабильны)
- Статистика: hits/misses, tokens saved, estimated cost saved

#### LLMJobExtractor (`job_extraction.py`)
Извлечение вакансий через LLM:
- `extract_jobs()` - гибридная экстракция (Schema.org + LLM)
- `extract_jobs_with_pagination()` - с поддержкой next_page_url
- `validate_jobs()` - валидация и фильтрация не-вакансий
- Retry логика при пустых результатах (MAX_LLM_RETRIES)

#### HTML утилиты (`html_utils.py`)
Подготовка HTML для LLM:
- `clean_html()` - очистка от скриптов, стилей, лишних атрибутов
- `html_to_markdown()` - конвертация в Markdown (3-5x экономия токенов)
- `find_job_section()` - поиск секции с вакансиями в HTML
- `extract_json()` - извлечение JSON из LLM-ответа

#### LLMUrlDiscovery (`url_discovery.py`)
Поиск URL через LLM:
- `find_careers_url()` - поиск страницы вакансий
- `find_job_board_url()` - поиск внешнего job board
- `find_careers_url_from_sitemap()` - поиск в sitemap URLs
- `find_job_urls()` - поиск URL отдельных вакансий

#### Реализации
- **OllamaProvider** (`ollama.py`) - локальный Ollama сервер
- **OpenRouterProvider** (`openrouter.py`) - OpenRouter API с Provider Routing:
  - Поддержка 300+ моделей
  - Дефолтная модель: `openai/gpt-4o-mini`
  - **Provider Routing** ([docs](https://openrouter.ai/docs/features/provider-routing)):
    - `provider` - конкретный бэкенд (azure, openai, deepinfra, etc.)
    - `provider_order` - список провайдеров в порядке приоритета
    - `require_parameters` - требуемые параметры (json_schema, tools, etc.)
    - `allow_fallbacks` - разрешать fallback при ошибках
  - Логирование фактического провайдера из ответа
  - Retry logic для transient errors (502, 503, rate limit)
  - Structured Output: `response_format={"type": "json_schema"}` для строгой типизации

#### Промпты (`prompts.py`)
- Структурированные промпты для парсинга вакансий
- JSON schema для валидации ответов
- Поддержка пагинации (next_page_url в ответе)
- Поддержка разных языков

### 7. Браузерная автоматизация (`src/browser/`)

Модули для работы с Playwright:

- **loader.py** - загрузка SPA страниц:
  - `fetch()` - простая загрузка HTML
  - `fetch_with_navigation()` - загрузка с навигацией к вакансиям
  - `fetch_with_page()` - загрузка с возвратом Page объекта
  - Автоматическая установка браузеров при первом запуске
- **navigation.py** - навигация по сайту, поиск careers страниц
- **cookie_handler.py** - автоматическая обработка cookie consent
- **patterns.py** - паттерны для поиска элементов
- **exceptions.py** - кастомные исключения

### 8. HTTP клиент (`src/searchers/http_client.py`)

Асинхронный HTTP клиент с:
- Автоматическими retry
- Обработкой rate limits
- Таймаутами
- User-Agent ротацией
- Domain availability check

### 9. URL Discovery (`src/searchers/url_discovery.py`)

Поиск careers страниц на сайте компании:
- Проверка стандартных путей (/careers, /jobs, /vacancies)
- Поиск ссылок на странице
- Обнаружение внешних job board платформ
- Генерация URL вариантов (plural/singular)

### 10. Конфигурация (`src/config.py`)

Pydantic Settings для управления настройками:
- Загрузка из `.env` файла
- Значения по умолчанию
- Валидация типов
- OpenRouter provider routing настройки:
  - `openrouter_provider` - конкретный бэкенд (например: `azure`)
  - `openrouter_provider_order` - список через запятую (например: `azure,openai`)
  - `openrouter_require_parameters` - требуемые параметры (например: `json_schema`)
  - `openrouter_allow_fallbacks` - разрешать fallback при ошибках

### 11. Константы (`src/constants.py`)

Централизованные константы:
- **Пагинация**: `MAX_PAGINATION_PAGES`, `MAX_SITEMAP_URLS`
- **LLM**: `MAX_LLM_RETRIES`, `MAX_URLS_FOR_LLM`, `LLM_TIMEOUT`
- **HTML лимиты**: `MIN_JOB_SECTION_SIZE`, `MAX_JOB_SECTION_SIZE`
- **Браузер**: таймауты для навигации, ожидания, CF challenge

### 12. CacheManager (`src/searchers/cache_manager.py`)

Управление кэшированием career URLs и вакансий:
- `search_with_cache()` - поиск через кэшированные URL
- `save_to_cache()` - сохранение career URL и вакансий
- `_deduplicate_jobs()` - дедупликация по URL или (title, location)
- Отслеживание изменений (new/removed/reactivated)
- Автоматическое извлечение информации о компании

### 13. JobExtractor (`src/searchers/job_extraction.py`)

Извлечение вакансий с career pages:
- `extract_jobs()` - с пагинацией (до MAX_PAGINATION_PAGES страниц)
- Дедупликация между страницами
- Автоматическое определение job board платформ
- Fallback на LLM при отсутствии структурированных данных

### 14. Фильтры (`src/searchers/job_filters.py`)

Фильтрация и нормализация вакансий:
- `normalize_title()` - удаление gender notation (m/w/d)
- `normalize_location()` - удаление country/employment type suffixes
- `filter_jobs_by_search_query()` - фильтрация по поисковому запросу
- `filter_jobs_by_source_company()` - фильтрация по исходной компании

### 15. Модели данных (`src/models.py`)

Pydantic модели для:
- Job (вакансия)
- Location (локация)
- JobDict, JobExtractionResult (TypedDict для LLM)
- Валидация и сериализация данных

### 16. Вывод результатов (`src/output.py`)

Форматирование и сохранение результатов:
- Красивый вывод в терминал (Rich)
- Экспорт в JSON
- Экспорт в CSV

## Потоки данных

### Поиск на HeadHunter/StepStone/Karriere
```
CLI → Searcher → API/HTTP → Parse → Models → Output
```

### Поиск на сайте компании (с кэшированием)
```
CLI → WebsiteSearcher → URL Discovery → 
  ↓
  [Job Board Detected?] → JobBoardParser → Models
  ↓                                          ↓
  [No Job Board] → Browser/HTTP → HybridExtractor → LLM/Schema.org → Models
                                                                        ↓
                                                     [Pagination?] → LLM (next pages)
                                                           ↓
                                                     JobRepository.sync_jobs()
                                                           ↓
                                                     SyncResult (new/removed/reactivated)
                                                           ↓
                                                        Output
```

### Поиск URL вакансий (find-job-urls)
```
CLI → Browser → LLM.find_job_urls() → List[URLs] → Output
```

### Просмотр истории
```
CLI (history) → JobRepository → job_history table → Output
```

## Асинхронность

Проект полностью асинхронный:
- Все HTTP запросы через `httpx.AsyncClient` или `aiohttp`
- Браузерные операции через Playwright async API
- База данных через `aiosqlite`
- Конкурентный поиск на нескольких платформах (в будущем)

## Обработка ошибок

- Кастомные исключения для специфичных ошибок:
  - `DomainUnreachableError` - домен недоступен
  - `PlaywrightBrowsersNotInstalledError` - браузеры не установлены
- Graceful degradation - при ошибке парсинга возвращается пустой список
- Логирование всех ошибок для отладки
- Retry логика для сетевых запросов и LLM API
- Career URL деактивация после 3 неудачных попыток

## Расширяемость

### Добавление нового поисковика
1. Наследовать `BaseSearcher`
2. Реализовать `search()` метод
3. Добавить команду в `main.py`

### Добавление нового LLM провайдера
1. Наследовать `BaseLLMProvider`
2. Реализовать `complete()` метод
3. Добавить в factory функцию `get_llm_provider()`

### Добавление нового Job Board парсера
1. Наследовать `BaseJobBoardParser`
2. Реализовать `parse()` метод
3. Для API-based платформ: `get_api_url()`, `parse_api_json()`
4. Зарегистрировать в `JobBoardParserRegistry`
5. Добавить паттерн в `detector.py`

### Добавление новой стратегии экстракции
1. Создать класс в `src/extraction/strategies.py`
2. Реализовать метод `extract(html, url) -> list[JobCandidate]`
3. Добавить в `HybridJobExtractor` (если нужно)

## Зависимости

### Основные
- `httpx` - асинхронные HTTP запросы
- `beautifulsoup4` - парсинг HTML
- `playwright` - браузерная автоматизация
- `pydantic` - валидация данных
- `typer` - CLI интерфейс
- `rich` - красивый вывод

### База данных
- `aiosqlite` - асинхронная работа с SQLite

### LLM
- OpenRouter API (через httpx) - для LLM запросов
- Ollama (через aiohttp) - альтернативный локальный провайдер

## Производительность

- Асинхронные операции для параллельной обработки
- Кэширование вакансий в SQLite
- Оптимизация LLM промптов для меньшего количества токенов
- Ленивая загрузка браузера (только при необходимости)
- Инкрементальная синхронизация (только изменения)
- Пагинация: до 3 страниц по умолчанию (MAX_PAGINATION_PAGES)
- Дедупликация вакансий при пагинации

## Безопасность

- API ключи хранятся в `.env` файле (не в репозитории)
- User-Agent ротация для избежания блокировок
- Таймауты для всех сетевых запросов
- Валидация входных данных через Pydantic
- Provider routing для стабильности LLM запросов

## Тестирование

### Типы тестов

| Тип | Файлы | Описание |
|-----|-------|----------|
| Smoke | `test_smoke_*.py` | Быстрые проверки отдельных функций |
| Integration | `test_integration_*.py` | Парсинг с сохранённым HTML |
| Job Boards | `test_job_board_parsers.py` | Парсеры платформ |
| Filters | `test_website_filters.py` | Фильтрация вакансий |
| Cache | `test_cache_manager.py`, `test_llm_cache.py` | CacheManager, LLM cache |
| Translation | `test_translation.py` | Перевод названий |
| Lazy Loading | `test_lazy_loading.py` | Lazy loading в браузере |

### Структура

```
tests/
├── fixtures/                      # Тестовые HTML (21 файл)
├── test_smoke_*.py                # Smoke тесты модулей
├── test_integration_parsing.py    # E2E парсинг
├── test_job_board_parsers.py      # Lever, Personio, Recruitee, Workable, Greenhouse, Odoo, HRworks, HiBob
├── test_website_filters.py        # Фильтрация и нормализация
├── test_cache_manager.py          # CacheManager тесты
├── test_llm_cache.py              # LLM cache тесты
├── test_translation.py            # Перевод названий
└── test_lazy_loading.py           # Lazy loading тесты
```

### Запуск

```bash
python -m pytest tests/ -q                        # Все тесты (~363 штуки, ~2.5 мин)
python -m pytest tests/test_job_board_parsers.py  # После изменений в job_boards/
python -m pytest tests/test_cache_manager.py      # После изменений в cache_manager
python -m pytest tests/test_llm_cache.py          # После изменений в llm/cache.py
```
