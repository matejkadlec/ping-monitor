@echo off
REM Easy Setup Script for Ping Monitor
REM This script sets up everything needed to run the Ping Monitor

echo.
echo ========================================
echo    Ping Monitor Setup Script
echo ========================================
echo.

cd /d "%~dp0"

REM Check for broken virtual environment
if exist "venv" (
    "venv\Scripts\python.exe" --version >nul 2>&1
    if errorlevel 1 (
        echo.
        echo Detected broken virtual environment.
        echo Cleaning up old environment...
        rmdir /s /q "venv"
    )
)

if not exist "venv" (
    echo Creating virtual environment...
    REM Prefer the py launcher, "python" may resolve to the Microsoft Store alias stub
    py -3.14 --version >nul 2>&1
    if not errorlevel 1 (
        py -3.14 -m venv venv
    ) else (
        python -m venv venv
    )
    if not exist "venv\Scripts\python.exe" (
        echo.
        echo Failed to create virtual environment. Please make sure Python 3.14.2 is installed and in your PATH.
        echo If Windows suggests the Microsoft Store, disable the python.exe and python3.exe aliases in
        echo Settings - Apps - Advanced app settings - App execution aliases.
        pause
        exit /b 1
    )
)

echo Installing/Updating required packages...
"venv\Scripts\python.exe" -m pip install --upgrade pip
"venv\Scripts\python.exe" -m pip install --upgrade uv
set "UV_PROJECT_ENVIRONMENT=%CD%\venv"
"venv\Scripts\uv.exe" sync --python "venv\Scripts\python.exe" --frozen --no-dev

if %errorlevel% neq 0 (
    echo.
    echo Failed to install required packages.
    pause
    exit /b 1
)

echo.
echo Testing package imports...
"venv\Scripts\python.exe" -c "import PySide6.QtWidgets, PySide6.QtSvg, PySide6.QtNetwork; print('All packages imported successfully')"

if %errorlevel% neq 0 (
    echo.
    echo Package import test failed. Please check the installation.
    pause
    exit /b 1
)

echo.
echo ========================================
echo Setup completed successfully!
echo ========================================
echo.
echo You can now:
echo 1. Run the application: run.vbs
echo 2. Start the application now (y/n)?
echo.

set /p choice=Start Ping Monitor now? (y/n): 
if /i "%choice%"=="y" goto start_app
if /i "%choice%"=="yes" goto start_app
goto end_setup

:start_app
echo.
echo Starting Ping Monitor ...
cscript //nologo run.vbs
echo.
echo Ping Monitor started! Check your system tray for the icon.
goto final_pause

:end_setup
echo.
echo You can start the Ping Monitor later using:
echo   - run.vbs
goto final_pause

:final_pause

echo.
echo Press any key to exit...
pause >nul
