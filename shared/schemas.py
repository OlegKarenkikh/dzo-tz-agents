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

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Существующие схемы (агенты 1-3)
# ---------------------------------------------------------------------------

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



class TZSectionSchema(BaseModel):
    """Single section in TZ inspection result."""
    name: str = ""
    status: str = ""
    issues: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)

class TZInspectionResult(BaseModel):
    """Structured output for TZ inspector agent.

    Принимает поле 'decision' (формат tz_v2.md) и 'overall_status' (обратная совместимость).
    """
    decision: str = "ВЕРНУТЬ НА ДОРАБОТКУ"

    @field_validator("decision", mode="before")
    @classmethod
    def normalize_decision(cls, v: str) -> str:
        if not isinstance(v, str):
            return "ВЕРНУТЬ НА ДОРАБОТКУ"
        canonical = {
            "принять": "ПРИНЯТЬ",
            "принять с замечанием": "ПРИНЯТЬ С ЗАМЕЧАНИЕМ",
            "вернуть на доработку": "ВЕРНУТЬ НА ДОРАБОТКУ",
            "соответствует": "ПРИНЯТЬ",
            "требует доработки": "ВЕРНУТЬ НА ДОРАБОТКУ",
            "не соответствует": "ВЕРНУТЬ НА ДОРАБОТКУ",
            "вернуть": "ВЕРНУТЬ НА ДОРАБОТКУ",
        }
        return canonical.get(
            v.lower().strip(),
            v if v in {"ПРИНЯТЬ", "ПРИНЯТЬ С ЗАМЕЧАНИЕМ", "ВЕРНУТЬ НА ДОРАБОТКУ"}
            else "ВЕРНУТЬ НА ДОРАБОТКУ",
        )

    overall_status: str = ""

    @field_validator("overall_status", mode="before")
    @classmethod
    def normalize_status(cls, v: str) -> str:
        if not v:
            return ""
        s = str(v).strip()
        if s.isupper():
            return s[0].upper() + s[1:].lower() if s else s
        return s

    category: str = ""
    sections: list[TZSectionSchema] = Field(default_factory=list)
    sections_present: dict[str, bool] = Field(default_factory=dict)
    missing_critical: list[str] = Field(default_factory=list)
    missing_optional: list[str] = Field(default_factory=list)
    critical_issues: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    score_pct: float = Field(ge=0, le=100, default=0)
    summary: str = ""


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


# ---------------------------------------------------------------------------
# Новые схемы для DA-агентов (агенты 4-6)
# ---------------------------------------------------------------------------

class LeasingAddressSchema(BaseModel):
    """Territory / address block for leasing contract."""
    territory_raw: str | None = Field(default=None, max_length=250)
    country: str | None = Field(default=None, max_length=250)
    region: str | None = Field(default=None, max_length=250)
    city: str | None = Field(default=None, max_length=250)
    street: str | None = Field(default=None, max_length=250)
    house: str | None = Field(default=None, max_length=20)
    building: str | None = Field(default=None, max_length=20)
    cadastre_number: str | None = Field(default=None, max_length=20)
    postal_code: str | None = None


class LeasingBaseSchema(BaseModel):
    """Base block: policy header fields."""
    policy_number: str | None = Field(default=None, max_length=250)
    date_sign: str | None = None  # DD.MM.YYYY
    date_start: str | None = None  # DD.MM.YYYY
    date_end: str | None = None    # DD.MM.YYYY
    currency: str | None = None    # RUR | USD | EUR
    insurance_rules: str | None = Field(default=None, max_length=250)
    insurance_rules_list: list[str] = Field(default_factory=list)
    signer_igs: str | None = Field(default=None, max_length=250)
    general_contract: str | None = None
    risks_list: list[str] = Field(default_factory=list)
    address: LeasingAddressSchema | None = None

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, v: Any) -> str | None:
        if not v:
            return None
        return str(v).upper().strip()


class LeasingPaymentSchema(BaseModel):
    """Single payment record in leasing contract."""
    number: int | None = None
    date_pay: str | None = None
    amount: float | None = None
    date_start: str | None = None
    date_end: str | None = None


class LeasingInsurancePaymentSchema(BaseModel):
    """Insurance sum payment inside an insurance object."""
    number: int | None = None
    premium_rate: float | None = None
    date_start: str | None = None
    date_end: str | None = None
    premium_sum: float | None = None
    insured_sum: float | None = None


class LeasingObjectSchema(BaseModel):
    """Single insured object in leasing contract."""
    serial_number: str | None = Field(default=None, max_length=20)
    object_name: str | None = Field(default=None, max_length=250)
    insurance_payments: list[LeasingInsurancePaymentSchema] = Field(default_factory=list)


class LeasingRoleSchema(BaseModel):
    """Contract participant (role)."""
    role: str
    organization_name: str | None = None
    inn: str | None = None
    address: str | None = Field(default=None, max_length=250)


class LeasingRiskSchema(BaseModel):
    """Insured risk."""
    short_name: str | None = None
    classisn: int | None = None
    ruleisn: int | None = None


class LeasingAgentSchema(BaseModel):
    """Agent / recommender block."""
    agent_name: str | None = None
    percentage: float | None = None
    role: str | None = None
    collection_flag: int | None = None  # 0 or 1
    contract_id: str | None = None
    recommender: str | None = None
    recommender_inn: str | None = None


class LeasingParseResult(BaseModel):
    """Structured output for Leasing parser agent (agent4).

    Mirrors DA LeasingResponse but in a flat agentic-friendly format.
    Validation ensures:
    - all string fields respect DA length limits (250 / 20 chars)
    - dates normalised to DD.MM.YYYY
    - numeric fields are float/int
    """
    file_name: str = ""
    base: LeasingBaseSchema = Field(default_factory=LeasingBaseSchema)
    additional: dict[str, Any] = Field(default_factory=dict)  # noqa: ANN401 — структура неизвестна до получения данных от DA API
    roles: list[LeasingRoleSchema] = Field(default_factory=list)
    insurance_objects: list[LeasingObjectSchema] = Field(default_factory=list)
    payments: list[LeasingPaymentSchema] = Field(default_factory=list)
    risks: list[LeasingRiskSchema] = Field(default_factory=list)
    agents: list[LeasingAgentSchema] = Field(default_factory=list)
    validation_status: str = "pending"
    parse_errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# OSAGO схема (агент 5)
# ---------------------------------------------------------------------------

class OsagoInsurerSchema(BaseModel):
    """OSAGO insurer block."""
    name: str | None = None
    inn: str | None = None
    address: str | None = None


class OsagoParseResult(BaseModel):
    """Structured output for OSAGO parser agent (agent5)."""
    file_name: str = ""
    insurer: OsagoInsurerSchema | None = None
    ts_owner: OsagoInsurerSchema | None = None
    vehicle_brand: str | None = None
    vehicle_model: str | None = None
    vehicle_number: str | None = None
    vin: str | None = None
    ts_type: str | None = None
    usage_purpose: str | None = None
    year: int | None = None
    date_start: str | None = None  # DD.MM.YYYY
    date_end: str | None = None    # DD.MM.YYYY
    # Технические характеристики
    power_hp: float | None = None
    power_kw: float | None = None
    max_mass: float | None = None
    permitted_max_mass: float | None = None
    seats_count: int | None = None
    cargo_capacity: float | None = None
    category: str | None = None
    parse_errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Transportation схема (агент 6)
# ---------------------------------------------------------------------------

class TransportParseResult(BaseModel):
    """Structured output for Transportation parser agent (agent6)."""
    file_name: str = ""
    cargo_name: str | None = None
    cargo_weight: float | None = None
    cargo_value: float | None = None
    currency: str | None = None
    departure_point: str | None = None
    destination_point: str | None = None
    transport_type: str | None = None
    date_start: str | None = None
    date_end: str | None = None
    insurer: str | None = None
    insurer_inn: str | None = None
    insurance_sum: float | None = None
    premium: float | None = None
    parse_errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# OsgopParseResult — agent7
# ---------------------------------------------------------------------------


class OsgopTariffSchema(BaseModel):
    """Single tariff entry in OSGOP contract."""
    transport_type: str | None = None
    rate: float | None = None
    base_sum: float | None = None

class OsgopParseResult(BaseModel):
    """Structured output for OSGOP parser agent (agent7).
    Mirrors DA OsgopResponse fields.
    """
    file_name: str = ""
    policy_number: str | None = None
    insurer_company: str | None = None
    insurer_name: str | None = None
    insurer_inn: str | None = None
    insurer_kpp: str | None = None
    insurer_address: str | None = None
    date_start: str | None = None
    date_end: str | None = None
    insurance_sum: float | None = None
    premium: float | None = None
    currency: str | None = None
    vehicle_count: int | None = None
    transportation_types: list[str] = Field(default_factory=list)
    vehicle_models: list[str] = Field(default_factory=list)
    tariffs: dict[str, OsgopTariffSchema] = Field(default_factory=dict)
    payment_schedule: list[dict] = Field(default_factory=list)
    franchise: float | None = None
    regions: list[str] = Field(default_factory=list)
    special_conditions: str | None = None
    parse_errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# ResponsibilityParseResult — agent8 (types 431 / 432 / 433)
# ---------------------------------------------------------------------------

class ResponsibilityParseResult(BaseModel):
    """Structured output for Responsibility parser agent (agent8).
    Covers all three subtypes: 431, 432, 433.
    """
    file_name: str = ""
    subtype: str = "431"
    contract_number: str | None = None
    date_start: str | None = None
    date_end: str | None = None
    date_conclusion: str | None = None
    insurance_sum: float | None = None
    premium: float | None = None
    currency: str | None = None
    insurer: str | None = None
    policyholder: str | None = None
    beneficiary: str | None = None
    risks: list[str] = Field(default_factory=list)
    roles: dict = Field(default_factory=dict)
    objects: list[dict] = Field(default_factory=list)
    fid: dict | None = None
    credit_limit: float | None = None
    payment_schedule: list = Field(default_factory=list)
    parse_errors: list[str] = Field(default_factory=list)
