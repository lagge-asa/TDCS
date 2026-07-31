$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$python = Join-Path $root '.venv\Scripts\python.exe'
$config = Join-Path $root 'config\config.yaml'
$logDir = Join-Path $root 'logs'
$outLog = Join-Path $logDir 'tdcs.stdout.log'
$errLog = Join-Path $logDir 'tdcs.stderr.log'
$pidFile = Join-Path $root '.tdcs.pid'
$port = 8080

if (-not (Test-Path $python)) { throw "Virtual environment not found: $python" }
if (-not (Test-Path $config)) { throw "Config file not found: $config" }
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Test-Healthy {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port/health" -TimeoutSec 3
        return $response.StatusCode -eq 200 -and $response.Content -match '"status":"ok"'
    } catch { return $false }
}

function Test-Port {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect('127.0.0.1', $port)
        $client.Close()
        return $true
    } catch { return $false }
}

if (Test-Healthy) {
    Write-Host "[OK] TDCS is already listening and healthy on port $port."
    Write-Host "Web UI: http://127.0.0.1:$port"
    Write-Host "LAN UI: http://192.168.10.25:$port"
    exit 0
}

# Remove stale TDCS processes before every restart. This prevents two Python
# processes from sharing the same port/PID state.
$tdcsProcesses = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'src\.main' }
foreach ($item in $tdcsProcesses) {
    Stop-Process -Id $item.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Milliseconds 500

# The local Docker compose file defines this development password. Prefer an
# explicitly supplied TDCS_DB_PASSWORD; do not reuse stale DB_MASTER_PASSWORD.
if ($env:TDCS_DB_PASSWORD) { $env:DB_MASTER_PASSWORD = $env:TDCS_DB_PASSWORD }
else { $env:DB_MASTER_PASSWORD = 'etl_dev_pass' }
if (-not $env:WEB_SECRET_KEY) { $env:WEB_SECRET_KEY = 'dev_secret_key_change_in_production' }
$env:PYTHONPATH = $root

# Refuse to start if another application still owns 8080.
$listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    throw "Port $port is still occupied by PID $($listener[0].OwningProcess)."
}

Set-Content -Path $outLog -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Starting TDCS" -Encoding UTF8
Set-Content -Path $errLog -Value '' -Encoding UTF8
Write-Host '[..] Starting TDCS with the project Python environment...'

$process = Start-Process -FilePath $python -ArgumentList @('-m', 'src.main') -WorkingDirectory $root `
    -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru
Set-Content -Path $pidFile -Value $process.Id -NoNewline
Write-Host "[OK] TDCS process started, PID $($process.Id)"

for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    if ($process.HasExited) {
        Write-Host '[ERROR] TDCS stopped during startup.' -ForegroundColor Red
        Get-Content $errLog -ErrorAction SilentlyContinue
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
        exit 1
    }
    if (Test-Healthy) {
        Write-Host '[OK] TDCS health check passed'
        Write-Host '[OK] TDCS is listening on 0.0.0.0:8080'
        Write-Host 'Web UI: http://127.0.0.1:8080'
        Write-Host 'LAN UI: http://192.168.10.25:8080'
        exit 0
    }
    if ($i -eq 4 -and (Test-Port)) {
        Write-Host '[WARN] Port 8080 is open, but database health is not ready.' -ForegroundColor Yellow
    }
}

if (Test-Port) {
    Write-Host '[WARN] TDCS is running, but /health reports database failure. Check:' -ForegroundColor Yellow
} else {
    Write-Host '[ERROR] TDCS did not open port 8080. Check:' -ForegroundColor Red
}
