@echo off
title Stop All
color 0C
setlocal

where py >nul 2>&1
if errorlevel 1 (
    echo Python was not found.
    pause
    exit /b 1
)

py -c "import psutil" >nul 2>&1
if errorlevel 1 (
    echo psutil is missing. Installing it now...
    py -m pip install psutil
    if errorlevel 1 (
        echo psutil installation failed.
        pause
        exit /b 1
    )
)

py "%~dp0Stop_All.py"

endlocal
