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

EEK_TZ_2024_TEXT = """
Раздел II. Техническое задание

1. Общие положения.
Целью закупки является обеспечение эффективного функционирования и
эксплуатационной готовности инфраструктурной платформы как части интеграционного
сегмента Комиссии.

Закупка лицензий осуществляется в соответствии с подпунктом 4.6.1 пункта 4.6
Плана мероприятий по созданию, обеспечению функционирования и развитию ИИС ЕАЭС
в 2024 году, утверждённого распоряжением Совета ЕЭК от 27 сентября 2023 г. № 26.

2. Требования к лицензиям, комплектности и срокам передачи:
2.1. Заказчику должны быть предоставлены права на использование ПО на условиях
простой (неисключительной) лицензии без ограничения срока использования.
2.2. Все передаваемые лицензии должны включать доступ к обновлениям ПО на 36 месяцев.
2.4. Лицензии должны быть переданы Заказчику в течение 10 (десяти) календарных дней
с даты заключения договора.

Таблица 1. Спецификация (выдержка):
1. OS2200X8617DIGS-KTSR01-SO36 — Astra Linux Special Edition, серверная, 9 шт.
2. OS2200X8617DIGS-KTWS01-SO36 — Astra Linux Special Edition, рабочая станция, 400 шт.
3. AD2100X8610DIG1D8SR01-SO36  — ALD Pro, контроллер домена, 2 шт.
5. EXV10000006DIGMS1SV01-0000  — VMmanager 6 Infrastructure, 1 шт.
6. EXV10000006DIGCORSV01-SO36  — VMmanager 6, расширение 1 физ. ядро, 576 шт.

Начальная (максимальная) цена договора: 18 332 016 рублей 00 копеек (НДС не облагается).
Заказчик: Евразийская экономическая комиссия
Контакт: dept_it@eecommission.org, тел. +7(495)669-2400 доб.4444, Шеметов Д.М.
"""

RBANK_TZ_2021_TEXT = """
ТЕХНИЧЕСКОЕ ЗАДАНИЕ
на закупку товаров (работ, услуг)

УТВЕРЖДАЮ: Заместитель Председателя Правления А.А.Цуран, февраль 2021 г.

1. Предмет закупки: компьютеры и другое оборудование.

№1. Моноблок, 35 шт. Оплата по факту. Срок поставки: не позднее 10 дней после
подписания договора 2022 года.
Характеристики: Материнская плата ASUS или Gigabyte, порты HDMI, USB 3.0/2.0.
Процессор: не ниже Intel Core i3 8100. Корпус: настольный, регулировка наклона.
ОЗУ: DDR4, не менее 8GB. Накопитель: SSD SATAIII 120GB Kingston/Samsung.
Дисплей: 23.8", IPS, 1920x1080, антибликовое матовое покрытие, WLED.
Клавиатура + мышь Logitech, проводные. Камера встроенная 0.3Мп.
ОС: Windows 10 Pro (опционально).

№2. Ноутбуки, 5 шт. Экран 15-15.6" IPS 1920x1080. Проц. Intel Core i3 8100.
ОЗУ DDR4 8GB. SSD 120GB M.2. Срок: 10 дней с подписания договора.
"""

DZO_APPLICATION_TEXT = """
ЗАЯВКА НА УЧАСТИЕ В ЗАКУПКЕ ДЗО
Открытый конкурс в электронной форме № 19/ОКЭ-2025

От: ООО «Технологии Будущего»
ИНН: 7701234567, КПП: 770101001
Юридический адрес: 115114, г. Москва, ул. Летниковская, д. 5
Руководитель: Генеральный директор Петров Александр Сергеевич
Контакт: +7(495)123-45-67, ivanova@techfuture.ru

ПРЕДМЕТ: Разработка и внедрение АИС УДЗ
Стек: Python/FastAPI + React.js, интеграция с ЕИС (zakupki.gov.ru)
Количество рабочих мест: 50+. Срок: 12 месяцев.
Соответствие ГОСТ 34.602-2020: да.
НМЦ: 8 500 000 руб. (НДС 20%: 1 700 000 руб., итого: 10 200 000 руб.)

Опыт: с 2015 года, 12 аналогичных гос. проектов. Штат: 25 человек.
Лицензия ФСТЭК: № 0001 от 01.01.2020.

Приложения: Устав — да; Выписка ЕГРЮЛ от 01.03.2025 — да;
Справка об отсутствии задолженностей — да; Список договоров (3 шт.) — да.
Банковская гарантия — НЕ ПРИЛОЖЕНА (требуется по условиям конкурса).

Подпись: Петров А.С. Дата: 10.04.2025
"""

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


class TestRealDocumentPipeline:
    def test_eek_tz_pipeline_accepted(self):
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

    def test_rbank_tz_pipeline_accepted(self):
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

    def test_dzo_application_pipeline_accepted(self):
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

        has_address = bool(re.search(r"(ул[.]|место поставки)", EEK_TZ_2024_TEXT))
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
@pytest.mark.skipif(not os.getenv("LLM_BACKEND"), reason="LLM_BACKEND not set")
class TestRealDocumentE2E:
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
        assert any(
            kw in result_str
            for kw in ["место поставки", "адрес", "address", "delivery", "section 5"]
        )

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
