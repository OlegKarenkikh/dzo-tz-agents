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
from shared.prompt_loader import load_prompt
from shared.runner_base import BaseAgentRunner

logger = setup_logger("agent_dzo")

SYSTEM_PROMPT = load_prompt("dzo_v1.md")


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
    llm = build_llm(temperature=0.0, model_name_override=model_name)
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
