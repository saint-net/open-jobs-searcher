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
- **WebsiteSearcher** (`website.py`) - универсальный парсер с LLM и кэшированием

### 3. Job Board парсеры (`src/searchers/job_boards/`)

Автоматическое определение и парсинг популярных платформ:

#### Архитектура
- **BaseJobBoardParser** - абстрактный класс для парсеров
- **JobBoardParserRegistry** - реестр всех парсеров
- **detector.py** - автоматическое определение платформы по URL/HTML

#### Поддерживаемые платформы
- Personio, Greenhouse, Lever - HTML парсинг
- Workable, Deloitte - HTML парсинг
- Recruitee - API-based парсинг

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

#### BaseLLMProvider
Абстрактный класс для всех LLM провайдеров:
- `complete()` - генерация ответа
- `find_careers_url()` - поиск страницы вакансий
- `extract_jobs()` - извлечение вакансий через HybridJobExtractor
- `translate_job_titles()` - перевод названий на английский
- Фильтрация не-вакансий (Initiativbewerbung и др.)

#### Реализации
- **OllamaProvider** - локальный Ollama сервер
- **OpenRouterProvider** - OpenRouter API (поддержка 300+ моделей, дефолт: openai/gpt-oss-120b)

#### Промпты (`prompts.py`)
- Структурированные промпты для парсинга вакансий
- JSON schema для валидации ответов
- Поддержка разных языков

### 7. Браузерная автоматизация (`src/browser/`)

Модули для работы с Playwright:

- **loader.py** - загрузка SPA страниц
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

### 9. URL Discovery (`src/searchers/url_discovery.py`)

Поиск careers страниц на сайте компании:
- Проверка стандартных путей (/careers, /jobs, /vacancies)
- Поиск ссылок на странице
- Обнаружение внешних job board платформ

### 10. Конфигурация (`src/config.py`)

Pydantic Settings для управления настройками:
- Загрузка из `.env` файла
- Значения по умолчанию
- Валидация типов

### 11. Модели данных (`src/models.py`)

Pydantic модели для:
- Job (вакансия)
- Location (локация)
- Валидация и сериализация данных

### 12. Вывод результатов (`src/output.py`)

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
                                                     JobRepository.sync_jobs()
                                                           ↓
                                                     SyncResult (new/removed/reactivated)
                                                           ↓
                                                        Output
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

- Кастомные исключения для специфичных ошибок
- Graceful degradation - при ошибке парсинга возвращается пустой список
- Логирование всех ошибок для отладки
- Retry логика для сетевых запросов
- Career URL деактивация после 3 неудачных попыток

## Расширяемость

### Добавление нового поисковика
1. Наследовать `BaseSearcher`
2. Реализовать `search()` метод
3. Добавить команду в `main.py`

### Добавление нового LLM провайдера
1. Наследовать `BaseLLMProvider`
2. Реализовать методы парсинга
3. Добавить в factory функцию

### Добавление нового Job Board парсера
1. Наследовать `BaseJobBoardParser`
2. Реализовать `parse()` метод
3. Зарегистрировать в `JobBoardParserRegistry`
4. Добавить паттерн в `detector.py`

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
- `openai` (через OpenRouter) - для LLM запросов
- `ollama` (локально) - альтернативный провайдер

## Производительность

- Асинхронные операции для параллельной обработки
- Кэширование вакансий в SQLite
- Оптимизация LLM промптов для меньшего количества токенов
- Ленивая загрузка браузера (только при необходимости)
- Инкрементальная синхронизация (только изменения)

## Безопасность

- API ключи хранятся в `.env` файле (не в репозитории)
- User-Agent ротация для избежания блокировок
- Таймауты для всех сетевых запросов
- Валидация входных данных через Pydantic
