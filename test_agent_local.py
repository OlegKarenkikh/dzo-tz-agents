#!/usr/bin/env python
"""Локальное тестирование агентов с полным логированием.

Использование:
    python test_agent_local.py dzo "Текст заявки ДЗО здесь"
    python test_agent_local.py tz "Текст ТЗ здесь"
    AGENT_DEBUG=1 python test_agent_local.py dzo "..."
"""
import json
import logging
import sys

from agent1_dzo_inspector.agent import create_dzo_agent
from agent2_tz_inspector.agent import create_tz_agent

# Настройка логирования на уровень DEBUG
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def test_agent(agent_type: str, input_text: str) -> None:
    """Тестировать агент с полным логированием.

    Args:
        agent_type: "dzo" или "tz"
        input_text: текст для обработки
    """
    print(f"\n{'='*80}")
    print(f"Тестирование агента: {agent_type.upper()}")
    print(f"Input текст ({len(input_text)} символов):\n{input_text[:200]}...")
    print(f"{'='*80}\n")

    try:
        if agent_type == "dzo":
            agent = create_dzo_agent()
        elif agent_type == "tz":
            agent = create_tz_agent()
        else:
            print(f"❌ Неизвестный тип агента: {agent_type}")
            sys.exit(1)

        # Запуск агента
        print("▶️  Запуск агента...\n")
        result = agent.invoke({"input": input_text})

        # Вывод результатов
        print("\n" + "="*80)
        print("РЕЗУЛЬТАТЫ")
        print("="*80)

        if result:
            print(f"\n📋 Output ({len(result.get('output', ''))} символов):")
            print("-" * 40)
            output = result.get("output", "")
            if output:
                print(output)
            else:
                print("(пусто)")

            intermediate = result.get("intermediate_steps", [])
            print(f"\n🔧 Intermediate steps ({len(intermediate)}):")
            print("-" * 40)
            if intermediate:
                for i, step in enumerate(intermediate, 1):
                    print(f"{i}. {step}")
            else:
                print("(нет)")

            # Попытка распарсить JSON из output
            print("\n📊 Попытка парсинга JSON из output:")
            print("-" * 40)
            try:
                # Ищем JSON-структуры в output
                import re
                json_matches = re.findall(r'\{[^{}]*\}|\[[^\[\]]*\]', output, re.DOTALL)
                if json_matches:
                    for j, match in enumerate(json_matches, 1):
                        try:
                            parsed = json.loads(match)
                            print(f"JSON {j}:")
                            print(json.dumps(parsed, indent=2, ensure_ascii=False))
                        except json.JSONDecodeError:
                            pass
                else:
                    print("(найдено 0 JSON-структур в output)")
            except Exception as e:
                print(f"Ошибка парсинга: {e}")

        print("\n" + "="*80)
        print("✅ Агент успешно выполнен")
        print("="*80)

    except Exception as e:
        print("\n" + "="*80)
        print("❌ ОШИБКА")
        print("="*80)
        print(f"Тип: {type(e).__name__}")
        print(f"Сообщение: {e}")
        import traceback
        print("\nПолный stack trace:")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Использование:")
        print("  python test_agent_local.py dzo <текст заявки>")
        print("  python test_agent_local.py tz <текст ТЗ>")
        print("\nПримеры:")
        print('  python test_agent_local.py dzo "От: dzo@company.ru\\nТема: Закупка серверов\\nТекст заявки"')
        print('  AGENT_DEBUG=1 python test_agent_local.py tz "Техническое задание..."')
        sys.exit(1)

    agent_type = sys.argv[1]
    input_text = " ".join(sys.argv[2:])

    test_agent(agent_type, input_text)
