@echo off
title Claude Auto Continue
color 0A
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

py -c "import uiautomation" >nul 2>&1
if errorlevel 1 (
    echo uiautomation is missing. Installing it now...
    py -m pip install uiautomation
    if errorlevel 1 (
        echo uiautomation installation failed.
        pause
        exit /b 1
    )
)

py "%~dp0Claude_Auto_Continue.py"

endlocal
