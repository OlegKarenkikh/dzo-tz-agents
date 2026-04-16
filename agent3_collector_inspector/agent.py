"""Агент сбора анкет участников тендерного отбора (collector).

Автоматизирует процесс сбора и проверки документов от участников
тендерного отбора Страховая компания, Управление централизованных закупок (УЦЗ).
"""

from langgraph.prebuilt import create_react_agent

from agent3_collector_inspector.tools import collect_tender_documents, invoke_peer_agent
from shared.llm import build_llm
from shared.logger import setup_logger
from shared.prompt_loader import load_prompt
from shared.runner_base import BaseAgentRunner

logger = setup_logger("agent_collector")

SYSTEM_PROMPT = load_prompt("collector_v1.md")


# Backward-compatible alias: AgentRunner = BaseAgentRunner (из shared.runner_base)
AgentRunner = BaseAgentRunner


def create_collector_agent(model_name: str | None = None) -> AgentRunner:
    """Создать агент сбора документов тендерного отбора.

    Args:
        model_name: явное имя модели (для fallback при 429); None = из env MODEL_NAME.

    Note:
        Использует langgraph.prebuilt.create_react_agent — единый API LangGraph.
    """
    llm = build_llm(temperature=0.0, model_name_override=model_name)
    tools = [invoke_peer_agent, collect_tender_documents]
    logger.info(
        "Создание агента Collector (модель=%s)",
        getattr(llm, "model_name", "?"),
    )

    graph_agent = create_react_agent(
        model=llm,
        tools=tools,
        prompt=SYSTEM_PROMPT,
    )
    logger.debug("Агент Collector успешно создан")
    return AgentRunner(graph_agent, agent_label="agent_collector")
