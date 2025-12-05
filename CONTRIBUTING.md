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
3. Реализуйте методы `parse_jobs()` и `extract_jobs()`
4. Добавьте в `get_llm_provider()` factory

### Новый Job Board парсер
1. Создайте файл в `src/searchers/job_boards/`
2. Наследуйте `BaseJobBoardParser`
3. Реализуйте метод `parse()`
4. Зарегистрируйте в `JobBoardParserRegistry._register_defaults()`
5. Добавьте паттерн в `detector.py` (EXTERNAL_JOB_BOARDS)

## Стиль кода

- Используйте type hints везде
- Пишите docstrings для всех публичных функций и классов
- Следуйте PEP 8 (проверяется через ruff)
- Комментарии на русском для бизнес-логики
- Используйте async/await для всех I/O операций

## Коммиты

Используйте понятные сообщения коммитов:
- `feat: добавлен парсер для Workable`
- `fix: исправлена обработка ошибок в HeadHunter API`
- `docs: обновлен README`
- `refactor: рефакторинг LLM провайдеров`

## Pull Requests

1. Создайте ветку от `main`
2. Внесите изменения
3. Убедитесь, что код проходит линтинг и тесты
4. Создайте PR с описанием изменений

