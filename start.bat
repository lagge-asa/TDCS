@echo off
setlocal enabledelayedexpansion
title TDCS Launcher

cd /d "%~dp0"
set "PID_FILE=%cd%\.tdcs.pid"

echo.
echo ========================================
echo   TDCS - Timed Data Collection Service
echo ========================================
echo.

:: ── 1. Python ────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+.
    pause & exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo [OK] Python %%v

:: ── 2. venv ──────────────────────────────
if not exist ".venv\Scripts\activate.bat" (
    echo [..] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 ( echo [ERROR] venv creation failed & pause & exit /b 1 )
    echo [OK] venv created
) else (
    echo [OK] venv ready
)
call .venv\Scripts\activate.bat

:: ── 3. dependencies ──────────────────────
pip show PyMySQL >nul 2>&1
if errorlevel 1 (
    echo [..] Installing dependencies...
    pip install -r requirements.txt -q
    if errorlevel 1 ( echo [ERROR] pip install failed & pause & exit /b 1 )
    echo [OK] dependencies installed
) else (
    echo [OK] dependencies ready
)

:: ── 4. config ────────────────────────────
if not exist "config\config.yaml" (
    if exist "config\config.yaml.example" (
        copy "config\config.yaml.example" "config\config.yaml" >nul
        echo [OK] config.yaml created from example
    ) else (
        echo [ERROR] config.yaml.example not found
        pause & exit /b 1
    )
) else (
    echo [OK] config.yaml ready
)

if "%DB_MASTER_PASSWORD%"=="" set "DB_MASTER_PASSWORD=etl_dev_pass"
if "%WEB_SECRET_KEY%"==""    set "WEB_SECRET_KEY=dev_secret_key_change_in_production"

:: ── 5. Docker ────────────────────────────
set "SKIP_DOCKER=1"
where docker >nul 2>&1 && (
    docker info >nul 2>&1 && set "SKIP_DOCKER=0"
)

if "%SKIP_DOCKER%"=="0" (
    echo [..] Starting MySQL + Redis...
    docker-compose up -d mysql redis
    if errorlevel 1 ( echo [WARN] docker-compose failed, continuing anyway... & set SKIP_DOCKER=1 )
)

if "%SKIP_DOCKER%"=="0" (
    echo [..] Waiting for MySQL...
    for /l %%i in (1,1,30) do (
        docker exec etl-mysql mysqladmin ping -h localhost -uroot -proot_dev_only >nul 2>&1
        if not errorlevel 1 goto :mysql_ok
        timeout /t 2 /nobreak >nul
    )
    echo [WARN] MySQL not ready after 60s
    goto :skip_mysql
    :mysql_ok
    echo [OK] MySQL is ready
    :skip_mysql
) else (
    echo [SKIP] Docker not available
)

:: ── 6. Start service ─────────────────────
echo.
echo Starting TDCS on http://127.0.0.1:8080 ...

start "TDCS" /B python -m src.main >nul 2>&1

:: Save PID
powershell -Command "(Get-WmiObject Win32_Process -Filter \"name='python.exe' and commandline like '%%src.main%%'\" | Select-Object -ExpandProperty ProcessId) -join ' '"  > "%PID_FILE%" 2>nul
echo PID saved to %PID_FILE%

:: ── 7. Wait for port ─────────────────────
set "PORT_OK=0"
for /l %%i in (1,1,20) do (
    powershell -Command "try{(New-Object Net.Sockets.TcpClient('127.0.0.1',8080)).Close();exit 0}catch{exit 1}" >nul 2>&1
    if not errorlevel 1 set "PORT_OK=1" & goto :port_ok
    timeout /t 1 /nobreak >nul
)
:port_ok

if "!PORT_OK!"=="1" (
    echo [OK] Service is ready
    start http://127.0.0.1:8080
) else (
    echo [WARN] Service may still be starting, open http://127.0.0.1:8080 manually
)

echo.
echo ───────────────────────────────────────
echo   Web UI:   http://127.0.0.1:8080
echo   Swagger:  http://127.0.0.1:8080/docs
echo   Run stop.bat to shut down
echo ───────────────────────────────────────
echo.

endlocal
