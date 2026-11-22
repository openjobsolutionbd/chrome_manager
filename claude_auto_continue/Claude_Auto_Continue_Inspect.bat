@echo off
title Claude Auto Continue - Inspect (read-only)
color 0A
setlocal

echo.
echo Open the Claude chat window that shows "Continue" first, then press a key here.
echo This only READS the windows. It does not click or change anything.
echo.
pause

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

py "%~dp0Claude_Auto_Continue_Inspect.py"

endlocal
