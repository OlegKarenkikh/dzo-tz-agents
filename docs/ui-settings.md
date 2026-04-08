# Настройка UI — описание страницы «Настройки»

## Блок 1 — Текущая конфигурация (read-only)

Показывает фактические значения из `.env` при запуске сервиса:

| Параметр | Переменная окружения | Описание |
|---|---|---|
| UI_API_URL | `UI_API_URL` | URL бэкенда FastAPI |
| MODEL_NAME | `MODEL_NAME` | Модель LLM |
| LLM_BACKEND | `LLM_BACKEND` | Бэкенд модели (`openai`, `ollama`, `deepseek`, `vllm`, `lmstudio`, `github_models`) |
| OPENAI_API_BASE | `OPENAI_API_BASE` | Эндпоинт LLM API |
| AGENT_MODE | `AGENT_MODE` | `both` / `dzo` / `tz` / `tender` |
| FORCE_REPROCESS | `FORCE_REPROCESS` | Обход дедупликации |
| AGENT_TOOL_ENABLED | `AGENT_TOOL_ENABLED` | Разрешение межагентных вызовов |

## Блок 2 — Конструктор конфигурации

Интерактивный генератор `.env`-сниппета без перезапуска сервиса.

### Выбор бэкенда LLM

| Бэкенд | OPENAI_API_BASE | Рекомендуемый LLM_BACKEND |
|---|---|---|
| OpenAI | пусто (по умолчанию `api.openai.com/v1`) | `openai` |
| Ollama | `http://localhost:11434/v1` | `ollama` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek` |
| vLLM | `http://localhost:8000/v1` | `vllm` |
| LM Studio | `http://localhost:1234/v1` | `lmstudio` |
| Произвольный | любой обратно-совместимый URL | зависит от реализации endpoint |

### LLM_BACKEND

- **`openai`** — OpenAI API
- **`github_models`** — GitHub Models через OpenAI-compatible endpoint
- **`ollama`** — локальный Ollama
- **`deepseek`** — DeepSeek API
- **`vllm`** / **`lmstudio`** — локальные OpenAI-compatible endpoint

Все агенты используют единый `build_llm()` и `langgraph.prebuilt.create_react_agent`.

### Генерация сниппета

1. Выберите бэкенд LLM в selectbox
2. Выберите модель (или введите вручную)
3. Проверьте/измените `OPENAI_API_BASE`, `LLM_BACKEND`, `AGENT_MODE`
4. Нажмите **«Сгенерировать .env сниппет»**
5. Скопируйте или скачайте сгенерированный `.env.generated` в `.env`
6. Перезапустите сервис

## Блок 3 — Справочник моделей и эндпоинтов

Пять вкладок: **OpenAI**, **GitHub Models**, **Ollama**, **DeepSeek**, **vLLM / LM Studio**.

Каждая вкладка содержит таблицу `MODEL_NAME` с описанием и рекомендацию по `LLM_BACKEND`.

## Блок 4 — Тест соединения

Три кнопки:
- **«Проверить API (/health)»** — возвращает uptime, версию, модель, режим агента
- **«Список агентов (/agents)»** — выводит ID, названия и описания зарегистрированных агентов
- **«Статистика (/stats)»** — агрегированные показатели в JSON

## Страница «Тестирование» — динамический выбор агента

- Селектор «Выберите агента» заполняется динамически через `GET /agents`.
- Режим «Авто (определить по тексту)» использует `POST /api/v1/resolve-agent`.
- Полученный ID агента используется для проверки дубликатов (`/api/v1/check-duplicate`) и запуска обработки (`/api/v1/process/{agent}`).
- Во время ожидания результата отображается «живой журнал обработки» (последние события `processing_log`).

## Страница «Дашборд» — динамический ручной запуск

- Кнопки «Ручной запуск» формируются динамически по списку `GET /agents`.
- Кнопка «Запустить все» запускает обработку по всем зарегистрированным агентам, включая тендерный.

## Переменные окружения UI

| Переменная | По умолчанию | Описание |
|---|---|---|
| `UI_API_URL` | `http://localhost:8000` | URL бэкенда |
| `UI_API_KEY` | пусто | Ключ доступа к API |
| `UI_AUTO_REFRESH_SEC` | `30` | Deprecated: не используется — авто-обновление дашборда удалено, данные обновляются вручную |
| `LLM_BACKEND` | `openai` | Бэкенд LLM для отображения в UI |
| `FORCE_REPROCESS` | `false` | Обход дедупликации |
| `AGENT_TOOL_ENABLED` | `true` | Разрешить межагентные вызовы |
