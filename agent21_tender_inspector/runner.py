"""Бегун агента «Парсер тендерной документации».

Обрабатывает пакет тендерных документов:
  - принимает пути к файлам (PDF / DOCX / XLSX) или HTTP(S)-ссылки на документы;
  - для каждого документа вызывает агент, который извлекает перечень требуемых
    от участника закупки документов;
  - сохраняет результат в JSON-файл с тем же именем, но с расширением .json.

Поддерживаемые режимы запуска:
  1. Обработка директории — сканирует TENDER_DOCS_DIR, обрабатывает все файлы.
  2. Обработка списка путей/URL — через аргумент или вызов process_tender_documents().
  3. Запуск через API — /api/v1/process/tender вызывает агент напрямую.
"""
import json
import os
import pathlib
import urllib.parse
from datetime import UTC, datetime

from dotenv import load_dotenv

load_dotenv()

import shared.database as db  # noqa: E402
from agent21_tender_inspector.agent import create_tender_agent  # noqa: E402
from api.metrics import EMAILS_ERRORS, EMAILS_PROCESSED, JobTimer, POLL_CYCLES  # noqa: E402
from shared.file_extractor import extract_text_from_attachment  # noqa: E402
from shared.logger import setup_logger  # noqa: E402
from shared.telegram_notify import notify  # noqa: E402
from shared.tracing import get_langfuse_callback, log_agent_steps  # noqa: E402

logger = setup_logger("agent_tender")

# Директория с тендерными документами (по умолчанию — поддиректория tender_docs)
TENDER_DOCS_DIR = os.getenv("TENDER_DOCS_DIR", "tender_docs")

# Директория для сохранения JSON-результатов (по умолчанию — рядом с исходным файлом)
TENDER_OUTPUT_DIR = os.getenv("TENDER_OUTPUT_DIR", "")

# Поддерживаемые расширения документов
SUPPORTED_EXTS = {".pdf", ".docx", ".doc", ".xlsx", ".xls"}

FORCE_REPROCESS = os.getenv("FORCE_REPROCESS", "false").lower() == "true"


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _is_url(path: str) -> bool:
    """Проверяет, является ли строка URL."""
    parsed = urllib.parse.urlparse(path)
    return parsed.scheme in ("http", "https")


def _download_document(url: str) -> tuple[bytes, str]:
    """Скачивает документ по URL. Возвращает (bytes, filename)."""
    import httpx

    _MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024  # 50 МБ

    logger.info("⬇️ Загрузка документа: %s", url)
    chunks: list[bytes] = []
    total = 0
    with httpx.stream("GET", url, follow_redirects=True, timeout=60) as resp:
        resp.raise_for_status()
        for chunk in resp.iter_bytes(chunk_size=65536):
            total += len(chunk)
            if total > _MAX_DOWNLOAD_BYTES:
                raise ValueError(
                    f"Документ превышает максимально допустимый размер "
                    f"({_MAX_DOWNLOAD_BYTES // (1024 * 1024)} МБ): {url}"
                )
            chunks.append(chunk)
        content_disp = resp.headers.get("content-disposition", "")
        content_type = resp.headers.get("content-type", "")

    raw = b"".join(chunks)

    # Определяем имя файла из заголовка или URL
    filename = ""
    if "filename=" in content_disp:
        filename = content_disp.split("filename=")[-1].strip().strip('"\'')
    if not filename:
        filename = pathlib.Path(urllib.parse.urlparse(url).path).name or "document"
    # Санитизируем: берём только basename, чтобы предотвратить path traversal
    filename = pathlib.PurePath(filename).name or "document"
    # Добавляем расширение из Content-Type если нет
    if not pathlib.Path(filename).suffix:
        if "pdf" in content_type:
            filename += ".pdf"
        elif "wordprocessingml" in content_type:
            filename += ".docx"
        elif "spreadsheetml" in content_type:
            filename += ".xlsx"
        elif "msword" in content_type:
            filename += ".doc"
        elif "ms-excel" in content_type:
            filename += ".xls"
        elif "officedocument" in content_type:
            filename += ".docx"
        else:
            filename += ".bin"

    logger.info("✅ Загружено: %s (%d байт)", filename, len(raw))
    return raw, filename


def _extract_text(file_data: bytes, filename: str) -> str:
    """Извлекает текст из файла."""
    import base64
    import mimetypes

    ext = pathlib.Path(filename).suffix.lstrip(".").lower()
    b64 = base64.b64encode(file_data).decode()
    # Используем mimetypes для корректного Content-Type; fallback — application/octet-stream
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    att = {
        "filename": filename,
        "ext": ext,
        "data": file_data,
        "b64": b64,
        "mime": mime,
    }
    return extract_text_from_attachment(att)


def _build_output_path(source_path: str, output_dir: str) -> pathlib.Path:
    """Формирует путь к выходному JSON-файлу."""
    source = pathlib.Path(source_path)
    if output_dir:
        out = pathlib.Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        return out / f"{source.stem}.json"
    # По умолчанию — рядом с исходным файлом
    return source.parent / f"{source.stem}.json"


def _save_json_result(result: dict, output_path: pathlib.Path) -> None:
    """Сохраняет JSON-результат в файл."""
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("💾 Результат сохранён: %s", output_path)


def _extract_document_list_from_steps(steps: list) -> dict:
    """Извлекает результат generate_document_list из шагов агента."""
    for step in steps:
        try:
            obs = json.loads(step[1]) if isinstance(step[1], str) else step[1]
            if isinstance(obs, dict) and "documents" in obs:
                return obs
        except Exception:
            pass
    return {}


# ---------------------------------------------------------------------------
# Основная функция обработки
# ---------------------------------------------------------------------------

def process_single_document(
    source: str,
    output_dir: str = "",
    save_to_file: bool = True,
) -> dict:
    """Обрабатывает один тендерный документ (путь к файлу или URL).

    Args:
        source:       Путь к файлу или HTTP(S)-URL тендерного документа.
        output_dir:   Директория для сохранения JSON (по умолчанию — рядом с файлом).
        save_to_file: Если True — сохраняет результат в JSON-файл.

    Returns:
        Словарь с результатами анализа (содержимое JSON-файла).
    """
    logger.info("📄 Обрабатываю документ: %s", source)

    # ── Загрузка/чтение документа ─────────────────────────────────────────
    if _is_url(source):
        file_data, filename = _download_document(source)
        # URL → используем явную директорию: output_dir → TENDER_OUTPUT_DIR → cwd
        eff_url_dir = output_dir or TENDER_OUTPUT_DIR or os.getcwd()
        file_path = os.path.join(eff_url_dir, filename)

        suffix = pathlib.Path(filename).suffix.lower()
        if suffix not in SUPPORTED_EXTS:
            logger.warning(
                "Неподдерживаемое расширение файла '%s' для документа '%s'. "
                "Поддерживаемые расширения: %s",
                suffix, filename, ", ".join(sorted(SUPPORTED_EXTS)),
            )
            return {
                "status": "error",
                "error": (
                    f"Unsupported file extension '{suffix}' for document '{filename}'. "
                    f"Supported extensions: {', '.join(sorted(SUPPORTED_EXTS))}"
                ),
                "filename": filename,
                "source": source,
            }
    else:
        file_path = source
        filename = pathlib.Path(source).name

        # ── Проверка расширения до чтения файла ──────────────────────────
        suffix = pathlib.Path(filename).suffix.lower()
        if suffix not in SUPPORTED_EXTS:
            logger.warning(
                "Неподдерживаемое расширение файла '%s' для документа '%s'. "
                "Поддерживаемые расширения: %s",
                suffix, filename, ", ".join(sorted(SUPPORTED_EXTS)),
            )
            return {
                "status": "error",
                "error": (
                    f"Unsupported file extension '{suffix}' for document '{filename}'. "
                    f"Supported extensions: {', '.join(sorted(SUPPORTED_EXTS))}"
                ),
                "filename": filename,
                "source": source,
            }

        _MAX_LOCAL_BYTES = 50 * 1024 * 1024  # 50 МБ
        file_size = pathlib.Path(source).stat().st_size
        if file_size > _MAX_LOCAL_BYTES:
            logger.warning(
                "Файл '%s' превышает максимально допустимый размер (%d МБ)",
                filename, _MAX_LOCAL_BYTES // (1024 * 1024),
            )
            return {
                "status": "error",
                "error": (
                    f"File '{filename}' exceeds the maximum allowed size "
                    f"({_MAX_LOCAL_BYTES // (1024 * 1024)} MB)."
                ),
                "filename": filename,
                "source": source,
            }
        file_data = pathlib.Path(source).read_bytes()

    # ── Дедупликация ───────────────────────────────────────────────────────
    if not FORCE_REPROCESS:
        dup = db.find_duplicate_job("tender", "", filename)
        if dup:
            logger.info(
                "[dedup] Пропускаем дубль: '%s' (ранее обработано %s)",
                filename, dup["created_at"][:10],
            )
            return dup.get("result") or {}

    job_id = db.create_job("tender", sender="", subject=filename)

    try:
        # ── Извлечение текста ─────────────────────────────────────────────
        text = _extract_text(file_data, filename)
        logger.info(
            "📖 Текст извлечён: %s (%d символов)",
            filename, len(text),
        )

        chat_input = (
            "ТЕНДЕРНЫЙ ДОКУМЕНТ ДЛЯ АНАЛИЗА\n"
            "===========================================\n"
            f"Файл: {filename}\n"
            f"Дата: {datetime.now(UTC).isoformat()}\n\n"
            f"-- СОДЕРЖИМОЕ ДОКУМЕНТА --\n{text}"
        )

        # ── Запуск агента ─────────────────────────────────────────────────
        agent = create_tender_agent()
        lf_cb = get_langfuse_callback()
        callbacks = [lf_cb] if lf_cb is not None else []

        with JobTimer("tender"):
            result = agent.invoke(
                {"input": chat_input},
                config={
                    "callbacks": callbacks,
                    "metadata": {"session_id": job_id},
                } if callbacks else {},
            )

        # ── Извлечение результата ─────────────────────────────────────────
        steps = result.get("intermediate_steps", [])
        log_agent_steps(job_id=job_id, agent="tender", steps=steps)

        document_list = _extract_document_list_from_steps(steps)
        if not document_list:
            # Если агент не вызвал инструмент, пробуем распарсить output
            logger.warning(
                "⚠️ Агент не вызвал generate_document_list, используем текстовый output"
            )
            document_list = {
                "timestamp": datetime.now().isoformat(),
                "procurement_subject": "Не определён (агент не вызвал инструмент)",
                "documents": [],
                "summary": {"total": 0, "mandatory": 0, "conditional": 0},
                "raw_output": result.get("output", ""),
            }

        # Добавляем метаданные источника
        document_list["source_document"] = filename
        if "timestamp" not in document_list:
            document_list["timestamp"] = datetime.now().isoformat()

        # ── Сохранение результата ─────────────────────────────────────────
        if save_to_file:
            eff_output_dir = output_dir or TENDER_OUTPUT_DIR
            output_path = _build_output_path(file_path, eff_output_dir)
            _save_json_result(document_list, output_path)

        db.update_job(
            job_id,
            status="done",
            decision=f"Найдено документов: {document_list.get('summary', {}).get('total', 0)}",
            result=document_list,
        )
        EMAILS_PROCESSED.labels(agent="tender").inc()
        logger.info(
            "✅ Документ обработан: %s (всего документов: %d)",
            filename,
            document_list.get("summary", {}).get("total", 0),
        )
        return document_list

    except Exception as e:
        EMAILS_ERRORS.labels(agent="tender", error_type=type(e).__name__).inc()
        db.update_job(job_id, status="error", error=str(e))
        logger.error("❌ Критическая ошибка при обработке %s: %s", filename, e)
        notify("Ошибка Агент-Тендер. Файл: " + filename + ". " + str(e), level="error")
        raise


# ---------------------------------------------------------------------------
# Пакетная обработка директории
# ---------------------------------------------------------------------------

def process_tender_documents(
    sources: list[str] | None = None,
    output_dir: str = "",
    save_to_file: bool = True,
) -> list[dict]:
    """Обрабатывает список тендерных документов (пути или URL).

    Если sources не указан — сканирует директорию TENDER_DOCS_DIR.

    Args:
        sources:      Список путей к файлам или URL. Если None — берёт из TENDER_DOCS_DIR.
        output_dir:   Директория для сохранения JSON.
        save_to_file: Сохранять ли результаты в файлы.

    Returns:
        Список результатов для каждого документа.
    """
    POLL_CYCLES.labels(agent="tender").inc()
    logger.info("🗂️ Запуск пакетной обработки тендерных документов...")

    if sources is None:
        docs_dir = pathlib.Path(TENDER_DOCS_DIR)
        if not docs_dir.exists():
            logger.warning("Директория '%s' не найдена — создаю пустую.", TENDER_DOCS_DIR)
            docs_dir.mkdir(parents=True, exist_ok=True)
            return []
        sources = [
            str(p)
            for p in sorted(docs_dir.iterdir())
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
        ]
        logger.info("Найдено %d документов в '%s'", len(sources), TENDER_DOCS_DIR)

    if not sources:
        logger.info("Нет документов для обработки.")
        return []

    results = []
    for source in sources:
        try:
            res = process_single_document(source, output_dir=output_dir, save_to_file=save_to_file)
            results.append(res)
        except Exception as e:
            logger.error("❌ Пропуск '%s' из-за ошибки: %s", source, e)
            results.append({"source_document": source, "error": str(e)})

    logger.info("✅ Пакетная обработка завершена: %d документов", len(results))
    return results


if __name__ == "__main__":
    process_tender_documents()
