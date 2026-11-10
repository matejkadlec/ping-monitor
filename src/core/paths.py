"""
Filesystem locations used by the app.

* Running from source: resources come from the project folder, settings and
  logs live in ``<project>/logs`` (same place as before the PySide6 rewrite).
* Running as a frozen executable (PyInstaller): resources come from the bundle,
  settings and logs live in ``%LOCALAPPDATA%\\PingMonitor``.
* ``PING_MONITOR_DATA_DIR`` overrides the data folder (tests, screenshots).
"""

import os
import sys
from pathlib import Path

APP_NAME = "Ping Monitor"
APP_ID = "PingMonitor"
# Windows AppUserModelID (taskbar grouping + notification identity).
APP_USER_MODEL_ID = "matka.pingmonitor.2"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    """Folder that contains the bundled ``assets`` directory."""
    if is_frozen():
        bundle_dir = getattr(sys, "_MEIPASS", None)
        return Path(bundle_dir) if bundle_dir else Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def assets_dir() -> Path:
    return project_root() / "assets"


def asset_path(*parts: str) -> Path:
    return assets_dir().joinpath(*parts)


def data_dir() -> Path:
    """Writable folder for settings and logs (created on demand)."""
    override = os.environ.get("PING_MONITOR_DATA_DIR")
    if override:
        path = Path(override)
    elif is_frozen():
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        path = Path(base) / APP_ID
    else:
        path = project_root() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path
