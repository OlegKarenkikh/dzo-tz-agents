.PHONY: help install test lint fmt build up down logs clean api ui api-ui monitoring monitoring-down

help: ## Показать доступные команды
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Установить зависимости
	pip install -r requirements.txt

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

dzo-only: ## Запустить только Агент ДЗО
	AGENT_MODE=dzo python main.py

tz-only: ## Запустить только Агент ТЗ
	AGENT_MODE=tz python main.py

monitoring: ## Запустить стек мониторинга
	docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d

monitoring-down: ## Остановить стек мониторинга
	docker compose -f docker-compose.yml -f docker-compose.monitoring.yml down
