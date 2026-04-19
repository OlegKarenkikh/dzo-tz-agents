"""
Эндпоинты обработки документов: /process, /upload.

Перенесено из api/app.py (TD-01).
"""
from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile

from api.schemas import AttachmentData, DuplicateResponse, ProcessRequest
from api.security import require_api_key
from api.services.processing import check_and_process
from api.services.routing import AGENT_REGISTRY, detect_agent_type

logger = logging.getLogger("api")

router = APIRouter(prefix="/api/v1", tags=["process"])

_run_log: list[dict] = []


@router.post("/process", response_model=DuplicateResponse)
def process_document(
    request: ProcessRequest,
    background_tasks: BackgroundTasks,
    _key: str = Depends(require_api_key),
):
    agent_type = detect_agent_type(request)
    logger.info(
        "/process agent=%s subject=%r sender=%r",
        agent_type, request.subject[:80] if request.subject else "", request.sender_email,
    )
    return check_and_process(agent_type, request, background_tasks, _run_log, AGENT_REGISTRY)


@router.post("/process/{agent_type}", response_model=DuplicateResponse)
def process_document_explicit(
    agent_type: str,
    request: ProcessRequest,
    background_tasks: BackgroundTasks,
    _key: str = Depends(require_api_key),
):
    if agent_type not in AGENT_REGISTRY:
        raise HTTPException(status_code=400, detail="Неизвестный агент: " + repr(agent_type))
    logger.info(
        "/process/%s subject=%r sender=%r",
        agent_type, request.subject[:80] if request.subject else "", request.sender_email,
    )
    return check_and_process(agent_type, request, background_tasks, _run_log, AGENT_REGISTRY)


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    sender_email: str = Form(default=""),
    subject: str = Form(default=""),
    agent_type: str | None = Form(default=None),
    force: bool = Form(default=False),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    _key: str = Depends(require_api_key),
):
    raw = await file.read()
    if len(raw) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Файл превышает 50 МБ")
    content_b64 = base64.b64encode(raw).decode()
    filename = file.filename or "uploaded_file"
    mime = file.content_type or "application/octet-stream"
    request = ProcessRequest(
        text="",
        filename=filename,
        sender_email=sender_email,
        subject=subject or filename,
        attachments=[AttachmentData(filename=filename, content_base64=content_b64, mime_type=mime)],
        force=force,
    )
    _agent = agent_type if agent_type else detect_agent_type(request)
    if _agent not in AGENT_REGISTRY:
        raise HTTPException(status_code=400, detail="Неизвестный агент: " + repr(_agent))
    return check_and_process(_agent, request, background_tasks, _run_log, AGENT_REGISTRY)


@router.get("/run_log")
def get_run_log(_key: str = Depends(require_api_key)):
    return {"run_log": _run_log[-200:]}
