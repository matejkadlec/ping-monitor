"""
Small Windows integrations (all no-ops elsewhere):

* dark title bar tinted to the app background (Windows 10 2004+ / Windows 11),
* taskbar identity (AppUserModelID) and the sender name + icon of notifications,
* the OS "Animation effects" preference,
* a native message box for fatal start-up errors (works without Qt).
"""

import ctypes
import logging
import sys

LOGGER = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36
SPI_GETCLIENTAREAANIMATION = 0x1042


def _colorref(hex_color: str) -> int:
    value = hex_color.lstrip("#")
    red, green, blue = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    return red | (green << 8) | (blue << 16)


def set_app_user_model_id(app_id: str) -> None:
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        LOGGER.debug("SetCurrentProcessExplicitAppUserModelID failed", exc_info=True)


def register_app_identity(app_id: str, display_name: str, icon, data_folder) -> None:
    """Windows names the sender of a notification after the AppUserModelID; for
    an app that is not installed it shows the raw ID unless the ID is registered
    under HKCU\\Software\\Classes\\AppUserModelId with a name and an icon."""
    if not IS_WINDOWS:
        return
    try:
        import shutil
        import winreg
        from pathlib import Path

        icon_copy = Path(data_folder) / "icon.ico"  # the exe's bundle lives in a temporary folder
        if Path(icon).exists() and not icon_copy.exists():
            shutil.copyfile(icon, icon_copy)
        key_path = rf"Software\Classes\AppUserModelId\{app_id}"
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, display_name)
            if icon_copy.exists():
                winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, str(icon_copy))
    except OSError:
        LOGGER.debug("Registering the notification identity failed", exc_info=True)


def style_title_bar(window_id: int, caption: str, text: str, border: str) -> None:
    """Dark mode title bar; on Windows 11 also exact caption/text/border colors."""
    if not IS_WINDOWS:
        return
    try:
        from ctypes import wintypes

        dwm = ctypes.WinDLL("dwmapi")
        set_attribute = dwm.DwmSetWindowAttribute
        set_attribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        set_attribute.restype = ctypes.c_long
        hwnd = wintypes.HWND(window_id)

        enabled = ctypes.c_int(1)
        for attribute in (DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD):
            if set_attribute(hwnd, attribute, ctypes.byref(enabled), ctypes.sizeof(enabled)) == 0:
                break
        for attribute, color in ((DWMWA_CAPTION_COLOR, caption), (DWMWA_TEXT_COLOR, text),
                                 (DWMWA_BORDER_COLOR, border)):
            value = ctypes.c_uint32(_colorref(color))
            set_attribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value))  # Windows 11 only
    except Exception:
        LOGGER.debug("Styling the title bar failed", exc_info=True)


def animations_enabled() -> bool:
    """False when the user turned off "Animation effects" in Windows settings."""
    if not IS_WINDOWS:
        return True
    try:
        from ctypes import wintypes

        value = wintypes.BOOL(True)
        if ctypes.windll.user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(value), 0):
            return bool(value.value)
    except Exception:
        LOGGER.debug("Reading animation preference failed", exc_info=True)
    return True


def message_box(title: str, text: str) -> None:
    """Show an error dialog even when Qt itself failed to load."""
    if IS_WINDOWS:
        try:
            MB_ICONERROR = 0x10
            MB_SETFOREGROUND = 0x10000
            ctypes.windll.user32.MessageBoxW(None, text, title, MB_ICONERROR | MB_SETFOREGROUND)
            return
        except Exception:
            pass
    print(f"{title}: {text}", file=sys.stderr)
