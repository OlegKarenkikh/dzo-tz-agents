from langgraph.prebuilt import create_react_agent

from agent1_dzo_inspector.tools import (
    analyze_tz_with_agent,
    generate_corrected_application,
    generate_escalation,
    generate_info_request,
    generate_response_email,
    generate_tezis_form,
    generate_validation_report,
    invoke_peer_agent,
)
from shared.llm import build_llm
from shared.logger import setup_logger
from shared.runner_base import BaseAgentRunner

logger = setup_logger("agent_dzo")

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
ШАГ 1.1 — Если найдено ТЗ (или текст ТЗ в теле/вложении), вызови analyze_tz_with_agent.
         Результат анализа ТЗ обязательно включи в итоговое резюме и письмо.
ШАГ 1.2 — При необходимости дополнительной проверки можно вызвать invoke_peer_agent
         для любого доступного агента (например, tender для перечня документов).
ШАГ 2 — Проверь реквизиты (чек-листы №2 и №3) — ищи И в теле письма, И во вложениях
ШАГ 3 — Прими решение:
  • «Заявка полная» → вызови generate_tezis_form
  • «Требуется доработка» → вызови generate_info_request
  • «Требуется эскалация» → вызови generate_escalation
ШАГ 4 — Сформируй отчёт → generate_validation_report
ШАГ 5 — Сформируй письмо → generate_response_email
ШАГ 6 — Если доработка → generate_corrected_application

ОГРАНИЧЕНИЯ: не оценивай качество ТЗ — только полноту заявки. Вежливый деловой тон."""


# Backward-compatible alias: AgentRunner = BaseAgentRunner (из shared.runner_base)
AgentRunner = BaseAgentRunner


def create_dzo_agent(model_name: str | None = None) -> AgentRunner:
    """Создать агент ДЗО.

    Args:
        model_name: явное имя модели (для fallback при 429); None = из env MODEL_NAME.

    Note:
        Использует langgraph.prebuilt.create_react_agent (ReAct + tool-calling).
        system_prompt передаётся как строка — langgraph принимает его напрямую
        через параметр `prompt` или как системное сообщение в messages.
    """
    llm = build_llm(temperature=0.2, model_name_override=model_name)
    tools = [
        invoke_peer_agent,
        analyze_tz_with_agent,
        generate_validation_report,
        generate_tezis_form,
        generate_info_request,
        generate_escalation,
        generate_response_email,
        generate_corrected_application,
    ]
    logger.info("Создание агента ДЗО (модель=%s)", getattr(llm, 'model_name', '?'))

    # langgraph >= 0.2: create_react_agent(model, tools, prompt=system_str)
    graph_agent = create_react_agent(
        model=llm,
        tools=tools,
        prompt=SYSTEM_PROMPT,
    )
    logger.debug("Агент ДЗО успешно создан")
    return AgentRunner(graph_agent, agent_label="agent_dzo")
