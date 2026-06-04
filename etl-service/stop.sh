#!/usr/bin/env bash
# TDCS 停止服务脚本
set -e

GREEN='\033[0;32m'
NC='\033[0m'

echo ""
echo "========================================"
echo "  TDCS 停止服务"
echo "========================================"
echo ""

cd "$(dirname "$0")"

# 停止 Docker 容器
if command -v docker &>/dev/null && docker info &>/dev/null; then
    echo "正在停止 Docker 容器..."
    docker-compose down
    echo -e "${GREEN}[OK] Docker 容器已停止${NC}"
fi

echo -e "${GREEN}[OK] TDCS 服务已停止${NC}"