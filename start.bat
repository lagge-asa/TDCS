@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title TDCS Launcher

set "ROOT=%cd%"
set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
set "PID_FILE=%ROOT%\.tdcs.pid"
set "LOG_DIR=%ROOT%\logs"
set "OUT_LOG=%LOG_DIR%\tdcs.stdout.log"
set "ERR_LOG=%LOG_DIR%\tdcs.stderr.log"
set "PORT=8080"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo.
echo ========================================
echo   TDCS - Timed Data Collection Service
echo ========================================
echo.

if not exist "%PYTHON%" (
    echo [ERROR] Virtual environment not found: %PYTHON%
    echo Run: py -3 -m venv .venv
    pause
    exit /b 1
)
if not exist "%ROOT%\config\config.yaml" (
    echo [ERROR] config\config.yaml not found.
    pause
    exit /b 1
)

rem If 8080 is already listening, reuse the existing healthy service.
powershell -NoProfile -Command "try {$c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',%PORT%); $c.Close(); exit 0} catch {exit 1}" >nul 2>&1
if not errorlevel 1 (
    echo [OK] TDCS is already listening on port %PORT%.
    echo Web UI: http://127.0.0.1:%PORT%
    echo LAN UI: http://192.168.10.25:%PORT%
    start "" "http://127.0.0.1:%PORT%/"
    pause
    exit /b 0
)

rem Do not start a second TDCS instance.
if exist "%PID_FILE%" (
    set /p OLD_PID=<"%PID_FILE%"
    if defined OLD_PID (
        powershell -NoProfile -Command "if (Get-Process -Id !OLD_PID! -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
        if not errorlevel 1 (
            echo [WARN] TDCS is already running, PID !OLD_PID!.
            echo Web UI: http://127.0.0.1:%PORT%
            pause
            exit /b 0
        )
    )
    del /q "%PID_FILE%" >nul 2>&1
)

rem Database password priority: explicit DB_MASTER_PASSWORD, then TDCS_DB_PASSWORD,
rem then the local Docker default from docker-compose.yml.
if not defined DB_MASTER_PASSWORD if defined TDCS_DB_PASSWORD set "DB_MASTER_PASSWORD=%TDCS_DB_PASSWORD%"
if not defined DB_MASTER_PASSWORD set "DB_MASTER_PASSWORD=etl_dev_pass"
if not defined WEB_SECRET_KEY set "WEB_SECRET_KEY=dev_secret_key_change_in_production"

>"%OUT_LOG%" echo [%date% %time%] Starting TDCS
>"%ERR_LOG%" echo [%date% %time%] Startup errors

echo [..] Starting TDCS with the project Python environment...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $p = Start-Process -FilePath '%PYTHON%' -ArgumentList @('-m','src.main') -WorkingDirectory '%ROOT%' -RedirectStandardOutput '%OUT_LOG%' -RedirectStandardError '%ERR_LOG%' -PassThru; $p.Id | Set-Content -NoNewline '%PID_FILE%'" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Could not create the TDCS process. See:
    echo        %ERR_LOG%
    type "%ERR_LOG%"
    pause
    exit /b 1
)
if not exist "%PID_FILE%" (
    echo [ERROR] TDCS PID file was not created.
    type "%ERR_LOG%"
    pause
    exit /b 1
)
echo [OK] TDCS process started, PID !PID!
echo [..] Waiting for port %PORT% ...
set "PORT_OK=0"
for /l %%i in (1,1,30) do (
    powershell -NoProfile -Command "try {$c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',%PORT%); $c.Close(); exit 0} catch {exit 1}" >nul 2>&1
    if not errorlevel 1 (
        set "PORT_OK=1"
        goto :port_ok
    )
    powershell -NoProfile -Command "if (-not (Get-Process -Id !PID! -ErrorAction SilentlyContinue)) { exit 1 } else { exit 0 }" >nul 2>&1
    if errorlevel 1 goto :process_dead
    timeout /t 1 /nobreak >nul
)

:port_ok
if "!PORT_OK!"=="1" (
    rem A listening port is not enough: /health must also report HTTP 200.
    powershell -NoProfile -Command "try {$r=Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:%PORT%/health'; if($r.StatusCode -eq 200){exit 0}else{exit 1}} catch {exit 1}" >nul 2>&1
    if errorlevel 1 (
        echo [WARN] Web port is open, but /health is not ready (often database credentials/schema).
        echo        Check %ERR_LOG%
    ) else (
        echo [OK] TDCS health check passed
    )
    echo [OK] TDCS is listening on 0.0.0.0:%PORT%
    echo Web UI: http://127.0.0.1:%PORT%
    echo LAN UI: http://192.168.10.25:%PORT%
    echo Logs: %OUT_LOG% and %ERR_LOG%
    start "" "http://127.0.0.1:%PORT%/"
) else (
    echo [WARN] Process is still starting. Check logs:
    echo        %OUT_LOG%
    echo        %ERR_LOG%
)
echo.
pause
exit /b 0

:process_dead
echo [ERROR] TDCS stopped during startup.
echo ----- stderr -----
type "%ERR_LOG%"
echo -------------------
del /q "%PID_FILE%" >nul 2>&1
pause
exit /b 1
