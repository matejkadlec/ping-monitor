@echo off
REM Builds dist\PingMonitor.exe (one file, no console window) with PyInstaller.
REM Uses its own environment in build\env, so the app's venv stays untouched.
setlocal
cd /d "%~dp0"

echo.
echo ========================================
echo    Ping Monitor - building the .exe
echo ========================================
echo.

if not exist "build\env\Scripts\python.exe" (
    echo Creating the build environment...
    REM Prefer the py launcher, "python" may resolve to the Microsoft Store alias stub
    py -3.14 --version >nul 2>&1
    if not errorlevel 1 (
        py -3.14 -m venv build\env
    ) else (
        python -m venv build\env
    )
    if not exist "build\env\Scripts\python.exe" (
        echo Failed to create the build environment. Please make sure Python 3.14 is installed.
        goto failed
    )
)

"build\env\Scripts\python.exe" -m pip install --quiet --upgrade pip uv
if errorlevel 1 goto failed
set "UV_PROJECT_ENVIRONMENT=%CD%\build\env"
"build\env\Scripts\uv.exe" sync --python "build\env\Scripts\python.exe" --frozen --no-dev --group build --inexact
if errorlevel 1 goto failed

"build\env\Scripts\pyinstaller.exe" --noconfirm --clean --distpath dist --workpath build\work packaging\PingMonitor.spec
if errorlevel 1 goto failed
if not exist "dist\PingMonitor.exe" goto failed

echo.
echo Done: dist\PingMonitor.exe
if not defined CI pause
exit /b 0

:failed
echo.
echo Building PingMonitor.exe failed.
if not defined CI pause
exit /b 1
