import pymysql
conn = pymysql.connect(host='127.0.0.1',port=3306,user='etl_user',password='etl_dev_pass',database='etl_db')
cur = conn.cursor()
cur.execute("SELECT file_name, status, error_type, error_message FROM processed_files WHERE task_id='smoke_import' ORDER BY created_at DESC LIMIT 5")
for r in cur.fetchall():
    print(f"{r[0]}: {r[1]} [{r[2]}] {str(r[3])[:300] if r[3] else ''}")
cur.close(); conn.close()
