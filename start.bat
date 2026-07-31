@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title TDCS Launcher

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" (
    echo [ERROR] TDCS startup failed with code %EXIT_CODE%.
)
pause
exit /b %EXIT_CODE%
