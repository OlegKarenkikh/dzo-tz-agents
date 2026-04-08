"""
conftest.py — общие фикстуры и mock-объекты для тестов.

FIX ST-03 (updated): принудительно патчим langgraph.prebuilt.create_react_agent
даже если langgraph реально установлен — чтобы agent.invoke() не вызывал
настоящий LLM/граф и не падал с MESSAGE_COERCION_FAILURE на MagicMock.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Единый API_KEY до любых импортов.
os.environ["OPENAI_API_KEY"] = "sk-test"
os.environ["API_KEY"] = "test-secret"


def _make_fake_graph():
    """Создаёт фейковый граф, invoke которого возвращает корректный dict
    совместимый с AgentRunner (messages содержит AIMessage-подобный объект).
    """
    from unittest.mock import MagicMock

    # AIMessage-подобный объект
    ai_msg = MagicMock()
    ai_msg.content = "ok"
    ai_msg.tool_call_id = None  # не ToolMessage
    # Чтобы langgraph не пытался конвертировать через convert_to_messages,
    # возвращаем уже готовый dict — invoke вернётся до любой обработки langgraph.

    fake_graph = MagicMock()
    fake_graph.invoke = MagicMock(return_value={
        "messages": [ai_msg],
        "output": "ok",
        "intermediate_steps": [],
    })
    return fake_graph


def _install_langchain_mocks() -> None:
    """
    Устанавливает / перезаписывает mock-объекты для langgraph.prebuilt.
    Принудительно патчим create_react_agent независимо от наличия пакета,
    чтобы в тестах не поднимался реальный LLM-граф.
    """
    # --- langchain.agents (только если пакет отсутствует) ---
    _langchain_agents_ok = False
    try:
        from langchain.agents import AgentExecutor  # noqa: F401
        _langchain_agents_ok = True
    except ImportError:
        pass

    if not _langchain_agents_ok:
        agents_mock = MagicMock()
        agents_mock.AgentExecutor = MagicMock
        agents_mock.create_openai_tools_agent = MagicMock(return_value=MagicMock())
        agents_mock.create_react_agent = MagicMock(return_value=MagicMock())
        sys.modules["langchain.agents"] = agents_mock

    # --- langgraph.prebuilt — ВСЕГДА принудительно патчим ---
    # Это ключевое изменение: даже при установленном langgraph
    # create_react_agent должен возвращать fake_graph, иначе
    # тесты падают с NotImplementedError: Unsupported message type: MagicMock.
    langgraph_prebuilt_mock = MagicMock()
    langgraph_prebuilt_mock.create_react_agent = MagicMock(
        side_effect=lambda *a, **kw: _make_fake_graph()
    )
    sys.modules["langgraph.prebuilt"] = langgraph_prebuilt_mock

    # Гарантируем что langgraph.prebuilt импортируется из mock
    # (на случай если он уже закеширован в sys.modules как реальный пакет).
    try:
        import langgraph.prebuilt as _lgp
        _lgp.create_react_agent = langgraph_prebuilt_mock.create_react_agent
    except Exception:
        pass

    # --- langchain.memory ---
    memory_mock = MagicMock()
    memory_mock.ConversationBufferWindowMemory = MagicMock
    sys.modules.setdefault("langchain.memory", memory_mock)

    # --- langchain_core.prompts ---
    prompts_mock = MagicMock()
    prompts_mock.ChatPromptTemplate = MagicMock()
    prompts_mock.ChatPromptTemplate.from_messages = MagicMock(return_value=MagicMock())
    prompts_mock.MessagesPlaceholder = MagicMock
    prompts_mock.PromptTemplate = MagicMock()
    prompts_mock.PromptTemplate.from_template = MagicMock(return_value=MagicMock())
    sys.modules.setdefault("langchain_core.prompts", prompts_mock)

    # --- langchain_openai ---
    lc_openai_mock = MagicMock()
    lc_openai_mock.ChatOpenAI = MagicMock
    sys.modules.setdefault("langchain_openai", lc_openai_mock)


# Применяем до любого импорта тестовых модулей.
_install_langchain_mocks()
