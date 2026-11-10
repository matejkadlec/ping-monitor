"""
"Start with Windows": a value under HKCU\\...\\CurrentVersion\\Run.

The registry is the source of truth, so the setting stays correct when the user
changes it outside the app:

* removing the entry, or
* switching it off in Task Manager / Settings > Apps > Startup, which keeps the
  Run value but marks it disabled under ...\\Explorer\\StartupApproved\\Run
  (first byte odd: 03 00 00 00 + time; 02 00 ... means enabled).
"""

import logging
import sys
from pathlib import Path

from src.core.paths import APP_ID, is_frozen, project_root

LOGGER = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
VALUE_NAME = APP_ID
MINIMIZED_FLAG = "--minimized"


class _WindowsRegistry:
    """HKEY_CURRENT_USER values (tests swap this for a dictionary)."""

    def read(self, path: str, name: str):
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ) as key:
                return winreg.QueryValueEx(key, name)[0]
        except FileNotFoundError:
            return None

    def write_string(self, path: str, name: str, value: str) -> None:
        import winreg

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    def delete(self, path: str, name: str) -> None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass


registry = _WindowsRegistry()


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


def _disabled_in_windows(approved) -> bool:
    return isinstance(approved, (bytes, bytearray)) and len(approved) > 0 and approved[0] & 1 == 1


def is_enabled() -> bool:
    if not is_supported():
        return False
    try:
        command = registry.read(RUN_KEY, VALUE_NAME)
        if not command or not str(command).strip():
            return False
        return not _disabled_in_windows(registry.read(APPROVED_KEY, VALUE_NAME))
    except OSError:
        LOGGER.exception("Reading the autostart entry failed")
        return False


def set_enabled(enabled: bool) -> None:
    """Create or remove the entry (raises OSError when the registry refuses)."""
    if not is_supported():
        return
    if enabled:
        registry.write_string(RUN_KEY, VALUE_NAME, launch_command())
        registry.delete(APPROVED_KEY, VALUE_NAME)  # undo "Disabled" from Task Manager
        LOGGER.info("Autostart enabled: %s", launch_command())
    else:
        registry.delete(RUN_KEY, VALUE_NAME)
        registry.delete(APPROVED_KEY, VALUE_NAME)
        LOGGER.info("Autostart disabled")


def refresh() -> None:
    """On start: point an enabled entry at this copy of the app (the folder may
    have moved or the venv been recreated since it was turned on)."""
    if not is_enabled():
        return
    command = launch_command()
    if registry.read(RUN_KEY, VALUE_NAME) != command:
        registry.write_string(RUN_KEY, VALUE_NAME, command)
        LOGGER.info("Autostart entry updated: %s", command)
