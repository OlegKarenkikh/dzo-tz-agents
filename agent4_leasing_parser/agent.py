"""
agent4_leasing_parser/agent.py
ReAct-агент для разбора договоров лизинга.
Воспроизводит логику DA leasing_pipeline через инструменты с валидацией.
"""
from langgraph.prebuilt import create_react_agent

from agent4_leasing_parser.tools import (
    extract_leasing_base,
    extract_leasing_additional,
    extract_leasing_roles,
    extract_leasing_territory,
    extract_leasing_risks,
    validate_leasing_result,
    fix_leasing_field,
)
from shared.llm import build_llm
from shared.logger import setup_logger
from shared.prompt_loader import load_prompt
from shared.runner_base import BaseAgentRunner

logger = setup_logger("agent_leasing")

SYSTEM_PROMPT = load_prompt("leasing_v1.md")

AgentRunner = BaseAgentRunner


def create_leasing_agent(model_name: str | None = None) -> AgentRunner:
    """Создать агент разбора договоров лизинга.

    Args:
        model_name: явное имя модели (для fallback при 429); None = из env MODEL_NAME.

    Note:
        Порядок вызова инструментов аналогичен DA leasing_pipeline:
        1. extract_leasing_base          — базовые поля полиса
        2. extract_leasing_additional    — объекты страхования, платежи, франшиза
        3. extract_leasing_roles         — участники договора
        4. extract_leasing_territory     — территория страхования
        5. extract_leasing_risks         — риски
        6. validate_leasing_result       — структурная валидация JSON
        7. fix_leasing_field             — точечное исправление поля (при ошибке)
    """
    llm = build_llm(temperature=0.0, model_name_override=model_name)
    tools = [
        extract_leasing_base,
        extract_leasing_additional,
        extract_leasing_roles,
        extract_leasing_territory,
        extract_leasing_risks,
        validate_leasing_result,
        fix_leasing_field,
    ]
    logger.info("Создание агента лизинга (модель=%s)", getattr(llm, "model_name", "?"))
    graph_agent = create_react_agent(
        model=llm,
        tools=tools,
        prompt=SYSTEM_PROMPT,
    )
    logger.debug("Агент лизинга успешно создан")
    return AgentRunner(graph_agent, agent_label="agent_leasing")
