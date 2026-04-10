"""
shared/mcp_server.py
MCP (Model Context Protocol) server — предоставляет агентов ДЗО, ТЗ, Тендер
и Collector как инструменты для любых MCP-совместимых клиентов (Claude Desktop,
Cursor, Copilot, Continue и др.).

Депендансы: mcp[cli]>=1.3.0 (fastmcp)

Использование:
  # Встроенный запуск (stdio — для Claude Desktop / Cursor):
  python -m shared.mcp_server

  # Монтирование как HTTP-стрим в FastAPI:
  from shared.mcp_server import mcp
  app.mount("/mcp", mcp.streamable_http_app())
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as _err:  # pragma: no cover
    raise ImportError(
        "Пакет 'mcp' не установлен. Выполните: pip install 'mcp[cli]>=1.3.0'"
    ) from _err

from shared.logger import setup_logger

logger = setup_logger("mcp_server")

mcp = FastMCP(
    "dzo-tz-agents",
    instructions=(
        "Инструменты для проверки документов корпоративных закупок. "
        "Используй inspect_dzo для заявок ДЗО, inspect_tz для технических заданий, "
        "inspect_tender для тендерной документации, "
        "collect_documents для сбора анкет участников тендерного отбора."
    ),
    streamable_http_path="/",
)

# Максимальная длина суммарного входного текста — соответствует max_length
# поля text в ProcessRequest (api/app.py), защищает от чрезмерно дорогих LLM-вызовов.
_MCP_MAX_INPUT_CHARS = 5_000_000

# Mapping agent_type → MCP tool function name, used by list_agents
# to derive the tool field from AGENT_REGISTRY.
_AGENT_TOOL_MAP: dict[str, str] = {
    "dzo": "inspect_dzo",
    "tz": "inspect_tz",
    "tender": "inspect_tender",
    "collector": "collect_documents",
}


def _invoke_agent(agent_type: str, chat_input: str, model_name: str | None = None) -> dict[str, Any]:
    """Общий вызов агента по типу (синхронный — вызывается через asyncio.to_thread)."""
    # Проверяем лимит ДО создания агента — создание агента тяжело (инициализация LLM/графа)
    if len(chat_input) > _MCP_MAX_INPUT_CHARS:
        msg = (
            f"Текст превышает лимит {_MCP_MAX_INPUT_CHARS:,} символов "
            f"(получено {len(chat_input):,}). Сократите входной текст."
        )
        logger.warning("[MCP] agent=%s input too large: %d chars", agent_type, len(chat_input))
        return {"output": "", "agent": agent_type, "steps": 0, "error": msg}

    if agent_type == "dzo":
        from agent1_dzo_inspector.agent import create_dzo_agent
        agent = create_dzo_agent(model_name=model_name)
    elif agent_type == "tz":
        from agent2_tz_inspector.agent import create_tz_agent
        agent = create_tz_agent(model_name=model_name)
    elif agent_type == "tender":
        from agent21_tender_inspector.agent import create_tender_agent
        agent = create_tender_agent(model_name=model_name)
    elif agent_type == "collector":
        from agent3_collector_inspector.agent import create_collector_agent
        agent = create_collector_agent(model_name=model_name)
    else:
        raise ValueError(f"Неизвестный тип агента: {agent_type!r}")

    logger.info("[MCP] invoke agent=%s input_len=%d", agent_type, len(chat_input))
    try:
        result = agent.invoke({"input": chat_input})
        return {
            "output": result.get("output", ""),
            "agent": agent_type,
            "steps": len(result.get("intermediate_steps", [])),
        }
    except Exception as exc:
        logger.exception("[MCP] agent=%s error_type=%s error=%s", agent_type, type(exc).__name__, exc)
        return {"output": "", "agent": agent_type, "steps": 0, "error": str(exc)}


async def _invoke_agent_async(agent_type: str, chat_input: str, model_name: str | None = None) -> dict[str, Any]:
    """Non-blocking wrapper: offloads sync agent invocation to a thread pool.

    This prevents the synchronous LLM calls (30-300s) from blocking the
    FastAPI event loop (which would freeze /health, /metrics, etc.).
    """
    return await asyncio.to_thread(_invoke_agent, agent_type, chat_input, model_name)


def _create_mcp_job(agent_type: str, chat_input: str, model_name: str | None = None) -> dict[str, Any]:
    """Invoke agent through the job-tracking pipeline.

    Creates a tracked job, runs the agent, and records the outcome — making
    MCP invocations visible in /api/v1/jobs, /api/v1/stats, and Prometheus.
    """
    from shared.database import create_job, update_job

    job_id = create_job(agent_type, sender="mcp", subject="MCP tool call")
    update_job(job_id, status="running")
    try:
        result = _invoke_agent(agent_type, chat_input, model_name)
        if "error" in result:
            update_job(job_id, status="error", error=result["error"])
        else:
            update_job(
                job_id,
                status="done",
                decision=f"mcp_{agent_type}",
                result={"output": result.get("output", ""), "steps": result.get("steps", 0)},
            )
        result["job_id"] = job_id
        return result
    except Exception as exc:
        update_job(job_id, status="error", error=str(exc))
        raise


async def _create_mcp_job_async(agent_type: str, chat_input: str, model_name: str | None = None) -> dict[str, Any]:
    """Non-blocking wrapper for _create_mcp_job."""
    return await asyncio.to_thread(_create_mcp_job, agent_type, chat_input, model_name)


@mcp.tool()
async def inspect_dzo(
    text: str,
    sender_email: str = "",
    subject: str = "",
    model_name: str = "",
) -> dict[str, Any]:
    """Проверяет заявку ДЗО (дочернего зависимого общества) на полноту
    и соответствие корпоративным требованиям перед регистрацией в системе Тезис.

    Проверяет:
    - Наличие всех обязательных реквизитов (инициатор, количество, сроки, адрес)
    - Комплектность вложений (ТЗ, спецификация)
    - Бюджет и обоснование закупки

    Returns:
        dict с полями: output (текстовый результат), agent, steps, job_id
    """
    parts: list[str] = []
    if sender_email:
        parts.append(f"От: {sender_email}")
    if subject:
        parts.append(f"Тема: {subject}")
    parts.append(text)
    chat_input = "\n".join(parts)
    return await _create_mcp_job_async("dzo", chat_input, model_name or None)


@mcp.tool()
async def inspect_tz(
    text: str,
    model_name: str = "",
) -> dict[str, Any]:
    """Анализирует техническое задание (ТЗ) на соответствие корпоративному шаблону
    и требованиям ГОСТ.

    Проверяет наличие 8 обязательных разделов:
    1. Цель закупки
    2. Требования к товару/работе/услуге
    3. Количество и единицы измерения
    4. Срок и условия поставки
    5. Место поставки
    6. Требования к исполнителю
    7. Критерии оценки заявок
    8. Приложения

    Returns:
        dict с полями: output (текстовый результат), agent, steps, job_id
    """
    return await _create_mcp_job_async("tz", text, model_name or None)


@mcp.tool()
async def inspect_tender(
    text: str,
    model_name: str = "",
) -> dict[str, Any]:
    """Парсит тендерную документацию и извлекает полный список документов,
    требуемых от участника закупки (44-ФЗ / 223-ФЗ).

    Возвращает структурированный список документов с указанием:
    - Раздела документации
    - Требований к содержанию
    - Обязательности

    Returns:
        dict с полями: output (текстовый результат), agent, steps, job_id
    """
    return await _create_mcp_job_async("tender", text, model_name or None)


@mcp.tool()
async def collect_documents(
    text: str,
    model_name: str = "",
) -> dict[str, Any]:
    """Собирает и проверяет документы участников тендерного отбора (анкеты, NDA).

    Автоматизирует процесс:
    - Идентификация участников по email/ИНН/наименованию
    - Классификация вложений (анкета / NDA / прочее)
    - Валидация ИНН и наименования из анкеты
    - Формирование структуры папок и отчёта о сборе

    Returns:
        dict с полями: output (текстовый результат), agent, steps, job_id
    """
    return await _create_mcp_job_async("collector", text, model_name or None)


@mcp.tool()
def list_agents() -> dict[str, Any]:
    """Возвращает список доступных агентов с описанием.

    Returns:
        dict с полем agents — список агентов {id, name, description, tool}
    """
    # Derive from the single AGENT_REGISTRY source of truth (api/app.py).
    # Deferred import to avoid circular import at module load time.
    from api.app import AGENT_REGISTRY

    return {
        "agents": [
            {
                "id": agent_id,
                "name": info.get("name", agent_id),
                "description": info.get("description", ""),
                "tool": _AGENT_TOOL_MAP.get(agent_id, f"inspect_{agent_id}"),
            }
            for agent_id, info in AGENT_REGISTRY.items()
        ]
    }


if __name__ == "__main__":  # pragma: no cover
    # Запуск stdio-транспорта (для Claude Desktop / Cursor)
    _level_str = os.getenv("MCP_LOG_LEVEL", "WARNING").upper()
    _level_int = getattr(logging, _level_str, None)
    if not isinstance(_level_int, int):
        logger.warning(
            "Invalid MCP_LOG_LEVEL=%r, falling back to WARNING",
            os.getenv("MCP_LOG_LEVEL", ""),
        )
        _level_int = logging.WARNING
    # Задаём уровень непосредственно логгеру mcp_server и отключаем propagation,
    # чтобы его записи не дублировались в root-logger после basicConfig.
    # Root-логирование полезно для зависимостей (mcp, uvicorn и т.д.).
    logger.setLevel(_level_int)
    logger.propagate = False
    logging.basicConfig(level=_level_int)
    mcp.run(transport="stdio")
