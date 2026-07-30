"""初始化 ETL 数据库表"""
import pymysql

conn = pymysql.connect(
    host='127.0.0.1', port=3306,
    user='etl_user', password='etl_dev_pass', database='etl_db')
cur = conn.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS processed_files (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    task_id VARCHAR(64), file_path VARCHAR(500), file_name VARCHAR(255),
    file_mtime BIGINT, file_size BIGINT, file_hash VARCHAR(64),
    status VARCHAR(32), claimed_by VARCHAR(64), claimed_at DATETIME,
    claim_expires_at DATETIME, instance_id VARCHAR(64),
    retry_count INT DEFAULT 0, error_type VARCHAR(64), error_message TEXT,
    row_count INT, valid_row_count INT, processing_time_ms INT,
    archive_path VARCHAR(500), created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    processed_at DATETIME,
    UNIQUE KEY uk_file (task_id, file_path, file_mtime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

cur.execute("""CREATE TABLE IF NOT EXISTS monthly_table_registry (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    task_id VARCHAR(64), table_name VARCHAR(128),
    `year_month` VARCHAR(7),
    lifecycle_status VARCHAR(32) DEFAULT 'ACTIVE', archived_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_table (task_id, table_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

cur.execute("""CREATE TABLE IF NOT EXISTS data_quality_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    task_id VARCHAR(64), file_id BIGINT, file_path VARCHAR(500),
    total_rows INT, valid_rows INT, error_rows INT,
    null_rate DOUBLE, error_rate DOUBLE, quality_score DOUBLE,
    processing_time_ms INT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_task (task_id), INDEX idx_file (file_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

# User table for auth
cur.execute("""CREATE TABLE IF NOT EXISTS users (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(64) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(32) DEFAULT 'viewer',
    enabled TINYINT DEFAULT 1,
    last_login DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

# Audit log
cur.execute("""CREATE TABLE IF NOT EXISTS audit_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(64), username VARCHAR(64), user_ip VARCHAR(64),
    action VARCHAR(64), target VARCHAR(255), detail TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_action (action), INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

conn.commit()

# Create default admin user (password: admin123)
import bcrypt
pw = bcrypt.hashpw(b'admin123', bcrypt.gensalt()).decode()
cur.execute(
    "INSERT IGNORE INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
    ('admin', pw, 'admin'))

conn.commit()
cur.execute("SHOW TABLES")
print("Tables:", [r[0] for r in cur.fetchall()])
cur.close(); conn.close()
print("DB init OK")
