"""
Flask 应用工厂 + waitress 生产服务器
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

if TYPE_CHECKING:
    from ..core.config import ConfigManager
    from ..core.task_manager import TaskManager
    from ..infrastructure.worker_pool import WorkerPool
    from ..monitoring.quality_reporter import QualityReporter
    from ..infrastructure.database import DatabaseManager
    from ..etl.cleaner_registry import CleanerRegistry

logger = logging.getLogger(__name__)


def create_app(config_manager: ConfigManager,
               task_manager: Optional[TaskManager] = None,
               worker_pool: Optional[WorkerPool] = None,
               quality_reporter: Optional[QualityReporter] = None,
               db: Optional[DatabaseManager] = None,
               cleaner_registry: Optional[CleanerRegistry] = None) -> Flask:
    app = Flask(__name__)
    cfg = config_manager.config

    app.config["SECRET_KEY"] = cfg.web.secret_key
    app.config["TOKEN_EXPIRE_HOURS"] = cfg.web.token_expire_hours

    # 速率限制 per-IP
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=[cfg.web.rate_limit],
        storage_uri="memory://",
    )

    # 注入依赖到 app context
    app.config["config_manager"] = config_manager
    app.config["task_manager"] = task_manager
    app.config["worker_pool"] = worker_pool
    app.config["limiter"] = limiter  # 供 Blueprint 中端点级 rate limit 使用
    app.config["quality_reporter"] = quality_reporter
    app.config["db"] = db
    app.config["cleaner_registry"] = cleaner_registry

    # 注册 Blueprint
    from .api.system import bp as system_bp
    from .api.tasks import bp as tasks_bp
    from .api.files import bp as files_bp
    from .api.quality import bp as quality_bp
    from .api.config_api import bp as config_bp
    from .api.cleaners import bp as cleaners_bp
    from .api.users import bp as users_bp
    from .api.audit import bp as audit_bp
    from .api.dashboard import bp as dashboard_bp
    from .api.monthly import bp as monthly_bp
    from .swagger import bp as swagger_bp

    import os
    from flask import send_from_directory

    static_dir = os.path.join(os.path.dirname(__file__), "static")

    @app.get("/")
    def index():
        resp = send_from_directory(static_dir, "index.html")
        # 防止浏览器缓存旧页面（前端热更新时用户无感知）
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp

    app.register_blueprint(system_bp)
    app.register_blueprint(tasks_bp, url_prefix="/api/v1/tasks")
    app.register_blueprint(files_bp, url_prefix="/api/v1/files")
    app.register_blueprint(quality_bp, url_prefix="/api/v1/quality")
    app.register_blueprint(config_bp, url_prefix="/api/v1/config")
    app.register_blueprint(cleaners_bp, url_prefix="/api/v1/cleaners")
    app.register_blueprint(users_bp, url_prefix="/api/v1/users")
    app.register_blueprint(audit_bp, url_prefix="/api/v1/audit-logs")
    app.register_blueprint(dashboard_bp, url_prefix="/api/v1/dashboard")
    app.register_blueprint(monthly_bp, url_prefix="/api/v1/monthly")
    app.register_blueprint(swagger_bp)  # /docs + /openapi.json

    # 全局错误处理器 — 保证所有未捕获异常返回 JSON 而非 HTML
    @app.errorhandler(Exception)
    def _handle_exception(e):
        import traceback
        from werkzeug.exceptions import HTTPException
        from .response import error as err_resp
        if isinstance(e, HTTPException):
            return err_resp("HTTP_ERROR", e.description or str(e), status=e.code)
        logger.error("Unhandled exception: %s", traceback.format_exc())
        return err_resp("INTERNAL_ERROR", "Internal server error", status=500)

    return app


def run_server(app, host: str, port: int, threads: int = 4) -> None:
    """使用 waitress 生产服务器启动."""
    from waitress import serve
    logger.info("Starting waitress server on %s:%d", host, port)
    serve(app, host=host, port=port, threads=threads)
