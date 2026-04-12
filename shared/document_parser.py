"""
shared/document_parser.py
Structured data extraction from participant anketa files (PDF and DOCX).

Parses the standard 15-field anketa table and returns an ``AnketaData``
dataclass. Supports both PDF (via pdfplumber) and DOCX (via python-docx).

Usage::

    from shared.document_parser import parse_anketa

    data = parse_anketa(file_bytes, "application/pdf")
    print(data.company_name, data.inn)
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field

from shared.logger import setup_logger  # noqa: F401

logger = logging.getLogger("document_parser")


@dataclass
class AnketaData:
    """Structured data extracted from a participant anketa."""

    tender_id: str = ""
    company_name: str = ""
    org_form: str = ""
    inn: str = ""
    kpp: str = ""
    ogrn: str = ""
    legal_address: str = ""
    actual_address: str = ""
    postal_address: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    bank_details: str = ""
    holding_membership: str = ""
    tax_system: str = ""
    subcontractors: str = ""
    authorized_person: str = ""
    responsible_contact: str = ""
    raw_fields: dict[int, str] = field(default_factory=dict)


@dataclass
class NDAData:
    """Extracted info from NDA documents."""

    signatory_name: str = ""
    signatory_position: str = ""
    company_name: str = ""
    date: str = ""


# Row number (1-based) → AnketaData field name mapping
_FIELD_MAP: dict[int, str] = {
    1: "company_name",
    2: "org_form",
    3: "inn",  # May contain INN, KPP, OGRN combined
    4: "legal_address",
    5: "actual_address",
    6: "postal_address",
    7: "phone",
    8: "email",
    9: "website",
    10: "bank_details",
    11: "holding_membership",
    12: "tax_system",
    13: "subcontractors",
    14: "authorized_person",
    15: "responsible_contact",
}

# Pattern to extract tender ID from anketa header
_TENDER_ID_RE = re.compile(
    r"(?:АНКЕТА\s+УЧАСТНИКА\s+(?:ТЕНДЕРНОГО\s+ОТБОРА|ТО)\s+)"
    r"(\d{3,5}[-–—]\s*[А-Яа-яA-Za-z]{2,}[-–—]\s*[А-Яа-яA-Za-z0-9]+)",
    re.IGNORECASE,
)

# Fallback: just look for the ID pattern anywhere
_TENDER_ID_FALLBACK_RE = re.compile(
    r"\d{3,5}[-–—]\s*[А-Яа-яA-Za-z]{2,}[-–—]\s*[А-Яа-яA-Za-z0-9]+",
)

# INN pattern (10 or 12 digits)
_INN_RE = re.compile(r"\b(\d{10}(?:\d{2})?)\b")
_KPP_RE = re.compile(r"КПП[:\s]*(\d{9})", re.IGNORECASE)
_OGRN_RE = re.compile(r"ОГРН[:\s]*(\d{13,15})", re.IGNORECASE)


def parse_anketa(file_bytes: bytes, content_type: str = "") -> AnketaData:
    """Parse anketa file and extract all 15 fields.

    Args:
        file_bytes: Raw file content
        content_type: MIME type or file extension hint

    Returns:
        AnketaData with extracted fields
    """
    ct = content_type.lower()
    if "pdf" in ct or ct.endswith(".pdf"):
        return _parse_pdf(file_bytes)
    elif "docx" in ct or "word" in ct or ct.endswith(".docx"):
        return _parse_docx(file_bytes)
    elif "doc" in ct:
        # Try DOCX first, fall back to PDF
        try:
            return _parse_docx(file_bytes)
        except Exception:
            return _parse_pdf(file_bytes)
    # Default: try DOCX then PDF
    try:
        return _parse_docx(file_bytes)
    except Exception:
        return _parse_pdf(file_bytes)


def parse_nda(file_bytes: bytes, content_type: str = "") -> NDAData:
    """Parse NDA document to extract signatory information."""
    ct = content_type.lower()
    text = ""
    if "pdf" in ct:
        text = _extract_pdf_text(file_bytes)
    elif "docx" in ct or "word" in ct:
        text = _extract_docx_text(file_bytes)
    else:
        try:
            text = _extract_docx_text(file_bytes)
        except Exception:
            text = _extract_pdf_text(file_bytes)

    return _parse_nda_text(text)


# ---------------------------------------------------------------------------
#  DOCX parsing
# ---------------------------------------------------------------------------


def _parse_docx(file_bytes: bytes) -> AnketaData:
    """Extract anketa data from a DOCX file."""
    from docx import Document

    doc = Document(io.BytesIO(file_bytes))
    data = AnketaData()

    # Extract tender ID from paragraphs
    for p in doc.paragraphs:
        text = p.text.strip()
        if not text:
            continue
        m = _TENDER_ID_RE.search(text)
        if m:
            data.tender_id = m.group(1).strip()
            break
        m = _TENDER_ID_FALLBACK_RE.search(text)
        if m and not data.tender_id:
            data.tender_id = m.group(0).strip()

    # Find the main anketa table (first table with >= 15 rows)
    for table in doc.tables:
        if len(table.rows) < 3:
            continue
        _extract_from_docx_table(table, data)
        if data.company_name:
            break

    return data


def _extract_from_docx_table(table, data: AnketaData) -> None:
    """Extract fields from a DOCX table."""
    for row in table.rows:
        cells = [c.text.strip() for c in row.cells]
        if len(cells) < 3:
            continue

        # Try to get row number from first cell
        try:
            row_num = int(cells[0])
        except (ValueError, IndexError):
            continue

        # The value is in the last non-empty cell (typically column 3)
        value = cells[-1].strip()
        if not value:
            # Try second-to-last
            for c in reversed(cells[1:]):
                if c.strip() and not c.strip().isdigit():
                    value = c.strip()
                    break

        data.raw_fields[row_num] = value
        field_name = _FIELD_MAP.get(row_num)
        if field_name and value:
            if field_name == "inn":
                _parse_inn_field(value, data)
            else:
                setattr(data, field_name, value)


# ---------------------------------------------------------------------------
#  PDF parsing
# ---------------------------------------------------------------------------


def _parse_pdf(file_bytes: bytes) -> AnketaData:
    """Extract anketa data from a PDF file."""
    import pdfplumber

    data = AnketaData()

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        # Extract text for tender ID
        full_text = ""
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            full_text += page_text + "\n"

        # Extract tender ID
        m = _TENDER_ID_RE.search(full_text)
        if m:
            data.tender_id = m.group(1).strip()
        else:
            m = _TENDER_ID_FALLBACK_RE.search(full_text)
            if m:
                data.tender_id = m.group(0).strip()

        # Extract tables
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                _extract_from_pdf_table(table, data)
                if data.company_name:
                    break
            if data.company_name:
                break

    return data


def _extract_from_pdf_table(table: list[list], data: AnketaData) -> None:
    """Extract fields from a pdfplumber table."""
    for row in table:
        if not row or len(row) < 2:
            continue

        # Clean cells: remove None, strip whitespace
        cells = [str(c or "").strip() for c in row]

        # Try to get row number from first cell
        try:
            row_num = int(cells[0])
        except (ValueError, IndexError):
            continue

        # Find the value cell — skip the number and label columns
        # PDF tables may have merged cells resulting in None/empty
        value = ""
        for c in reversed(cells[1:]):
            c_clean = c.strip().replace("\n", " ")
            # Skip if it looks like a label (long text with no data)
            if c_clean and not _is_label_text(c_clean, row_num):
                value = c_clean
                break

        if not value:
            # Try to get from the last non-empty cell
            for c in reversed(cells):
                c_clean = c.strip()
                if c_clean and c_clean != str(row_num):
                    value = c_clean.replace("\n", " ")
                    break

        data.raw_fields[row_num] = value
        field_name = _FIELD_MAP.get(row_num)
        if field_name and value:
            if field_name == "inn":
                _parse_inn_field(value, data)
            else:
                setattr(data, field_name, value)


def _is_label_text(text: str, row_num: int) -> bool:
    """Check if text looks like a field label rather than a value."""
    labels = {
        1: "наименование",
        2: "организационно-правовая",
        3: "инн",
        4: "юридический",
        5: "фактический",
        6: "почтовый",
        7: "телефон",
        8: "адрес электронной",
        9: "адрес сайта",
        10: "банковские",
        11: "вхождение",
        12: "сведения об отнесении",
        13: "сведения о привлечении",
        14: "ф.и.о. уполномоченного",
        15: "ф.и.о. лица",
    }
    label = labels.get(row_num, "")
    if label and text.lower().startswith(label):
        return True
    return False


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


def _parse_inn_field(value: str, data: AnketaData) -> None:
    """Parse the INN/KPP/OGRN combined field."""
    # Extract INN
    inn_match = _INN_RE.search(value)
    if inn_match:
        data.inn = inn_match.group(1)

    # Extract KPP
    kpp_match = _KPP_RE.search(value)
    if kpp_match:
        data.kpp = kpp_match.group(1)

    # Extract OGRN
    ogrn_match = _OGRN_RE.search(value)
    if ogrn_match:
        data.ogrn = ogrn_match.group(1)

    # If no separate INN found, use entire value as INN
    if not data.inn and value.strip().isdigit():
        data.inn = value.strip()


def _extract_pdf_text(file_bytes: bytes) -> str:
    """Extract full text from PDF."""
    import pdfplumber

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def _extract_docx_text(file_bytes: bytes) -> str:
    """Extract full text from DOCX."""
    from docx import Document

    doc = Document(io.BytesIO(file_bytes))
    return "\n".join(p.text for p in doc.paragraphs)


def _parse_nda_text(text: str) -> NDAData:
    """Parse NDA text to extract signatory info."""
    data = NDAData()

    # Look for signatory patterns
    signatory_re = re.compile(
        r"(?:подписант|уполномоченное\s+лицо|от\s+имени)[:\s]+(.+?)(?:\n|$)",
        re.IGNORECASE,
    )
    m = signatory_re.search(text)
    if m:
        data.signatory_name = m.group(1).strip()

    # Look for company name
    company_re = re.compile(
        r"(?:ООО|АО|ЗАО|ПАО|СПАО)\s*[«\"](.+?)[»\"]",
        re.IGNORECASE,
    )
    m = company_re.search(text)
    if m:
        data.company_name = m.group(0).strip()

    # Look for date
    date_re = re.compile(r"\d{1,2}[.\s]+\w+[.\s]+\d{4}")
    m = date_re.search(text)
    if m:
        data.date = m.group(0).strip()

    return data
