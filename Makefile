.PHONY: help install test lint fmt build up down logs clean api ui api-ui stop-local restart-local dzo-only tz-only tender-only test-agent-dzo test-agent-tz test-agent-tender monitoring monitoring-down

help: ## Показать доступные команды
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Установить зависимости (как в CI и README: editable + ui + dev)
	pip install -e ".[ui,dev]"

test: ## Запустить тесты
	python -m pytest tests/ -v --tb=short --cov=. --cov-report=term-missing

lint: ## Проверить код
	python -m ruff check . --config pyproject.toml

fmt: ## Отформатировать код
	python -m ruff format .

build: ## Собрать Docker-образ
	docker compose build

up: ## Запустить основные контейнеры
	docker compose up -d

down: ## Остановить контейнеры
	docker compose down

logs: ## Показать логи
	docker compose logs -f

clean: ## Очистить артефакты
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -name "*.pyc" -delete
	rm -rf .coverage coverage.xml htmlcov/ .pytest_cache/

api: ## Запустить FastAPI локально
	python -m uvicorn api.app:app --reload --port 8000

ui: ## Запустить Streamlit локально
	python -m streamlit run ui/app.py --server.port 8501

api-ui: ## Запустить API + UI одновременно
	$(MAKE) -j2 api ui

stop-local: ## Остановить локально запущенные API и UI (по порту)
	@echo "Останавливаем процессы на портах 8000 и 8501..."
	@_stop_port() { \
		port=$$1; name=$$2; \
		if command -v fuser >/dev/null 2>&1; then \
			fuser -k $${port}/tcp 2>/dev/null && echo "  $${name} ($${port}) остановлен" || echo "  $${name} ($${port}) не запущен"; \
		elif command -v lsof >/dev/null 2>&1; then \
			pid=$$(lsof -ti tcp:$${port} 2>/dev/null); \
			if [ -n "$$pid" ]; then kill $$pid 2>/dev/null && echo "  $${name} ($${port}) остановлен" || echo "  $${name} ($${port}) не запущен"; else echo "  $${name} ($${port}) не запущен"; fi; \
		else \
			echo "  $${name} ($${port}): требуется fuser (psmisc) или lsof"; \
		fi; \
	}; \
	_stop_port 8000 API; \
	_stop_port 8501 UI

restart-local: stop-local ## Перезапустить API + UI локально (kill по порту → запуск)
	@sleep 1
	$(MAKE) api-ui

dzo-only: ## Запустить только Агент ДЗО
	AGENT_MODE=dzo python main.py

tz-only: ## Запустить только Агент ТЗ
	AGENT_MODE=tz python main.py

tender-only: ## Запустить только Агент Тендер
	AGENT_MODE=tender python main.py

test-agent-dzo: ## Тестировать агент ДЗО локально (с отладкой)
	AGENT_DEBUG=1 python test_agent_local.py dzo "От: ДЗО@company.ru\nТема: Запрос на закупку\n\nПрошу одобрить закупку 10 шт. серверов Dell PowerEdge R750 с доставкой в офис по адресу ул. Примера 1."

test-agent-tz: ## Тестировать агент ТЗ локально (с отладкой)
	AGENT_DEBUG=1 python test_agent_local.py tz "ТЕХНИЧЕСКОЕ ЗАДАНИЕ\n\n1. Цель: Закупка серверов для ЦОД\n2. Требования: Dell PowerEdge R750, 2x Xeon 8380, 256GB RAM\n3. Количество: 10 шт.\n4. Сроки: до 01.05.2026\n5. Место: ЦОД корпуса 2\n6. Исполнитель: авторизованный партнер Dell\n7. Критерии: цена 50%, сроки 30%, поддержка 20%\n8. Приложения: спецификация, чертежи"

test-agent-tender: ## Тестировать тендерный агент локально (с отладкой)
	AGENT_DEBUG=1 python test_agent_local.py tender "ТЕНДЕРНАЯ ДОКУМЕНТАЦИЯ\n\nУчастник должен предоставить выписку ЕГРЮЛ, копию лицензии, подтверждение опыта аналогичных поставок и банковскую гарантию обеспечения заявки."

monitoring: ## Запустить стек мониторинга
	docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d

monitoring-down: ## Остановить стек мониторинга
	docker compose -f docker-compose.yml -f docker-compose.monitoring.yml down
