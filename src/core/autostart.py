"""
"Start with Windows": a value under HKCU\\...\\CurrentVersion\\Run.

The registry is the source of truth, so the setting stays correct even if the
user removes the entry in Task Manager's "Startup apps".
"""

import logging
import sys
from pathlib import Path

from src.core.paths import APP_ID, is_frozen, project_root

LOGGER = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = APP_ID
MINIMIZED_FLAG = "--minimized"


def is_supported() -> bool:
    return sys.platform == "win32"


def launch_command() -> str:
    """Command that starts the app hidden in the tray."""
    if is_frozen():
        return f'"{Path(sys.executable).resolve()}" {MINIMIZED_FLAG}'
    executable = Path(sys.executable).resolve()
    windowless = executable.with_name("pythonw.exe")
    if windowless.exists():
        executable = windowless
    script = project_root() / "main.py"
    return f'"{executable}" "{script}" {MINIMIZED_FLAG}'


def is_enabled() -> bool:
    if not is_supported():
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _kind = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(str(value).strip())
    except FileNotFoundError:
        return False
    except OSError:
        LOGGER.exception("Reading the autostart entry failed")
        return False


def set_enabled(enabled: bool) -> None:
    """Create or remove the Run entry (raises OSError when the registry refuses)."""
    if not is_supported():
        return
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, launch_command())
            LOGGER.info("Autostart enabled: %s", launch_command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
                LOGGER.info("Autostart disabled")
            except FileNotFoundError:
                pass
