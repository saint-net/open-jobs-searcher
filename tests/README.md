# Tests

Тесты для проверки критичных компонентов проекта.

## Типы тестов

| Тип | Файл | Описание |
|-----|------|----------|
| Smoke | `test_smoke_*.py` | Быстрые проверки отдельных функций |
| Integration | `test_integration_*.py` | Проверка парсинга с реальным HTML |
| Job Boards | `test_job_board_parsers.py` | Тесты парсеров платформ |
| Filters | `test_website_filters.py` | Фильтрация вакансий |
| Cache | `test_cache_manager.py` | CacheManager и дедупликация |
| LLM Cache | `test_llm_cache.py` | LLM response кэширование |
| Translation | `test_translation.py` | Перевод названий вакансий |
| Lazy Loading | `test_lazy_loading.py` | Lazy loading в браузере |

## Запуск тестов

```bash
# ВСЕ тесты (~363 штуки, ~2.5 мин)
python -m pytest tests/ -v

# Только smoke тесты (быстро)
python -m pytest tests/test_smoke_*.py -v

# Только интеграционные (после изменений в парсинге)
python -m pytest tests/test_integration_parsing.py -v

# Конкретный модуль
python -m pytest tests/test_smoke_llm_base.py -v
python -m pytest tests/test_smoke_prompts.py -v
python -m pytest tests/test_smoke_browser.py -v
python -m pytest tests/test_smoke_extraction.py -v
python -m pytest tests/test_llm_cache.py -v

# Быстрый запуск без verbose
python -m pytest tests/ -q
```

## Когда запускать тесты

### Обязательно после изменений в:

| Файл | Тесты |
|------|-------|
| `src/llm/base.py`, `html_utils.py`, `job_extraction.py`, `url_discovery.py` | `test_smoke_llm_base.py`, `test_integration_parsing.py` |
| `src/llm/prompts.py` | `test_smoke_prompts.py` |
| `src/llm/cache.py` | `test_llm_cache.py` |
| `src/browser/loader.py` | `test_smoke_browser.py`, `test_lazy_loading.py` |
| `src/extraction/*.py` | `test_smoke_extraction.py`, `test_integration_parsing.py` |
| `src/searchers/job_boards/*.py` | `test_job_board_parsers.py` |
| `src/searchers/website.py`, `page_fetcher.py`, `job_converter.py`, `company_info.py` | все тесты |
| `src/searchers/job_extraction.py`, `job_filters.py` | `test_website_filters.py` |
| `src/searchers/cache_manager.py` | `test_cache_manager.py` |
| `src/searchers/url_discovery.py` | `test_integration_parsing.py` |

### Рекомендуется перед коммитом

```bash
python -m pytest tests/ -q --tb=short
```

## Структура тестов

```
tests/
├── __init__.py
├── conftest.py                    # Общие фикстуры
├── fixtures/                      # Тестовые HTML файлы (21 файл)
│   │
│   │  # Job Board платформы (специализированные парсеры)
│   ├── greenhouse_style.html      # Greenhouse job board
│   ├── hibob_jobs.html            # HiBob job board (Angular SPA)
│   ├── hrworks_jobs.html          # HRworks job board
│   ├── lever_jobs.html            # Lever job board
│   ├── odoo_jobs.html             # Odoo CMS
│   ├── personio_jobs.html         # Personio job board
│   ├── recruitee_jobs.html        # Recruitee (embedded JSON)
│   ├── talention_jobs.html        # Talention job board
│   ├── workable_jobs.html         # Workable (JSON-LD)
│   │
│   │  # Custom sites (LLM extraction)
│   ├── schema_org_jobs.html       # Schema.org JSON-LD (custom site)
│   ├── ui_city_jobs.html          # ui.city - Custom site (Smart City)
│   ├── abs_karriere_jobs.html     # abs-karriere.de - lazy loading
│   ├── 1nce_jobs.html             # 1nce.com - Custom site (IoT)
│   ├── 3p_services_jobs.html      # 3p-services.com - Custom site (Pipeline)
│   ├── 3ss_careers.html           # 3ss.tv - Streaming
│   ├── 4dd_werbeagentur_jobs.html # 4dd.de - Advertising
│   ├── 4pipes_jobs.html           # 4pipes
│   ├── 4zero_jobs.html            # 4zero
│   ├── 711media_jobs.html         # 711media.de - Digital
│   ├── 8com_jobs.html             # 8com.de - Security
│   └── pdf_links_jobs.html        # PDF links filtering
├── test_smoke_llm_base.py         # LLM/HTML утилиты: clean_html, extract_json, html_to_markdown
├── test_smoke_prompts.py          # Промпты: форматирование
├── test_smoke_browser.py          # Браузер: BrowserLoader
├── test_smoke_extraction.py       # Экстракция: Schema.org
├── test_integration_parsing.py    # Парсинг с реальным HTML
├── test_job_board_parsers.py      # Job Board парсеры (Lever, Personio, HiBob, etc.)
├── test_website_filters.py        # Фильтрация вакансий
├── test_cache_manager.py          # CacheManager тесты
├── test_llm_cache.py              # LLM response cache тесты
├── test_translation.py            # Перевод названий
└── test_lazy_loading.py           # Lazy loading тесты
```

## Покрытие тестами

### `test_smoke_llm_base.py` (LLM/HTML утилиты)

**html_utils.py:**
- `clean_html()` - очистка HTML от скриптов, стилей, cookie dialogs
- `html_to_markdown()` - конвертация HTML в Markdown для экономии токенов
- `extract_json()` - парсинг JSON из ответов LLM
- `extract_url()` - извлечение URL из текста
- `find_job_section()` - поиск секции с вакансиями

**job_extraction.py:**
- `validate_jobs()` - валидация списка вакансий
- `is_non_job_entry()` - фильтрация "не-вакансий" (Initiativbewerbung)

**url_discovery.py:**
- `extract_links_from_html()` - извлечение ссылок

### `test_smoke_prompts.py` (Промпты)
- Проверка наличия всех промптов
- Проверка форматирования без ошибок
- Проверка наличия маркеров безопасности (UNTRUSTED)
- Проверка плейсхолдеров

### `test_smoke_browser.py` (Браузер)
- Инициализация `BrowserLoader`
- Context manager (`async with`)
- Обработка ошибок (`DomainUnreachableError`)
- Паттерны (`DEFAULT_USER_AGENT`, `NETWORK_ERROR_PATTERNS`)

### `test_smoke_extraction.py` (Экстракция)
- `SchemaOrgStrategy` - парсинг JSON-LD, @graph, microdata
- `HybridJobExtractor` - интеграция стратегий
- `JobCandidate` - модель вакансии
- `is_likely_job_title()` - определение job titles

### `test_integration_parsing.py` (Интеграционные)
- Парсинг Schema.org из реального HTML
- Fallback на LLM когда нет Schema.org
- Определение Odoo сайтов
- Очистка HTML перед отправкой в LLM
- Валидация и фильтрация результатов
- Тесты парсинга реальных сайтов (ui.city, 1nce, 3p-services, 3ss, 4dd, 4zero, 711media, 8com)

### `test_job_board_parsers.py` (Job Board парсеры)
- **LeverParser** - `.posting`, `.posting-title` классы
- **PersonioParser** - `/job/ID` ссылки
- **RecruiteeParser** - embedded JSON, `/o/` ссылки
- **WorkableParser** - JSON-LD, `/j/` ссылки
- **GreenhouseParser** - `.opening`, `/jobs/` ссылки
- **OdooParser** - `.o_job`, `/jobs/detail/` ссылки
- **HRworksParser** - HRworks job board
- **HiBobParser** - HiBob Angular SPA (`b-virtual-scroll-list-item`)
- **TalentionDetection** - Talention platform detection

### `test_llm_cache.py` (LLM Cache)
- Кэширование ответов с namespace-based TTL
- `CacheNamespace`: JOBS (6h), TRANSLATION (30d), URL_DISCOVERY (7d), COMPANY_INFO (30d)
- Статистика: hits, misses, tokens saved

### `test_translation.py` (Перевод)
- Перевод названий вакансий на английский
- Валидация переводов
- Dictionary fallback для частых терминов

### `test_lazy_loading.py` (Lazy Loading)
- Обработка lazy loading на страницах
- Scrolling для загрузки контента

### `test_website_filters.py` (Фильтрация)
- Нормализация доменов
- Фильтрация вакансий по поисковому запросу
- Определение редиректов доменов

## Добавление новых тестов

```python
# В соответствующем файле test_smoke_*.py

class TestNewFeature:
    """Tests for new feature."""
    
    def test_basic_functionality(self):
        """Should work with valid input."""
        result = new_feature("valid input")
        assert result is not None
    
    def test_handles_edge_cases(self):
        """Should handle edge cases gracefully."""
        result = new_feature("")
        assert result == expected_default
```

## Зависимости

- `pytest>=8.0.0`
- `pytest-asyncio>=0.23.0`
