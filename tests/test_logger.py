"""
Тесты для shared/logger.py.
Проверяют:
- нормальный сценарий (файловый хендлер создаётся)
- fallback на stdout при PermissionError
- отсутствие дублирования хендлеров при повторном вызове
- уважение переменной окружения LOG_DIR
"""

import logging
import os
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def reset_logging():
    """Сбрасываем состояние логгеров между тестами."""
    yield
    for name in ("test_normal", "test_permission", "test_dedup", "test_logdir"):
        log = logging.getLogger(name)
        log.handlers.clear()


def test_logger_creates_file_handler(tmp_path):
    """При наличии прав файловый хендлер должен быть добавлен."""
    with patch.dict(os.environ, {"LOG_DIR": str(tmp_path)}):
        from shared.logger import setup_logger

        logger = setup_logger("test_normal")

    handler_types = [type(h).__name__ for h in logger.handlers]
    assert "RotatingFileHandler" in handler_types
    assert "StreamHandler" in handler_types


def test_logger_fallback_on_permission_error(tmp_path):
    """При PermissionError логгер должен работать только через stdout."""
    with patch(
        "shared.logger.RotatingFileHandler",
        side_effect=PermissionError("[Errno 13] Permission denied"),
    ):
        with patch.dict(os.environ, {"LOG_DIR": str(tmp_path)}):
            from shared.logger import setup_logger

            with pytest.warns(UserWarning, match="Cannot write log file"):
                logger = setup_logger("test_permission")

    handler_types = [type(h).__name__ for h in logger.handlers]
    assert "RotatingFileHandler" not in handler_types
    assert "StreamHandler" in handler_types


def test_logger_no_duplicate_handlers(tmp_path):
    """Повторный вызов setup_logger не должен дублировать хендлеры."""
    with patch.dict(os.environ, {"LOG_DIR": str(tmp_path)}):
        from shared.logger import setup_logger

        logger1 = setup_logger("test_dedup")
        handler_count_first = len(logger1.handlers)
        logger2 = setup_logger("test_dedup")
        handler_count_second = len(logger2.handlers)

    assert logger1 is logger2
    assert handler_count_first == handler_count_second


def test_logger_respects_log_dir_env(tmp_path):
    """LOG_DIR из окружения должен использоваться для пути к файлу."""
    custom_dir = tmp_path / "custom_logs"
    with patch.dict(os.environ, {"LOG_DIR": str(custom_dir)}):
        from shared.logger import setup_logger

        setup_logger("test_logdir")

    assert (custom_dir / "test_logdir.log").exists()
