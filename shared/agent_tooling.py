"""Универсальный bridge: вызов одного агента из другого как tool.

Поддерживает:
  - конфигурируемый реестр фабрик агентов (через config.AGENT_TOOL_REGISTRY)
  - whitelist разрешений source_agent -> target_agent
  - кэш инстансов раннеров для снижения накладных расходов
"""

from __future__ import annotations

import importlib
import json
import os
import pkgutil
import re
import time
from functools import lru_cache
from threading import Lock
from typing import Any

import config
from shared.logger import setup_logger
from shared.llm import build_fallback_chain

logger = setup_logger("agent_tooling")

# Корень проекта — директория, в которой находится этот файл's parent (shared/../).
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_DEFAULT_AGENT_FACTORY_REGISTRY: dict[str, str] = {
    "dzo": "agent1_dzo_inspector.agent:create_dzo_agent",
    "tz": "agent2_tz_inspector.agent:create_tz_agent",
    "tender": "agent21_tender_inspector.agent:create_tender_agent",
    "collector": "agent3_collector_inspector.agent:create_collector_agent",
}

_DEFAULT_AGENT_TOOL_PERMISSIONS: dict[str, list[str]] = {
    "*": ["*"],
}

_agent_cache: dict[tuple[str, str | None], Any] = {}
_cache_lock = Lock()
_model_cooldown_until: dict[str, float] = {}
_cooldown_lock = Lock()
_AUTO_DISCOVER_PATTERN = re.compile(r"^agent\d+_([a-zA-Z0-9_]+)_inspector$")
_TOOL_CAPABLE_GITHUB_MODELS = {"gpt-4o", "gpt-4o-mini"}


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
    """Автообнаружение фабрик create_<agent_id>_agent по naming-convention.

    Сканируется только корень проекта (не весь sys.path), чтобы исключить
    случайный импорт сторонних пакетов с совпадающим именем.
    """
    discovered: dict[str, str] = {}
    for m in pkgutil.iter_modules([_PROJECT_ROOT]):
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


def _get_agent_runner(agent_id: str, model_name_override: str | None = None):
    with _cache_lock:
        cache_key = (agent_id, model_name_override)
        cached = _agent_cache.get(cache_key)
        if cached is not None:
            return cached

        registry = _get_registry()
        import_path = registry.get(agent_id)
        if not import_path:
            raise KeyError(f"Агент {agent_id!r} не найден в AGENT_TOOL_REGISTRY")

        factory = _load_factory(import_path)
        try:
            if model_name_override is not None:
                runner = factory(model_name=model_name_override)
            else:
                runner = factory()
        except TypeError:
            # Совместимость с кастомными фабриками без model_name.
            runner = factory()
        _agent_cache[cache_key] = runner
        logger.info("[agent-tool] cached runner for target=%s model=%s", agent_id, model_name_override)
        return runner


def _is_model_on_cooldown(model_name: str) -> bool:
    with _cooldown_lock:
        until = _model_cooldown_until.get(model_name, 0.0)
    return time.monotonic() < until


def _mark_model_cooldown(model_name: str, error_text: str) -> None:
    cooldown_sec = 60
    m = re.search(r"wait\s+(\d+)\s+seconds", error_text, re.IGNORECASE)
    if m:
        try:
            cooldown_sec = max(1, int(m.group(1)))
        except ValueError:
            cooldown_sec = 60
    with _cooldown_lock:
        _model_cooldown_until[model_name] = time.monotonic() + cooldown_sec


def _is_retryable_model_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "429" in text
        or "ratelimit" in text
        or "rate limit" in text
        or "413" in text
        or "tokens_limit_reached" in text
        or "too large" in text
        or "max size" in text
    )


def _build_tool_fallback_chain() -> list[str]:
    primary = getattr(config, "MODEL_NAME", "gpt-4o")
    chain = build_fallback_chain(primary)
    if getattr(config, "LLM_BACKEND", "openai") == "github_models":
        preferred = [m for m in chain if m in _TOOL_CAPABLE_GITHUB_MODELS]
        if preferred:
            chain = preferred
    return chain


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

    invoke_config = {"metadata": metadata} if metadata else {}

    last_exc: Exception | None = None
    for model_name in _build_tool_fallback_chain():
        if _is_model_on_cooldown(model_name):
            logger.info("[agent-tool] skip cooldown model=%s target=%s", model_name, target_agent)
            continue
        try:
            runner = _get_agent_runner(target_agent, model_name_override=model_name)
            result = runner.invoke({"input": chat_input}, config=invoke_config)
            if not isinstance(result, dict):
                raise TypeError("Некорректный формат ответа target-агента: ожидался dict")

            steps = result.get("intermediate_steps", []) or []
            if len(steps) == 0:
                raise RuntimeError("NoToolCalls")

            output = result.get("output", "")
            observations = extract_observations(result)
            return {
                "target_agent": target_agent,
                "output": output,
                "intermediate_steps": steps,
                "observations": observations,
            }
        except Exception as exc:
            last_exc = exc
            if _is_retryable_model_error(exc):
                _mark_model_cooldown(model_name, str(exc))
            logger.warning(
                "[agent-tool] model=%s target=%s failed: %s",
                model_name,
                target_agent,
                exc,
            )
            continue

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Не удалось выбрать доступную модель для межагентного tool-вызова")
