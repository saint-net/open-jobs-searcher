# Архитектура проекта Open Jobs Searcher

## Обзор

Open Jobs Searcher - это инструмент для поиска вакансий с различных платформ, использующий комбинацию API запросов, веб-скрапинга и LLM для парсинга сайтов компаний.

## Основные компоненты

### 1. CLI интерфейс (`main.py`)

Точка входа приложения, использующая Typer для создания CLI команд:
- `search` - поиск на HeadHunter
- `stepstone` - поиск на StepStone.de
- `karriere` - поиск на Karriere.at
- `website` - универсальный поиск на сайте компании
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
- **WebsiteSearcher** (`website.py`) - универсальный парсер с LLM

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

### 4. LLM провайдеры (`src/llm/`)

#### BaseLLMProvider
Абстрактный класс для всех LLM провайдеров:
- `parse_jobs()` - парсинг HTML через LLM
- `extract_jobs()` - извлечение структурированных данных
- Единый интерфейс для разных провайдеров

#### Реализации
- **OllamaProvider** - локальный Ollama сервер
- **OpenRouterProvider** - OpenRouter API (поддержка 300+ моделей)

#### Промпты (`prompts.py`)
- Структурированные промпты для парсинга вакансий
- JSON schema для валидации ответов
- Поддержка разных языков

### 5. Браузерная автоматизация (`src/browser/`)

Модули для работы с Playwright:

- **loader.py** - загрузка SPA страниц
- **navigation.py** - навигация по сайту, поиск careers страниц
- **cookie_handler.py** - автоматическая обработка cookie consent
- **patterns.py** - паттерны для поиска элементов
- **exceptions.py** - кастомные исключения

### 6. HTTP клиент (`src/searchers/http_client.py`)

Асинхронный HTTP клиент с:
- Автоматическими retry
- Обработкой rate limits
- Таймаутами
- User-Agent ротацией

### 7. URL Discovery (`src/searchers/url_discovery.py`)

Поиск careers страниц на сайте компании:
- Проверка стандартных путей (/careers, /jobs, /vacancies)
- Поиск ссылок на странице
- Обнаружение внешних job board платформ

### 8. Конфигурация (`src/config.py`)

Pydantic Settings для управления настройками:
- Загрузка из `.env` файла
- Значения по умолчанию
- Валидация типов

### 9. Модели данных (`src/models.py`)

Pydantic модели для:
- Job (вакансия)
- Location (локация)
- Валидация и сериализация данных

### 10. Вывод результатов (`src/output.py`)

Форматирование и сохранение результатов:
- Красивый вывод в терминал (Rich)
- Экспорт в JSON
- Экспорт в CSV

## Потоки данных

### Поиск на HeadHunter/StepStone/Karriere
```
CLI → Searcher → API/HTTP → Parse → Models → Output
```

### Поиск на сайте компании
```
CLI → WebsiteSearcher → URL Discovery → 
  ↓
  [Job Board Detected?] → JobBoardParser → Models → Output
  ↓
  [No Job Board] → Browser/HTTP → LLM Provider → Parse → Models → Output
```

## Асинхронность

Проект полностью асинхронный:
- Все HTTP запросы через `httpx.AsyncClient` или `aiohttp`
- Браузерные операции через Playwright async API
- Конкурентный поиск на нескольких платформах (в будущем)

## Обработка ошибок

- Кастомные исключения для специфичных ошибок
- Graceful degradation - при ошибке парсинга возвращается пустой список
- Логирование всех ошибок для отладки
- Retry логика для сетевых запросов

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

## Зависимости

### Основные
- `httpx` - асинхронные HTTP запросы
- `beautifulsoup4` - парсинг HTML
- `playwright` - браузерная автоматизация
- `pydantic` - валидация данных
- `typer` - CLI интерфейс
- `rich` - красивый вывод

### LLM
- `openai` (через OpenRouter) - для LLM запросов
- `ollama` (локально) - альтернативный провайдер

## Производительность

- Асинхронные операции для параллельной обработки
- Кэширование результатов парсинга (в будущем)
- Оптимизация LLM промптов для меньшего количества токенов
- Ленивая загрузка браузера (только при необходимости)

## Безопасность

- API ключи хранятся в `.env` файле (не в репозитории)
- User-Agent ротация для избежания блокировок
- Таймауты для всех сетевых запросов
- Валидация входных данных через Pydantic

