"""Трейсинг агентов: Langfuse каллбэк и структурированный лог шагов.

Конфигурация через .env:
  LANGFUSE_PUBLIC_KEY  — публичный ключ проекта Langfuse
  LANGFUSE_SECRET_KEY  — секретный ключ
  LANGFUSE_HOST        — URL инстанции (default: https://cloud.langfuse.com)
                         для self-hosted: http://localhost:3000

Если LANGFUSE_PUBLIC_KEY не задан — трейсинг отключён, ошибок нет.
"""
from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING

from shared.logger import setup_logger

if TYPE_CHECKING:
    from langchain_core.callbacks import BaseCallbackHandler

logger = setup_logger("agent_trace")


def _init_langfuse() -> BaseCallbackHandler | None:
    """Инициализируется один раз при импорте модуля."""
    if not os.getenv("LANGFUSE_PUBLIC_KEY"):
        return None
    try:
        from langfuse.callback import CallbackHandler  # type: ignore
        cb = CallbackHandler()  # читает LANGFUSE_* из env автоматически
        logger.info("Langfuse трейсинг включён (host=%s)", os.getenv("LANGFUSE_HOST", "cloud"))
        return cb
    except ImportError:
        logger.warning("langfuse не установлен. Трейсинг отключён. Установите: pip install langfuse")
        return None


# Единственный экземпляр CallbackHandler на весь процесс
_langfuse_cb: BaseCallbackHandler | None = _init_langfuse()


def get_langfuse_callback() -> BaseCallbackHandler | None:
    """Вернуть кэшированный Langfuse CallbackHandler или None если трейсинг отключён."""
    return _langfuse_cb


def log_agent_steps(job_id: str, agent: str, steps: list) -> list[dict]:
    """Структурированно залогировать каждый шаг агента и вернуть trace-список для сохранения в БД.

    Каждый элемент trace:
        step        — порядковый номер шага
        tool        — название вызванного инструмента
        tool_input  — входные данные инструмента
        output_keys — ключи возвращаемого JSON (без больших HTML-блоков)
        decision    — решение если есть в observation
        latency_ms  — время обработки шага в миллисекундах
    """
    trace: list[dict] = []
    for i, (action, observation) in enumerate(steps, 1):
        t0 = time.perf_counter()
        try:
            obs = json.loads(observation) if isinstance(observation, str) else observation
        except Exception:  # noqa: BLE001
            obs = {"raw": str(observation)[:500]}
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)

        # Приводим к JSON-сериализуемым типам: str/dict/list/int/float/bool/None.
        # getattr на MagicMock возвращает MagicMock — без этого json.dumps упадёт.
        raw_tool = getattr(action, "tool", None)
        tool_name = raw_tool if isinstance(raw_tool, str) else str(raw_tool)

        raw_input = getattr(action, "tool_input", {})
        if isinstance(raw_input, (dict, str)):
            tool_input: dict | str = _truncate(raw_input)
        else:
            tool_input = str(raw_input)[:300]

        step_record: dict = {
            "step": i,
            "tool": tool_name,
            "tool_input": tool_input,
            "output_keys": list(obs.keys()) if isinstance(obs, dict) else [],
            "decision": obs.get("decision") if isinstance(obs, dict) else None,
            "latency_ms": latency_ms,
        }
        trace.append(step_record)
        try:
            logger.info(
                json.dumps(
                    {"job_id": job_id, "agent": agent, **step_record},
                    ensure_ascii=False,
                )
            )
        except (TypeError, ValueError):  # noqa: BLE001
            logger.info("[trace] job=%s agent=%s step=%d tool=%s", job_id, agent, i, tool_name)
    return trace


def _truncate(value: object, max_len: int = 300) -> object:
    """Укорачивает длинные строки в логе чтобы не засорять файл."""
    if isinstance(value, str) and len(value) > max_len:
        return value[:max_len] + "..."
    if isinstance(value, dict):
        return {k: _truncate(v, max_len) for k, v in value.items()}
    return value
