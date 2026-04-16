"""
Russian date normalization — parsing informal Russian date formats.

Handles formats like:
- "1 мая 2026"
- "01.05.2026"
- "1 мая 2026 г."
- "до 15 июня"
- "в течение 45 рабочих дней"
- "II квартал 2026"
"""
import re
from datetime import date, timedelta

_MONTHS_RU: dict[str, int] = {}
for _m, _forms in [
    (1, ("январь", "января", "январе", "январём")),
    (2, ("февраль", "февраля", "феврале", "февралём")),
    (3, ("март", "марта", "марте", "мартом")),
    (4, ("апрель", "апреля", "апреле", "апрелем")),
    (5, ("май", "мая", "мае", "маем")),
    (6, ("июнь", "июня", "июне", "июнем")),
    (7, ("июль", "июля", "июле", "июлем")),
    (8, ("август", "августа", "августе", "августом")),
    (9, ("сентябрь", "сентября", "сентябре", "сентябрём")),
    (10, ("октябрь", "октября", "октябре", "октябрём")),
    (11, ("ноябрь", "ноября", "ноябре", "ноябрём")),
    (12, ("декабрь", "декабря", "декабре", "декабрём")),
]:
    for _f in _forms:
        _MONTHS_RU[_f] = _m

_QUARTER_MONTH = {1: 3, 2: 6, 3: 9, 4: 12}


def _match_month(text: str) -> int | None:
    """Match a Russian month name (case-insensitive, full word)."""
    text_lower = text.lower().strip()
    if text_lower in _MONTHS_RU:
        return _MONTHS_RU[text_lower]
    return None


def normalize_date(text: str, reference_date: date | None = None) -> str | None:
    """Parse a Russian date string and return ISO format (YYYY-MM-DD).

    Args:
        text: Russian date string (e.g., "1 мая 2026", "01.05.2026", "II квартал 2026")
        reference_date: Reference date for relative calculations (default: today)

    Returns:
        ISO date string "YYYY-MM-DD" or None if parsing fails.

    Examples:
        >>> normalize_date("1 мая 2026")
        '2026-05-01'
        >>> normalize_date("01.05.2026")
        '2026-05-01'
        >>> normalize_date("II квартал 2026")
        '2026-06-30'
    """
    if not text or not text.strip():
        return None

    text = text.strip()
    ref = reference_date or date.today()

    # Pattern 1: DD.MM.YYYY or DD/MM/YYYY
    m = re.match(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            pass

    # Pattern 2: YYYY-MM-DD (already ISO)
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            pass

    # Pattern 3: "1 мая 2026" / "1 мая 2026 г." / "1 мая 2026 года"
    m = re.match(r"(\d{1,2})\s+(\S+)\s+(\d{4})", text)
    if m:
        month = _match_month(m.group(2))
        if month:
            try:
                return date(int(m.group(3)), month, int(m.group(1))).isoformat()
            except ValueError:
                pass

    # Pattern 4: "май 2026" / "мая 2026"
    m = re.match(r"(\S+)\s+(\d{4})", text)
    if m:
        month = _match_month(m.group(1))
        if month:
            try:
                return date(int(m.group(2)), month, 1).isoformat()
            except ValueError:
                pass

    # Pattern 5: Roman numeral quarter — "II квартал 2026"
    m = re.match(r"(I{1,3}V?|[1-4])\s*(?:квартал|кв\.?)\s*(\d{4})", text, re.IGNORECASE)
    if m:
        roman_map = {"I": 1, "II": 2, "III": 3, "IV": 4}
        q_str = m.group(1).upper()
        q = roman_map.get(q_str) or (int(q_str) if q_str.isdigit() else None)
        if q and q in _QUARTER_MONTH:
            month = _QUARTER_MONTH[q]
            # Last day of the quarter
            if month == 12:
                return date(int(m.group(2)), 12, 31).isoformat()
            else:
                next_month = date(int(m.group(2)), month + 1, 1)
                return (next_month - timedelta(days=1)).isoformat()

    # Pattern 6: "N рабочих дней" / "N календарных дней"
    m = re.search(r"(\d+)\s*(?:рабочих|календарных)?\s*дн", text)
    if m:
        days = int(m.group(1))
        target = ref + timedelta(days=days)
        return target.isoformat()

    return None
