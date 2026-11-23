@echo off
title Start All
color 0A
setlocal

echo.
echo ==========================================================
echo    START ALL  (Chrome Opener + Claude Auto Continue)
echo ==========================================================
echo.

tasklist /FI "IMAGENAME eq chrome.exe" 2>nul | find /I "chrome.exe" >nul
if not errorlevel 1 (
    echo Chrome is already running. For all profile windows to stay readable,
    echo Chrome must be restarted by this tool.
    echo.
    echo  Chrome will be CLOSED in 10 seconds. Press N to keep it open.
    choice /C YN /T 10 /D Y /M "Close Chrome now"
    if errorlevel 2 (
        echo Chrome was left open. Windows hidden behind others may not work.
    ) else (
        taskkill /IM chrome.exe >nul 2>&1
        timeout /t 4 /nobreak >nul
        taskkill /F /IM chrome.exe >nul 2>&1
        timeout /t 2 /nobreak >nul
    )
)

echo Starting Chrome Opener...
start "Chrome Opener" "%~dp0Chrome_Opener.bat"

echo Waiting 20 seconds for the profile windows to open...
timeout /t 20 /nobreak >nul

echo Starting Claude Auto Continue...
start "Claude Auto Continue" "%~dp0claude_auto_continue\Claude_Auto_Continue.bat"

echo.
echo Both tools are running in their own windows. You can close this window.
timeout /t 5 /nobreak >nul
endlocal
