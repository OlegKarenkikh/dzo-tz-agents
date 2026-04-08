"""
conftest.py — общие фикстуры и mock-объекты для тестов.

Стратегия патчинга create_react_agent
--------------------------------------
langgraph реально установлен в CI, поэтому простая замена sys.modules["langgraph.prebuilt"]
не работает: агентные модули (agent1/agent2/agent21) выполняют
    from langgraph.prebuilt import create_react_agent
на уровне модуля или лениво. Python кеширует имя в пространстве имён модуля
(binding), и последующая замена sys.modules не меняет уже связанный объект.

Правильное решение: патчить атрибут create_react_agent **в каждом агентном
модуле** через `module.create_react_agent = fake_fn` ПОСЛЕ их импорта,
а также заменять в langgraph.prebuilt (для ленивых импортов).

Дополнительно: build_llm патчится через monkeypatching shared.llm.build_llm,
чтобы не создавать реальный ChatOpenAI с фейковым ключом.
"""

import os
import sys
from unittest.mock import MagicMock

import pytest

os.environ["OPENAI_API_KEY"] = "sk-test"
os.environ["API_KEY"] = "test-secret"
os.environ["LLM_BACKEND"] = "openai"


# ---------------------------------------------------------------------------
# Fake graph factory
# ---------------------------------------------------------------------------

def _make_fake_graph() -> MagicMock:
    """
    Возвращает фиктивный граф-агент.
    AgentRunner.invoke() ожидает result["messages"] — список объектов с .content.
    tool_call_id должен быть falsy, чтобы msg не считался ToolMessage.
    """
    ai_msg = MagicMock()
    ai_msg.content = "ok"
    # Явно делаем tool_call_id falsy, чтобы AgentRunner не трактовал как ToolMessage
    ai_msg.tool_call_id = None
    # hasattr(msg, "tool_call_id") будет True, но значение None — пропускаем
    # AgentRunner проверяет: if hasattr(msg, "tool_call_id") — ToolMessage.
    # Поэтому удаляем атрибут полностью через spec или del.
    del ai_msg.tool_call_id

    fake_graph = MagicMock()
    fake_graph.invoke = MagicMock(return_value={
        "messages": [ai_msg],
    })
    return fake_graph


def _fake_create_react_agent(*args, **kwargs) -> MagicMock:
    """Замена create_react_agent — возвращает fake graph без запуска LLM."""
    return _make_fake_graph()


def _fake_build_llm(*args, **kwargs) -> MagicMock:
    """Замена build_llm — возвращает MagicMock вместо реального ChatOpenAI."""
    llm = MagicMock()
    llm.model_name = "gpt-mock"
    return llm


# ---------------------------------------------------------------------------
# Установка mock-ов
# ---------------------------------------------------------------------------

def _install_mocks() -> None:
    """
    Устанавливает все необходимые патчи ДО импорта тестовых модулей.

    Порядок:
    1. Патчим sys.modules["langgraph.prebuilt"] (для ленивых from-импортов).
    2. Патчим атрибут в реальном модуле langgraph.prebuilt (если установлен).
    3. Патчим shared.llm.build_llm (создание LLM без реального API-ключа).
    4. Импортируем агентные модули и патчим create_react_agent в каждом из них
       (устраняем проблему import binding — from X import Y кеширует ссылку).
    5. Патчим вспомогательные langchain-модули.
    """

    # 1. Патч sys.modules для ленивых импортов
    langgraph_prebuilt_mock = MagicMock()
    langgraph_prebuilt_mock.create_react_agent = _fake_create_react_agent
    sys.modules["langgraph.prebuilt"] = langgraph_prebuilt_mock

    # 2. Патч атрибута реального модуля (если langgraph установлен)
    try:
        import importlib
        real_lgp = importlib.import_module("langgraph.prebuilt")
        # После замены sys.modules выше import_module вернёт наш mock,
        # но на случай если он уже был закеширован — патчим напрямую:
        object.__setattr__(langgraph_prebuilt_mock, "create_react_agent", _fake_create_react_agent)
    except Exception:
        pass

    # 3. Патч shared.llm.build_llm — до импорта агентных модулей
    try:
        import shared.llm as _shared_llm
        _shared_llm.build_llm = _fake_build_llm
    except Exception:
        pass

    # 4. Импортируем агентные модули и патчим create_react_agent непосредственно
    #    в их пространстве имён (решает проблему import binding).
    _agent_modules = [
        "agent1_dzo_inspector.agent",
        "agent2_tz_inspector.agent",
        "agent21_tender_inspector.agent",
    ]
    for mod_name in _agent_modules:
        try:
            import importlib
            mod = importlib.import_module(mod_name)
            # Перезаписываем имя create_react_agent в пространстве имён модуля
            mod.create_react_agent = _fake_create_react_agent  # type: ignore[attr-defined]
        except Exception:
            # Модуль может отсутствовать или иметь ошибки импорта — не блокируем тесты
            pass

    # 5. Вспомогательные langchain-модули
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

    memory_mock = MagicMock()
    memory_mock.ConversationBufferWindowMemory = MagicMock
    sys.modules.setdefault("langchain.memory", memory_mock)

    prompts_mock = MagicMock()
    prompts_mock.ChatPromptTemplate = MagicMock()
    prompts_mock.ChatPromptTemplate.from_messages = MagicMock(return_value=MagicMock())
    prompts_mock.MessagesPlaceholder = MagicMock
    prompts_mock.PromptTemplate = MagicMock()
    prompts_mock.PromptTemplate.from_template = MagicMock(return_value=MagicMock())
    sys.modules.setdefault("langchain_core.prompts", prompts_mock)

    lc_openai_mock = MagicMock()
    lc_openai_mock.ChatOpenAI = MagicMock
    sys.modules.setdefault("langchain_openai", lc_openai_mock)


_install_mocks()
