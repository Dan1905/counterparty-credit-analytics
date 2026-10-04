"""Central logging configuration (console + rotating file)."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def configure_logging(log_file: Path | None = None, level: int = logging.INFO) -> None:
    """Configure the root logger once; repeated calls are no-ops."""
    root = logging.getLogger()
    if getattr(root, "_ccr_configured", False):
        return
    root.setLevel(level)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(console)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3)
        file_handler.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(file_handler)
    root._ccr_configured = True  # type: ignore[attr-defined]
