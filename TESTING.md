# 🧪 Локальное тестирование агентов

## Быстрый старт

### Тестирование агента ДЗО с полным логированием

```bash
make test-agent-dzo
```

Это выполнит:
```bash
AGENT_DEBUG=1 python test_agent_local.py dzo "От: ДЗО@company.ru\n..."
```

### Тестирование агента ТЗ с полным логированием

```bash
make test-agent-tz
```

### Собственный текст для тестирования

```bash
# Агент ДЗО
AGENT_DEBUG=1 python test_agent_local.py dzo "Ваш текст заявки здесь"

# Агент ТЗ
AGENT_DEBUG=1 python test_agent_local.py tz "Ваш текст ТЗ здесь"
```

## Что вы увидите

При запуске скрипта вы получите полный отчет:

```
════════════════════════════════════════════════════════════════════════════════
Тестирование агента: DZO
Input текст (123 символов):
От: ДЗО@company.ru
...
════════════════════════════════════════════════════════════════════════════════

▶️  Запуск агента...

[2026-03-26 12:34:56] [DEBUG] agent_dzo: Запуск агента ДЗО с input: От: ДЗО@company.ru
[2026-03-26 12:34:56] [DEBUG] agent_dzo: 🔧 generate_validation_report вызван
[2026-03-26 12:34:57] [INFO] agent_dzo: ✅ generate_validation_report: отчёт готов (decision=Заявка полная)
[2026-03-26 12:34:57] [DEBUG] agent_dzo: 🔧 generate_tezis_form вызван
[2026-03-26 12:34:57] [INFO] agent_dzo: ✅ generate_tezis_form: HTML-форма готова

════════════════════════════════════════════════════════════════════════════════
РЕЗУЛЬТАТЫ
════════════════════════════════════════════════════════════════════════════════

📋 Output (1234 символов):
----------------------------------------
{
  "decision": "Заявка полная",
  "report": {...},
  "emailHtml": "<div>...</div>"
}

🔧 Intermediate steps (3):
----------------------------------------
1. ('generate_validation_report', '{"decision": "Заявка полная",...}')
2. ('generate_tezis_form', '{"tezisFormHtml": "<!DOCTYPE html>...",...}')
3. ('generate_response_email', '{"emailHtml": "<div>...",...}')

📊 Попытка парсинга JSON из output:
----------------------------------------
JSON 1:
{
  "decision": "Заявка полная",
  "checklist_attachments": [...],
  ...
}

════════════════════════════════════════════════════════════════════════════════
✅ Агент успешно выполнен
════════════════════════════════════════════════════════════════════════════════
```

## Логирование

### Уровни логирования

Основной скрипт использует уровень **DEBUG**, поэтому вы видите:

- 🔧 **DEBUG**: Вызов инструмента (`generate_validation_report вызван`)
- ✅ **INFO**: Успешное выполнение (`отчёт готов`)
- ⚠️ **WARNING**: Предупреждения (например, эскалация)
- ❌ **ERROR**: Ошибки

### Файлы логов

Логи также сохраняются в файлы:

```bash
ls -la logs/
# agent_dzo.log  agent_tz.log
```

Просмотр логов в реальном времени:

```bash
tail -f logs/agent_dzo.log
tail -f logs/agent_tz.log
```

## Отключение отладки

Если вам нужен менее подробный вывод, отключите debug-режим:

```bash
# Отключить debug (только INFO, WARNING, ERROR)
AGENT_DEBUG=0 python test_agent_local.py dzo "текст"

# Или через Makefile с переопределением
AGENT_DEBUG=0 make test-agent-dzo
```

## Проверка инструментов

Каждый инструмент логирует свою работу. Если инструмент **не вызывается**, вы это сразу увидите в логах:

### Все инструменты ДЗО

- ✅ `generate_validation_report` — проверка чек-листов
- ✅ `generate_tezis_form` — форма для ЭДО «Тезис»
- ✅ `generate_info_request` — письмо запроса информации
- ✅ `generate_escalation` — письмо эскалации (⚠️ WARNING)
- ✅ `generate_response_email` — финальное письмо
- ✅ `generate_corrected_application` — исправленная заявка

### Все инструменты ТЗ

- ✅ `generate_json_report` — отчёт по 8 разделам
- ✅ `generate_corrected_tz` — исправленное ТЗ
- ✅ `generate_email_to_dzo` — письмо в ДЗО

## Примеры тестирования

### Тест ДЗО: Полная заявка

```bash
python test_agent_local.py dzo "От: dzo@company.ru
Тема: Закупка серверов
Прошу одобрить закупку 10 шт. серверов Dell PowerEdge R750 с нижеследующими параметрами:
- Процессор: 2x Intel Xeon 8380 (20 core каждый)
- Память: 256GB DDR4
- Хранилище: 4x 960GB SSD
Желаемый срок поставки: 01.05.2026
Место поставки: ЦОД корпуса 1 по адресу ул. Примера 1
Инициатор: Иванов И.И. (ivan@company.ru)
Бюджет: 2 млн руб. с НДС
Обоснование: модернизация инфраструктуры
Приложение: спецификация.pdf"
```

### Тест ТЗ: Хорошее ТЗ

```bash
python test_agent_local.py tz "ТЕХНИЧЕСКОЕ ЗАДАНИЕ

1. Цель закупки
Закупка серверов для пополнения ресурсов ЦОД

2. Требования к товару
- Сервер Dell PowerEdge R750
- 2x Intel Xeon 8380 (20 core, 3.4 GHz)
- 256GB DDR4 3200MHz RDIMM
- 4x 960GB SSD SATA
- RAID 10

3. Количество
10 (десять) штук

4. Сроки поставки
01.05.2026 - 31.05.2026

5. Место поставки
ЦОД, корпус 1, адрес: ул. Примера 1, бокс 5

6. Требования к исполнителю
- Авторизованный партнер Dell
- Опыт поставок серверов не менее 5 лет
- Наличие сервисной поддержки в РФ

7. Критерии оценки
- Цена (50%)
- Сроки доставки (30%)
- Условия гарантии и поддержки (20%)

8. Приложения
Спецификация сервера (Dell-R750-spec.pdf)"
```

## 🐛 Отладка проблем

Если инструмент не вызывается:

1. Проверьте логи — должна быть строка `🔧 tool_name вызван`
2. Проверьте JSON в ответе от предыдущего шага
3. Убедитесь, что входные данные для инструмента валидны

Если агент не отвечает:

1. Проверьте переменные окружения: `echo $OPENAI_API_KEY`, `echo $GITHUB_TOKEN`
2. Проверьте, что выбран правильный `LLM_BACKEND`: `AGENT_DEBUG=1 python -c "from config import LLM_BACKEND; print(LLM_BACKEND)"`
3. Проверьте логи API: `tail -f logs/api.log` (если запущен через API)

## 📊 Анализ результатов

Скрипт автоматически:
- ✅ Извлекает JSON из вывода
- ✅ Показывает intermediate_steps (цепочка вызванных инструментов)
- ✅ Форматирует JSON для читаемости
- ✅ Показывает ошибки (если есть)

## Интеграция с CI/CD

Для добавления в CI/CD используйте скрипт:

```yaml
# .github/workflows/test.yml
- name: Test DZO agent
  run: AGENT_DEBUG=0 python test_agent_local.py dzo "test input"

- name: Test TZ agent
  run: AGENT_DEBUG=0 python test_agent_local.py tz "test input"
```

---

## 🐳 Тестирование через Docker

### Сборка и запуск

```bash
# Сборка образа
make build

# Запуск полного стека (API + PostgreSQL + UI)
make up

# Проверить статус контейнеров
docker compose ps

# Health check
curl -s http://localhost:8000/health | python3 -m json.tool
```

### Запуск тестов внутри контейнера

```bash
# Юнит-тесты внутри контейнера
docker compose exec api python -m pytest tests/ -m "not e2e and not integration" --strict-markers -v

# С покрытием
docker compose exec api python -m pytest tests/ --cov=. --cov-report=term-missing
```

### Мониторинг

```bash
# Запуск мониторинга (Prometheus + Grafana + Alertmanager)
make monitoring

# Grafana: http://localhost:3000 (admin / $GRAFANA_PASSWORD)
# Prometheus: http://localhost:9090
# Alertmanager: http://localhost:9093
```

### Остановка

```bash
make down
```
