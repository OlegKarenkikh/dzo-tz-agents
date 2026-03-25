import os
from typing import Any

from langchain.agents import create_agent

from agent2_tz_inspector.tools import (
    generate_corrected_tz,
    generate_email_to_dzo,
    generate_json_report,
)
from shared.llm import build_llm

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

ОГРАНИЧЕНИЯ: не оценивай правильность характеристик — только наличие и формальное соответствие. Нейтральный вежливый тон."""

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
        result = self._agent.invoke({"messages": [{"role": "user", "content": chat_input}]})

        output = ""
        if isinstance(result, dict):
            messages = result.get("messages") or []
            if messages:
                last = messages[-1]
                output = getattr(last, "content", "") or ""
                if isinstance(output, list):
                    output = "\n".join(str(x) for x in output)

        return {"output": output, "intermediate_steps": []}


def create_tz_agent(model_name: str | None = None) -> AgentRunner:
    """Создать агент ТЗ.

    Args:
        model_name: явное имя модели (для fallback при 429); None = из env MODEL_NAME.
    """
    llm = build_llm(temperature=0.2, model_name_override=model_name)
    tools = [generate_json_report, generate_corrected_tz, generate_email_to_dzo]
    graph_agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
        debug=os.getenv("AGENT_DEBUG", "0") in {"1", "true", "True"},
    )
    return AgentRunner(graph_agent)
