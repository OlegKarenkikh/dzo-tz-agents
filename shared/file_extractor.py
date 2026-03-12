import io
import logging
import os
from typing import Any

import openpyxl
import pdfplumber
import xlrd
from docx import Document
from openai import OpenAI

logger = logging.getLogger("file_extractor")

IMAGE_EXTS = {"jpg", "jpeg", "png", "tiff", "tif", "bmp", "gif", "webp"}

# Ленивая инициализация клиента — не создаём при импорте модуля.
# Использует OPENAI_API_BASE, чтобы OCR работал с Ollama/vLLM/DeepSeek.
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY") or "ollama",
            base_url=os.getenv("OPENAI_API_BASE") or None,
        )
    return _client


def extract_text_from_attachment(att: dict[str, Any]) -> str:
    """
    Маршрутизация извлечения текста по типу файла.
    Аналог Switch-ноды в n8n: PDF / DOCX / DOC / XLSX / XLS / IMAGE / other.
    """
    ext = att.get("ext", "").lower()
    data = att["data"]
    b64 = att["b64"]
    mime = att.get("mime", "application/octet-stream")

    if ext == "pdf":
        return _extract_pdf(data, b64, mime)
    elif ext == "docx":
        return _extract_docx(data, b64, mime)
    elif ext == "doc":
        return _ocr_vision(b64, mime, "DOC")
    elif ext in ("xlsx", "xls"):
        return _extract_spreadsheet(data, ext)
    elif ext in IMAGE_EXTS:
        return _ocr_vision(b64, mime, "IMAGE")
    else:
        return f"[⚠️ Формат '{att.get('filename','?')}' ({ext}) не поддерживается]"


def _extract_pdf(data: bytes, b64: str, mime: str) -> str:
    """PDF: pdfplumber → при коротком тексте OCR через GPT-4o Vision."""
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages).strip()
        if len(text) >= 50:
            return text
    except Exception as e:
        logger.warning(f"pdfplumber не смог прочитать PDF: {e}")
    return _ocr_vision(b64, mime or "application/pdf", "PDF-скан")


def _extract_docx(data: bytes, b64: str, mime: str) -> str:
    """DOCX: python-docx → при ошибке OCR через Vision."""
    try:
        doc = Document(io.BytesIO(data))
        text = "\n".join(p.text for p in doc.paragraphs).strip()
        if len(text) >= 50:
            return text
    except Exception as e:
        logger.warning(f"python-docx не смог прочитать DOCX: {e}")
    return _ocr_vision(b64, mime, "DOCX")


def _ocr_vision(b64: str, mime: str, doc_type: str) -> str:
    """OCR через GPT-4o Vision (или совместимую модель через OPENAI_API_BASE)."""
    try:
        model = os.getenv("MODEL_NAME", "gpt-4o")
        resp = _get_client().chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"Ты — OCR-движок. Извлеки ВЕСЬ текст из документа {doc_type}. "
                        "Сохрани структуру: заголовки, таблицы (markdown), списки. "
                        "Нечитаемые фрагменты помечай [нечитаемый фрагмент]. "
                        "Отвечай ТОЛЬКО извлечённым текстом."
                    ),
                },
                {
                    "role": "user",
                    "content": [{
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"},
                    }],
                },
            ],
            max_tokens=4096,
            temperature=0.1,
        )
        return resp.choices[0].message.content
    except Exception as e:
        logger.error(f"OCR Vision ошибка ({doc_type}): {e}")
        return f"[OCR ошибка: {e}]"


def _extract_spreadsheet(data: bytes, ext: str) -> str:
    """XLSX/XLS → Markdown-таблица."""
    try:
        if ext == "xlsx":
            wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
            sheets = []
            for name in wb.sheetnames:
                ws = wb[name]
                rows = [[str(c.value or "") for c in row] for row in ws.iter_rows()]
                sheets.append(f"### Лист: {name}\n" + _rows_to_md(rows))
            return "\n\n".join(sheets)
        else:
            wb = xlrd.open_workbook(file_contents=data)
            sheets = []
            for i in range(wb.nsheets):
                ws = wb.sheet_by_index(i)
                rows = [
                    [str(ws.cell_value(r, c)) for c in range(ws.ncols)]
                    for r in range(ws.nrows)
                ]
                sheets.append(f"### Лист: {ws.name}\n" + _rows_to_md(rows))
            return "\n\n".join(sheets)
    except Exception as e:
        return f"[Ошибка извлечения таблицы: {e}]"


def _rows_to_md(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    header = "| " + " | ".join(rows[0]) + " |"
    sep = "| " + " | ".join(["---"] * len(rows[0])) + " |"
    body = "\n".join("| " + " | ".join(r) + " |" for r in rows[1:])
    return f"{header}\n{sep}\n{body}"
