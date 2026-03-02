"""
Application logging setup utilities.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_app_logging():
    """Configure app-wide logging to logs/app.log and console."""
    if getattr(sys, "frozen", False):
        project_root = Path(sys.executable).resolve().parent
    else:
        project_root = Path(__file__).resolve().parents[2]
    logs_dir = project_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    log_file = logs_dir / "app.log"

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    if root_logger.handlers:
        return str(log_file)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    def _log_excepthook(exc_type, exc_value, exc_traceback):
        logging.getLogger(__name__).exception(
            "Unhandled exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    sys.excepthook = _log_excepthook

    try:
        import threading

        def _thread_exception_handler(args):
            logging.getLogger(__name__).exception(
                "Unhandled thread exception",
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )

        threading.excepthook = _thread_exception_handler
    except Exception:
        pass

    logging.getLogger(__name__).info("Application logging initialized: %s", log_file)
    return str(log_file)
