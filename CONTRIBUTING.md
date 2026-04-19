# Contributing Guide — dzo-tz-agents

## Branch Naming

| Тип | Паттерн | Пример |
|-----|---------|--------|
| Feature | `feat/<short-desc>` | `feat/agent9-property-parser` |
| Fix | `fix/<short-desc>` | `fix/delete-status-204` |
| Chore | `chore/<short-desc>` | `chore/update-deps` |
| Docs | `docs/<short-desc>` | `docs/contributing` |
| Hotfix | `hotfix/<short-desc>` | `hotfix/jwt-decode-error` |

## Commit Message Format (Conventional Commits)

```
<type>(<scope>): <description>

[optional body]

Fixes: ISSUE-XXX
```

Допустимые типы: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `ci`, `perf`.

Scope — имя модуля или агента: `api`, `shared`, `agent1`, `ci`, `schemas`, `database`.

Пример:
```
fix(api): DELETE /jobs/{id} → status_code=204, response_model=None

Fixes: MAJOR-02
Audit session: 2026-04-19
```

## Pull Request Process

1. Создать ветку от `main` по naming convention выше.
2. Все изменения должны проходить `ruff check .` и `mypy shared/ api/ config.py --ignore-missing-imports` без ошибок.
3. Тесты: `pytest tests/ -v --tb=short -m "not e2e and not integration"` — все зелёные.
4. Docker build: `docker build --target production .` — без warnings.
5. Минимум 1 reviewer для merge в `main`.
6. Merge strategy: **Squash and merge** для feature/fix, **Merge commit** для hotfix.

## Code Style

- **Formatter/Linter:** `ruff` (конфиг в `pyproject.toml`)
- **Type checker:** `mypy --ignore-missing-imports` (запускается в CI)
- **Python target:** 3.11+
- Используйте `X | None` вместо `Optional[X]`
- Используйте `list[X]`, `dict[K, V]` вместо `List[X]`, `Dict[K, V]`

## Naming Conventions

### Backend

| Категория | Паттерн | Пример |
|-----------|---------|--------|
| Service class | `XxxService` | `PackageService` |
| Repository class | `XxxRepository` | `JobRepository` |
| Analyzer class | `XxxAnalyzer` | `DocumentAnalyzer` |
| Pydantic Input | `CreateXxxRequest` / `XxxRequest` | `ProcessRequest` |
| Pydantic Output | `XxxResponse` / `XxxSchema` | `JobResponse` |
| SQLAlchemy Model | `Xxx` (PascalCase, singular) | `Job` |
| Route function | `verb_noun` (snake_case) | `get_job`, `delete_job` |
| Service method | `verb_noun` | `build_package`, `analyze_document` |

### Frontend (если добавляется)

| Категория | Паттерн | Пример |
|-----------|---------|--------|
| View | `XxxView.vue` | `JobsView.vue` |
| UI component | `BaseXxx.vue` | `BaseButton.vue` |
| Composable | `useXxx.ts` | `useJobs.ts` |
| Store (Pinia) | `useXxxStore` | `useJobStore` |
| API service | `xxxApi.ts` | `jobsApi.ts` |

## Domain Glossary

| Термин | Описание |
|--------|----------|
| ДЗО | Дочернее/зависимое общество — организация в составе холдинга |
| ТЗ | Техническое задание |
| ТО | Тендерный отбор |
| ECP | Электронная цифровая подпись |
| EIS | Единая информационная система в сфере закупок |
| DA | Документарный агент (внешний API для обработки страховых контрактов) |
| CBR | Центральный банк РФ (Банк России) |
| ОСАГО | Обязательное страхование гражданской ответственности владельцев транспортных средств |
| ОСГОП | Обязательное страхование гражданской ответственности перевозчика |
| МСП | Малое/среднее предпринимательство |
| A2A | Agent-to-Agent (протокол взаимодействия агентов) |
| MCP | Model Context Protocol |

## Docstring Policy

- Все публичные классы и методы с нетривиальной логикой — **обязательно** docstring.
- Язык docstrings: **английский** (новые файлы и обновления).
- Существующие русскоязычные docstrings оставлять до планового рефакторинга.
- Формат: Google-style docstrings.

```python
def process_document(text: str, agent_type: str) -> dict:
    """Process a document using the specified agent.

    Args:
        text: Raw document text, up to 5_000_000 characters.
        agent_type: One of 'dzo', 'tz', 'tender', 'collector'.

    Returns:
        Dict with keys: decision, output, processing_log.

    Raises:
        ValueError: If agent_type is not registered in AGENT_REGISTRY.
    """
```

## Testing Requirements

- Минимальное покрытие бизнес-логики (`shared/`, `api/`): **80%**
- Обязательные виды тестов:
  - Unit-тесты для всех сервисных функций
  - Интеграционные тесты для API-роутов (с запущенным сервером)
  - E2E-тесты (только `pytest -m e2e`, с реальным LLM, опционально)
- `time.sleep()` в тестах **запрещён** — используйте `unittest.mock.patch` или `freezegun`
- Тестовые данные не должны содержать реальных PII (имена, email, телефоны, ИНН реальных лиц)

## Environment Variables

Все переменные окружения должны быть задокументированы в `.env.example` перед merge.
