"""Unit-тесты для agent21_tender_inspector/runner.py.

Покрывают:
  - _build_output_path: коллизии basename, hash_source для URL
  - process_single_document: неподдерживаемое расширение (локальный файл и URL),
    лимит 50 МБ, дедупликация URL vs локальный файл.

Все внешние зависимости (httpx, db, extract_text, create_tender_agent) замокированы,
поэтому тесты работают без реального API-ключа, БД или LLM.
"""
# ruff: noqa: I001
import hashlib
import json
import pathlib
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Вспомогательные фикстуры
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_fallback_cache():
    """Сбрасываем кэш цепочки fallback между тестами."""
    import agent21_tender_inspector.runner as runner_mod
    runner_mod._fallback_chain_cache.clear()
    yield
    runner_mod._fallback_chain_cache.clear()


@pytest.fixture()
def mock_db(monkeypatch):
    """Заглушка shared.database."""
    import shared.database as db_mod
    monkeypatch.setattr(db_mod, "find_duplicate_job", lambda *a, **kw: None)
    monkeypatch.setattr(db_mod, "create_job", lambda *a, **kw: "job-test-123")
    monkeypatch.setattr(db_mod, "update_job", lambda *a, **kw: None)
    return db_mod


@pytest.fixture()
def mock_extract_text(monkeypatch):
    """Заглушка _extract_text, возвращающая короткий текст."""
    import agent21_tender_inspector.runner as runner_mod
    monkeypatch.setattr(runner_mod, "_extract_text", lambda data, fname: "extracted text")
    return runner_mod


@pytest.fixture()
def mock_agent(monkeypatch):
    """Заглушка create_tender_agent + get_langfuse_callback."""
    import agent21_tender_inspector.runner as runner_mod

    fake_result = {
        "intermediate_steps": [
            (
                "generate_document_list",
                json.dumps({
                    "documents": [],
                    "summary": {"total": 0, "mandatory": 0, "conditional": 0},
                    "procurement_subject": "Тест",
                    "timestamp": "2024-01-01T00:00:00+00:00",
                }),
            )
        ],
        "output": "Документов не найдено",
    }
    fake_runner = MagicMock()
    fake_runner.invoke.return_value = fake_result
    monkeypatch.setattr(runner_mod, "create_tender_agent", lambda: fake_runner)
    monkeypatch.setattr(runner_mod, "get_langfuse_callback", lambda: None)
    monkeypatch.setattr(runner_mod, "EMAILS_PROCESSED", MagicMock())
    monkeypatch.setattr(runner_mod, "EMAILS_ERRORS", MagicMock())
    monkeypatch.setattr(runner_mod, "notify", lambda *a, **kw: None)
    return fake_runner


# ---------------------------------------------------------------------------
# Тесты _build_output_path
# ---------------------------------------------------------------------------

class TestBuildOutputPath:
    def _fn(self, *args, **kwargs):
        from agent21_tender_inspector.runner import _build_output_path
        return _build_output_path(*args, **kwargs)

    def test_stem_ext_hash_in_filename(self, tmp_path):
        """Имя файла должно содержать stem, расширение и 8-символьный хеш."""
        p = self._fn("/some/path/doc.pdf", str(tmp_path))
        name = p.name
        # формат: doc_pdf_<hash8>.json
        assert name.startswith("doc_pdf_")
        assert name.endswith(".json")
        assert len(name) == len("doc_pdf_") + 8 + len(".json")

    def test_same_basename_different_ext_differ(self, tmp_path):
        """doc.pdf и doc.docx — одинаковый stem, но разные расширения → разные имена."""
        p1 = self._fn("/dir/doc.pdf", str(tmp_path))
        p2 = self._fn("/dir/doc.docx", str(tmp_path))
        assert p1.name != p2.name, "doc.pdf и doc.docx не должны давать одинаковое имя"

    def test_same_basename_different_path_differ(self, tmp_path):
        """Файлы с одинаковым basename в разных директориях → разные хеши."""
        p1 = self._fn("/dir1/doc.pdf", str(tmp_path))
        p2 = self._fn("/dir2/doc.pdf", str(tmp_path))
        assert p1.name != p2.name

    def test_hash_source_overrides_hash(self, tmp_path):
        """Когда hash_source передан, хеш считается от него, а не от source_path."""
        url1 = "https://example.com/files/document.pdf"
        url2 = "https://other.org/files/document.pdf"
        # Оба URL заканчиваются одинаковым basename
        p1 = self._fn("/tmp/document.pdf", str(tmp_path), hash_source=url1)
        p2 = self._fn("/tmp/document.pdf", str(tmp_path), hash_source=url2)
        assert p1.name != p2.name, "Разные URL с одинаковым basename должны давать разные имена"

    def test_hash_source_none_uses_source_path(self, tmp_path):
        """Без hash_source хеш считается от source_path."""
        source = "/some/dir/tender.xlsx"
        p = self._fn(source, str(tmp_path))
        expected_hash = hashlib.sha256(source.encode()).hexdigest()[:8]
        assert expected_hash in p.name

    def test_url_hash_source_correct_hash_value(self, tmp_path):
        """hash_source=URL → хеш вычислен от URL, не от пути к файлу."""
        url = "https://zakupki.gov.ru/files/tender_doc.pdf"
        local_path = "/tmp/url_downloads/tender_doc.pdf"
        p = self._fn(local_path, str(tmp_path), hash_source=url)
        expected_hash = hashlib.sha256(url.encode()).hexdigest()[:8]
        assert expected_hash in p.name, f"Ожидался хеш от URL {url!r}"

    def test_output_dir_used(self, tmp_path):
        """Результирующий файл должен быть в output_dir."""
        out = str(tmp_path / "results")
        p = self._fn("/some/doc.pdf", out)
        assert str(p).startswith(out)

    def test_no_output_dir_next_to_source(self, tmp_path):
        """Без output_dir результат сохраняется рядом с исходным файлом."""
        source = str(tmp_path / "source" / "doc.pdf")
        pathlib.Path(source).parent.mkdir(parents=True, exist_ok=True)
        p = self._fn(source, "")
        assert p.parent == pathlib.Path(source).parent


# ---------------------------------------------------------------------------
# Тесты process_single_document — неподдерживаемое расширение (локальный файл)
# ---------------------------------------------------------------------------

class TestProcessSingleDocumentUnsupportedExt:
    def test_local_txt_returns_error(self, tmp_path):
        """Файл .txt не поддерживается — должен вернуть error без вызова агента."""
        from agent21_tender_inspector.runner import process_single_document

        fake_file = tmp_path / "readme.txt"
        fake_file.write_bytes(b"hello")

        result = process_single_document(str(fake_file), save_to_file=False)
        assert result["status"] == "error"
        assert ".txt" in result["error"]
        assert result["filename"] == "readme.txt"

    def test_local_bin_returns_error(self, tmp_path):
        """Файл .bin не поддерживается."""
        from agent21_tender_inspector.runner import process_single_document

        fake_file = tmp_path / "data.bin"
        fake_file.write_bytes(b"\x00\x01\x02")

        result = process_single_document(str(fake_file), save_to_file=False)
        assert result["status"] == "error"
        assert ".bin" in result["error"]

    def test_unsupported_ext_no_agent_called(self, tmp_path, monkeypatch):
        """При неподдерживаемом расширении агент не вызывается."""
        import agent21_tender_inspector.runner as runner_mod
        from agent21_tender_inspector.runner import process_single_document

        mock_create_agent = MagicMock()
        monkeypatch.setattr(runner_mod, "create_tender_agent", mock_create_agent)

        fake_file = tmp_path / "file.csv"
        fake_file.write_bytes(b"a,b,c")

        process_single_document(str(fake_file), save_to_file=False)
        mock_create_agent.assert_not_called()


# ---------------------------------------------------------------------------
# Тесты process_single_document — лимит 50 МБ
# ---------------------------------------------------------------------------

class TestProcessSingleDocumentSizeLimit:
    def test_local_file_exceeds_50mb_returns_error(self, tmp_path):
        """Файл > 50 МБ должен вернуть error без чтения содержимого."""
        from agent21_tender_inspector.runner import process_single_document

        large_file = tmp_path / "big.pdf"
        large_file.write_bytes(b"")  # создаём файл, потом мокируем size

        _50MB_PLUS_1 = 50 * 1024 * 1024 + 1

        with patch("pathlib.Path.stat") as mock_stat:
            mock_stat.return_value = MagicMock(st_size=_50MB_PLUS_1)
            result = process_single_document(str(large_file), save_to_file=False)

        assert result["status"] == "error"
        assert "50" in result["error"]  # сообщение содержит лимит "50 MB"
        assert result["filename"] == "big.pdf"

    def test_local_file_exactly_50mb_is_allowed(self, tmp_path, mock_db, mock_extract_text, mock_agent):
        """Файл ровно 50 МБ — граничное значение, должен обрабатываться."""
        from agent21_tender_inspector.runner import process_single_document

        ok_file = tmp_path / "ok.pdf"
        ok_file.write_bytes(b"")

        _50MB = 50 * 1024 * 1024

        with patch("pathlib.Path.stat") as mock_stat:
            mock_stat.return_value = MagicMock(st_size=_50MB)
            with patch("pathlib.Path.read_bytes", return_value=b"x" * 100):
                result = process_single_document(str(ok_file), save_to_file=False)

        # Не должен вернуть ошибку размера
        assert result.get("status") != "error" or "50" not in result.get("error", "")


# ---------------------------------------------------------------------------
# Тесты process_single_document — URL с неподдерживаемым расширением
# ---------------------------------------------------------------------------

class TestProcessSingleDocumentUrlUnsupportedExt:
    def test_url_with_html_extension_returns_error(self, monkeypatch):
        """URL с .html расширением не поддерживается."""
        import agent21_tender_inspector.runner as runner_mod
        from agent21_tender_inspector.runner import process_single_document

        # Мокируем _download_document: возвращает файл с неподдерживаемым расширением
        monkeypatch.setattr(
            runner_mod,
            "_download_document",
            lambda url: (b"<html></html>", "page.html"),
        )

        result = process_single_document("https://example.com/page.html", save_to_file=False)
        assert result["status"] == "error"
        assert ".html" in result["error"]
        assert result["source"] == "https://example.com/page.html"


# ---------------------------------------------------------------------------
# Тесты process_single_document — дедупликация
# ---------------------------------------------------------------------------

class TestProcessSingleDocumentDedup:
    def test_url_dedup_returns_cached_result(self, monkeypatch):
        """Если тот же URL уже обработан, возвращается кэш из БД без вызова агента."""
        from agent21_tender_inspector.runner import process_single_document
        import agent21_tender_inspector.runner as runner_mod
        import shared.database as db_mod

        cached = {"documents": [{"id": 1}], "source_document": "doc.pdf"}
        monkeypatch.setattr(
            db_mod,
            "find_duplicate_job",
            lambda agent, sender, subject: {"result": cached, "created_at": "2024-01-01"},
        )
        monkeypatch.setattr(runner_mod, "FORCE_REPROCESS", False)
        # В URL-ветке скачивание происходит ДО dedup-проверки, поэтому мокируем его:
        monkeypatch.setattr(runner_mod, "_download_document", lambda url: (b"%PDF", "doc.pdf"))
        # create_tender_agent не должен вызываться при хите кэша
        mock_create_agent = MagicMock()
        monkeypatch.setattr(runner_mod, "create_tender_agent", mock_create_agent)

        result = process_single_document("https://example.com/doc.pdf", save_to_file=False)
        assert result == cached
        mock_create_agent.assert_not_called()

    def test_local_dedup_uses_resolved_path(self, tmp_path, monkeypatch):
        """Для локального файла ключ дедупликации — resolved-путь."""
        from agent21_tender_inspector.runner import process_single_document
        import agent21_tender_inspector.runner as runner_mod
        import shared.database as db_mod

        recorded_subjects = []

        def fake_find(agent, sender, subject):
            recorded_subjects.append(subject)
            return None  # нет дублей

        monkeypatch.setattr(db_mod, "find_duplicate_job", fake_find)
        monkeypatch.setattr(db_mod, "create_job", lambda *a, **kw: "job-1")
        monkeypatch.setattr(db_mod, "update_job", lambda *a, **kw: None)
        monkeypatch.setattr(runner_mod, "FORCE_REPROCESS", False)
        monkeypatch.setattr(runner_mod, "_extract_text", lambda d, f: "text")
        monkeypatch.setattr(runner_mod, "create_tender_agent", lambda: MagicMock(
            invoke=MagicMock(return_value={
                "intermediate_steps": [
                    ("generate_document_list", json.dumps({
                        "documents": [],
                        "summary": {"total": 0, "mandatory": 0, "conditional": 0},
                        "procurement_subject": "Тест",
                        "timestamp": "2024-01-01T00:00:00+00:00",
                    }))
                ],
                "output": "",
            })
        ))
        monkeypatch.setattr(runner_mod, "get_langfuse_callback", lambda: None)
        monkeypatch.setattr(runner_mod, "EMAILS_PROCESSED", MagicMock())
        monkeypatch.setattr(runner_mod, "EMAILS_ERRORS", MagicMock())
        monkeypatch.setattr(runner_mod, "notify", lambda *a, **kw: None)

        f = tmp_path / "tender.pdf"
        f.write_bytes(b"%PDF fake")

        process_single_document(str(f), save_to_file=False)

        # Ключ дедупликации должен быть абсолютным путём
        assert len(recorded_subjects) == 1
        assert pathlib.Path(recorded_subjects[0]).is_absolute()

    def test_force_reprocess_skips_dedup(self, tmp_path, monkeypatch, mock_db, mock_extract_text, mock_agent):
        """FORCE_REPROCESS=True обходит дедупликацию."""
        from agent21_tender_inspector.runner import process_single_document
        import agent21_tender_inspector.runner as runner_mod
        import shared.database as db_mod

        monkeypatch.setattr(runner_mod, "FORCE_REPROCESS", True)

        find_spy = MagicMock(return_value=None)
        monkeypatch.setattr(db_mod, "find_duplicate_job", find_spy)

        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF ok")

        with patch("pathlib.Path.read_bytes", return_value=b"%PDF ok"):
            process_single_document(str(f), save_to_file=False)

        find_spy.assert_not_called()
