# Smoke Tests

Быстрые smoke тесты для проверки критичных компонентов проекта.

## Запуск тестов

```bash
# Все smoke тесты
python -m pytest tests/ -v

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
| `src/llm/base.py` | `test_smoke_llm_base.py` |
| `src/llm/prompts.py` | `test_smoke_prompts.py` |
| `src/browser/loader.py` | `test_smoke_browser.py` |
| `src/extraction/*.py` | `test_smoke_extraction.py` |

### Рекомендуется перед коммитом

```bash
python -m pytest tests/ -q --tb=short
```

## Структура тестов

```
tests/
├── __init__.py
├── conftest.py              # Общие фикстуры
├── test_smoke_llm_base.py   # LLM: clean_html, extract_json, validate_jobs
├── test_smoke_prompts.py    # Промпты: форматирование, плейсхолдеры
├── test_smoke_browser.py    # Браузер: BrowserLoader, исключения
└── test_smoke_extraction.py # Экстракция: Schema.org, HybridExtractor
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

