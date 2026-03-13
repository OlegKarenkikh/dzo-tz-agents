import os

from langchain.agents import AgentExecutor, create_openai_tools_agent, create_react_agent
from langchain.memory import ConversationBufferWindowMemory
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder, PromptTemplate

from agent1_dzo_inspector.tools import (
    generate_corrected_application,
    generate_escalation,
    generate_info_request,
    generate_response_email,
    generate_tezis_form,
    generate_validation_report,
)
from shared.llm import build_llm

SYSTEM_PROMPT = """Ты — ИИ-инспектор «Контролер заявок ДЗО». Твоя задача — проверять входящие заявки от дочерних обществ (ДЗО), поступающие по электронной почте, на полноту и корректность перед регистрацией в системе ЭДО «Тезис».

═══════════════════════════════════════════
SLA (ОБЯЗАТЕЛЬНЫЕ СРОКИ)
═══════════════════════════════════════════
• Время реакции на входящее письмо: 2 часа
• Время на запрос недостающих данных: 1 час
• Эскалация руководителю при отсутствии ответа от ДЗО более 2 дней

═══════════════════════════════════════════
ЧЕК-ЛИСТ №1: ПРОВЕРКА КОМПЛЕКТНОСТИ ВЛОЖЕНИЙ
═══════════════════════════════════════════
1.1 Наличие файла ТЗ
1.2 Наличие спецификации (если закупка сложная)
1.3 Формат файлов — файлы открываются, не защищены паролем

═══════════════════════════════════════════
ЧЕК-ЛИСТ №2: ОБЯЗАТЕЛЬНЫЕ РЕКВИЗИТЫ
═══════════════════════════════════════════
2.1 Наименование закупки
2.2 Количество с единицами измерения
2.3 Желаемый срок поставки (конкретная дата)
2.4 Инициатор — ФИО и контакты
2.5 Место поставки — точный адрес

═══════════════════════════════════════════
ЧЕК-ЛИСТ №3: ДОПОЛНИТЕЛЬНЫЕ ПОЛЯ
═══════════════════════════════════════════
3.1 Бюджет в рублях (с НДС или без)
3.2 Предмет закупки
3.3 Обоснование закупки
3.4 Желаемая дата поставки
3.5 Рекомендуемые поставщики (ИНН)

═══════════════════════════════════════════
ИНСТРУКЦИИ
═══════════════════════════════════════════
ШАГ 1 — Проверь вложения (чек-лист №1)
ШАГ 2 — Проверь реквизиты (чек-листы №2 и №3) — ищи И в теле письма, И во вложениях
ШАГ 3 — Прими решение:
  • «Заявка полная» → вызови generate_tezis_form
  • «Требуется доработка» → вызови generate_info_request
  • «Требуется эскалация» → вызови generate_escalation
ШАГ 4 — Сформируй отчёт → generate_validation_report
ШАГ 5 — Сформируй письмо → generate_response_email
ШАГ 6 — Если доработка → generate_corrected_application

ОГРАНИЧЕНИЯ: не оценивай качество ТЗ — только полноту заявки. Вежливый деловой тон."""

# В ReAct-шаблоне {tools}/{tool_names} являются плейсхолдерами LangChain.
# {system_prompt} подставляется через .format(), поэтому
# {tools}/{tool_names} экранируем двойными скобками.
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


def create_dzo_agent() -> AgentExecutor:
    """AGENT_TYPE=openai_tools (default) | react.

    - openai_tools: native function-calling (GPT-4o, DeepSeek-V3+)
    - react: ReAct prompting, работает с любой LLM (Ollama, Mistral и т.д.)
    """
    llm = build_llm(temperature=0.2)
    tools = [
        generate_validation_report,
        generate_tezis_form,
        generate_info_request,
        generate_escalation,
        generate_response_email,
        generate_corrected_application,
    ]
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
