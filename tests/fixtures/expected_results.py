"""Expected classification results for all 17 tender documents.

Source of truth: /home/user/workspace/expected_test_outputs.md
Each entry maps a tender filename to expected insurance type and key fields.
"""

EXPECTED_RESULTS: dict[str, dict] = {
    # ── ОСАГО ─────────────────────────────────────────────────────────
    "tender_osago_1.md": {
        "insurance_type": "ОСАГО",
        "insurance_subtype": "Обязательное страхование гражданской ответственности владельцев ТС",
        "tender_number": "0137100001126000002",
        "customer": "Управление ФССП по Калужской области",
        "nmck": 132821.81,
        "law": "44-ФЗ",
        "okpd2_code": "65.12.21.000",
    },
    "tender_osago_2.md": {
        "insurance_type": "ОСАГО",
        "insurance_subtype": "Обязательное страхование гражданской ответственности владельцев ТС",
        "law": "44-ФЗ",
        "okpd2_code": "65.12.21.000",
    },

    # ── КАСКО ─────────────────────────────────────────────────────────
    "tender_kasko_1.md": {
        "insurance_type": "КАСКО",
        "insurance_subtype": "Добровольное страхование средств наземного транспорта",
        "tender_number": "184877-25LO",
        "customer": "МКУ «Административно-хозяйственный комплекс» Кингисеппского района",
        "nmck": 54340.00,
        "law": "44-ФЗ",
    },
    "tender_kasko_2.md": {
        "insurance_type": "КАСКО",
        "insurance_subtype": "Добровольное страхование средств наземного транспорта",
        "law": "223-ФЗ",
    },

    # ── ДМС ───────────────────────────────────────────────────────────
    "tender_dms_1.md": {
        "insurance_type": "ДМС",
        "insurance_subtype": "Добровольное медицинское страхование работников",
        "customer": "АО «СМАК»",
        "nmck": 15590236.31,
        "law": "223-ФЗ",
    },
    "tender_dms_2.md": {
        "insurance_type": "НС",  # This is actually accident/illness insurance
    },
    "tender_dms_3.md": {
        "insurance_type": "ДМС",
        "law": "223-ФЗ",
    },

    # ── Имущество ─────────────────────────────────────────────────────
    "tender_property_1.md": {
        "insurance_type": "Имущество",
        "insurance_subtype": "Комплексное имущественное страхование промышленных активов",
        "tender_number": "315049124",
        "customer": "ООО «РН-Юганскнефтегаз» (Роснефть)",
        "nmck": None,
        "law": "223-ФЗ",
        "okpd2_code": "65.12",
    },
    "tender_property_2.md": {
        "insurance_type": "Имущество",
        "law": "223-ФЗ",
    },

    # ── Ответственность ───────────────────────────────────────────────
    "tender_liability_1.md": {
        "insurance_type": "Ответственность",
        "insurance_subtype": "Обязательное страхование ОПО",
        "tender_number": "3892658",
        "customer": "АО «Хиагда» (Росатом)",
        "nmck": None,
        "law": "223-ФЗ",
        "okpd2_code": "65.12.50.000",
    },
    "tender_liability_2.md": {
        "insurance_type": "Ответственность",
        "law": "44-ФЗ",
    },

    # ── НС (Несчастные случаи / Жизнь) ───────────────────────────────
    "tender_life_ns_1.md": {
        "insurance_type": "НС",
        # life_ns_1 is state personal insurance (prosecutors)
    },
    "tender_life_ns_2.md": {
        "insurance_type": "НС",
        "insurance_subtype": "Страхование от несчастных случаев и болезней работников",
        "tender_number": "322065105",
        "customer": "ООО «Волгодонская АЭС-Сервис» (Росатом)",
        "nmck": 2530735.42,
        "law": "223-ФЗ",
        "okpd2_code": "65.12.4",
    },

    # ── Грузы ─────────────────────────────────────────────────────────
    "tender_cargo_1.md": {
        "insurance_type": "Грузы",
        "insurance_subtype": "Страхование грузов при перевозке (генеральный договор)",
        "tender_number": "288334442",
        "customer": "АО «РЖД Логистика»",
        "nmck": 36000000,
        "law": "223-ФЗ",
        "okpd2_code": "65.12",
    },
    "tender_cargo_2.md": {
        "insurance_type": "Грузы",
        "law": "223-ФЗ",
    },

    # ── СМР ───────────────────────────────────────────────────────────
    "tender_smr_1.md": {
        "insurance_type": "СМР",
        "insurance_subtype": "Комбинированное страхование строительно-монтажных рисков",
        "tender_number": "324237587",
        "customer": "АО «Энергосервис Кубани»",
        "nmck": 1419534,
        "law": "223-ФЗ",
        "okpd2_code": "65.12.5",
    },
    "tender_smr_2.md": {
        "insurance_type": "СМР",
        "law": "223-ФЗ",
    },
}

# Mapping from tender filename to expected insurance type (for quick lookup)
TENDER_TYPE_MAP: dict[str, str] = {
    fname: data["insurance_type"]
    for fname, data in EXPECTED_RESULTS.items()
}

# All 8 canonical insurance types covered by test tenders
TESTED_INSURANCE_TYPES = sorted({
    data["insurance_type"] for data in EXPECTED_RESULTS.values()
})
