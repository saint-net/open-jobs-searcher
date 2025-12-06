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
pytest
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
3. Реализуйте методы:
   - `complete()` - базовый вызов LLM
   - Методы для экстракции наследуются от базового класса:
     - `find_careers_url()` - поиск страницы вакансий
     - `find_job_board_url()` - поиск внешнего job board
     - `find_job_urls()` - поиск URL вакансий на странице
     - `extract_jobs()` - извлечение вакансий через HybridJobExtractor
     - `extract_jobs_with_pagination()` - извлечение с пагинацией
     - `translate_job_titles()` - перевод названий на английский
4. Добавьте в `get_llm_provider()` factory в `src/llm/__init__.py`

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

## Структура тестов

```
tests/
├── test_searchers/       # Тесты поисковиков
├── test_extraction/      # Тесты экстракции
├── test_database/        # Тесты базы данных
├── test_llm/             # Тесты LLM провайдеров
└── conftest.py           # Фикстуры pytest
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
