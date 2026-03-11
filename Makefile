.PHONY: help install test lint fmt build up down logs clean

help: ## Показать доступные команды
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Установить зависимости
	pip install -r requirements.txt pytest pytest-cov ruff

test: ## Запустить тесты
	pytest tests/ -v --cov=. --cov-report=term-missing

lint: ## Проверить код
	ruff check . --ignore E501

fmt: ## Отформатировать код
	ruff format .

build: ## Собрать Docker-образ
	docker-compose build

up: ## Запустить контейнеры
	docker-compose up -d

down: ## Остановить контейнеры
	docker-compose down

logs: ## Показать логи
	docker-compose logs -f

clean: ## Очистить артефакты
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -name "*.pyc" -delete
	rm -rf .coverage coverage.xml htmlcov/

dzo-only: ## Запустить только Агент ДЗО
	AGENT_MODE=dzo python main.py

tz-only: ## Запустить только Агент ТЗ
	AGENT_MODE=tz python main.py
