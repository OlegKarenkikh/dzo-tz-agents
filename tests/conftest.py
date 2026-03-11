"""
conftest.py — общие фикстуры и мок-объекты для тестов.

Этот файл создаёт фиктивные модули langchain для окружений,
где установлена версия langchain без AgentExecutor (v1.x).
"""

import sys
from unittest.mock import MagicMock

import pytest


def _install_langchain_mocks() -> None:
    """
    Устанавливает mock-объекты для модулей langchain, которые
    отсутствуют в новых версиях библиотеки (AgentExecutor и т.д.).
    Вызывается один раз при загрузке тестового сессии.
    """
    # Проверяем, нужна ли заглушка
    try:
        from langchain.agents import AgentExecutor  # noqa: F401
        return  # Импорт работает — заглушки не нужны
    except ImportError:
        pass

    # Создаём mock для langchain.agents с нужными атрибутами
    agents_mock = MagicMock()
    agents_mock.AgentExecutor = MagicMock
    agents_mock.create_openai_tools_agent = MagicMock(return_value=MagicMock())

    sys.modules["langchain.agents"] = agents_mock

    # langchain.memory.ConversationBufferWindowMemory
    memory_mock = MagicMock()
    memory_mock.ConversationBufferWindowMemory = MagicMock
    sys.modules.setdefault("langchain.memory", memory_mock)

    # langchain_openai.ChatOpenAI
    lc_openai_mock = MagicMock()
    lc_openai_mock.ChatOpenAI = MagicMock
    sys.modules.setdefault("langchain_openai", lc_openai_mock)


# Устанавливаем mock-и до любого импорта тестовых модулей
_install_langchain_mocks()
