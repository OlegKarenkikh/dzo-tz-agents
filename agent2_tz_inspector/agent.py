import os

from langchain.agents import AgentExecutor, create_openai_tools_agent, create_react_agent
from langchain.memory import ConversationBufferWindowMemory
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder, PromptTemplate
from langchain_openai import ChatOpenAI

from agent2_tz_inspector.tools import (
    generate_corrected_tz,
    generate_email_to_dzo,
    generate_json_report,
)

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


def _build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=os.getenv("MODEL_NAME", "gpt-4o"),
        temperature=0.2,
        max_tokens=8192,
        api_key=os.getenv("OPENAI_API_KEY") or "ollama",
        base_url=os.getenv("OPENAI_API_BASE") or None,
    )


def create_tz_agent() -> AgentExecutor:
    """AGENT_TYPE=openai_tools (default) | react.

    - openai_tools: native function-calling (GPT-4o, DeepSeek-V3+)
    - react: ReAct prompting, работает с любой LLM (Ollama, Mistral и т.д.)
    """
    llm = _build_llm()
    tools = [generate_json_report, generate_corrected_tz, generate_email_to_dzo]
    memory = ConversationBufferWindowMemory(k=20, return_messages=True, memory_key="chat_history")

    agent_type = os.getenv("AGENT_TYPE", "openai_tools").lower()
    if agent_type == "react":
        prompt = PromptTemplate.from_template(REACT_TEMPLATE)
        agent = create_react_agent(llm, tools, prompt)
    else:
        prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder("chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder("agent_scratchpad"),
        ])
        agent = create_openai_tools_agent(llm, tools, prompt)

    return AgentExecutor(
        agent=agent,
        tools=tools,
        memory=memory,
        verbose=True,
        max_iterations=15,
        return_intermediate_steps=True,
    )
