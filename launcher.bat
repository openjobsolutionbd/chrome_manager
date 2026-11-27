@echo off
title Claude Limit Closer
cd /d "%~dp0"

where py >nul 2>&1
if errorlevel 1 (
    echo Python was not found.
    pause
    exit /b 1
)

py launcher.py
echo.
echo Finished. You can close this window.
pause
