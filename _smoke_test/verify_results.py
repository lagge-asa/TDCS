import pymysql
conn = pymysql.connect(host='127.0.0.1',port=3306,user='etl_user',password='etl_dev_pass',database='etl_db')
cur = conn.cursor()

cur.execute("SELECT status, COUNT(*) AS cnt FROM processed_files WHERE task_id='smoke_import' GROUP BY status")
print("=== Processed Files ===")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]}")

cur.execute("SELECT table_name, `year_month`, lifecycle_status FROM monthly_table_registry WHERE task_id='smoke_import' ORDER BY `year_month`")
tables = cur.fetchall()
print(f"\n=== Monthly Tables: {len(tables)} ===")

# Total data
cur.execute("SELECT COUNT(*) FROM smoke_data_202401")
total = 0
for t in tables:
    cur.execute(f"SELECT COUNT(*) FROM {t[0]}")
    cnt = cur.fetchone()[0]
    total += cnt
    print(f"  {t[0]} ({t[1]}): {cnt} rows")

print(f"\n  TOTAL: {total} rows across {len(tables)} tables")

# Sample
cur.execute("SELECT id, name, value, date, status, score FROM smoke_data_202506 LIMIT 5")
print("\n=== Sample Data (202506) ===")
for r in cur.fetchall():
    print(f"  {r}")

cur.close(); conn.close()
