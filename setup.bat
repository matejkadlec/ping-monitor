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
        echo ⚠️  Detected broken virtual environment.
        echo 🔄 Cleaning up old environment...
        rmdir /s /q "venv"
    )
)

if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo.
        echo ✗ Failed to create virtual environment. Please make sure Python 3.14.2 is installed and in your PATH.
        pause
        exit /b 1
    )
)

echo Installing/Updating required packages...
"venv\Scripts\python.exe" -m pip install --upgrade pip
"venv\Scripts\pip.exe" install -r requirements.txt

echo.
echo Testing package imports...
"venv\Scripts\python.exe" -c "import pystray, PIL, winshell, win32com.client; print('All packages imported successfully')"

if %errorlevel% neq 0 (
    echo.
    echo ✗ Package import test failed. Please check the installation.
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
pause >nul
