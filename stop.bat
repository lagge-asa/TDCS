@echo off
echo.
echo ========================================
echo   TDCS - Stop Service
echo ========================================
echo.

cd /d "%~dp0"

:: Stop Docker containers
where docker >nul 2>&1
if not errorlevel 1 (
    docker info >nul 2>&1
    if not errorlevel 1 (
        echo Stopping Docker containers...
        docker-compose down
        echo [OK] Docker containers stopped
    )
)

echo [OK] TDCS service stopped
pause