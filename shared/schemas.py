"""Pydantic schemas for structured agent output validation.

These models define the expected JSON structure of each agent's final decision.
Use for runtime validation of LLM output with graceful fallback on parse errors.

Usage::

    from shared.schemas import TZInspectionResult
    try:
        result = TZInspectionResult.model_validate_json(agent_output)
    except ValidationError:
        # graceful fallback — use raw text
        pass
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
from typing import Literal


class DZOInspectionResult(BaseModel):
    """Structured output for DZO inspector agent."""
    decision: Literal["Заявка полная", "Требуется доработка", "Требуется эскалация"]
    score_pct: float = Field(ge=0, le=100)
    checklist_1: dict[str, bool] = Field(default_factory=dict, description="Чек-лист №1: вложения")
    checklist_2: dict[str, bool] = Field(default_factory=dict, description="Чек-лист №2: реквизиты")
    checklist_3: dict[str, bool] = Field(default_factory=dict, description="Чек-лист №3: доп. поля")
    missing_critical: list[str] = Field(default_factory=list)
    missing_non_critical: list[str] = Field(default_factory=list)
    recommendation: str = ""


class TZInspectionResult(BaseModel):
    """Structured output for TZ inspector agent."""
    overall_status: str = "Требует доработки"

    @field_validator("overall_status", mode="before")
    @classmethod
    def normalize_status(cls, v: str) -> str:
        if not isinstance(v, str):
            return str(v)
        mapping = {
            "соответствует": "Соответствует",
            "принять": "Соответствует",
            "принять с замечанием": "Принять с замечанием",
            "требует доработки": "Требует доработки",
            "вернуть на доработку": "Вернуть на доработку",
            "вернуть": "Вернуть на доработку",
        }
        return mapping.get(v.lower().strip(), v)

    category: str = ""
    sections: list[dict] = Field(default_factory=list)
    critical_issues: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    score_pct: float = Field(ge=0, le=100, default=0)


class TenderInspectionResult(BaseModel):
    """Structured output for Tender document parser agent."""
    procurement_subject: str = ""
    documents: list[dict] = Field(default_factory=list)
    total_documents: int = 0
    mandatory_count: int = 0
    optional_count: int = 0


class CollectorResult(BaseModel):
    """Structured output for Collector agent."""
    tender_id: str = ""
    status: Literal["Сбор завершён", "Сбор не завершён", "Требуется проверка"] = "Сбор не завершён"
    total_expected: int = 0
    total_received: int = 0
    completeness_pct: float = Field(ge=0, le=100, default=0)
    participants: list[dict] = Field(default_factory=list)
    discrepancies: list[dict] = Field(default_factory=list)
    summary: str = ""
