"""
Fixtures: real procurement document texts used in test_real_procurement_docs.py.

Sources:
  EEK_TZ_2024  — ЕЭК open competition №1205, IT licenses (Astra Linux, ALD Pro, VMmanager)
                 https://eec.eaeunion.org/upload/iblock/474/.../1205.pdf
  RBANK_TZ_2021 — rbank.by tender TZ for PC equipment (35 monoblocks + 5 laptops)
                 https://rbank.by/upload/medialibrary/a99/Tekh.zadanie-na-tender.pdf
  DZO_APPLICATION — synthetic 44-FZ/223-FZ DZO application template
                    (based on publicly available corporate procurement standards)

Expected expert decisions (without LLM — rules-engine only):
  EEK_TZ_2024    → ПРИНЯТЬ С ЗАМЕЧАНИЕМ  (отсутствует место поставки)
  RBANK_TZ_2021  → ВЕРНУТЬ НА ДОРАБОТКУ  (нет цели, места поставки, нормативов)
  DZO_APPLICATION → ВЕРНУТЬ НА ДОРАБОТКУ  (критично: банковская гарантия не приложена)
"""
from __future__ import annotations

# ── Document 1: ЕЭК ТЗ на закупку лицензий ПО ИИС ЕАЭС (2024) ───────────────
# п. 2.3 опущен — выдержка из оригинального документа (раздел отсутствует в исходном PDF)

EEK_TZ_2024 = """
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

# Known gaps in EEK_TZ_2024 (used to assert rules-engine behaviour)
EEK_TZ_2024_EXPECTED = {
    "has_goal": True,
    "has_requirements": True,
    "has_quantities": True,
    "has_delivery_term": True,
    "has_regulatory_reference": True,
    "has_delivery_address": False,   # <<< KNOWN GAP — missing physical address
    "has_evaluation_criteria": False, # criteria in separate section IV
    "expert_score_pct": 87.5,
    "expert_decision": "ПРИНЯТЬ С ЗАМЕЧАНИЕМ",
    "rules_engine_decision": "ВЕРНУТЬ НА ДОРАБОТКУ",  # agent uses stricter threshold (85%)
    "key_missing": ["место поставки"],
}


# ── Document 2: rbank ТЗ на закупку компьютерного оборудования (2021) ─────────
# Документ утверждён в феврале 2021 г., описывает поставку в 2022 г. — это корректно:
# ТЗ подготовлено заранее на следующий финансовый год.

RBANK_TZ_2021 = """
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

RBANK_TZ_2021_EXPECTED = {
    "has_goal": False,           # No explicit "Цель закупки" section
    "has_requirements": True,    # Detailed hardware specs present
    "has_quantities": True,      # 35 + 5 units
    "has_delivery_term": True,   # 10 days after signing
    "has_regulatory_reference": False,  # No GOST/TR references
    "has_delivery_address": False,      # Bank address not specified
    "has_evaluation_criteria": False,   # No supplier evaluation section
    "expert_score_pct": 56.0,
    "expert_decision": "ВЕРНУТЬ НА ДОРАБОТКУ",
    "rules_engine_decision": "ПРИНЯТЬ",  # FALSE POSITIVE — keyword matching limitation
    "key_missing": ["цель закупки", "место поставки", "нормативные документы", "критерии оценки"],
    "known_limitation": (
        "rules-engine даёт ложноположительный результат (100%), т.к. keywords "
        "'г.' и '%' встречаются в тексте характеристик, а не в разделах. "
        "LLM корректно определил бы ≥2 отсутствующих раздела."
    ),
}


# ── Document 3: Заявка ДЗО — ООО «Технологии Будущего» ───────────────────────

# Синтетический документ на основе шаблонов 44-ФЗ / 223-ФЗ.
# Не является реальным ground truth — используется для regression testing.
# TODO: заменить реальным документом из zakupki.gov.ru
DZO_APPLICATION = """
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

DZO_APPLICATION_EXPECTED = {
    "has_company_details": True,     # ООО, ИНН, КПП, адрес, контакт
    "has_subject": True,             # АИС УДЗ, стек, срок
    "has_price": True,               # 8 500 000 + НДС детализированы
    "has_qualifications": True,      # ФСТЭК, 12 проектов, штат
    "has_attachments_list": True,    # Устав, ЕГРЮЛ, справки
    "bank_guarantee_attached": False,  # <<< CRITICAL — explicitly NOT attached
    "expert_score_pct": 80.0,
    "expert_decision": "ВЕРНУТЬ НА ДОРАБОТКУ",
    "rules_engine_decision": "ВЕРНУТЬ НА ДОРАБОТКУ",  # Correct — phrase detected
    "key_missing": ["банковская гарантия"],
    "critical_flag": True,
}


# ── Document 4: ТЗ с расплывчатыми критериями (синтетический по 44-ФЗ) ────────

TZ_VAGUE_CRITERIA = """
ТЕХНИЧЕСКОЕ ЗАДАНИЕ
Предмет: Поставка офисной техники
1. Цель: обеспечение подразделений оргтехникой
2. Требования: хорошее качество, надёжный производитель
3. Количество: несколько единиц (по потребности)
4. Срок: как можно быстрее
5. Место поставки: центральный офис
6. Критерии: выбор лучшего поставщика по совокупности факторов
"""

TZ_VAGUE_CRITERIA_EXPECTED = {
    "expert_decision": "ВЕРНУТЬ НА ДОРАБОТКУ",
    "key_missing": ["конкретные технические характеристики", "единицы измерения", "срок поставки", "критерии оценки"],
    "structural_score_pct": 62.5,
}


# ── Document 5: ТЗ без единиц измерения и без нормативных ссылок ─────────────

TZ_NO_UNITS = """
ТЕХНИЧЕСКОЕ ЗАДАНИЕ
Предмет закупки: Расходные материалы для печати
1. Цель закупки: обеспечение бесперебойной печати документов
2. Требования к товару:
   - Картриджи для принтеров HP LaserJet Pro
   - Бумага А4 плотностью 80 г/м²
3. Количество: достаточное для работы офиса на квартал
4. Срок поставки: в течение месяца после подписания договора
5. Место поставки: г. Москва, Пресненская наб., д. 12
6. Гарантия: стандартная от производителя
"""

TZ_NO_UNITS_EXPECTED = {
    "expert_decision": "ВЕРНУТЬ НА ДОРАБОТКУ",
    "key_missing": ["единицы измерения", "нормативные документы", "критерии оценки"],
    "structural_score_pct": 50.0,
}


# ── Combined registry ─────────────────────────────────────────────────────────

REAL_DOCS_REGISTRY = {
    "eek_tz_2024": {
        "text": EEK_TZ_2024,
        "expected": EEK_TZ_2024_EXPECTED,
        "agent": "tz",
        "filename": "tz_eek_licenses_2024.txt",
        "subject": "ТЗ ЕЭК — закупка лицензий ПО ИИС ЕАЭС 2024 (Конкурс №1205)",
        "source_url": "https://eec.eaeunion.org/upload/iblock/474/s35m15bhwpgshpcwo4ajapf4mgdenqzo/1205.pdf",
    },
    "rbank_tz_2021": {
        "text": RBANK_TZ_2021,
        "expected": RBANK_TZ_2021_EXPECTED,
        "agent": "tz",
        "filename": "tz_rbank_equipment_2021.txt",
        "subject": "ТЗ на закупку компьютерного оборудования — 35 моноблоков + 5 ноутбуков",
        "source_url": "https://rbank.by/upload/medialibrary/a99/Tekh.zadanie-na-tender.pdf",
        "source_note": "Snapshot verified April 2026. External URL may become unavailable; text is preserved in fixture.",
    },
    "dzo_application": {
        "text": DZO_APPLICATION,
        "expected": DZO_APPLICATION_EXPECTED,
        "agent": "dzo",
        "filename": "dzo_application_techfuture.txt",
        "subject": "Заявка ДЗО — ООО Технологии Будущего — Конкурс 19/ОКЭ-2025",
        "synthetic": True,
        "source_url": None,  # Synthetic: based on 44-FZ/223-FZ public templates
    },
    "tz_vague_criteria": {
        "agent": "tz",
        "text": TZ_VAGUE_CRITERIA,
        "filename": "tz_vague_criteria.md",
        "subject": "Поставка офисной техники — расплывчатые критерии",
        "expected": {
            "expert_decision": "ВЕРНУТЬ НА ДОРАБОТКУ",
            "key_missing": ["конкретные технические характеристики", "единицы измерения", "срок поставки", "критерии оценки"],
            "structural_score_pct": 62.5,
        },
        "source_url": None,
    },
    "tz_no_units": {
        "agent": "tz",
        "text": TZ_NO_UNITS,
        "filename": "tz_no_units.md",
        "subject": "Расходные материалы — нет единиц измерения и нормативов",
        "expected": {
            "expert_decision": "ВЕРНУТЬ НА ДОРАБОТКУ",
            "key_missing": ["единицы измерения", "нормативные документы", "критерии оценки"],
            "structural_score_pct": 50.0,
        },
        "source_url": None,
    },
}
