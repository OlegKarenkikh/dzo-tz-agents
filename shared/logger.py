import logging
import os
import warnings
from logging.handlers import RotatingFileHandler


def setup_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # Избегаем дублирования хендлеров
    logger.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    log_dir = os.environ.get("LOG_DIR", "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        fh = RotatingFileHandler(
            os.path.join(log_dir, f"{name}.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except (PermissionError, OSError) as exc:
        warnings.warn(
            f"[logger] Cannot write log file for '{name}': {exc}. Falling back to stdout only.",
            stacklevel=2,
        )

    return logger
