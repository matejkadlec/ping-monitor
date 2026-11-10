# PyInstaller spec for dist\PingMonitor.exe: one file, no console window.
# Build it with build.bat (Windows); see README > Building the .exe.
import sys
import tomllib
from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 - provided by PyInstaller
ASSETS = ROOT / "assets"
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def windows_version_info():
    """File properties shown by Explorer and Task Manager ("Ping Monitor")."""
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    numbers = tuple(int(part) for part in VERSION.split("."))
    numbers = numbers + (0,) * (4 - len(numbers))
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("CompanyName", "Matěj Kadlec"),
                StringStruct("FileDescription", "Ping Monitor"),
                StringStruct("FileVersion", VERSION),
                StringStruct("InternalName", "PingMonitor"),
                StringStruct("LegalCopyright", "MIT License"),
                StringStruct("OriginalFilename", "PingMonitor.exe"),
                StringStruct("ProductName", "Ping Monitor"),
                StringStruct("ProductVersion", VERSION),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )


# Everything the app loads at run time (not the README screenshot).
datas = [
    (str(ASSETS / "fonts"), "assets/fonts"),
    (str(ASSETS / "icons"), "assets/icons"),
    (str(ASSETS / "background.png"), "assets"),
    (str(ASSETS / "icon.ico"), "assets"),
]

a = Analysis(  # noqa: F821
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    datas=datas,
    excludes=["tkinter", "unittest", "pydoc", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PingMonitor",
    icon=str(ASSETS / "icon.ico"),
    version=windows_version_info() if sys.platform == "win32" else None,
    console=False,
    upx=False,
    runtime_tmpdir=None,
)
