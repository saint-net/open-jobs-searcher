# Tests

Тесты для проверки критичных компонентов проекта.

## Типы тестов

| Тип | Файл | Описание |
|-----|------|----------|
| Smoke | `test_smoke_*.py` | Быстрые проверки отдельных функций (95 тестов) |
| Integration | `test_integration_*.py` | Проверка парсинга с реальным HTML (28 тестов) |
| Job Boards | `test_job_board_parsers.py` | Тесты парсеров платформ (34 теста) |

## Запуск тестов

```bash
# ВСЕ тесты (157 штук, ~1 сек)
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

# Быстрый запуск без verbose
python -m pytest tests/ -q
```

## Когда запускать тесты

### Обязательно после изменений в:

| Файл | Тесты |
|------|-------|
| `src/llm/base.py` | `test_smoke_llm_base.py`, `test_integration_parsing.py` |
| `src/llm/prompts.py` | `test_smoke_prompts.py` |
| `src/browser/loader.py` | `test_smoke_browser.py` |
| `src/extraction/*.py` | `test_smoke_extraction.py`, `test_integration_parsing.py` |
| `src/searchers/job_boards/*.py` | `test_job_board_parsers.py` |

### Рекомендуется перед коммитом

```bash
python -m pytest tests/ -q --tb=short
```

## Структура тестов

```
tests/
├── __init__.py
├── conftest.py                    # Общие фикстуры
├── fixtures/                      # Тестовые HTML файлы
│   ├── schema_org_jobs.html       # Schema.org JSON-LD
│   ├── greenhouse_style.html      # Greenhouse-style layout
│   ├── lever_jobs.html            # Lever job board
│   ├── personio_jobs.html         # Personio job board
│   ├── recruitee_jobs.html        # Recruitee (embedded JSON)
│   ├── workable_jobs.html         # Workable (JSON-LD)
│   ├── odoo_jobs.html             # Odoo CMS page
│   ├── ui_city_jobs.html          # ui.city corporate site
│   ├── 1nce_jobs.html             # 1nce.com IoT company
│   └── 3p_services_jobs.html      # 3p-services.com pipeline inspection
├── test_smoke_llm_base.py         # LLM: clean_html, extract_json
├── test_smoke_prompts.py          # Промпты: форматирование
├── test_smoke_browser.py          # Браузер: BrowserLoader
├── test_smoke_extraction.py       # Экстракция: Schema.org
├── test_integration_parsing.py    # Парсинг с реальным HTML
└── test_job_board_parsers.py      # Job Board парсеры (Lever, Personio, etc.)
```

## Покрытие тестами

### `test_smoke_llm_base.py` (LLM base)
- `_clean_html()` - очистка HTML от скриптов, стилей
- `_extract_json()` - парсинг JSON из ответов LLM
- `_extract_url()` - извлечение URL из текста
- `_validate_jobs()` - валидация списка вакансий
- `_is_non_job_entry()` - фильтрация "не-вакансий"
- `_find_job_section()` - поиск секции с вакансиями
- `_extract_links_from_html()` - извлечение ссылок

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

### `test_job_board_parsers.py` (Job Board парсеры)
- **LeverParser** - `.posting`, `.posting-title` классы
- **PersonioParser** - `/job/ID` ссылки
- **RecruiteeParser** - embedded JSON, `/o/` ссылки
- **WorkableParser** - JSON-LD, `/j/` ссылки
- **GreenhouseParser** - `.opening`, `/jobs/` ссылки
- **OdooParser** - `.o_job`, `/jobs/detail/` ссылки

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

