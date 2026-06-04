-- ETL 服务数据库初始化脚本
-- MySQL 8.0+  charset: utf8mb4

CREATE DATABASE IF NOT EXISTS etl_db
    DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE etl_db;

-- 1. 用户表 (RBAC)
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('admin','operator','viewer') NOT NULL DEFAULT 'viewer',
    enabled BOOL DEFAULT TRUE,
    last_login TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO users (username, password_hash, role)
VALUES ('admin', 'CHANGE_ON_FIRST_RUN', 'admin');

-- 2. 文件处理状态表 (核心状态机)
CREATE TABLE IF NOT EXISTS processed_files (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    task_id VARCHAR(100) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_size BIGINT,
    file_mtime BIGINT NOT NULL,
    file_hash VARCHAR(64),
    status ENUM('PENDING','CLAIMED','PROCESSING','SUCCESS','FAILED','SKIPPED')
        NOT NULL DEFAULT 'PENDING',
    claimed_by VARCHAR(200),
    claimed_at TIMESTAMP NULL,
    claim_expires_at TIMESTAMP NULL,
    retry_count INT DEFAULT 0,
    error_message TEXT,
    error_type VARCHAR(50),
    row_count INT DEFAULT 0,
    valid_row_count INT DEFAULT 0,
    processing_time_ms INT,
    archive_path VARCHAR(500),
    instance_id VARCHAR(200),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    processed_at TIMESTAMP NULL,
    UNIQUE KEY uk_task_file_mtime (task_id, file_path(400), file_mtime),
    INDEX idx_status (status),
    INDEX idx_task_status (task_id, status),
    INDEX idx_claim_expires (claim_expires_at),
    INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. Leader 选举表
CREATE TABLE IF NOT EXISTS leader (
    id INT PRIMARY KEY DEFAULT 1,
    instance_id VARCHAR(200),
    last_heartbeat TIMESTAMP(3) NULL,
    started_at TIMESTAMP NULL,
    version INT DEFAULT 0,
    status ENUM('ACTIVE','DEGRADED') DEFAULT 'ACTIVE'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO leader (id) VALUES (1);

-- 4. 数据质量日志
CREATE TABLE IF NOT EXISTS data_quality_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    task_id VARCHAR(100) NOT NULL,
    file_id BIGINT,
    file_path VARCHAR(500),
    batch_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    total_rows INT DEFAULT 0,
    valid_rows INT DEFAULT 0,
    skipped_rows INT DEFAULT 0,
    error_rows INT DEFAULT 0,
    null_rate DECIMAL(5,4),
    error_details JSON,
    quality_score DECIMAL(5,2),
    processing_time_ms INT,
    INDEX idx_task_time (task_id, batch_time),
    FOREIGN KEY (file_id) REFERENCES processed_files(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5. 审计日志
CREATE TABLE IF NOT EXISTS audit_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    timestamp TIMESTAMP(3) DEFAULT CURRENT_TIMESTAMP(3),
    user_id INT,
    username VARCHAR(50),
    user_ip VARCHAR(45),
    action VARCHAR(100) NOT NULL,
    target VARCHAR(300),
    detail JSON,
    instance_id VARCHAR(200),
    INDEX idx_time (timestamp),
    INDEX idx_user (user_id),
    INDEX idx_action (action)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 6. 配置变更历史 (支持回滚)
CREATE TABLE IF NOT EXISTS config_history (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    config_type ENUM('main','template','cleaner') NOT NULL,
    config_key VARCHAR(200) NOT NULL,
    content_before MEDIUMTEXT,
    content_after MEDIUMTEXT,
    changed_by VARCHAR(50),
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_type_key_time (config_type, config_key, changed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 7. 月表元数据注册表
CREATE TABLE IF NOT EXISTS monthly_table_registry (
    id INT AUTO_INCREMENT PRIMARY KEY,
    task_id VARCHAR(100) NOT NULL,
    table_name VARCHAR(150) NOT NULL,
    `year_month` CHAR(7) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    row_count BIGINT DEFAULT 0,
    last_written_at TIMESTAMP NULL,
    lifecycle_status ENUM('ACTIVE','ARCHIVED','DROPPED') DEFAULT 'ACTIVE',
    archived_at TIMESTAMP NULL,
    dropped_at TIMESTAMP NULL,
    UNIQUE KEY uk_task_table (task_id, table_name),
    INDEX idx_task_month (task_id, `year_month`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 8. 每日统计汇总
CREATE TABLE IF NOT EXISTS daily_statistics (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    task_id VARCHAR(100) NOT NULL,
    stat_date DATE NOT NULL,
    total_files INT DEFAULT 0,
    success_files INT DEFAULT 0,
    failed_files INT DEFAULT 0,
    skipped_files INT DEFAULT 0,
    total_rows BIGINT DEFAULT 0,
    valid_rows BIGINT DEFAULT 0,
    avg_quality_score DECIMAL(5,2),
    avg_processing_time_ms INT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_task_date (task_id, stat_date),
    INDEX idx_date (stat_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 9. 服务心跳历史
CREATE TABLE IF NOT EXISTS heartbeat_history (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    instance_id VARCHAR(200) NOT NULL,
    heartbeat_time TIMESTAMP(3) DEFAULT CURRENT_TIMESTAMP(3),
    role ENUM('ACTIVE','STANDBY'),
    queue_size INT DEFAULT 0,
    active_workers INT DEFAULT 0,
    memory_mb DECIMAL(8,2),
    cpu_percent DECIMAL(5,2),
    INDEX idx_instance_time (instance_id, heartbeat_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
