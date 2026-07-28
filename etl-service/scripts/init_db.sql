-- ETL 服务数据库初始化脚本
-- MySQL 8.0+  charset: utf8mb4
--
-- 仅创建数据库和初始 admin 用户。
-- 业务表结构由 Alembic migration 管理: alembic upgrade head

CREATE DATABASE IF NOT EXISTS etl_db
    DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE etl_db;

-- 初始管理员用户（密码需在首次登录后修改）
-- 业务表由 Alembic migration 001_initial_schema.py 创建
