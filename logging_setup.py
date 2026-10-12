"""Configure Scooty Scout's terminal and rotating file logs."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(log_path: str | Path = "botlog.log") -> logging.Logger:
    """Set up the application logger once and return it."""
    logger = logging.getLogger("scooty_scout")
    if any(handler.name == "scooty_scout_file" for handler in logger.handlers):
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = RotatingFileHandler(
        log_path, maxBytes=10_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.set_name("scooty_scout_file")
    file_handler.setFormatter(formatter)
    terminal = logging.StreamHandler()
    terminal.set_name("scooty_scout_terminal")
    terminal.setFormatter(formatter)
    logger.addHandler(terminal)
    logger.addHandler(file_handler)
    return logger
