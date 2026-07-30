"""
端到端冒烟测试 — 启动 ETL 服务并处理文件
"""
import sys, os, time, threading, json, signal
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.main import bootstrap
from src.core.config import ConfigManager

# 使用冒烟测试配置
config_path = str(PROJECT_ROOT / "_smoke_test" / "config.yaml")

# 在独立线程启动 bootstrap
stop_event = threading.Event()
errors = []

def _run():
    try:
        bootstrap(config_path, stop_event=stop_event)
    except Exception as e:
        errors.append(e)
        import traceback
        traceback.print_exc()

t = threading.Thread(target=_run, daemon=True, name="ETLMain")
t.start()

print("ETL Service starting...")
time.sleep(5)  # 等待初始化

# 检查 Web 服务是否启动
import urllib.request
try:
    resp = urllib.request.urlopen("http://127.0.0.1:8500/health", timeout=3)
    data = json.loads(resp.read())
    print(f"Health: {data}")
except Exception as e:
    print(f"Health check failed: {e}")

# 投放测试文件（复制到监控目录）
import shutil
src = PROJECT_ROOT / "_smoke_test" / "input" / "test_10k.csv"
dst = PROJECT_ROOT / "_smoke_test" / "input" / "test_delivery.csv"
shutil.copy(src, dst)
print(f"Delivered: {dst}")

# 等待处理
print("Waiting for ETL to process...")
time.sleep(15)

# 检查数据库结果
import pymysql
conn = pymysql.connect(
    host='127.0.0.1', port=3306,
    user='etl_user', password='etl_dev_pass', database='etl_db')
cur = conn.cursor()

# 检查 processed_files
cur.execute("SELECT status, row_count, retry_count, error_message FROM processed_files WHERE task_id='smoke_import' ORDER BY created_at DESC LIMIT 3")
rows = cur.fetchall()
print("\nProcessed files:")
for r in rows:
    print(f"  status={r[0]}, rows={r[1]}, retry={r[2]}, err={str(r[3])[:80] if r[3] else 'None'}")

# 检查是否创建了月表
cur.execute("SELECT table_name, lifecycle_status FROM monthly_table_registry WHERE task_id='smoke_import'")
mt = cur.fetchall()
print(f"\nMonthly tables: {mt}")

# 检查数据
cur.execute("SHOW TABLES LIKE 'smoke_data%'")
data_tables = [r[0] for r in cur.fetchall()]
print(f"Data tables: {data_tables}")

for tbl in data_tables:
    cur.execute(f"SELECT COUNT(*) FROM `{tbl}`")
    cnt = cur.fetchone()[0]
    print(f"  {tbl}: {cnt} rows")

cur.close(); conn.close()

# 停止
stop_event.set()
print("\nDone.")
