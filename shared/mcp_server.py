"""
shared/mcp_server.py
MCP (Model Context Protocol) server — предоставляет агентов ДЗО, ТЗ и Тендер
как инструменты для любых MCP-совместимых клиентов (Claude Desktop, Cursor,
Copilot, Continue и др.).

Депендансы: mcp[cli]>=1.3.0 (fastmcp)

Использование:
  # Встроенный запуск (stdio — для Claude Desktop / Cursor):
  python -m shared.mcp_server

  # Монтирование как HTTP-стрим в FastAPI:
  from shared.mcp_server import mcp
  app.mount("/mcp", mcp.streamable_http_app())
"""
from __future__ import annotations

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
        "inspect_tender для тендерной документации."
    ),
    streamable_http_path="/",
)

# Максимальная длина суммарного входного текста — соответствует max_length
# поля text в ProcessRequest (api/app.py), защищает от чрезмерно дорогих LLM-вызовов.
_MCP_MAX_INPUT_CHARS = 5_000_000


def _invoke_agent(agent_type: str, chat_input: str, model_name: str | None = None) -> dict[str, Any]:
    """Общий вызов агента по типу."""
    if agent_type == "dzo":
        from agent1_dzo_inspector.agent import create_dzo_agent
        agent = create_dzo_agent(model_name=model_name)
    elif agent_type == "tz":
        from agent2_tz_inspector.agent import create_tz_agent
        agent = create_tz_agent(model_name=model_name)
    elif agent_type == "tender":
        from agent21_tender_inspector.agent import create_tender_agent
        agent = create_tender_agent(model_name=model_name)
    else:
        raise ValueError(f"Неизвестный тип агента: {agent_type!r}")

    logger.info("[MCP] invoke agent=%s input_len=%d", agent_type, len(chat_input))
    if len(chat_input) > _MCP_MAX_INPUT_CHARS:
        msg = (
            f"Текст превышает лимит {_MCP_MAX_INPUT_CHARS:,} символов "
            f"(получено {len(chat_input):,}). Сократите входной текст."
        )
        logger.warning("[MCP] agent=%s input too large: %d chars", agent_type, len(chat_input))
        return {"output": "", "agent": agent_type, "steps": 0, "error": msg}
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


@mcp.tool()
def inspect_dzo(
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
        dict с полями: output (текстовый результат), agent, steps
    """
    parts: list[str] = []
    if sender_email:
        parts.append(f"От: {sender_email}")
    if subject:
        parts.append(f"Тема: {subject}")
    parts.append(text)
    chat_input = "\n".join(parts)
    return _invoke_agent("dzo", chat_input, model_name or None)


@mcp.tool()
def inspect_tz(
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
        dict с полями: output (текстовый результат), agent, steps
    """
    return _invoke_agent("tz", text, model_name or None)


@mcp.tool()
def inspect_tender(
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
        dict с полями: output (текстовый результат), agent, steps
    """
    return _invoke_agent("tender", text, model_name or None)


@mcp.tool()
def list_agents() -> dict[str, Any]:
    """Возвращает список доступных агентов с описанием.

    Returns:
        dict с полем agents — список агентов {id, name, description}
    """
    return {
        "agents": [
            {
                "id": "dzo",
                "name": "Инспектор ДЗО",
                "description": "Проверяет заявки ДЗО на полноту и корректность",
                "tool": "inspect_dzo",
            },
            {
                "id": "tz",
                "name": "Инспектор ТЗ",
                "description": "Анализирует ТЗ на соответствие ГОСТ и внутренним стандартам",
                "tool": "inspect_tz",
            },
            {
                "id": "tender",
                "name": "Парсер тендерной документации",
                "description": "Извлекает список документов из тендерной документации",
                "tool": "inspect_tender",
            },
        ]
    }


if __name__ == "__main__":  # pragma: no cover
    # Запуск stdio-транспорта (для Claude Desktop / Cursor)
    log_level = os.getenv("MCP_LOG_LEVEL", "WARNING")
    logging.basicConfig(level=getattr(logging, log_level, logging.WARNING))
    mcp.run(transport="stdio")
