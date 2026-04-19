"""
Системные эндпоинты: /health, /agents, /.well-known/agent.json.

Перенесено из api/app.py (TD-01).
"""
from __future__ import annotations

import logging
import platform
import socket
import sys
import time
from datetime import UTC, datetime

from fastapi import APIRouter

logger = logging.getLogger("api")

router = APIRouter(tags=["system"])

_start_time = time.time()


@router.get("/health")
def health_check():
    from config import MODEL_NAME, LLM_BACKEND
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
        "db": "ok" if db_ok else "error",
        "db_error": db_error,
        "jobs_count": jobs_count,
        "model": MODEL_NAME,
        "llm_backend": LLM_BACKEND,
        "version": "1.0",
        "python": sys.version.split()[0],
        "host": socket.gethostname(),
        "platform": platform.system(),
    }


@router.get("/agents")
def list_agents():
    from api.services.routing import AGENT_REGISTRY
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


@router.get("/.well-known/agent.json")
def agent_card():
    return {
        "name": "AISRM Multi-Agent API",
        "version": "1.0",
        "description": "Система инспекции документов на базе LLM-агентов",
        "url": "/api/v1",
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": True,
        },
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [
            {"id": ag_id, "name": ag["name"], "description": ag.get("description", "")}
            for ag_id, ag in AGENT_REGISTRY.items()
        ],
    }
