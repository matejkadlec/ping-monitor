"""
Application logging: rotating ``app.log`` in the data folder (+ console when available).
"""

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.core.paths import data_dir

LOG_FILE_NAME = "app.log"


def configure_logging(level: int = logging.INFO) -> Path:
    log_file = data_dir() / LOG_FILE_NAME
    root = logging.getLogger()
    if getattr(configure_logging, "_done", False):
        return log_file
    configure_logging._done = True  # type: ignore[attr-defined]

    root.setLevel(level)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(threadName)s | %(name)s | %(message)s")
    file_handler = RotatingFileHandler(log_file, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    if sys.stderr is not None:  # pythonw.exe has no console
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        root.addHandler(console)

    def log_exception(exc_type, exc_value, exc_traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logging.getLogger("unhandled").error("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))

    def log_thread_exception(args: threading.ExceptHookArgs) -> None:
        logging.getLogger("unhandled").error(
            "Unhandled exception in thread %s", args.thread.name if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = log_exception
    threading.excepthook = log_thread_exception
    logging.getLogger(__name__).info("Logging to %s", log_file)
    return log_file
