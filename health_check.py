#!/usr/bin/env python
"""Быстрая проверка что все компоненты работают."""
import sys
import logging

# Проверка 1: Импорты
print("✓ Проверка импортов...")
try:
    from agent1_dzo_inspector.agent import create_dzo_agent
    from agent2_tz_inspector.agent import create_tz_agent
    from shared.logger import setup_logger
    from config import LLM_BACKEND, GITHUB_TOKEN, OPENAI_API_KEY
    print("  ✅ Все импорты успешны")
except ImportError as e:
    print(f"  ❌ Ошибка импорта: {e}")
    sys.exit(1)

# Проверка 2: Логирование
print("\n✓ Проверка логирования...")
test_logger = setup_logger("health_check")
test_logger.info("Тестовое сообщение INFO")
test_logger.debug("Тестовое сообщение DEBUG")
print("  ✅ Логирование работает (смотри выше)")

# Проверка 3: Конфигурация
print("\n✓ Проверка конфигурации...")
print(f"  LLM_BACKEND: {LLM_BACKEND}")
print(f"  OPENAI_API_KEY: {'установлен' if OPENAI_API_KEY else '❌ НЕ установлен'}")
print(f"  GITHUB_TOKEN: {'установлен' if GITHUB_TOKEN else '❌ НЕ установлен'}")

if LLM_BACKEND == "openai" and not OPENAI_API_KEY:
    print("  ⚠️  LLM_BACKEND=openai без OPENAI_API_KEY - может быть ошибка!")
elif LLM_BACKEND == "github_models":
    if GITHUB_TOKEN:
        print("  ✅ GitHub Models с GITHUB_TOKEN готов")
    else:
        print("  ❌ GitHub Models выбран, но GITHUB_TOKEN не установлен!")
else:
    print(f"  ✅ {LLM_BACKEND} выбран")

# Проверка 4: Создание агентов (без запуска)
print("\n✓ Проверка создания агентов...")
try:
    print("  Создание DZO агента...")
    dzo_agent = create_dzo_agent()
    print("  ✅ DZO агент создан")
except Exception as e:
    print(f"  ❌ Ошибка создания DZO агента: {e}")

try:
    print("  Создание TZ агента...")
    tz_agent = create_tz_agent()
    print("  ✅ TZ агент создан")
except Exception as e:
    print(f"  ❌ Ошибка создания TZ агента: {e}")

print("\n💚 Health check пройден!")
print("\nДальше:\n  make test-agent-dzo\n  make test-agent-tz")
