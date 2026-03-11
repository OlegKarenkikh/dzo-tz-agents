"""
conftest.py — общие фикстуры и mock-объекты для тестов.

Создаёт заглушки модулей langchain для окружений без реального API ключа.
"""

import sys
from unittest.mock import MagicMock

import pytest


def _install_langchain_mocks() -> None:
    """
    Устанавливает mock-объекты для модулей langchain.
    Вызывается один раз при загрузке тестовой сессии.
    """
    try:
        from langchain.agents import AgentExecutor  # noqa: F401
        return  # Импорт работает — заглушки не нужны
    except ImportError:
        pass

    # langchain.agents: AgentExecutor + create_openai_tools_agent + create_react_agent
    agents_mock = MagicMock()
    agents_mock.AgentExecutor = MagicMock
    agents_mock.create_openai_tools_agent = MagicMock(return_value=MagicMock())
    agents_mock.create_react_agent = MagicMock(return_value=MagicMock())
    sys.modules["langchain.agents"] = agents_mock

    # langchain.memory
    memory_mock = MagicMock()
    memory_mock.ConversationBufferWindowMemory = MagicMock
    sys.modules.setdefault("langchain.memory", memory_mock)

    # langchain_core.prompts: ChatPromptTemplate + MessagesPlaceholder + PromptTemplate
    prompts_mock = MagicMock()
    prompts_mock.ChatPromptTemplate = MagicMock()
    prompts_mock.ChatPromptTemplate.from_messages = MagicMock(return_value=MagicMock())
    prompts_mock.MessagesPlaceholder = MagicMock
    prompts_mock.PromptTemplate = MagicMock()
    prompts_mock.PromptTemplate.from_template = MagicMock(return_value=MagicMock())
    sys.modules.setdefault("langchain_core.prompts", prompts_mock)

    # langchain_openai
    lc_openai_mock = MagicMock()
    lc_openai_mock.ChatOpenAI = MagicMock
    sys.modules.setdefault("langchain_openai", lc_openai_mock)


# Устанавливаем mock-и до любого импорта тестовых модулей
_install_langchain_mocks()
