@echo off
setlocal
cd /d "%~dp0"
title DZMM Card Exporter

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    echo Install Python 3.10+ from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during setup.
    echo.
    pause
    exit /b 1
)

python -c "import webview" >nul 2>nul
if errorlevel 1 (
    echo [SETUP] pywebview not found. Installing (first run only)...
    python -m pip install --upgrade pip >nul 2>nul
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [ERROR] pip install failed. Try manually:
        echo     python -m pip install pywebview
        echo.
        pause
        exit /b 1
    )
)

python app.py
if errorlevel 1 (
    echo.
    echo [ERROR] app.py exited with an error - see messages above.
    echo Run "python app.py --selftest" to check your environment.
    echo.
    pause
)
endlocal
