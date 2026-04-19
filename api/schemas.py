"""
Pydantic-схемы запросов и ответов API.

Перенесено из api/app.py (TD-01).
"""
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

_MAX_BASE64_CHARS = 7_000_000
_MAX_REQUEST_BYTES = 10_000_000


class AttachmentData(BaseModel):
    filename: str = Field(max_length=500)
    content_base64: str = Field(max_length=_MAX_BASE64_CHARS)
    mime_type: str = Field(max_length=200)


class ProcessRequest(BaseModel):
    text: str = Field(default="", description="Текст документа", max_length=5_000_000)
    filename: str = Field(default="", description="Имя исходного файла", max_length=500)
    sender_email: str = Field(default="", description="Email отправителя", max_length=1000)
    subject: str = Field(default="", description="Тема письма", max_length=10_000)
    attachments: list[AttachmentData] = Field(default_factory=list, description="Вложения в base64")
    force: bool = Field(default=False, description="Обработать заново, даже если дубликат уже есть")

    @model_validator(mode="after")
    def check_total_payload_size(self) -> "ProcessRequest":
        total = len(self.text) + len(self.filename) + len(self.sender_email) + len(self.subject)
        for att in self.attachments:
            total += len(att.content_base64) + len(att.filename) + len(att.mime_type)
        if total > _MAX_REQUEST_BYTES:
            raise ValueError(
                f"Суммарный размер полей запроса (~{total} байт) превышает лимит {_MAX_REQUEST_BYTES} байт"
            )
        return self


class JobResponse(BaseModel):
    job_id: str
    status: str
    agent: str
    created_at: datetime
    result: dict | None = None
    error: str | None = None


class DuplicateResponse(BaseModel):
    duplicate: bool
    existing_job_id: str | None = None
    job: dict | None = None
    message: str = ""


class PaginatedResponse(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int
    has_next: bool
    items: list[dict]
