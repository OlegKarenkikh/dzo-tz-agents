import os
import sys
from unittest.mock import MagicMock

os.environ["OPENAI_API_KEY"] = "sk-test"
os.environ["API_KEY"] = "test-secret"
os.environ["LLM_BACKEND"] = "openai"


def _make_fake_graph() -> MagicMock:
    """
    Returns a fake graph agent for tests.

    AgentRunner.invoke() expects result["messages"] — list of objects with .content.
    We delete tool_call_id entirely so hasattr() returns False and AgentRunner
    does not mistake ai_msg for a ToolMessage (MagicMock creates any attr on access).
    """
    ai_msg = MagicMock()
    ai_msg.content = "ok"
    del ai_msg.tool_call_id  # prevent hasattr() returning True on MagicMock

    fake_graph = MagicMock()
    fake_graph.invoke = MagicMock(return_value={"messages": [ai_msg]})
    return fake_graph


def _fake_create_react_agent(*args, **kwargs) -> MagicMock:
    """Drop-in replacement for create_react_agent — returns fake graph without LLM."""
    return _make_fake_graph()


def _fake_build_llm(*args, **kwargs) -> MagicMock:
    """Drop-in replacement for build_llm — avoids real ChatOpenAI instantiation."""
    llm = MagicMock()
    llm.model_name = "gpt-mock"
    return llm


def _install_mocks() -> None:
    """
    Patch all LLM/agent dependencies before test modules are imported.

    Why we patch module attributes (not just sys.modules)
    -------------------------------------------------------
    When a module does ``from langgraph.prebuilt import create_react_agent`` the
    name is bound in the module's own namespace at import time.  Replacing
    sys.modules["langgraph.prebuilt"] afterwards does **not** update names that
    are already bound.  We must therefore also write directly into each agent
    module's namespace after importing it.

    Order
    -----
    1. Replace sys.modules["langgraph.prebuilt"] for lazy / future imports.
    2. Patch the real langgraph.prebuilt module object attribute (if installed).
    3. Patch shared.llm.build_llm before agent modules are imported.
    4. Import each agent module and overwrite create_react_agent in its namespace.
    5. Stub optional langchain helper modules.
    """
    import importlib

    # 1. sys.modules patch for lazy imports
    langgraph_prebuilt_mock = MagicMock()
    langgraph_prebuilt_mock.create_react_agent = _fake_create_react_agent
    sys.modules["langgraph.prebuilt"] = langgraph_prebuilt_mock

    # 2. Patch attribute on real module object in case it was already cached
    try:
        importlib.import_module("langgraph.prebuilt")  # returns our mock from sys.modules
        object.__setattr__(langgraph_prebuilt_mock, "create_react_agent", _fake_create_react_agent)
    except Exception:
        pass

    # 3. Patch shared.llm.build_llm before agent modules are imported
    try:
        import shared.llm as _shared_llm
        _shared_llm.build_llm = _fake_build_llm
    except Exception:
        pass

    # 4. Import agent modules and overwrite create_react_agent in their namespaces
    for mod_name in (
        "agent1_dzo_inspector.agent",
        "agent2_tz_inspector.agent",
        "agent21_tender_inspector.agent",
    ):
        try:
            mod = importlib.import_module(mod_name)
            mod.create_react_agent = _fake_create_react_agent  # type: ignore[attr-defined]
        except Exception:
            pass

    # 5. Stub optional langchain helper modules
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
