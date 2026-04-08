"""
Трейсинг шагов агента через Langfuse (opionally).

FIX SE-02: AUTH_HEADERS больше не строится на уровне модуля
(с раскрытием API_KEY в момент импорта).
Теперь ключ читается лениво — при первом реальном вызове log_agent_steps.
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger("tracing")


def _get_langfuse_auth_headers() -> dict[str, str]:
    """FIX SE-02: ленивое чтение API_KEY — не на уровне модуля."""
    api_key = os.getenv("API_KEY", "")
    return {"X-API-Key": api_key} if api_key else {}


def get_langfuse_callback():
    """Возвращает LangfuseCallbackHandler или None если Langfuse не настроен."""
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


def log_agent_steps(
    job_id: str,
    agent: str,
    steps: list,
) -> list[dict]:
    """Преобразует intermediate_steps агента в чистый JSON-сериализуемый trace."""
    trace: list[dict] = []
    for i, step in enumerate(steps):
        try:
            if isinstance(step, (list, tuple)) and len(step) >= 2:
                action, observation = step[0], step[1]
                tool = getattr(action, "tool", None) or str(action)
                tool_input = getattr(action, "tool_input", None)
                obs_parsed = (
                    json.loads(observation)
                    if isinstance(observation, str)
                    else observation
                )
                trace.append({
                    "step": i,
                    "tool": tool,
                    "tool_input": tool_input,
                    "observation": obs_parsed,
                })
            else:
                trace.append({"step": i, "raw": str(step)})
        except Exception as exc:
            logger.debug("[%s] Ошибка сериализации шага %d: %s", job_id, i, exc)
            trace.append({"step": i, "error": str(exc)})

    logger.info("[%s] agent=%s steps=%d", job_id, agent, len(trace))
    return trace
