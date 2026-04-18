"""
agent6_transportation_parser/agent.py
ReAct-агент для разбора заявок на страхование грузоперевозок.
Воспроизводит логику DA transportation_pipeline через инструменты с валидацией.
"""
from langgraph.prebuilt import create_react_agent

from agent6_transportation_parser.tools import (
    extract_transport_base,
    extract_transport_route,
    extract_transport_additional,
    resolve_transport_type,
    validate_transport_result,
    fix_transport_field,
)
from shared.llm import build_llm
from shared.logger import setup_logger
from shared.prompt_loader import load_prompt
from shared.runner_base import BaseAgentRunner

logger = setup_logger("agent_transportation")
SYSTEM_PROMPT = load_prompt("transportation_v1.md")
AgentRunner = BaseAgentRunner


def create_transportation_agent(model_name: str | None = None) -> AgentRunner:
    """Создать агент разбора заявок на грузоперевозки.

    Args:
        model_name: явное имя модели (для fallback при 429); None = из env MODEL_NAME.

    Note:
        Порядок вызова инструментов аналогичен DA transportation_pipeline:
        1. extract_transport_base        — base_prompt
        2. extract_transport_route       — extract_route_prompt
        3. extract_transport_additional  — additional_prompt
        4. resolve_transport_type        — type/several_types + справочник
        5. validate_transport_result     — Pydantic validate + _strip_none
        6. fix_transport_field           — retry по конкретному полю (max 3x)
    """
    llm = build_llm(temperature=0.0, model_name_override=model_name)
    tools = [
        extract_transport_base,
        extract_transport_route,
        extract_transport_additional,
        resolve_transport_type,
        validate_transport_result,
        fix_transport_field,
    ]
    logger.info("Создание агента перевозки (модель=%s)", getattr(llm, "model_name", "?"))
    graph_agent = create_react_agent(model=llm, tools=tools, prompt=SYSTEM_PROMPT)
    logger.debug("Агент перевозки успешно создан")
    return AgentRunner(graph_agent, agent_label="agent_transportation")
