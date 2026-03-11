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

# ReAct prompt для моделей без native function-calling (Ollama, vLLM без tool-support и т.д.)
REACT_TEMPLATE = """Assistant is a helpful AI agent.

Has access to the following tools:
{tools}

Use the following format:
Thought: what to do next
Action: tool name (one of [{tool_names}])
Action Input: input to the tool
Observation: result
... (repeat Thought/Action/Observation as needed)
Thought: I now know the final answer
Final Answer: the final answer

Begin!

System: """ + SYSTEM_PROMPT + """

Question: {input}
{agent_scratchpad}"""


def _build_llm() -> ChatOpenAI:
    """LLM с поддержкой любых OpenAI-совместимых эндпоинтов.
    - OPENAI_API_BASE=<url>  → любой совместимый URL (Ollama, vLLM, DeepSeek, Azure и т.д.)
    - OPENAI_API_KEY опционален — локальные LLM не требуют ключ, прописывается "ollama" как fallback
    """
    return ChatOpenAI(
        model=os.getenv("MODEL_NAME", "gpt-4o"),
        temperature=0.2,
        max_tokens=8192,
        api_key=os.getenv("OPENAI_API_KEY") or "ollama",
        base_url=os.getenv("OPENAI_API_BASE") or None,
    )


def create_tz_agent() -> AgentExecutor:
    """AGENT_TYPE=openai_tools (default) | react
    • openai_tools — быстрый native function-calling (для GPT-4o, DeepSeek-V3+)
    • react — ReAct prompting, работает с любой LLM без tool-support (Ollama, Mistral и т.д.)
    """
    llm    = _build_llm()
    tools  = [generate_json_report, generate_corrected_tz, generate_email_to_dzo]
    memory = ConversationBufferWindowMemory(k=20, return_messages=True, memory_key="chat_history")

    agent_type = os.getenv("AGENT_TYPE", "openai_tools").lower()
    if agent_type == "react":
        prompt = PromptTemplate.from_template(REACT_TEMPLATE)
        agent  = create_react_agent(llm, tools, prompt)
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
