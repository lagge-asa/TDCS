@echo off
echo.
echo ========================================
echo   TDCS - Stop Service
echo ========================================
echo.

cd /d "%~dp0"
set "PID_FILE=%cd%\.tdcs.pid"

:: ── Stop Python process via PID file ─────
if exist "%PID_FILE%" (
    echo [..] Stopping TDCS process...
    set /p PIDS=<"%PID_FILE%"
    if not "!PIDS!"=="" (
        for %%p in (!PIDS!) do (
            taskkill /PID %%p /F >nul 2>&1
        )
    )
    del "%PID_FILE%" >nul 2>&1
    echo [OK] Service stopped
) else (
    echo [..] No PID file found, trying window title fallback...
    taskkill /F /FI "WINDOWTITLE eq TDCS" >nul 2>&1
    echo [OK] Done
)

:: ── Stop Docker containers ───────────────
where docker >nul 2>&1 && (
    docker info >nul 2>&1 && (
        echo [..] Stopping Docker containers...
        docker-compose down >nul 2>&1
        echo [OK] Containers stopped
    )
)

echo.
echo TDCS shut down complete.
echo.
pause
