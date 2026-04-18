"""
agent7_osgop_parser/agent.py
ReAct-агент для разбора полисов ОСГОП.
Воспроизводит логику DA osgop_pipeline через инструменты с валидацией.
"""
from langgraph.prebuilt import create_react_agent

from agent7_osgop_parser.tools import (
    extract_osgop_base,
    extract_osgop_insurant,
    extract_osgop_territory,
    extract_osgop_additional,
    extract_osgop_transport,
    validate_osgop_result,
    fix_osgop_field,
)
from shared.llm import build_llm
from shared.logger import setup_logger
from shared.prompt_loader import load_prompt
from shared.runner_base import BaseAgentRunner

logger = setup_logger("agent_osgop")
SYSTEM_PROMPT = load_prompt("osgop_v1.md")
AgentRunner = BaseAgentRunner


def create_osgop_agent(model_name: str | None = None) -> AgentRunner:
    """Создать агент разбора полисов ОСГОП.

    Note:
        Порядок вызова инструментов аналогичен DA osgop_pipeline:
        1. extract_osgop_base       — base_prompt
        2. extract_osgop_insurant   — base_insurant_prompt
        3. extract_osgop_territory  — base_territory_prompt
        4. extract_osgop_additional — additional_prompt (+ tariffs_info, payments_info)
        5. extract_osgop_transport  — transport_prompt + transport_models_prompt
        6. validate_osgop_result    — Pydantic OsgopParseResult
        7. fix_osgop_field          — retry по полю (max 3x)
    """
    llm = build_llm(temperature=0.0, model_name_override=model_name)
    tools = [
        extract_osgop_base,
        extract_osgop_insurant,
        extract_osgop_territory,
        extract_osgop_additional,
        extract_osgop_transport,
        validate_osgop_result,
        fix_osgop_field,
    ]
    logger.info("Создание агента ОСГОП (модель=%s)", getattr(llm, "model_name", "?"))
    graph_agent = create_react_agent(model=llm, tools=tools, prompt=SYSTEM_PROMPT)
    return AgentRunner(graph_agent, agent_label="agent_osgop")
