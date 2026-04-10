"""Бегун агента «Сборщик документов тендерного отбора».

Обрабатывает пакет тендерных отборов:
  - принимает JSON-файлы с данными о тендерном отборе
    (tender_id, emails, participants_list);
  - для каждого файла вызывает агент, который собирает и проверяет
    документы участников;
  - сохраняет результат в JSON-файл.
"""
import argparse
import hashlib
import json
import os
import pathlib
from datetime import UTC, datetime

from dotenv import load_dotenv

load_dotenv()

import shared.database as db  # noqa: E402
from agent3_collector_inspector.agent import create_collector_agent  # noqa: E402
from api.metrics import EMAILS_ERRORS, EMAILS_PROCESSED, POLL_CYCLES, JobTimer  # noqa: E402
from config import FORCE_REPROCESS  # noqa: E402
from shared.logger import setup_logger  # noqa: E402
from shared.telegram_notify import notify  # noqa: E402
from shared.tracing import get_langfuse_callback, log_agent_steps  # noqa: E402

logger = setup_logger("agent_collector_runner")

COLLECTOR_INPUT_DIR = os.getenv("COLLECTOR_INPUT_DIR", "collector_input")
COLLECTOR_OUTPUT_DIR = os.getenv("COLLECTOR_OUTPUT_DIR", "")


def _build_output_path(
    source_path: str,
    output_dir: str,
) -> pathlib.Path:
    source = pathlib.Path(source_path)
    hash_suffix = hashlib.sha256(source_path.encode("utf-8")).hexdigest()[:8]
    out_filename = f"{source.stem}_{hash_suffix}_result.json"
    if output_dir:
        out = pathlib.Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        return out / out_filename
    return source.parent / out_filename


def _save_json_result(result: dict, output_path: pathlib.Path) -> None:
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Результат сохранён: %s", output_path)


def process_single_input(
    source: str,
    output_dir: str = "",
    save_to_file: bool = True,
) -> dict:
    """Обработать один JSON-файл с данными тендерного отбора.

    Args:
        source: путь к JSON-файлу с полями tender_id, emails, participants_list.
        output_dir: директория для сохранения результата.
        save_to_file: сохранять ли результат в JSON-файл.

    Returns:
        dict с результатом обработки.
    """
    logger.info("Обрабатываю входные данные: %s", source)

    file_path = pathlib.Path(source)
    if not file_path.exists():
        logger.error("Файл не найден: %s", source)
        return {"status": "error", "error": f"File not found: {source}", "source": source}

    if file_path.suffix.lower() != ".json":
        logger.warning("Ожидается JSON-файл, получен: %s", file_path.suffix)
        return {
            "status": "error",
            "error": f"Expected .json file, got '{file_path.suffix}'",
            "source": source,
        }

    try:
        input_data = json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error("Ошибка чтения JSON: %s — %s", source, e)
        return {"status": "error", "error": f"Invalid JSON: {e}", "source": source}

    tender_id = input_data.get("tender_id", "")
    if not tender_id:
        logger.error("Не указан tender_id в файле: %s", source)
        return {"status": "error", "error": "Missing tender_id", "source": source}

    dedup_subject = f"collector:{tender_id}:{file_path.name}"

    if not FORCE_REPROCESS:
        dup = db.find_duplicate_job("collector", "", dedup_subject)
        if dup:
            _ca = dup.get("created_at")
            _ca_str = (
                _ca.date().isoformat()
                if hasattr(_ca, "date")
                else str(_ca)[:10]
                if _ca
                else "N/A"
            )
            logger.info(
                "[dedup] Пропускаем дубль: '%s' (ранее обработано %s)",
                dedup_subject,
                _ca_str,
            )
            return dup.get("result") or {}

    job_id = db.create_job("collector", sender="", subject=dedup_subject)

    try:
        chat_input = json.dumps(input_data, ensure_ascii=False)

        agent = create_collector_agent()
        lf_cb = get_langfuse_callback()
        callbacks = [lf_cb] if lf_cb is not None else []

        with JobTimer("collector"):
            result = agent.invoke(
                {"input": chat_input},
                config=(
                    {
                        "callbacks": callbacks,
                        "metadata": {"session_id": job_id},
                    }
                    if callbacks
                    else {}
                ),
            )

        steps = result.get("intermediate_steps", [])
        trace = log_agent_steps(job_id=job_id, agent="collector", steps=steps)

        collector_result = _extract_collector_result(steps)
        if not collector_result:
            logger.warning("Агент не вызвал collect_tender_documents, используем текстовый output")
            collector_result = {
                "timestamp": datetime.now(UTC).isoformat(),
                "tender_id": tender_id,
                "raw_output": result.get("output", ""),
            }

        collector_result["source_file"] = file_path.name
        if "timestamp" not in collector_result:
            collector_result["timestamp"] = datetime.now(UTC).isoformat()

        if save_to_file:
            eff_output_dir = output_dir or COLLECTOR_OUTPUT_DIR
            output_path = _build_output_path(source, eff_output_dir)
            _save_json_result(collector_result, output_path)

        tool_error = collector_result.get("error")
        if tool_error:
            db.update_job(
                job_id,
                status="error",
                decision=f"Ошибка инструмента: {tool_error}",
                result=collector_result,
                trace=trace,
            )
            EMAILS_ERRORS.labels(agent="collector", error_type="tool_error").inc()
            logger.warning("collect_tender_documents вернул ошибку: %s", tool_error)
        else:
            received = collector_result.get("received_count", 0)
            total = collector_result.get("total_expected_participants", 0)
            db.update_job(
                job_id,
                status="done",
                decision=f"Собрано {received}/{total} участников",
                result=collector_result,
                trace=trace,
            )
            EMAILS_PROCESSED.labels(agent="collector").inc()
            logger.info(
                "Обработка завершена: ТО %s (%d/%d участников)",
                tender_id,
                received,
                total,
            )
        return collector_result

    except Exception as e:
        EMAILS_ERRORS.labels(agent="collector", error_type=type(e).__name__).inc()
        db.update_job(job_id, status="error", error=str(e))
        logger.error("Критическая ошибка при обработке %s: %s", source, e)
        notify(f"Ошибка Агент-Collector. Файл: {file_path.name}. {e}", level="error")
        raise


def _extract_collector_result(steps: list) -> dict:
    """Извлечь результат collect_tender_documents из intermediate_steps."""
    for step in steps:
        try:
            if not isinstance(step, (list, tuple)) or len(step) < 2:
                continue
            tool_name, raw_obs = step[0], step[1]
            if tool_name != "collect_tender_documents":
                continue
            obs = json.loads(raw_obs) if isinstance(raw_obs, str) else raw_obs
            if not isinstance(obs, dict):
                continue
            if "tender_id" in obs or "error" in obs:
                return obs
        except Exception as exc:
            logger.warning(
                "Не удалось разобрать шаг collect_tender_documents: %r (%s)",
                step,
                exc,
            )
    return {}


def process_collector_inputs(
    sources: list[str] | None = None,
    output_dir: str = "",
    save_to_file: bool = True,
) -> list[dict]:
    """Пакетная обработка входных файлов тендерных отборов.

    Args:
        sources: список путей к JSON-файлам. Если None — сканирует COLLECTOR_INPUT_DIR.
        output_dir: директория для сохранения результатов.
        save_to_file: сохранять ли результаты в JSON-файлы.

    Returns:
        список результатов обработки.
    """
    POLL_CYCLES.labels(agent="collector").inc()
    logger.info("Запуск пакетной обработки collector...")

    if sources is None:
        input_dir = pathlib.Path(COLLECTOR_INPUT_DIR)
        if not input_dir.exists():
            logger.warning("Директория '%s' не найдена — создаю пустую.", COLLECTOR_INPUT_DIR)
            input_dir.mkdir(parents=True, exist_ok=True)
            return []
        sources = [
            str(p)
            for p in sorted(input_dir.iterdir())
            if p.is_file() and p.suffix.lower() == ".json"
        ]
        logger.info("Найдено %d файлов в '%s'", len(sources), COLLECTOR_INPUT_DIR)

    if not sources:
        logger.info("Нет файлов для обработки.")
        return []

    results = []
    for source in sources:
        try:
            res = process_single_input(source, output_dir=output_dir, save_to_file=save_to_file)
            results.append(res)
        except Exception as e:
            logger.error("Пропуск '%s' из-за ошибки: %s", source, e)
            results.append({"source_file": source, "error": str(e)})

    logger.info("Пакетная обработка завершена: %d файлов", len(results))
    return results


def main() -> None:
    """CLI-точка входа для runner агента collector."""
    parser = argparse.ArgumentParser(
        description="Сборщик документов тендерного отбора — пакетная обработка",
    )
    parser.add_argument(
        "sources",
        nargs="*",
        help="Пути к JSON-файлам с данными ТО (если не указаны — сканирует COLLECTOR_INPUT_DIR)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default="",
        help="Директория для сохранения результатов (по умолчанию — рядом с входным файлом)",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Не сохранять результаты в файлы",
    )
    parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        help="Формат вывода в stdout (по умолчанию: json)",
    )
    args = parser.parse_args()

    sources = args.sources if args.sources else None
    results = process_collector_inputs(
        sources=sources,
        output_dir=args.output_dir,
        save_to_file=not args.no_save,
    )

    if args.format == "json":
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for res in results:
            tender_id = res.get("tender_id", "?")
            if "error" in res:
                print(f"[ОШИБКА] ТО {tender_id}: {res['error']}")
            else:
                received = res.get("received_count", 0)
                total = res.get("total_expected_participants", 0)
                print(f"[OK] ТО {tender_id}: собрано {received}/{total} участников")
                report = res.get("report_text")
                if report:
                    print(report)
            print("---")


if __name__ == "__main__":
    main()
