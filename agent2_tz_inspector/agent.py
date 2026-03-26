import json
import os
from typing import Any

from langchain.agents import create_agent

from agent2_tz_inspector.tools import (
    generate_corrected_tz,
    generate_email_to_dzo,
    generate_json_report,
)
from shared.llm import build_llm
from shared.logger import setup_logger

logger = setup_logger("agent_tz")

SYSTEM_PROMPT = """Ты — ИИ-инспектор «Контролер ТЗ». Проверяешь технические задания от ДЗО на соответствие корпоративному шаблону.

═══════════════════════════════════════════
ЭТАЛОННАЯ СТРУКТУРА ТЗ (8 обязательных разделов)
═══════════════════════════════════════════
1. Цель закупки
2. Требования к товару/работе/услуге
3. Количество и единицы измерения
4. Срок и условия поставки
5. Место поставки
6. Требования к исполнителю (если применимо)
7. Критерии оценки заявок
8. Приложения

═══════════════════════════════════════════
ЧЕК-ЛИСТ ВАЛИДАЦИИ
═══════════════════════════════════════════
• Требования: ✅ модели, ГОСТ, параметры | ❌ «качественный», «современный»
• Критерии: ✅ «цена — 50%» | ❌ «лучшее предложение»
• Сроки: ✅ дата/период | ❌ «срочно», «по возможности»
• Единицы: ✅ шт., м² | ❌ «пачка», «набор» без расшифровки

═══════════════════════════════════════════
ИНСТРУКЦИИ
═══════════════════════════════════════════
ШАГ 1 — Прочитай текст ТЗ, учти возможные OCR-артефакты
ШАГ 2 — Проверь структуру по 8 разделам (ищи по смыслу)
ШАГ 3 — Сформируй отчёт → generate_json_report
ШАГ 4 — Сформируй исправленное ТЗ → generate_corrected_tz
ШАГ 5 — Сформируй письмо → generate_email_to_dzo

ОГРАНИЧЕНИЯ: не оценивай правильность характеристик — только наличие и формальное соответствие. Нейтральный вежливый тон.

═══════════════════════════════════════════
КРИТИЧЕСКИ ВАЖНО: ФОРМАТ ВЫЗОВА ИНСТРУМЕНТОВ
═══════════════════════════════════════════
⚠️ ЗАПРЕЩЕНО передавать оригинальный текст ТЗ в аргументы инструментов!
⚠️ ЗАПРЕЩЕНО вставлять большие блоки текста в query!
✅ Передавай ТОЛЬКО краткие результаты анализа.

Пример вызова generate_json_report (компактный JSON):
{"overall_status":"Требует доработки","category":"ИТ-услуги","sections":[{"id":1,"name":"Цель закупки","status":"ОК","comment":""},{"id":3,"name":"Количество","status":"❌","comment":"Не указано количество лицензий"}],"critical_issues":["Отсутствует раздел 3"],"recommendations":["Добавить количество и единицы измерения"]}

Пример вызова generate_corrected_tz (только изменения):
{"title":"Исправленное ТЗ","original_sections":[{"name":"Цель закупки","content":"Разработка ПО складского учёта","status":"ОК"}],"added_sections":[{"name":"Количество и единицы измерения","content":"1 лицензия (пользователей: не ограничено)"}],"modifications":[{"section":"Требования","old_text":"хорошее качество","new_text":"соответствующее ГОСТ Р ISO 9001"}]}

Пример вызова generate_email_to_dzo (только поля решения):
{"decision":"Требует доработки","dzo_name":"Название ДЗО","tz_subject":"Тема ТЗ","issues":["Замечание 1","Замечание 2"],"recommendations":["Рекомендация 1"],"has_corrected_tz":true}"""

# {tools}/{tool_names} экранируем двойными скобками — LangChain подставит их позже через PromptTemplate,
# а .format(system_prompt=...) обрабатывает только {system_prompt}.
_REACT_TEMPLATE = (
    "Assistant is a helpful AI agent.\n\n"
    "Has access to the following tools:\n"
    "{{tools}}\n\n"
    "Use the following format:\n"
    "Thought: what to do next\n"
    "Action: tool name (one of [{{tool_names}}])\n"
    "Action Input: input to the tool\n"
    "Observation: result\n"
    "... (repeat Thought/Action/Observation as needed)\n"
    "Thought: I now know the final answer\n"
    "Final Answer: the final answer\n\n"
    "Begin!\n\n"
    "System: {system_prompt}\n\n"
    "Question: {{input}}\n"
    "{{agent_scratchpad}}"
)

REACT_TEMPLATE = _REACT_TEMPLATE.format(system_prompt=SYSTEM_PROMPT)


class AgentRunner:
    """Adapter to keep legacy `invoke({"input": ...})` contract for api/app.py."""

    def __init__(self, graph_agent: Any):
        self._agent = graph_agent

    def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        chat_input = payload.get("input", "")
        logger.debug("Запуск агента ТЗ с input: %s", chat_input[:100] if chat_input else "(пусто)")
        
        result = self._agent.invoke({"messages": [{"role": "user", "content": chat_input}]})
        
        # Логируем весь результат для отладки
        logger.debug("Результат агента (тип: %s): %s", type(result).__name__, result)

        output = ""
        messages: list = []
        intermediate_steps: list = []
        
        if isinstance(result, dict):
            messages = result.get("messages") or []
            if messages:
                last = messages[-1]
                output = getattr(last, "content", "") or ""
                if isinstance(output, list):
                    output = "\n".join(str(x) for x in output)

        # Извлекаем результаты вызовов инструментов из ToolMessage-сообщений.
        # LangGraph хранит их в history messages, а не в отдельном поле steps.
        for msg in messages:
            if hasattr(msg, "tool_call_id"):  # ToolMessage
                name = getattr(msg, "name", None) or "tool"
                content = getattr(msg, "content", "")
                try:
                    obs = json.loads(content) if isinstance(content, str) else content
                except Exception:
                    obs = {"raw": str(content)}
                intermediate_steps.append((name, obs))

        logger.info(
            "Агент ТЗ завершён. Output: %d симв., инструментов вызвано: %d",
            len(output), len(intermediate_steps),
        )
        for name, obs in intermediate_steps:
            logger.info("  🔧 %s → %s", name, str(obs)[:200])
        
        return {"output": output, "intermediate_steps": intermediate_steps}


def create_tz_agent(model_name: str | None = None) -> AgentRunner:
    """Создать агент ТЗ.

    Args:
        model_name: явное имя модели (для fallback при 429); None = из env MODEL_NAME.
    """
    llm = build_llm(temperature=0.2, model_name_override=model_name)
    tools = [generate_json_report, generate_corrected_tz, generate_email_to_dzo]
    # Debug режим: по умолчанию включен, если явно не отключен
    debug_mode = os.getenv("AGENT_DEBUG", "1") not in {"0", "false", "False"}
    logger.info("Создание агента ТЗ (debug=%s, модель=%s)", debug_mode, llm.model_name)
    
    graph_agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
        debug=debug_mode,
    )
    logger.debug("Агент ТЗ успешно создан")
    return AgentRunner(graph_agent)
