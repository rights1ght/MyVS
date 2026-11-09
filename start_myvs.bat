@echo off
setlocal
cd /d "%~dp0"
title MyVS

set "PYTHONUTF8=1"
set "MYVS_AUTO_BROWSER=1"

if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON=%~dp0.venv\Scripts\python.exe"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo.
        echo Python not found in PATH.
        echo Install Python 3.11+ and enable "Add Python to PATH".
        echo.
        pause
        exit /b 1
    )
    set "PYTHON=python"
)

echo Starting MyVS...
echo The browser will open automatically.
echo Stop the server with Ctrl+C in this window.
echo.

"%PYTHON%" run.py %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo MyVS exited with code %EXIT_CODE%.
    pause
)
exit /b %EXIT_CODE%
