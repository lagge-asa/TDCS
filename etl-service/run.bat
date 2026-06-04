@echo off
echo ========================================
echo   TDCS Launcher
echo ========================================
echo.

cd /d "%~dp0"

echo [1/6] Checking Python...
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+
    pause
    exit /b 1
)

python --version 2>&1 >tmp_py_ver.txt
set /p PYVER=<tmp_py_ver.txt
del tmp_py_ver.txt >nul 2>&1
echo [OK] %PYVER%

echo [2/6] Checking Docker...
where docker >nul 2>&1
if errorlevel 1 (
    echo [WARN] Docker not found, skip infra
    set SKIP_DOCKER=1
) else (
    docker info >nul 2>&1
    if errorlevel 1 (
        echo [WARN] Docker not running, skip infra
        set SKIP_DOCKER=1
    ) else (
        echo [OK] Docker ready
        set SKIP_DOCKER=0
    )
)

echo [3/6] Setup venv...
if not exist ".venv\Scripts\activate.bat" (
    echo     Creating venv...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create venv
        pause
        exit /b 1
    )
    echo [OK]
) else (
    echo [OK]
)
call .venv\Scripts\activate.bat

echo [4/6] Check deps...
pip show PyMySQL >nul 2>&1
if errorlevel 1 (
    echo     Installing (first run, slow)...
    pip install -r requirements.txt -q
    if errorlevel 1 (
        echo [ERROR] pip install failed
        pause
        exit /b 1
    )
    echo [OK]
) else (
    echo [OK]
)

echo [5/6] Check config...
if not exist "config\config.yaml" (
    if exist "config\config.yaml.example" (
        copy "config\config.yaml.example" "config\config.yaml" >nul
        echo [OK] Created from example
    ) else (
        echo [ERROR] Missing config.yaml.example
        pause
        exit /b 1
    )
) else (
    echo [OK] Found
)

if "%DB_MASTER_PASSWORD%"=="" set DB_MASTER_PASSWORD=etl_dev_pass
if "%WEB_SECRET_KEY%"=="" set WEB_SECRET_KEY=dev_secret_key

if "%SKIP_DOCKER%"=="0" (
    echo [6/6] Start Docker...
    docker-compose up -d mysql redis
    if errorlevel 1 (
        echo [ERROR] docker-compose failed
        pause
        exit /b 1
    )

    echo     Waiting MySQL (60s max)...
    set MYSQL_OK=0
    for /l %%i in (1,1,30) do (
        if !MYSQL_OK!==0 (
            docker exec etl-service-mysql-1 mysqladmin ping -ulocalhost -uroot -proot_dev_only >nul 2>&1
            if not errorlevel 1 set MYSQL_OK=1
            if !MYSQL_OK!==0 timeout /t 2 /nobreak >nul
        )
    )
    if !MYSQL_OK!==0 echo [WARN] MySQL timeout, continue anyway
    if !MYSQL_OK!==1 echo [OK] MySQL ready
) else (
    echo [6/6] Skip Docker
)

echo.
echo ========================================
echo   All ready! Starting TDCS now.
echo   Web:  http://127.0.0.1:8080
echo ========================================

start "TDCS" python -m src.main

echo.
echo Waiting for port 8080...
set PORT_OK=0
for /l %%i in (1,1,30) do (
    if !PORT_OK!==0 (
        powershell -Command "try{(New-Object Net.Sockets.TcpClient('127.0.0.1',8080)).Close();exit 0}catch{exit 1}" >nul 2>&1
        if not errorlevel 1 set PORT_OK=1
        if !PORT_OK!==0 timeout /t 1 /nobreak >nul
    )
)

if !PORT_OK!==1 (
    echo [OK] Open browser...
    start http://127.0.0.1:8080
) else (
    echo [WARN] Port 8080 not ready, open manually: http://127.0.0.1:8080
)

echo.
echo ========================================
echo Service running. Press key to stop.
echo ========================================
pause >nul

taskkill /F /FI "WINDOWTITLE eq TDCS" >nul 2>&1
if "%SKIP_DOCKER%"=="0" docker-compose down >nul 2>&1
echo.
echo Bye!
pause
