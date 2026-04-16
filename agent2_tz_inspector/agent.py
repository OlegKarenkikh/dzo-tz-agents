from langgraph.prebuilt import create_react_agent

from agent2_tz_inspector.tools import (
    generate_corrected_tz,
    generate_email_to_dzo,
    generate_json_report,
    invoke_peer_agent,
)
from shared.llm import build_llm
from shared.logger import setup_logger
from shared.prompt_loader import load_prompt
from shared.runner_base import BaseAgentRunner

logger = setup_logger("agent_tz")

SYSTEM_PROMPT = load_prompt("tz_v2.md")


# Backward-compatible alias: AgentRunner = BaseAgentRunner (из shared.runner_base)
AgentRunner = BaseAgentRunner


def create_tz_agent(model_name: str | None = None) -> AgentRunner:
    """Создать агент ТЗ.

    Args:
        model_name: явное имя модели (для fallback при 429); None = из env MODEL_NAME.

    Note:
        Использует langgraph.prebuilt.create_react_agent (ReAct + tool-calling).
    """
    llm = build_llm(temperature=0.0, model_name_override=model_name)
    tools = [invoke_peer_agent, generate_json_report, generate_corrected_tz, generate_email_to_dzo]
    logger.info("Создание агента ТЗ (модель=%s)", getattr(llm, 'model_name', '?'))

    # langgraph >= 0.2: create_react_agent(model, tools, prompt=system_str)
    graph_agent = create_react_agent(
        model=llm,
        tools=tools,
        prompt=SYSTEM_PROMPT,
    )
    logger.debug("Агент ТЗ успешно создан")
    return AgentRunner(graph_agent, agent_label="agent_tz")
