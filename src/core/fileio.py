"""
Crash-safe file writes.
"""

import os
import tempfile
import time
from pathlib import Path

REPLACE_ATTEMPTS = 5


def atomic_write_text(path: Path, text: str) -> None:
    """Write via a temp file + fsync + replace.

    A crash never leaves a half-written file, and short-lived locks held by
    antivirus scanners or sync clients on Windows are retried.
    """
    path = Path(path)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(REPLACE_ATTEMPTS):
            try:
                os.replace(temp_name, path)
                return
            except PermissionError:
                if attempt == REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(0.1 * (attempt + 1))
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
