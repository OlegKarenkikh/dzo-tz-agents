"""
conftest.py — общие фикстуры и mock-объекты для тестов.
Создаёт заглушки модулей langchain/langgraph для окружений без реального API ключа.

FIX ST-03: mock покрывает реальный импорт langgraph.prebuilt.create_react_agent
(после ST-02, где заменили несуществующий langchain.agents.create_agent).
"""

import os
import sys
from unittest.mock import MagicMock

import pytest

# Устанавливаем единый API_KEY до любых импортов — один источник истины для всех тестов.
os.environ["OPENAI_API_KEY"] = "sk-test"
os.environ["API_KEY"] = "test-secret"


def _install_langchain_mocks() -> None:
    """
    Устанавливает mock-объекты для модулей langchain/langgraph.
    Вызывается один раз при загрузке тестовой сессии.

    FIX ST-03: добавлен mock для langgraph.prebuilt.create_react_agent,
    чтобы тесты не падали при отсутствии реального LLM/API-ключа.
    Также добавлена проверка наличия реального langgraph перед установкой mock:
    если пакет доступен — mock не нужен.
    """
    # --- langchain.agents ---
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

    # --- langgraph.prebuilt (FIX ST-03) ---
    _langgraph_ok = False
    try:
        from langgraph.prebuilt import create_react_agent  # noqa: F401
        _langgraph_ok = True
    except ImportError:
        pass

    if not _langgraph_ok:
        _fake_graph = MagicMock()
        _fake_graph.invoke = MagicMock(return_value={
            "messages": [],
        })
        langgraph_prebuilt_mock = MagicMock()
        langgraph_prebuilt_mock.create_react_agent = MagicMock(return_value=_fake_graph)
        sys.modules.setdefault("langgraph", MagicMock())
        sys.modules["langgraph.prebuilt"] = langgraph_prebuilt_mock

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


# Устанавливаем mock-и до любого импорта тестовых модулей
_install_langchain_mocks()
