@echo off
setlocal enabledelayedexpansion
echo TDCS Start Script
echo.

cd /d "%~dp0"

echo Step 1: Checking Python...
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found
    pause
    exit /b 1
)
echo OK: Python found

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo Python version: %PYVER%

echo.
echo Step 2: Checking Docker...
where docker >nul 2>&1
if errorlevel 1 (
    echo Docker not found - will skip MySQL/Redis
    set SKIP_DOCKER=1
) else (
    docker info >nul 2>&1
    if errorlevel 1 (
        echo Docker not running - will skip MySQL/Redis
        set SKIP_DOCKER=1
    ) else (
        echo OK: Docker found
        set SKIP_DOCKER=0
    )
)

echo.
echo Step 3: Setup virtual environment...
if not exist ".venv\Scripts\activate.bat" (
    echo Creating venv...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: venv creation failed
        pause
        exit /b 1
    )
    echo OK: venv created
) else (
    echo OK: venv exists
)
call .venv\Scripts\activate.bat

echo.
echo Step 4: Checking dependencies...
pip show PyMySQL >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    pip install -r requirements.txt -q
    if errorlevel 1 (
        echo ERROR: pip install failed
        pause
        exit /b 1
    )
    echo OK: dependencies installed
) else (
    echo OK: dependencies ready
)

echo.
echo Step 5: Setup config...
if not exist "config\config.yaml" (
    if exist "config\config.yaml.example" (
        copy "config\config.yaml.example" "config\config.yaml" >nul
        echo OK: config.yaml created from example
    ) else (
        echo ERROR: config.yaml.example not found
        pause
        exit /b 1
    )
) else (
    echo OK: config.yaml exists
)

if "%DB_MASTER_PASSWORD%"=="" set DB_MASTER_PASSWORD=etl_dev_pass
if "%WEB_SECRET_KEY%"=="" set WEB_SECRET_KEY=dev_secret_key

if "%SKIP_DOCKER%"=="0" (
    echo.
    echo Step 6: Starting Docker containers...
    docker-compose up -d mysql redis
    if errorlevel 1 (
        echo ERROR: docker-compose up failed
        pause
        exit /b 1
    )
    echo OK: Docker containers started

    echo.
    echo Step 7: Waiting MySQL to be ready...
    set MYSQL_OK=0
    for /l %%i in (1,1,30) do (
        if !MYSQL_OK!==0 (
            docker exec etl-mysql mysqladmin ping -h localhost -uroot -proot_dev_only >nul 2>&1
            if not errorlevel 1 set MYSQL_OK=1
            if !MYSQL_OK!==0 (
                echo     ...waiting for MySQL (%%i/30)
                timeout /t 2 /nobreak >nul
            )
        )
    )
    if !MYSQL_OK!==1 (
        echo OK: MySQL is ready
    ) else (
        echo WARN: MySQL not ready yet, continuing anyway...
    )
) else (
    echo Step 6: Skipped Docker containers (not available)
)

echo.
echo All checks passed.
echo.
echo Starting service in background...

start "TDCS Service" python -m src.main

echo.
echo Waiting for port 8080...
set PORT_OK=0
for /l %%i in (1,1,30) do (
    if !PORT_OK!==0 (
        powershell -Command "try{(New-Object Net.Sockets.TcpClient('127.0.0.1',8080)).Close();exit 0}catch{exit 1}" >nul 2>&1
        if not errorlevel 1 set PORT_OK=1
        if !PORT_OK!==0 (
            echo     ...waiting for service (%%i/30)
            timeout /t 1 /nobreak >nul
        )
    )
)

if !PORT_OK!==1 (
    echo OK: Service is ready
) else (
    echo WARN: Service may not be ready yet
)

if !PORT_OK!==1 (
    echo.
    echo Opening browser...
    start http://127.0.0.1:8080
)

echo.
echo ========================================
echo TDCS is running. Press any key to stop.
echo ========================================
pause >nul

taskkill /F /FI "WINDOWTITLE eq TDCS Service" >nul 2>&1
if "%SKIP_DOCKER%"=="0" (
    echo.
    echo Stopping Docker containers...
    docker-compose down >nul 2>&1
)
echo.
echo TDCS stopped.
pause
