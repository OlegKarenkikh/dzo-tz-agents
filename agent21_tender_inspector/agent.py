from langgraph.prebuilt import create_react_agent

from agent21_tender_inspector.tools import generate_document_list, invoke_peer_agent
from shared.llm import build_llm
from shared.logger import setup_logger
from shared.prompt_loader import load_prompt
from shared.runner_base import BaseAgentRunner

logger = setup_logger("agent_tender")

SYSTEM_PROMPT = load_prompt("tender_v1.md")


# Backward-compatible alias: AgentRunner = BaseAgentRunner (из shared.runner_base)
AgentRunner = BaseAgentRunner


def create_tender_agent(model_name: str | None = None) -> AgentRunner:
    """Создать агент парсинга тендерной документации.

    Args:
        model_name: явное имя модели (для fallback при 429); None = из env MODEL_NAME.

    Note:
        Использует langgraph.prebuilt.create_react_agent — единый API LangGraph.
    """
    # temperature=0.0 — детерминированный анализ документов;
    # повышение ухудшает воспроизводимость классификации и извлечения данных
    llm = build_llm(temperature=0.0, model_name_override=model_name)
    tools = [invoke_peer_agent, generate_document_list]
    logger.info(
        "Создание агента Тендер (модель=%s)",
        getattr(llm, "model_name", "?"),
    )

    graph_agent = create_react_agent(
        model=llm,
        tools=tools,
        prompt=SYSTEM_PROMPT,
    )
    logger.debug("Агент Тендер успешно создан")
    return AgentRunner(graph_agent, agent_label="agent_tender")
