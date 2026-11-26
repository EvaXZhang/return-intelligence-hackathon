"""Sanitized local rotating logging."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(path: Path) -> logging.Logger:
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("return_intelligence")
    if not logger.handlers:
        handler = RotatingFileHandler(path, maxBytes=500_000, backupCount=2)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
