"""初始 migration: 创建所有业务表

从 scripts/init_db.sql 导出基线。
Revision ID: 001
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 用户表 (RBAC)
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(50), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.Enum("admin", "operator", "viewer"), nullable=False, server_default="viewer"),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("TRUE")),
        sa.Column("last_login", sa.TIMESTAMP(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.execute("INSERT IGNORE INTO users (username, password_hash, role) VALUES ('admin', 'CHANGE_ON_FIRST_RUN', 'admin')")

    # 2. 文件处理状态表
    op.create_table(
        "processed_files",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.String(100), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("file_mtime", sa.BigInteger(), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=True),
        sa.Column("status", sa.Enum("PENDING", "CLAIMED", "PROCESSING", "SUCCESS", "FAILED", "SKIPPED"), nullable=False, server_default="PENDING"),
        sa.Column("claimed_by", sa.String(200), nullable=True),
        sa.Column("claimed_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("claim_expires_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_type", sa.String(50), nullable=True),
        sa.Column("row_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("valid_row_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("processing_time_ms", sa.Integer(), nullable=True),
        sa.Column("archive_path", sa.String(500), nullable=True),
        sa.Column("instance_id", sa.String(200), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
        sa.Column("processed_at", sa.TIMESTAMP(), nullable=True),
        sa.UniqueConstraint("task_id", "file_path", "file_mtime", name="uk_task_file_mtime"),
        sa.Index("idx_status", "status"),
        sa.Index("idx_task_status", "task_id", "status"),
        sa.Index("idx_claim_expires", "claim_expires_at"),
        sa.Index("idx_created", "created_at"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )

    # 3. Leader 选举表
    op.create_table(
        "leader",
        sa.Column("id", sa.Integer(), primary_key=True, server_default=sa.text("1")),
        sa.Column("instance_id", sa.String(200), nullable=True),
        sa.Column("last_heartbeat", sa.TIMESTAMP(timezone=False), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("0")),
        sa.Column("status", sa.Enum("ACTIVE", "DEGRADED"), server_default="ACTIVE"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.execute("INSERT IGNORE INTO leader (id) VALUES (1)")

    # 4. 数据质量日志
    op.create_table(
        "data_quality_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.String(100), nullable=False),
        sa.Column("file_id", sa.BigInteger(), sa.ForeignKey("processed_files.id", ondelete="SET NULL"), nullable=True),
        sa.Column("file_path", sa.String(500), nullable=True),
        sa.Column("batch_time", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("total_rows", sa.Integer(), server_default=sa.text("0")),
        sa.Column("valid_rows", sa.Integer(), server_default=sa.text("0")),
        sa.Column("skipped_rows", sa.Integer(), server_default=sa.text("0")),
        sa.Column("error_rows", sa.Integer(), server_default=sa.text("0")),
        sa.Column("null_rate", sa.DECIMAL(5, 4), nullable=True),
        sa.Column("error_details", sa.JSON(), nullable=True),
        sa.Column("quality_score", sa.DECIMAL(5, 2), nullable=True),
        sa.Column("processing_time_ms", sa.Integer(), nullable=True),
        sa.Index("idx_task_time", "task_id", "batch_time"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )

    # 5. 审计日志
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=False), server_default=sa.text("CURRENT_TIMESTAMP(3)")),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("username", sa.String(50), nullable=True),
        sa.Column("user_ip", sa.String(45), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target", sa.String(300), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("instance_id", sa.String(200), nullable=True),
        sa.Index("idx_time", "timestamp"),
        sa.Index("idx_user", "user_id"),
        sa.Index("idx_action", "action"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )

    # 6. 配置变更历史
    op.create_table(
        "config_history",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("config_type", sa.Enum("main", "template", "cleaner"), nullable=False),
        sa.Column("config_key", sa.String(200), nullable=False),
        sa.Column("content_before", sa.Text(length=16777215), nullable=True),  # MEDIUMTEXT
        sa.Column("content_after", sa.Text(length=16777215), nullable=True),
        sa.Column("changed_by", sa.String(50), nullable=True),
        sa.Column("changed_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Index("idx_type_key_time", "config_type", "config_key", "changed_at"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )

    # 7. 月表元数据注册表
    op.create_table(
        "monthly_table_registry",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.String(100), nullable=False),
        sa.Column("table_name", sa.String(150), nullable=False),
        sa.Column("year_month", sa.String(7), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_count", sa.BigInteger(), server_default=sa.text("0")),
        sa.Column("last_written_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("lifecycle_status", sa.Enum("ACTIVE", "ARCHIVED", "DROPPED"), server_default="ACTIVE"),
        sa.Column("archived_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("dropped_at", sa.TIMESTAMP(), nullable=True),
        sa.UniqueConstraint("task_id", "table_name", name="uk_task_table"),
        sa.Index("idx_task_month", "task_id", "year_month"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )

    # 8. 每日统计汇总
    op.create_table(
        "daily_statistics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.String(100), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("total_files", sa.Integer(), server_default=sa.text("0")),
        sa.Column("success_files", sa.Integer(), server_default=sa.text("0")),
        sa.Column("failed_files", sa.Integer(), server_default=sa.text("0")),
        sa.Column("skipped_files", sa.Integer(), server_default=sa.text("0")),
        sa.Column("total_rows", sa.BigInteger(), server_default=sa.text("0")),
        sa.Column("valid_rows", sa.BigInteger(), server_default=sa.text("0")),
        sa.Column("avg_quality_score", sa.DECIMAL(5, 2), nullable=True),
        sa.Column("avg_processing_time_ms", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("task_id", "stat_date", name="uk_task_date"),
        sa.Index("idx_date", "stat_date"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )

    # 9. 服务心跳历史
    op.create_table(
        "heartbeat_history",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("instance_id", sa.String(200), nullable=False),
        sa.Column("heartbeat_time", sa.TIMESTAMP(timezone=False), server_default=sa.text("CURRENT_TIMESTAMP(3)")),
        sa.Column("role", sa.Enum("ACTIVE", "STANDBY"), nullable=True),
        sa.Column("queue_size", sa.Integer(), server_default=sa.text("0")),
        sa.Column("active_workers", sa.Integer(), server_default=sa.text("0")),
        sa.Column("memory_mb", sa.DECIMAL(8, 2), nullable=True),
        sa.Column("cpu_percent", sa.DECIMAL(5, 2), nullable=True),
        sa.Index("idx_instance_time", "instance_id", "heartbeat_time"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )


def downgrade() -> None:
    op.drop_table("heartbeat_history")
    op.drop_table("daily_statistics")
    op.drop_table("monthly_table_registry")
    op.drop_table("config_history")
    op.drop_table("audit_log")
    op.drop_table("data_quality_log")
    op.drop_table("leader")
    op.drop_table("processed_files")
    op.drop_table("users")
