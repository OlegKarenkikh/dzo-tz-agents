"""
Fixtures: real procurement document texts used in test_real_procurement_docs.py.

Sources:
  EEK_TZ_2024  — ЕЭК open competition №1205, IT licenses (Astra Linux, ALD Pro, VMmanager)
                 https://eec.eaeunion.org/upload/iblock/474/.../1205.pdf
  RBANK_TZ_2021 — rbank.by tender TZ for PC equipment (35 monoblocks + 5 laptops)
                 https://rbank.by/upload/medialibrary/a99/Tekh.zadanie-na-tender.pdf
  DZO_APPLICATION — realistic 44-FZ/223-FZ DZO application (synthetic: True)
                    Structure based on Art. 51 44-FZ and pro-ability.ru templates

Expected expert decisions (without LLM — rules-engine only):
  EEK_TZ_2024    → ПРИНЯТЬ С ЗАМЕЧАНИЕМ  (отсутствует место поставки)
  RBANK_TZ_2021  → ВЕРНУТЬ НА ДОРАБОТКУ  (нет цели, места поставки, нормативов)
  DZO_APPLICATION → ВЕРНУТЬ НА ДОРАБОТКУ  (критично: банковская гарантия не приложена)
"""
from __future__ import annotations

import json
import pathlib as _pathlib

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
    "llm_decision_acceptable": ["ПРИНЯТЬ С ЗАМЕЧАНИЕМ", "ВЕРНУТЬ НА ДОРАБОТКУ"],
    "rules_engine_decision": "ВЕРНУТЬ НА ДОРАБОТКУ",  # structural_score=62.5% < 75% → агент возвращает на доработку
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


# ── Document 3: Заявка ДЗО — ООО «Объединённая компания электросетей» ────────

# Заявка ДЗО — составлена по структуре реальных заявок 44-ФЗ / 223-ФЗ.
# Источник структуры: ч. 3 ст. 51 44-ФЗ, примеры с pro-ability.ru и torgi223.ru
# Содержит намеренные дефекты для тестирования:
#   - Банковская гарантия: НЕ ПРИЛОЖЕНА (критическое нарушение)
#   - Адрес поставки: только город без улицы (неполный)
#   - Срок поставки: указан, но без штрафных санкций за просрочку
DZO_APPLICATION = """
ЗАЯВКА НА ЗАКУПКУ № ОКЭ-2025-0047

Заказчик: ООО «Объединённая компания электросетей» (ДЗО ПАО «Россети»)
ИНН/КПП: 7707049388 / 770701001
Юридический адрес: 121359, г. Москва, ул. Можайское шоссе, д. 22, к. 1

1. ПРЕДМЕТ ЗАКУПКИ
Наименование: Поставка силового трансформатора ТМГ-1000/10/0,4 кВ
Категория: Электротехническое оборудование
Код ОКПД2: 27.11.41
Способ закупки: Открытый конкурс среди субъектов МСП (223-ФЗ)

2. ОБЪЁМ И СПЕЦИФИКАЦИЯ
Количество: 3 (три) единицы
Единица измерения: шт.
Технические требования:
  — Номинальная мощность: 1000 кВА
  — Напряжение ВН: 10 кВ, НН: 0,4 кВ
  — Группа соединений: Y/Yн-0
  — Масса: не более 3200 кг
  — Климатическое исполнение: У1 (для наружной установки)
  — Потери холостого хода: ≤ 1,55 кВт
  — Потери короткого замыкания: ≤ 10,5 кВт
  — ГОСТ 11677-85, ГОСТ Р 52719-2007

3. ИНИЦИАТОР ЗАКУПКИ
ФИО: Козлов Дмитрий Сергеевич
Должность: Начальник отдела снабжения
Телефон: +7 (495) 789-23-45
Email: d.kozlov@oke-rosseti.ru

4. ОБОСНОВАНИЕ ЗАКУПКИ
Плановая замена трансформаторов на ПС-35/10 «Северная» в рамках инвестиционной
программы 2025 г. (приказ № 142/ИП от 15.01.2025). Текущие трансформаторы ТМ-630
выработали ресурс (год выпуска 2003, наработка > 175 000 ч.), зафиксирован перегрев
обмоток до 115°C при пиковых нагрузках (акт осмотра от 10.11.2024 № 847-ТО).

5. СТОИМОСТЬ И БЮДЖЕТ
Начальная максимальная цена контракта (НМЦК): 4 350 000 руб. (в т.ч. НДС 20%)
Метод определения НМЦК: сопоставимых рыночных цен (3 коммерческих предложения)
Источник финансирования: собственные средства ДЗО, статья бюджета 731.02.004

6. СРОКИ ПОСТАВКИ
Срок: 45 (сорок пять) рабочих дней с момента подписания договора
Дата заключения договора (план): не позднее 15.06.2025

7. МЕСТО ПОСТАВКИ
г. Москва

8. ОБЕСПЕЧЕНИЕ ЗАЯВКИ
Размер обеспечения: 2% от НМЦК = 87 000 руб.
Форма: банковская гарантия или денежный перевод на счёт заказчика
Статус: НЕ ПРИЛОЖЕНА

9. ПРИЛОЖЕНИЯ
  9.1. Техническое задание (файл: ТЗ_ОКЭ-2025-0047.pdf) — ПРИЛОЖЕНО
  9.2. Коммерческие предложения (3 шт.) — ПРИЛОЖЕНЫ
  9.3. Акт осмотра оборудования № 847-ТО от 10.11.2024 — ПРИЛОЖЕН
  9.4. Банковская гарантия — НЕ ПРИЛОЖЕНА
  9.5. Проект договора — ПРИЛОЖЕН

Подпись инициатора: ___________________ / Козлов Д.С. /
Дата: 28.03.2025
Согласовано:
  Начальник финансового отдела: ___________________ / Мирошникова Е.В. /
  Заместитель директора по закупкам: ___________________ / Петров А.Н. /
"""

DZO_APPLICATION_EXPECTED = {
    "expert_decision": "ВЕРНУТЬ НА ДОРАБОТКУ",
    "key_missing": ["банковская гарантия", "адрес поставки"],
    "structural_score_pct": 83.3,
    "has_subject": True,
    "has_quantity": True,
    "has_delivery_term": True,
    "has_initiator": True,
    "has_budget": True,
    "has_justification": True,
    "has_delivery_address": False,  # Only city, no street
    "has_bank_guarantee": False,
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


# ── Document 6: Полное ТЗ без дефектов (синтетический, по ГОСТ 34.602-2020) ──

TZ_COMPLETE_GOOD = """
ТЕХНИЧЕСКОЕ ЗАДАНИЕ
на поставку серверного оборудования для ЦОД

1. НАЗНАЧЕНИЕ И ЦЕЛЬ ЗАКУПКИ
Модернизация серверной инфраструктуры центра обработки данных (ЦОД)
в рамках программы цифровой трансформации 2025 г.

2. ТРЕБОВАНИЯ К ТОВАРУ
2.1. Серверы: Dell PowerEdge R760, 2× Intel Xeon Gold 6438Y (32 ядра),
     512 GB DDR5 ECC, 4× SSD NVMe 1.92 TB, 2× БП 1400W (1+1)
2.2. Сетевое оборудование: Cisco Catalyst 9300-48T, 48 портов 10GbE,
     StackWise-480, SNMP v3, поддержка VXLAN
2.3. СХД: NetApp FAS2820, 24× SAS 10K 1.8TB, dual controller, NFS/CIFS/iSCSI

3. КОЛИЧЕСТВО
Серверы: 4 шт.
Коммутаторы: 2 шт.
СХД: 1 шт.

4. СРОКИ ПОСТАВКИ
45 (сорок пять) рабочих дней с даты подписания договора.
Штрафные санкции: 0.1% от стоимости за каждый день просрочки.

5. МЕСТО ПОСТАВКИ
127015, г. Москва, ул. Бутырская, д. 76, стр. 1, серверная комната ЦОД-2.

6. ГАРАНТИЯ
36 месяцев с даты поставки. Время реакции на обращение: 4 часа (NBD).
Замена неисправного оборудования: в течение следующего рабочего дня.

7. НОРМАТИВНЫЕ ДОКУМЕНТЫ
— ГОСТ 34.602-2020 «Техническое задание на создание автоматизированной системы»
— ГОСТ Р 56939-2016 «Защита информации. Требования к СУБД»
— ФЗ-149 «Об информации, информационных технологиях и о защите информации»

8. КРИТЕРИИ ОЦЕНКИ ЗАЯВОК
Цена контракта: 60%
Срок поставки: 20%
Гарантийные условия: 20%
"""


# ── Тендерные документы — из существующих фикстур, основанных на реальных закупках ──

_TENDERS_DIR = _pathlib.Path(__file__).parent / "tenders"


def _read_tender(name: str) -> str:
    return (_TENDERS_DIR / name).read_text(encoding="utf-8")


TENDER_CARGO_RZD = _read_tender("tender_cargo_1.md")
TENDER_DMS_SMAK = _read_tender("tender_dms_1.md")
TENDER_OSAGO_FSSP = _read_tender("tender_osago_1.md")


# ── Collector — синтетический тестовый кейс сбора документов ──

COLLECTOR_TENDER_SELECTION = json.dumps({
    "tender_id": "ТО-2025-0183",
    "tender_subject": "Страхование имущества юридических лиц",
    "participants_list": [
        {
            "name": "ООО «СК Гарант»",
            "inn": "7722851537",
            "contact_email": "tender@garant-insurance.ru",
            "contact_person": "Козлова Мария Ивановна",
        },
        {
            "name": "АО «Росгосстрах»",
            "inn": "7702073683",
            "contact_email": "tender@rgs.ru",
            "contact_person": "Петров Алексей Сергеевич",
        },
    ],
    "emails": [
        {
            "from_email": "tender@garant-insurance.ru",
            "from_name": "Козлова Мария",
            "subject": "Re: ТО-2025-0183 Анкета и NDA",
            "body": "Добрый день! Направляю заполненную анкету участника и подписанный NDA.",
            "attachments": [
                {"filename": "Анкета_ООО_СК_Гарант.pdf", "content_type": "application/pdf", "size_bytes": 45000, "content_hint": "АНКЕТА УЧАСТНИКА ТЕНДЕРНОГО ОТБОРА ООО «СК Гарант» ИНН 7722851537 КПП 772201001 ОГРН 1157746123456"},
                {"filename": "NDA_подписанный.pdf", "content_type": "application/pdf", "size_bytes": 12000, "content_hint": "СОГЛАШЕНИЕ О НЕРАЗГЛАШЕНИИ Сторона 2: ООО «СК Гарант»"},
            ],
        },
        {
            "from_email": "tender@rgs.ru",
            "from_name": "Петров Алексей",
            "subject": "Re: ТО-2025-0183 Документы",
            "body": "Высылаю анкету. NDA будет направлен позже.",
            "attachments": [
                {"filename": "Anketa_RGS.pdf", "content_type": "application/pdf", "size_bytes": 52000, "content_hint": "АНКЕТА УЧАСТНИКА ТО АО «Росгосстрах» ИНН 7702073683"},
            ],
        },
    ],
}, ensure_ascii=False)


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
        "agent": "dzo",
        "text": DZO_APPLICATION,
        "filename": "dzo_application_oke_2025.md",
        "subject": "Заявка ДЗО на закупку силовых трансформаторов — ОКЭ-2025-0047",
        "synthetic": True,
        "expected": {
            "expert_decision": "ВЕРНУТЬ НА ДОРАБОТКУ",
            "key_missing": ["банковская гарантия", "адрес поставки"],
            "structural_score_pct": 83.3,
            "has_subject": True,
            "has_quantity": True,
            "has_delivery_term": True,
            "has_initiator": True,
            "has_budget": True,
            "has_justification": True,
            "has_delivery_address": False,  # Only city, no street
            "has_bank_guarantee": False,
        },
        "source_url": None,
        "source_note": "Структура на основе ч.3 ст.51 44-ФЗ и шаблонов 223-ФЗ. Содержит намеренные дефекты: банковская гарантия НЕ ПРИЛОЖЕНА, адрес неполный (только город).",
    },
    "tz_vague_criteria": {
        "agent": "tz",
        "synthetic": True,
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
        "synthetic": True,
        "text": TZ_NO_UNITS,
        "filename": "tz_no_units.md",
        "subject": "Расходные материалы — нет единиц измерения и нормативов",
        "expected": {
            "expert_decision": "ВЕРНУТЬ НА ДОРАБОТКУ",
            "llm_decision_acceptable": ["ВЕРНУТЬ НА ДОРАБОТКУ", "ПРИНЯТЬ С ЗАМЕЧАНИЕМ"],
            "key_missing": ["единицы измерения", "нормативные документы", "критерии оценки"],
            "structural_score_pct": 50.0,
        },
        "source_url": None,
    },
    # ── Полное ТЗ без дефектов ─────────────────────────────
    "tz_complete_good": {
        "agent": "tz",
        "text": TZ_COMPLETE_GOOD,
        "filename": "tz_server_equipment_2025.md",
        "subject": "ТЗ на серверное оборудование для ЦОД — полный документ без дефектов",
        "synthetic": True,
        "expected": {
            "expert_decision": "ПРИНЯТЬ",
            "key_missing": [],
            "structural_score_pct": 100.0,
        },
        "source_url": None,
        "source_note": "Синтетический полный ТЗ по ГОСТ 34.602-2020. Все 8 разделов присутствуют. Ожидаемое решение: ПРИНЯТЬ.",
    },
    # ── Тендерные документы (agent21) ───────────────────────
    "tender_cargo_rzd": {
        "agent": "tender",
        "text": TENDER_CARGO_RZD,
        "filename": "tender_cargo_1.md",
        "subject": "Страхование грузов — АО «РЖД Логистика» (223-ФЗ)",
        "synthetic": False,
        "expected": {
            "expert_decision": "ПРИНЯТЬ",
            "llm_decision_acceptable": ["ПРИНЯТЬ", "ДОКУМЕНТАЦИЯ ПОЛНАЯ", "ТРЕБУЕТСЯ ДОРАБОТКА"],
            "key_missing": [],
            "insurance_type": "Грузы",
            "tender_number": "288334442",
            "structural_score_pct": 95.0,
        },
        "source_url": "https://zakupki.gov.ru",
        "source_note": "Реестровая запись №288334442, АО «РЖД Логистика», 223-ФЗ",
    },
    "tender_dms_smak": {
        "agent": "tender",
        "text": TENDER_DMS_SMAK,
        "filename": "tender_dms_1.md",
        "subject": "ДМС работников АО «СМАК» (223-ФЗ)",
        "synthetic": False,
        "expected": {
            "expert_decision": "ПРИНЯТЬ",
            "llm_decision_acceptable": ["ПРИНЯТЬ", "ДОКУМЕНТАЦИЯ ПОЛНАЯ", "ТРЕБУЕТСЯ ДОРАБОТКА", "КРИТИЧЕСКИЕ НАРУШЕНИЯ"],
            "key_missing": [],
            "insurance_type": "ДМС",
            "structural_score_pct": 90.0,
        },
        "source_url": "https://zakupki.gov.ru",
        "source_note": "АО «СМАК», ИНН 6659003692, запрос предложений 223-ФЗ",
    },
    "tender_osago_fssp": {
        "agent": "tender",
        "text": TENDER_OSAGO_FSSP,
        "filename": "tender_osago_1.md",
        "subject": "ОСАГО — УФССП по Калужской области (44-ФЗ)",
        "synthetic": False,
        "expected": {
            "expert_decision": "ПРИНЯТЬ",
            "key_missing": [],
            "insurance_type": "ОСАГО",
            "tender_number": "0137100001126000002",
            "structural_score_pct": 95.0,
        },
        "source_url": "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber=0137100001126000002",
        "source_note": "ЕИС запись №0137100001126000002, УФССП Калужской обл., 44-ФЗ",
    },
    # ── Collector (agent3) ──────────────────────────────────
    "collector_to_2025_0183": {
        "agent": "collector",
        "text": COLLECTOR_TENDER_SELECTION,
        "filename": "collector_to_2025_0183.json",
        "subject": "Сбор анкет ТО-2025-0183 — страхование имущества",
        "synthetic": True,
        "expected": {
            "expert_decision": "СБОР НЕ ЗАВЕРШЁН",
            "key_missing": ["NDA от АО Росгосстрах"],
            "total_participants": 2,
            "received_anketa": 2,
            "received_nda": 1,
            "completeness_pct": 75.0,
        },
        "source_url": None,
        "source_note": "Синтетический кейс: 2 участника, один прислал анкету+NDA, второй только анкету",
    },
}
