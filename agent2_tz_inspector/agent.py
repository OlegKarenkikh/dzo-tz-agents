import os
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.memory import ConversationBufferWindowMemory
from agent2_tz_inspector.tools import (
    generate_json_report,
    generate_corrected_tz,
    generate_email_to_dzo,
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


def create_tz_agent() -> AgentExecutor:
    llm = ChatOpenAI(
        model=os.getenv("MODEL_NAME", "gpt-4o"),
        temperature=0.2,
        max_tokens=8192,
        api_key=os.getenv("OPENAI_API_KEY"),
    )
    tools  = [generate_json_report, generate_corrected_tz, generate_email_to_dzo]
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        MessagesPlaceholder("chat_history", optional=True),
        ("human", "{input}"),
        MessagesPlaceholder("agent_scratchpad"),
    ])
    agent  = create_openai_tools_agent(llm, tools, prompt)
    memory = ConversationBufferWindowMemory(k=20, return_messages=True, memory_key="chat_history")
    return AgentExecutor(
        agent=agent,
        tools=tools,
        memory=memory,
        verbose=True,
        max_iterations=15,
        return_intermediate_steps=True,
    )
