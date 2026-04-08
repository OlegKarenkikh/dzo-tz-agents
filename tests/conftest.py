import os
import sys
from unittest.mock import MagicMock

os.environ["OPENAI_API_KEY"] = "sk-test"
os.environ["API_KEY"] = "test-secret"
os.environ["LLM_BACKEND"] = "openai"


def _make_fake_graph() -> MagicMock:
    ai_msg = MagicMock()
    ai_msg.content = "ok"
    del ai_msg.tool_call_id

    fake_graph = MagicMock()
    fake_graph.invoke = MagicMock(return_value={"messages": [ai_msg]})
    return fake_graph


def _fake_create_react_agent(*args, **kwargs) -> MagicMock:
    return _make_fake_graph()


def _fake_build_llm(*args, **kwargs) -> MagicMock:
    llm = MagicMock()
    llm.model_name = "gpt-mock"
    return llm


def _install_mocks() -> None:
    import importlib

    langgraph_prebuilt_mock = MagicMock()
    langgraph_prebuilt_mock.create_react_agent = _fake_create_react_agent
    sys.modules["langgraph.prebuilt"] = langgraph_prebuilt_mock

    try:
        importlib.import_module("langgraph.prebuilt")
        object.__setattr__(langgraph_prebuilt_mock, "create_react_agent", _fake_create_react_agent)
    except Exception:
        pass

    try:
        import shared.llm as _shared_llm
        _shared_llm.build_llm = _fake_build_llm
    except Exception:
        pass

    for mod_name in (
        "agent1_dzo_inspector.agent",
        "agent2_tz_inspector.agent",
        "agent21_tender_inspector.agent",
    ):
        try:
            mod = importlib.import_module(mod_name)
            mod.create_react_agent = _fake_create_react_agent  # type: ignore[attr-defined]
            mod.build_llm = _fake_build_llm  # type: ignore[attr-defined]
        except Exception:
            pass

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
