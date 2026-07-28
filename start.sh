#!/usr/bin/env bash
# ============================================================
# TDCS 一键启动脚本 (Linux/macOS)
# 用法: ./start.sh
# ============================================================

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
cd "$(dirname "$0")"
PID_FILE="$PWD/.tdcs.pid"

ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
step() { echo -e "${CYAN}[..]${NC} $*"; }

echo ""
echo "========================================"
echo "  TDCS - Timed Data Collection Service"
echo "========================================"
echo ""

# ── 1. Python ─────────────────────────────
if command -v python3 &>/dev/null; then PYTHON=python3; else PYTHON=python; fi
$PYTHON --version &>/dev/null || err "Python not found. Install Python 3.10+."
ok "Python $($PYTHON --version 2>&1 | awk '{print $2}')"

# ── 2. venv ───────────────────────────────
if [ ! -f ".venv/bin/activate" ]; then
    step "Creating virtual environment..."
    $PYTHON -m venv .venv || err "venv creation failed"
    ok "venv created"
else
    ok "venv ready"
fi
source .venv/bin/activate

# ── 3. dependencies ───────────────────────
if ! python -c "import pymysql" &>/dev/null; then
    step "Installing dependencies..."
    pip install -r requirements.txt -q || err "pip install failed"
    ok "dependencies installed"
else
    ok "dependencies ready"
fi

# ── 4. config ─────────────────────────────
if [ ! -f "config/config.yaml" ]; then
    [ -f "config/config.yaml.example" ] || err "config.yaml.example not found"
    cp config/config.yaml.example config/config.yaml
    ok "config.yaml created from example"
else
    ok "config.yaml ready"
fi

export DB_MASTER_PASSWORD="${DB_MASTER_PASSWORD:-etl_dev_pass}"
export WEB_SECRET_KEY="${WEB_SECRET_KEY:-dev_secret_key_change_in_production}"

# ── 5. Docker ─────────────────────────────
SKIP_DOCKER=1
if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    SKIP_DOCKER=0
    step "Starting MySQL + Redis..."
    docker-compose up -d mysql redis || { warn "docker-compose failed"; SKIP_DOCKER=1; }
fi

if [ "$SKIP_DOCKER" -eq 0 ]; then
    step "Waiting for MySQL..."
    for i in $(seq 1 30); do
        if docker exec etl-mysql mysqladmin ping -h localhost -uroot -proot_dev_only &>/dev/null; then
            ok "MySQL is ready"
            break
        fi
        [ "$i" -eq 30 ] && warn "MySQL not ready after 60s"
        sleep 2
    done
else
    warn "Docker not available, skipping infrastructure"
fi

# ── 6. Start service (background) ─────────
echo ""
step "Starting TDCS on http://127.0.0.1:8080 ..."

nohup python -m src.main > /dev/null 2>&1 &
echo $! > "$PID_FILE"
ok "PID $(cat $PID_FILE) saved"

# ── 7. Wait for port ──────────────────────
for i in $(seq 1 20); do
    if curl -s http://127.0.0.1:8080/health >/dev/null 2>&1; then
        ok "Service is ready"
        break
    fi
    [ "$i" -eq 20 ] && warn "Service may still be starting"
    sleep 1
done

echo ""
echo "───────────────────────────────────────"
echo "  Web UI:   http://127.0.0.1:8080"
echo "  Swagger:  http://127.0.0.1:8080/docs"
echo "  Run stop.sh to shut down"
echo "───────────────────────────────────────"
echo ""
