import os

from langchain.agents import AgentExecutor, create_openai_tools_agent, create_react_agent
from langchain.memory import ConversationBufferWindowMemory
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder, PromptTemplate
from langchain_openai import ChatOpenAI

from agent1_dzo_inspector.tools import (
    generate_corrected_application,
    generate_escalation,
    generate_info_request,
    generate_response_email,
    generate_tezis_form,
    generate_validation_report,
)

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


def create_dzo_agent() -> AgentExecutor:
    """AGENT_TYPE=openai_tools (default) | react
    • openai_tools — быстрый native function-calling (для GPT-4o, GPT-4-turbo, DeepSeek-V3+)
    • react — ReAct prompting, работает с любой LLM без tool-support (Ollama llama3, Mistral и т.д.)
    """
    llm   = _build_llm()
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
