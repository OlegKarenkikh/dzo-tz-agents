"""Универсальный bridge: вызов одного агента из другого как tool.

Поддерживает:
  - конфигурируемый реестр фабрик агентов (через config.AGENT_TOOL_REGISTRY)
  - whitelist разрешений source_agent -> target_agent
  - кэш инстансов раннеров для снижения накладных расходов
"""

from __future__ import annotations

import importlib
import json
import pkgutil
import re
from functools import lru_cache
from threading import Lock
from typing import Any

import config
from shared.logger import setup_logger

logger = setup_logger("agent_tooling")

_DEFAULT_AGENT_FACTORY_REGISTRY: dict[str, str] = {
    "dzo": "agent1_dzo_inspector.agent:create_dzo_agent",
    "tz": "agent2_tz_inspector.agent:create_tz_agent",
    "tender": "agent21_tender_inspector.agent:create_tender_agent",
}

_DEFAULT_AGENT_TOOL_PERMISSIONS: dict[str, list[str]] = {
    "*": ["*"],
}

_agent_cache: dict[str, Any] = {}
_cache_lock = Lock()
_AUTO_DISCOVER_PATTERN = re.compile(r"^agent\d+_([a-zA-Z0-9_]+)_inspector$")


def _get_registry() -> dict[str, str]:
    merged = dict(_DEFAULT_AGENT_FACTORY_REGISTRY)
    merged.update(_discover_agent_factories())
    for agent_id, import_path in config.AGENT_TOOL_REGISTRY.items():
        if isinstance(agent_id, str) and isinstance(import_path, str):
            merged[agent_id.strip()] = import_path.strip()
    return merged


def _get_permissions() -> dict[str, list[str]]:
    merged = {k: list(v) for k, v in _DEFAULT_AGENT_TOOL_PERMISSIONS.items()}
    for source_agent, targets in config.AGENT_TOOL_PERMISSIONS.items():
        if isinstance(source_agent, str) and isinstance(targets, list):
            merged[source_agent.strip()] = [str(x).strip() for x in targets]
    return merged


@lru_cache(maxsize=1)
def _discover_agent_factories() -> dict[str, str]:
    """Автообнаружение фабрик create_<agent_id>_agent по naming-convention."""
    discovered: dict[str, str] = {}
    for m in pkgutil.iter_modules():
        match = _AUTO_DISCOVER_PATTERN.match(m.name)
        if not match:
            continue
        agent_id = match.group(1)
        module_name = f"{m.name}.agent"
        attr = f"create_{agent_id}_agent"
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        factory = getattr(module, attr, None)
        if callable(factory):
            discovered[agent_id] = f"{module_name}:{attr}"
    return discovered


def _load_factory(import_path: str):
    if ":" not in import_path:
        raise ValueError(f"Некорректный import path фабрики агента: {import_path}")
    module_name, attr = import_path.split(":", 1)
    module = importlib.import_module(module_name)
    factory = getattr(module, attr, None)
    if factory is None:
        raise AttributeError(f"Фабрика {attr!r} не найдена в модуле {module_name!r}")
    return factory


def _get_agent_runner(agent_id: str):
    with _cache_lock:
        cached = _agent_cache.get(agent_id)
        if cached is not None:
            return cached

        registry = _get_registry()
        import_path = registry.get(agent_id)
        if not import_path:
            raise KeyError(f"Агент {agent_id!r} не найден в AGENT_TOOL_REGISTRY")

        factory = _load_factory(import_path)
        runner = factory()
        _agent_cache[agent_id] = runner
        logger.info("[agent-tool] cached runner for target=%s", agent_id)
        return runner


def extract_observations(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Нормализует intermediate_steps результата invoke в список dict."""
    observations: list[dict[str, Any]] = []
    for step in result.get("intermediate_steps", []) or []:
        if not isinstance(step, (list, tuple)) or len(step) < 2:
            continue
        obs = step[1]
        if isinstance(obs, str):
            try:
                obs = json.loads(obs)
            except json.JSONDecodeError:
                obs = {"raw": obs}
        if isinstance(obs, dict):
            observations.append(obs)
    return observations


def invoke_agent_as_tool(
    *,
    source_agent: str,
    target_agent: str,
    chat_input: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Выполняет безопасный вызов target-агента из source-агента."""
    if not config.AGENT_TOOL_ENABLED:
        raise RuntimeError("Межагентные tool-вызовы отключены (AGENT_TOOL_ENABLED=false)")

    permissions = _get_permissions()
    registry = _get_registry()

    if source_agent in permissions:
        allowed_targets = set(permissions[source_agent])
    elif "*" in permissions:
        allowed_targets = set(permissions["*"])
    else:
        # default policy: любой агент может вызывать всех (кроме самого себя)
        allowed_targets = {agent_id for agent_id in registry if agent_id != source_agent}

    if "*" in allowed_targets:
        allowed_targets = {agent_id for agent_id in registry if agent_id != source_agent}

    if target_agent == source_agent:
        raise PermissionError("Межагентный вызов самого себя запрещён")

    if target_agent not in allowed_targets:
        raise PermissionError(
            f"Запрещён межагентный вызов: {source_agent!r} -> {target_agent!r}. "
            "Разрешите маршрут через AGENT_TOOL_PERMISSIONS."
        )

    runner = _get_agent_runner(target_agent)
    invoke_config = {"metadata": metadata} if metadata else {}
    result = runner.invoke({"input": chat_input}, config=invoke_config)
    if not isinstance(result, dict):
        raise TypeError("Некорректный формат ответа target-агента: ожидался dict")

    output = result.get("output", "")
    steps = result.get("intermediate_steps", []) or []
    observations = extract_observations(result)

    return {
        "target_agent": target_agent,
        "output": output,
        "intermediate_steps": steps,
        "observations": observations,
    }
