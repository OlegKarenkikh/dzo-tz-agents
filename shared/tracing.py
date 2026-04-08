"""
Трейсинг шагов агента через Langfuse (optionally).

FIX SE-02: AUTH_HEADERS больше не строится на уровне модуля.
Public API:
  get_langfuse_callback() -> CallbackHandler | None
  log_agent_steps(job_id, agent, steps) -> list[dict]
  _truncate(value, max_len=300) -> value  (экспортируется для тестов)
"""
from __future__ import annotations

import functools
import json
import os
import time
from typing import Any

from shared.logger import setup_logger

logger = setup_logger("agent_trace")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _truncate(value: Any, max_len: int = 300) -> Any:
    """Обрезает строку до max_len символов (добавляет '...').
    Для dict рекурсивно обрезает строковые значения верхнего уровня.
    Нестроковые/несловарные значения возвращаются без изменений.
    """
    if isinstance(value, str):
        if len(value) > max_len:
            return value[:max_len] + "..."
        return value
    if isinstance(value, dict):
        return {k: _truncate(v, max_len) for k, v in value.items()}
    return value


# ---------------------------------------------------------------------------
# Langfuse
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def get_langfuse_callback():
    """Возвращает LangfuseCallbackHandler или None если Langfuse не настроен.

    Результат кешируется (singleton per process) — повторные вызовы возвращают
    тот же экземпляр, что исключает дублирование callback-конфигурации.
    """
    pk = os.getenv("LANGFUSE_PUBLIC_KEY")
    sk = os.getenv("LANGFUSE_SECRET_KEY")
    if not pk or not sk:
        return None
    try:
        from langfuse.callback import CallbackHandler
        return CallbackHandler(public_key=pk, secret_key=sk)
    except ImportError:
        logger.debug("langfuse не установлен, трейсинг отключён")
        return None
    except Exception as exc:
        logger.warning("Не удалось создать LangfuseCallbackHandler: %s", exc)
        return None


# ---------------------------------------------------------------------------
# log_agent_steps
# ---------------------------------------------------------------------------

def log_agent_steps(
    job_id: str,
    agent: str,
    steps: list,
) -> list[dict]:
    """Преобразует intermediate_steps агента в JSON-сериализуемый trace.

    Каждый элемент trace:
      step       — 1-based номер шага
      tool       — имя инструмента (str)
      tool_input — входные данные (truncated, str если action — строка)
      decision   — значение поля 'decision' из observation (или None)
      output_keys — список ключей observation (или ['raw'] при невалидном JSON)
      latency_ms — float (0.0, реальное значение при наличии timestamps)
    """
    trace: list[dict] = []
    _t0 = time.monotonic()

    for i, step in enumerate(steps):
        step_t0 = time.monotonic()
        try:
            if not (isinstance(step, (list, tuple)) and len(step) >= 2):
                trace.append({"step": i + 1, "raw": str(step)})
                continue

            action, observation = step[0], step[1]

            # --- извлекаем tool и tool_input ---
            if isinstance(action, str):
                # tender-runner передаёт имя инструмента строкой
                tool_name: str = action
                tool_input: Any = {}
            else:
                # AgentAction / MagicMock — безопасно через getattr
                try:
                    tool_name = str(getattr(action, "tool", None) or action)
                except Exception:
                    tool_name = "unknown"
                try:
                    raw_input = getattr(action, "tool_input", None)
                    tool_input = raw_input
                except Exception:
                    tool_input = None

            # --- truncate tool_input ---
            if isinstance(tool_input, str):
                tool_input_stored: Any = _truncate(tool_input)
            elif isinstance(tool_input, dict):
                tool_input_stored = _truncate(tool_input)
            elif tool_input is None:
                tool_input_stored = {}
            else:
                try:
                    tool_input_stored = _truncate(str(tool_input))
                except Exception:
                    tool_input_stored = {}

            # --- разбираем observation ---
            obs_dict: dict | None = None
            output_keys: list[str]
            decision: str | None = None

            if isinstance(observation, dict):
                obs_dict = observation
            elif isinstance(observation, str):
                try:
                    parsed = json.loads(observation)
                    if isinstance(parsed, dict):
                        obs_dict = parsed
                    else:
                        obs_dict = None
                except (json.JSONDecodeError, ValueError):
                    obs_dict = None
            else:
                # прочие типы — пытаемся конвертировать
                try:
                    obs_dict = dict(observation) if observation is not None else None
                except Exception:
                    obs_dict = None

            if obs_dict is not None:
                output_keys = list(obs_dict.keys())
                decision = obs_dict.get("decision") or None
            else:
                output_keys = ["raw"]
                decision = None

            latency_ms = round((time.monotonic() - step_t0) * 1000, 3)

            trace.append({
                "step": i + 1,
                "tool": tool_name,
                "tool_input": tool_input_stored,
                "decision": decision,
                "output_keys": output_keys,
                "latency_ms": latency_ms,
            })

        except Exception as exc:
            logger.debug("[%s] Ошибка сериализации шага %d: %s", job_id, i + 1, exc)
            trace.append({"step": i + 1, "error": str(exc)})

    logger.info("[%s] agent=%s steps=%d elapsed_ms=%.1f",
                job_id, agent, len(trace),
                round((time.monotonic() - _t0) * 1000, 1))
    return trace
