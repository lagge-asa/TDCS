#!/usr/bin/env bash
# ============================================================
# TDCS 停止脚本 (Linux/macOS)
# 用法: ./stop.sh
# ============================================================

set -e

GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
cd "$(dirname "$0")"
PID_FILE="$PWD/.tdcs.pid"

ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
step() { echo -e "${CYAN}[..]${NC} $*"; }

echo ""
echo "========================================"
echo "  TDCS - Stop Service"
echo "========================================"
echo ""

# ── Stop Python process via PID file ──────
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    step "Stopping TDCS (PID $PID)..."
    if kill -0 "$PID" 2>/dev/null; then
        kill -TERM "$PID" 2>/dev/null || true
        # Wait up to 10s for graceful shutdown
        for i in $(seq 1 10); do
            kill -0 "$PID" 2>/dev/null || break
            sleep 1
        done
        # Force kill if still alive
        kill -0 "$PID" 2>/dev/null && kill -KILL "$PID" 2>/dev/null || true
        ok "Service stopped"
    else
        ok "Process already dead"
    fi
    rm -f "$PID_FILE"
else
    step "No PID file, trying pgrep..."
    pkill -f "python.*src.main" 2>/dev/null && ok "Service stopped" || ok "Nothing to stop"
fi

# ── Stop Docker containers ────────────────
if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    step "Stopping Docker containers..."
    docker-compose down 2>/dev/null && ok "Containers stopped" || ok "Containers already stopped"
fi

echo ""
echo "TDCS shut down complete."
echo ""
