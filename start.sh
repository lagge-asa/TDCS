#!/usr/bin/env bash
# ============================================================
# TDCS 一键启动脚本 (Linux/macOS)
# 用法: cd etl-service && ./start.sh
# ============================================================

set -e

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo ""
echo "========================================"
echo "  TDCS 一键启动"
echo "  Timed Data Collection Service"
echo "========================================"
echo ""

# 切换到脚本所在目录
cd "$(dirname "$0")"

# ============================================================
# 1. 前置检查
# ============================================================

# 检查 Python
if ! command -v python3 &>/dev/null; then
    if ! command -v python &>/dev/null; then
        echo -e "${RED}[错误] 未找到 Python，请安装 Python 3.10+ 后重试${NC}"
        exit 1
    fi
    PYTHON=python
else
    PYTHON=python3
fi

# 检查 Python 版本 >= 3.10
PYVER=$($PYTHON --version 2>&1 | awk '{print $2}')
PYMAJ=$(echo "$PYVER" | cut -d. -f1)
PYMIN=$(echo "$PYVER" | cut -d. -f2)

if [ "$PYMAJ" -lt 3 ] || ([ "$PYMAJ" -eq 3 ] && [ "$PYMIN" -lt 10 ]); then
    echo -e "${RED}[错误] Python 版本过低 ($PYVER)，需要 3.10+${NC}"
    exit 1
fi
echo -e "${GREEN}[OK] Python $PYVER${NC}"

# 检查 Docker
SKIP_DOCKER=0
if ! command -v docker &>/dev/null; then
    echo -e "${YELLOW}[警告] 未找到 Docker，将跳过基础设施启动${NC}"
    SKIP_DOCKER=1
elif ! docker info &>/dev/null; then
    echo -e "${YELLOW}[警告] Docker 未运行，将跳过基础设施启动${NC}"
    SKIP_DOCKER=1
else
    echo -e "${GREEN}[OK] Docker 已就绪${NC}"
fi

# ============================================================
# 2. 环境准备 — 虚拟环境 + 依赖安装
# ============================================================

echo ""
echo "--- 环境准备 ---"

if [ ! -f ".venv/bin/activate" ]; then
    echo -e "${CYAN}[1/2] 创建虚拟环境...${NC}"
    $PYTHON -m venv .venv
    if [ $? -ne 0 ]; then
        echo -e "${RED}[错误] 创建虚拟环境失败${NC}"
        exit 1
    fi
    echo -e "${GREEN}[OK] 虚拟环境已创建${NC}"
else
    echo -e "${GREEN}[OK] 虚拟环境已存在${NC}"
fi

# 激活虚拟环境
source .venv/bin/activate

# 安装依赖
echo -e "${CYAN}[2/2] 检查依赖...${NC}"
if ! python -c "import pymysql" &>/dev/null; then
    echo "正在安装依赖 (首次可能较慢)..."
    pip install -r requirements.txt -q
    if [ $? -ne 0 ]; then
        echo -e "${RED}[错误] 依赖安装失败，请检查网络连接${NC}"
        exit 1
    fi
    echo -e "${GREEN}[OK] 依赖安装完成${NC}"
else
    echo -e "${GREEN}[OK] 依赖已就绪${NC}"
fi

# ============================================================
# 3. 配置准备
# ============================================================

echo ""
echo "--- 配置准备 ---"

if [ ! -f "config/config.yaml" ]; then
    if [ -f "config/config.yaml.example" ]; then
        cp "config/config.yaml.example" "config/config.yaml"
        echo -e "${GREEN}[OK] 已从 config.yaml.example 复制创建 config.yaml${NC}"
    else
        echo -e "${RED}[错误] 未找到 config/config.yaml.example${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}[OK] config/config.yaml 已存在${NC}"
fi

# 检查关键环境变量
if [ -z "$DB_MASTER_PASSWORD" ]; then
    echo -e "${YELLOW}[提示] DB_MASTER_PASSWORD 未设置，使用 docker-compose 默认值 (etl_dev_pass)${NC}"
    export DB_MASTER_PASSWORD=etl_dev_pass
fi
if [ -z "$WEB_SECRET_KEY" ]; then
    echo -e "${YELLOW}[提示] WEB_SECRET_KEY 未设置，使用开发默认值${NC}"
    export WEB_SECRET_KEY=dev_secret_key_change_in_production
fi

# ============================================================
# 4. 启动基础设施 (Docker)
# ============================================================

if [ "$SKIP_DOCKER" -eq 0 ]; then
    echo ""
    echo "--- 启动基础设施 ---"

    echo -e "${CYAN}[1/2] 启动 MySQL + Redis 容器...${NC}"
    docker-compose up -d mysql redis
    if [ $? -ne 0 ]; then
        echo -e "${RED}[错误] Docker 容器启动失败${NC}"
        exit 1
    fi

    echo -e "${CYAN}[2/2] 等待 MySQL 就绪...${NC}"
    MYSQL_READY=0
    for i in $(seq 1 30); do
        if docker exec $(docker-compose ps -q mysql) \
            mysqladmin ping -h localhost --user=root --password=root_dev_only &>/dev/null; then
            MYSQL_READY=1
            break
        fi
        printf "."
        sleep 2
    done

    if [ "$MYSQL_READY" -eq 0 ]; then
        echo ""
        echo -e "${YELLOW}[警告] MySQL 等待超时 (60秒)，服务可能启动失败${NC}"
    else
        echo ""
        echo -e "${GREEN}[OK] MySQL 已就绪${NC}"
    fi
    echo -e "${GREEN}[OK] Redis 已就绪${NC}"
else
    echo ""
    echo -e "${YELLOW}[跳过] Docker 基础设施未启动 (SKIP_DOCKER=1)${NC}"
fi

# ============================================================
# 5. 启动 ETL 服务
# ============================================================

echo ""
echo "========================================"
echo -e "  ${GREEN}正在启动 TDCS 服务...${NC}"
echo "  Web UI:  http://127.0.0.1:8080"
echo "  停止服务: Ctrl+C 或运行 stop.sh"
echo "========================================"
echo ""

python -m src.main

echo ""
echo "[信息] TDCS 服务已停止"