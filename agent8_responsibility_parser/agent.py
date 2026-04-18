"""
agent8_responsibility_parser/agent.py
ReAct-агент для разбора договоров страхования ответственности (431/432/433).
Воспроизводит логику DA responsibility_pipeline через инструменты с валидацией.
"""
from langgraph.prebuilt import create_react_agent

from agent8_responsibility_parser.tools import (
    detect_responsibility_type,
    extract_responsibility_base,
    extract_responsibility_objects,
    extract_responsibility_fid,
    validate_responsibility_result,
    fix_responsibility_field,
)
from shared.llm import build_llm
from shared.logger import setup_logger
from shared.prompt_loader import load_prompt
from shared.runner_base import BaseAgentRunner

logger = setup_logger("agent_responsibility")
SYSTEM_PROMPT = load_prompt("responsibility_v1.md")
AgentRunner = BaseAgentRunner


def create_responsibility_agent(model_name: str | None = None) -> AgentRunner:
    """Создать агент разбора договоров ответственности.

    Note:
        Покрывает все три пайплайна DA:
        - pipeline_431.py: objects_prompt + responsibility_431_prompt
        - pipeline_432.py: fid_prompt + responsibility_432_prompt
        - pipeline_433.py: objects_prompt + responsibility_433_prompt
    """
    llm = build_llm(temperature=0.0, model_name_override=model_name)
    tools = [
        detect_responsibility_type,
        extract_responsibility_base,
        extract_responsibility_objects,
        extract_responsibility_fid,
        validate_responsibility_result,
        fix_responsibility_field,
    ]
    logger.info("Создание агента ответственности (модель=%s)", getattr(llm, "model_name", "?"))
    graph_agent = create_react_agent(model=llm, tools=tools, prompt=SYSTEM_PROMPT)
    return AgentRunner(graph_agent, agent_label="agent_responsibility")
