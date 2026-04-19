"""
Системные эндпоинты: /health, /agents, /.well-known/agent.json.
"""
from __future__ import annotations

import logging
import platform
import socket
import sys
import time
from datetime import UTC, datetime

from fastapi import APIRouter

from api.services.routing import AGENT_REGISTRY

logger = logging.getLogger("api")

router = APIRouter(tags=["system"])

_start_time = time.time()


@router.get("/health")
def health_check():
    from config import LLM_BACKEND, MODEL_NAME
    from shared.database import count_history
    try:
        jobs_count = count_history()
        db_ok = True
        db_error = None
    except Exception as e:
        jobs_count = 0
        db_ok = False
        db_error = str(e)
    uptime_sec = int(time.time() - _start_time)
    return {
        "status": "ok" if db_ok else "degraded",
        "timestamp": datetime.now(UTC).isoformat(),
        "uptime_seconds": uptime_sec,
        "uptime_sec": uptime_sec,          # backward compat
        "db": "ok" if db_ok else "error",
        "db_error": db_error,
        "jobs_count": jobs_count,
        "model": MODEL_NAME,
        "llm_backend": LLM_BACKEND,
        "version": "1.0",
        "python": sys.version.split()[0],
        "host": socket.gethostname(),
        "platform": platform.system(),
        "agent_mode": LLM_BACKEND,          # backward compat
    }


@router.get("/agents")
def list_agents():
    return {
        "agents": [
            {
                "id": agent_id,
                "name": info.get("name"),
                "description": info.get("description"),
                "decisions": info.get("decisions", []),
            }
            for agent_id, info in AGENT_REGISTRY.items()
        ]
    }


_AGENT_SKILL_ID: dict[str, str] = {
    "dzo": "inspect_dzo",
    "tz": "inspect_tz",
    "tender": "inspect_tender",
    "collector": "collect_documents",
}

import os as _os  # noqa: E402
from fastapi import Request, HTTPException  # noqa: E402


def _agent_card_base_url(request: Request) -> str:
    """Priority: PUBLIC_BASE_URL env > AGENT_CARD_ALLOWED_HOSTS > HTTP 500."""
    # Читаем PUBLIC_BASE_URL из os.environ — monkeypatch.setenv/delenv корректно
    # патчит os.environ, поэтому это единственный надёжный способ.
    pub = _os.getenv("PUBLIC_BASE_URL", "")
    if pub:
        return pub.rstrip("/")
    allowed_raw = _os.getenv("AGENT_CARD_ALLOWED_HOSTS", "")
    allowed = [h.strip() for h in allowed_raw.split(",") if h.strip()]
    if not allowed:
        raise HTTPException(
            status_code=500,
            detail="PUBLIC_BASE_URL not configured and AGENT_CARD_ALLOWED_HOSTS not set",
        )
    host = request.headers.get("host", "").split(":")[0]
    if host not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Host {host!r} not in AGENT_CARD_ALLOWED_HOSTS",
        )
    return f"https://{host}"


@router.get("/.well-known/agent.json")
def agent_card(request: Request):
    """A2A Agent Card (A2A spec 0.2.1)."""
    base_url = _agent_card_base_url(request)
    skills = [
        {
            "id": _AGENT_SKILL_ID.get(ag_id, f"inspect_{ag_id}"),
            "name": ag["name"],
            "description": ag.get("description", ""),
            "tags": [ag_id],
        }
        for ag_id, ag in AGENT_REGISTRY.items()
    ]
    return {
        "name": "AISRM Document Processing API",
        "description": "Мульти-агентная система инспекции документов",
        "version": "1.0.0",
        "protocolVersion": "0.2.1",
        "url": base_url,
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
        },
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": skills,
    }
