@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title TDCS Stopper

set "ROOT=%cd%"
set "PID_FILE=%ROOT%\.tdcs.pid"

echo.
echo ========================================
echo   TDCS - Stop Service
echo ========================================
echo.

set "STOPPED=0"
if exist "%PID_FILE%" (
    set /p PID=<"%PID_FILE%"
    if defined PID (
        powershell -NoProfile -Command "if (Get-Process -Id !PID! -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
        if not errorlevel 1 (
            echo [..] Stopping TDCS, PID !PID! ...
            powershell -NoProfile -Command "$p=Get-Process -Id !PID! -ErrorAction SilentlyContinue; if($p){$p.CloseMainWindow() | Out-Null; Start-Sleep -Seconds 2; if(-not $p.HasExited){$p.Kill()}}" >nul 2>&1
            set "STOPPED=1"
        )
    )
    del /q "%PID_FILE%" >nul 2>&1
)

rem Fallback: stop only processes whose command line is this project's src.main.
powershell -NoProfile -Command "$root=[regex]::Escape('%ROOT%'); Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object {$_.CommandLine -match $root -and $_.CommandLine -match 'src\.main'} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

if "!STOPPED!"=="1" (
    echo [OK] TDCS service stopped.
) else (
    echo [OK] No running TDCS process found.
)
echo.
echo TDCS shut down complete.
echo.
pause
exit /b 0
