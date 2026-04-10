import os
import sys
import types
from unittest.mock import MagicMock

os.environ["OPENAI_API_KEY"] = "sk-test"
os.environ["API_KEY"] = "test-secret"
os.environ["LLM_BACKEND"] = "openai"


def _make_fake_graph() -> MagicMock:
    """
    Returns a fake graph agent for tests.

    AgentRunner.invoke() expects result["messages"] — list of objects with .content.
    We use SimpleNamespace (not MagicMock) for ai_msg so that hasattr(msg, "tool_call_id")
    correctly returns False — MagicMock creates any attribute on access, making hasattr
    always True even after `del`.
    """
    ai_msg = types.SimpleNamespace(content="ok")

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

    Why we patch module attributes (not sys.modules replacement)
    -------------------------------------------------------------
    Replacing sys.modules["langgraph.prebuilt"] with a MagicMock breaks
    langchain internals: langchain/tools/tool_node.py does
        from langgraph.prebuilt.tool_node import ...
    which requires langgraph.prebuilt to be a real package object with
    sub-module support — a MagicMock cannot serve as a package.

    Instead we patch create_react_agent as an attribute on the REAL
    langgraph.prebuilt module object.  This survives all import styles:
    - `import langgraph.prebuilt; langgraph.prebuilt.create_react_agent()`
    - `from langgraph.prebuilt import create_react_agent` (binding already done)
      -> we also patch each agent module's namespace directly after import.

    Order
    -----
    1. Patch langgraph.prebuilt.create_react_agent on the real module object.
    2. Patch shared.llm.build_llm before agent modules are imported.
    3. Import each agent module and overwrite create_react_agent in its namespace.
    4. Stub optional langchain helper modules if not installed.
    """
    import importlib

    # 1. Patch create_react_agent on the REAL langgraph.prebuilt module.
    #    DO NOT replace sys.modules["langgraph.prebuilt"] — that breaks
    #    langchain sub-module imports (langgraph.prebuilt.tool_node etc.)
    try:
        real_lgp = importlib.import_module("langgraph.prebuilt")
        real_lgp.create_react_agent = _fake_create_react_agent
    except (ImportError, ModuleNotFoundError):
        pass

    # 2. Patch shared.llm.build_llm before agent modules are imported
    try:
        import shared.llm as _shared_llm
        _shared_llm.build_llm = _fake_build_llm
    except (ImportError, ModuleNotFoundError):
        pass

    # 3. Import agent modules and overwrite create_react_agent in their namespaces
    #    (resolves import binding: `from X import Y` caches the object reference)
    for mod_name in (
        "agent1_dzo_inspector.agent",
        "agent2_tz_inspector.agent",
        "agent21_tender_inspector.agent",
        "agent3_collector_inspector.agent",
    ):
        try:
            mod = importlib.import_module(mod_name)
            mod.create_react_agent = _fake_create_react_agent  # type: ignore[attr-defined]
        except (ImportError, ModuleNotFoundError):
            pass

    # 4. Stub optional langchain helper modules if absent
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
