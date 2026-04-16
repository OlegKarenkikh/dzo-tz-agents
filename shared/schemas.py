"""Pydantic schemas for structured agent output."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


class DZODecision(BaseModel):
    """Structured output for DZO agent."""
    decision: Literal["ЗАЯВКА ПОЛНАЯ", "ТРЕБУЕТСЯ ДОРАБОТКА", "ТРЕБУЕТСЯ ЭСКАЛАЦИЯ"]
    score_pct: float = Field(ge=0, le=100)
    missing_critical: list[str] = Field(default_factory=list)
    missing_optional: list[str] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)
    summary: str = ""


class TZDecision(BaseModel):
    """Structured output for TZ agent."""
    decision: Literal["ПРИНЯТЬ", "ПРИНЯТЬ С ЗАМЕЧАНИЕМ", "ВЕРНУТЬ НА ДОРАБОТКУ"]
    score_pct: float = Field(ge=0, le=100)
    sections_present: dict[str, bool] = Field(default_factory=dict)
    missing_critical: list[str] = Field(default_factory=list)
    missing_optional: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    summary: str = ""


class TenderDecision(BaseModel):
    """Structured output for Tender agent."""
    decision: Literal["ДОКУМЕНТАЦИЯ ПОЛНАЯ", "ТРЕБУЕТСЯ ДОРАБОТКА", "КРИТИЧЕСКИЕ НАРУШЕНИЯ"]
    documents_found: int = 0
    completeness_pct: float = Field(ge=0, le=100, default=0)
    critical_issues: list[str] = Field(default_factory=list)
    summary: str = ""


class CollectorDecision(BaseModel):
    """Structured output for Collector agent."""
    tender_id: str = ""
    status: Literal["СБОР ЗАВЕРШЁН", "СБОР НЕ ЗАВЕРШЁН", "ТРЕБУЕТСЯ ПРОВЕРКА"]
    total_expected: int = 0
    total_received: int = 0
    completeness_pct: float = Field(ge=0, le=100, default=0)
    discrepancies: list[str] = Field(default_factory=list)
    summary: str = ""
