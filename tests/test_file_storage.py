"""Tests for shared/file_storage.py — file storage for tender documents."""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

from shared.file_storage import FileStorage


class TestFileStorage:
    def test_create_folder_structure_sync(self, tmp_path):
        storage = FileStorage(str(tmp_path))
        participants = [
            {"name": "АО «Ромашка»", "inn": "7702365551"},
            {"name": "ООО «Гвоздика»", "inn": "7704565559"},
        ]
        result = storage._create_folder_structure_sync("3115-ДИТ-Сервер", participants)
        assert len(result) == 2
        for _name, folder in result.items():
            assert os.path.isdir(folder)
            assert "ТО 3115-ДИТ-Сервер" in folder
            assert "Предложения" in folder
            assert "Документы участника ТО" in folder

    def test_create_folder_structure_async(self, tmp_path):
        storage = FileStorage(str(tmp_path))
        participants = [{"name": "Test Company"}]
        result = asyncio.get_event_loop().run_until_complete(
            storage.create_folder_structure("TEST-ID", participants)
        )
        assert len(result) == 1
        assert os.path.isdir(list(result.values())[0])

    def test_save_document_sync(self, tmp_path):
        storage = FileStorage(str(tmp_path))
        folder = str(tmp_path / "docs")
        path = storage._save_document_sync(folder, "test.pdf", b"content")
        assert os.path.exists(path)
        assert Path(path).read_bytes() == b"content"

    def test_save_document_async(self, tmp_path):
        storage = FileStorage(str(tmp_path))
        folder = str(tmp_path / "docs")
        path = asyncio.get_event_loop().run_until_complete(
            storage.save_document(folder, "test.txt", b"hello")
        )
        assert os.path.exists(path)
        assert Path(path).read_bytes() == b"hello"

    def test_safe_filename(self):
        assert FileStorage._safe_filename("test/file:name*?.txt") == "test_file_name__.txt"
        assert FileStorage._safe_filename("normal.pdf") == "normal.pdf"
        assert FileStorage._safe_filename("file<>|.doc") == "file___.doc"

    def test_creates_nested_dirs(self, tmp_path):
        storage = FileStorage(str(tmp_path))
        folder = str(tmp_path / "a" / "b" / "c")
        path = storage._save_document_sync(folder, "deep.txt", b"deep")
        assert os.path.exists(path)

    def test_default_base_path(self):
        storage = FileStorage()
        assert storage.base_path == Path("./storage")

    def test_custom_base_path(self, tmp_path):
        storage = FileStorage(str(tmp_path / "custom"))
        assert storage.base_path == tmp_path / "custom"
