"""
Integration tests using REAL publicly available procurement documents.

Documents sourced from:
1. ЕЭК (Евразийская экономическая комиссия) — Open competition for IT licenses 2024
   Source: https://eec.eaeunion.org/upload/iblock/474/.../1205.pdf
2. rbank (Belarus) — Equipment procurement TZ 2021
   Source: https://rbank.by/upload/medialibrary/a99/Tekh.zadanie-na-tender.pdf
3. Synthetic DZO application based on public 44-FZ/223-FZ templates

These tests validate the FULL PIPELINE:
  receive → extract → prepare_input → route → (LLM check) → decision

Without LLM: tests check pipeline up to model_attempt stage.
With LLM (pytest -m e2e): tests check full decision accuracy.

Run (no LLM):  pytest tests/test_real_procurement_docs.py
Run (with LLM): LLM_BACKEND=openai pytest tests/test_real_procurement_docs.py -m e2e
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

import pytest
import requests

from tests.fixtures.real_procurement_docs import (
    EEK_TZ_2024 as EEK_TZ_2024_TEXT,
    RBANK_TZ_2021 as RBANK_TZ_2021_TEXT,
    DZO_APPLICATION as DZO_APPLICATION_TEXT,
    REAL_DOCS_REGISTRY,
)
from tests.conftest import record_accuracy_result

API_BASE = os.getenv("TEST_API_BASE", "http://localhost:8000")
API_KEY = os.getenv("TEST_API_KEY", "sandbox-test-api-key-12345")
HEADERS = {"x-api-key": API_KEY}


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode()


def _submit_job(agent: str, subject: str, body: str, doc_text: str, filename: str) -> str:
    payload = {
        "sender": f"test_{agent}@example.com",
        "subject": subject,
        "body_text": body,
        "attachments": [
            {
                "filename": filename,
                "content_base64": _b64(doc_text),
                "mime_type": "text/plain",
            }
        ],
    }
    r = requests.post(
        f"{API_BASE}/api/v1/process/{agent}",
        headers=HEADERS,
        json=payload,
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["job"]["job_id"]


def _wait_for_job(job_id: str, max_wait: int = 30) -> dict:
    for _ in range(max_wait):
        r = requests.get(f"{API_BASE}/api/v1/jobs/{job_id}", headers=HEADERS, timeout=5)
        r.raise_for_status()
        d = r.json()
        if d["status"] in ("success", "error", "failed"):
            return d
        time.sleep(1)
    raise TimeoutError(f"Job {job_id} did not complete in {max_wait}s")


@pytest.fixture(scope="session")
def server_available():
    import socket
    try:
        c = socket.create_connection(("localhost", 8000), timeout=2)
        c.close()
        return True
    except OSError:
        return False


@pytest.mark.integration
class TestRealDocumentPipeline:
    @pytest.fixture(autouse=True)
    def _require_server(self, server_available):
        if not server_available:
            pytest.skip("API server not running on localhost:8000")
    def test_eek_tz_pipeline_reaches_prepare_input(self):
        job_id = _submit_job(
            agent="tz",
            subject="ТЗ ЕЭК — закупка лицензий ПО ИИС ЕАЭС 2024 (Конкурс №1205)",
            body="Направляем ТЗ на закупку лицензий Astra Linux, ALD Pro, VMmanager. НМЦ: 18 332 016 руб.",
            doc_text=EEK_TZ_2024_TEXT,
            filename="tz_eek_licenses_2024.txt",
        )
        assert job_id
        d = requests.get(f"{API_BASE}/api/v1/jobs/{job_id}", headers=HEADERS, timeout=5).json()
        events = d.get("result", {}).get("processing_log", {}).get("events", [])
        stages = [e["stage"] for e in events]
        assert "received" in stages
        assert "extract_attachments_done" in stages
        assert "prepare_input" in stages

    def test_rbank_tz_pipeline_reaches_extract_stage(self):
        job_id = _submit_job(
            agent="tz",
            subject="ТЗ на закупку компьютерного оборудования — 35 моноблоков + 5 ноутбуков",
            body="Техническое задание на закупку оборудования. Intel Core i3 8100, DDR4 8GB, SSD 120GB.",
            doc_text=RBANK_TZ_2021_TEXT,
            filename="tz_rbank_equipment_2021.txt",
        )
        assert job_id
        d = requests.get(f"{API_BASE}/api/v1/jobs/{job_id}", headers=HEADERS, timeout=5).json()
        events = d.get("result", {}).get("processing_log", {}).get("events", [])
        stages = [e["stage"] for e in events]
        assert "extract_attachments_done" in stages
        extract_ev = next((e for e in events if e["stage"] == "extract_attachments_done"), None)
        assert extract_ev is not None
        assert extract_ev["details"]["extracted_count"] == 1

    def test_dzo_application_pipeline_reaches_extract_stage(self):
        job_id = _submit_job(
            agent="dzo",
            subject="Заявка ДЗО — ООО «Технологии Будущего» — Конкурс 19/ОКЭ-2025",
            body="Заявка на участие в конкурсе на разработку АИС УДЗ. ИНН 7701234567.",
            doc_text=DZO_APPLICATION_TEXT,
            filename="dzo_application_techfuture.txt",
        )
        assert job_id
        d = requests.get(f"{API_BASE}/api/v1/jobs/{job_id}", headers=HEADERS, timeout=5).json()
        events = d.get("result", {}).get("processing_log", {}).get("events", [])
        stages = [e["stage"] for e in events]
        assert "received" in stages
        assert "extract_attachments_done" in stages

    def test_api_lists_submitted_jobs(self):
        r = requests.get(f"{API_BASE}/api/v1/jobs", headers=HEADERS, timeout=5)
        assert r.status_code == 200
        assert r.json()["total"] >= 1

    def test_job_has_subject_preserved(self):
        subject = "ТЗ ЕЭК test_job_has_subject"
        job_id = _submit_job(
            agent="tz",
            subject=subject,
            body="Тест сохранения темы письма",
            doc_text="Цель закупки: тест. Количество: 1 шт. Срок: 5 дней.",
            filename="test_subject.txt",
        )
        d = requests.get(f"{API_BASE}/api/v1/jobs/{job_id}", headers=HEADERS, timeout=5).json()
        assert d.get("subject") == subject or subject in str(d.get("result", {}))


class TestRealDocumentRulesEngine:
    def _has_section(self, text: str, *keywords: str) -> bool:
        text_lower = text.lower()
        return any(kw.lower() in text_lower for kw in keywords)

    def test_eek_tz_has_goal_section(self):
        assert self._has_section(EEK_TZ_2024_TEXT, "целью", "цель", "обеспечени")

    def test_eek_tz_has_requirements(self):
        assert self._has_section(EEK_TZ_2024_TEXT, "требовани", "лицензи", "характеристик")

    def test_eek_tz_has_quantities(self):
        assert "шт." in EEK_TZ_2024_TEXT

    def test_eek_tz_has_delivery_terms(self):
        assert self._has_section(EEK_TZ_2024_TEXT, "10", "календарных дней", "срок")

    def test_eek_tz_has_regulatory_reference(self):
        assert self._has_section(EEK_TZ_2024_TEXT, "Распоряжени", "Совет", "ЕЭК", "№ 26")

    def test_eek_tz_missing_delivery_address(self):
        import re
        ADDRESS_PATTERNS = re.compile(
            r"(ул[.]|пр[.]|пр-т|бульвар|наб[.]|шоссе|место\s+поставки|адрес\s+поставки)",
            re.IGNORECASE,
        )
        has_address = bool(ADDRESS_PATTERNS.search(EEK_TZ_2024_TEXT))
        assert not has_address

    def test_rbank_tz_has_item_count(self):
        assert self._has_section(RBANK_TZ_2021_TEXT, "35 шт", "5 шт", "35", "5")

    def test_rbank_tz_has_technical_specs(self):
        assert self._has_section(RBANK_TZ_2021_TEXT, "Intel", "DDR4", "SSD", "IPS")

    def test_rbank_tz_has_delivery_term(self):
        assert self._has_section(RBANK_TZ_2021_TEXT, "10 дней", "после подписания")

    def test_rbank_tz_missing_normative_docs(self):
        assert not self._has_section(RBANK_TZ_2021_TEXT, "ГОСТ", "ТР ТС", "техрегламент")

    def test_dzo_app_has_inn(self):
        assert "7701234567" in DZO_APPLICATION_TEXT

    def test_dzo_app_has_price(self):
        assert self._has_section(DZO_APPLICATION_TEXT, "руб", "НМЦ", "8 500 000")

    def test_dzo_app_critical_missing_bank_guarantee(self):
        assert "НЕ ПРИЛОЖЕНА" in DZO_APPLICATION_TEXT
        assert "банковская гарантия" in DZO_APPLICATION_TEXT.lower()

    def test_dzo_app_has_attachments_list(self):
        assert self._has_section(DZO_APPLICATION_TEXT, "Устав", "ЕГРЮЛ", "справк")

    def test_dzo_app_has_executor_requirements(self):
        assert self._has_section(DZO_APPLICATION_TEXT, "ФСТЭК", "лицензи", "опыт", "12 аналогичных")


@pytest.mark.e2e
class TestRealDocumentE2E:
    @pytest.fixture(autouse=True)
    def _require_server_and_llm(self, server_available):
        if not server_available:
            pytest.skip("API server not running on localhost:8000")
        if not os.getenv("LLM_BACKEND"):
            pytest.skip("LLM_BACKEND not set — E2E tests are opt-in")
    def test_eek_tz_flags_missing_delivery_address(self):
        job_id = _submit_job(
            agent="tz",
            subject="E2E: ЕЭК ТЗ лицензии ПО 2024",
            body="Полный текст ТЗ на закупку лицензий ЕЭК. НМЦ 18.3 млн руб.",
            doc_text=EEK_TZ_2024_TEXT,
            filename="e2e_eek_tz.txt",
        )
        d = _wait_for_job(job_id, max_wait=120)
        assert d["status"] == "success"
        result_str = json.dumps(d.get("result", {}), ensure_ascii=False).lower()
        assert any(kw in result_str for kw in ["место поставки", "адрес", "address", "delivery", "section 5"])

    def test_rbank_tz_flags_multiple_missing_sections(self):
        job_id = _submit_job(
            agent="tz",
            subject="E2E: rbank ТЗ оборудование 2021",
            body="ТЗ на закупку 35 моноблоков и 5 ноутбуков.",
            doc_text=RBANK_TZ_2021_TEXT,
            filename="e2e_rbank_tz.txt",
        )
        d = _wait_for_job(job_id, max_wait=120)
        assert d["status"] == "success"
        result_str = json.dumps(d.get("result", {}), ensure_ascii=False).lower()
        missing_flags = sum(1 for kw in ["цель", "место", "критерии", "гост"] if kw in result_str)
        assert missing_flags >= 2

    def test_dzo_critical_bank_guarantee_blocks_approval(self):
        job_id = _submit_job(
            agent="dzo",
            subject="E2E: Заявка ДЗО банковская гарантия",
            body="Заявка ДЗО с отсутствующей банковской гарантией.",
            doc_text=DZO_APPLICATION_TEXT,
            filename="e2e_dzo_no_guarantee.txt",
        )
        d = _wait_for_job(job_id, max_wait=120)
        assert d["status"] == "success"
        result_str = json.dumps(d.get("result", {}), ensure_ascii=False).lower()
        assert "гарантия" in result_str or "guarantee" in result_str
        assert "заявка полная" not in result_str

    @pytest.mark.e2e
    @pytest.mark.parametrize("doc_key", list(REAL_DOCS_REGISTRY.keys()))
    def test_accuracy_against_ground_truth(self, doc_key):
        """Parametrized: verify each real document against expert ground truth."""
        doc = REAL_DOCS_REGISTRY[doc_key]
        job_id = _submit_job(
            agent=doc["agent"],
            subject=f"Accuracy: {doc['subject'][:60]}",
            body=f"Ground truth test for {doc['filename']}",
            doc_text=doc["text"],
            filename=doc["filename"],
        )
        d = _wait_for_job(job_id, max_wait=120)
        assert d["status"] == "success", f"Job failed for {doc_key}"
        result_str = json.dumps(d.get("result", {}), ensure_ascii=False).lower()
        expected = doc["expected"]
        for missing_key in expected.get("key_missing", []):
            assert missing_key.lower() in result_str, \
                f"[{doc_key}] Agent did not detect missing: '{missing_key}'"

        # Record result for accuracy report — compute real match
        expected_decision = expected.get("expert_decision", "").lower()
        actual_status = d.get("status", "unknown")
        result_text = json.dumps(d.get("result", {}), ensure_ascii=False).lower()

        # Extract actual decision from agent output
        def _extract_decision(text):
            text = text.lower()
            if any(w in text for w in ["вернуть", "доработк", "требуется доработка"]):
                return "вернуть"
            if any(w in text for w in ["принять с замечанием", "замечан"]):
                return "принять с замечанием"
            if any(w in text for w in ["соответствует", "принять", "заявка полная", "полная"]):
                return "принять"
            return "unknown"

        actual_decision = _extract_decision(result_text)
        expected_normalized = _extract_decision(expected_decision) if expected_decision else "unknown"
        is_match = actual_decision == expected_normalized and actual_decision != "unknown"

        record_accuracy_result(
            doc_key=doc_key,
            expected_decision=expected.get("expert_decision", "unknown"),
            actual_decision=actual_decision,
            match=is_match,
        )
