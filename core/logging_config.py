"""Local application logging for diagnostics and support."""

from __future__ import annotations

import logging
from pathlib import Path

from db.database import PROJECT_ROOT


def configure_app_logging() -> logging.Logger:
    """Write application errors to both the terminal and logs/app.log."""
    log_directory = PROJECT_ROOT / "logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("learning_path")
    logger.setLevel(logging.ERROR)
    logger.propagate = False

    target = (log_directory / "app.log").resolve()
    if not any(
        isinstance(handler, logging.FileHandler)
        and Path(handler.baseFilename).resolve() == target
        for handler in logger.handlers
    ):
        file_handler = logging.FileHandler(target, encoding="utf-8")
        file_handler.setLevel(logging.ERROR)
        logger.addHandler(file_handler)
    if not any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
        for handler in logger.handlers
    ):
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.ERROR)
        logger.addHandler(stream_handler)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    for handler in logger.handlers:
        handler.setFormatter(formatter)
    return logger
