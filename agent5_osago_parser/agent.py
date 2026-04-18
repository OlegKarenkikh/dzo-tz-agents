"""
agent5_osago_parser/agent.py
ReAct-агент для разбора документов ОСАГО.
Воспроизводит логику DA osago_pipeline через инструменты с валидацией.
"""
from langgraph.prebuilt import create_react_agent

from agent5_osago_parser.tools import (
    extract_osago_base,
    extract_osago_additional,
    validate_osago_result,
    fix_osago_field,
)
from shared.llm import build_llm
from shared.logger import setup_logger
from shared.prompt_loader import load_prompt
from shared.runner_base import BaseAgentRunner

logger = setup_logger("agent_osago")

SYSTEM_PROMPT = load_prompt("osago_v1.md")

AgentRunner = BaseAgentRunner


def create_osago_agent(model_name: str | None = None) -> AgentRunner:
    """Создать агент разбора документов ОСАГО.

    Args:
        model_name: явное имя модели (для fallback при 429); None = из env MODEL_NAME.

    Note:
        Порядок вызова инструментов аналогичен DA osago_pipeline:
        1. extract_osago_base          — базовые + доп. поля (ТС ТТП, владелец, авто)
        2. extract_osago_additional    — мощность, масса, доп. данные
        3. validate_osago_result       — структурная валидация JSON
        4. fix_osago_field             — точечное исправление поля (при ошибке)
    """
    llm = build_llm(temperature=0.0, model_name_override=model_name)
    tools = [
        extract_osago_base,
        extract_osago_additional,
        validate_osago_result,
        fix_osago_field,
    ]
    logger.info("Создание агента ОСАГО (модель=%s)", getattr(llm, "model_name", "?"))
    graph_agent = create_react_agent(
        model=llm,
        tools=tools,
        prompt=SYSTEM_PROMPT,
    )
    logger.debug("Агент ОСАГО успешно создан")
    return AgentRunner(graph_agent, agent_label="agent_osago")
