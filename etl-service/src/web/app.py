"""
Flask 应用工厂 + waitress 生产服务器
"""

import logging
from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

logger = logging.getLogger(__name__)


def create_app(config_manager, task_manager=None,
               worker_pool=None, ha_elector=None,
               quality_reporter=None, encryption=None, db=None):
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
    app.config["ha_elector"] = ha_elector
    app.config["quality_reporter"] = quality_reporter
    app.config["encryption"] = encryption
    app.config["db"] = db

    # 注册 Blueprint
    from .api.system import bp as system_bp
    from .api.tasks import bp as tasks_bp
    from .api.files import bp as files_bp
    from .api.quality import bp as quality_bp
    from .api.config_api import bp as config_bp
    from .api.cleaners import bp as cleaners_bp
    from .api.users import bp as users_bp

    import os
    from flask import send_from_directory

    static_dir = os.path.join(os.path.dirname(__file__), "static")

    @app.get("/")
    def index():
        return send_from_directory(static_dir, "index.html")

    app.register_blueprint(system_bp)
    app.register_blueprint(tasks_bp, url_prefix="/api/v1/tasks")
    app.register_blueprint(files_bp, url_prefix="/api/v1/files")
    app.register_blueprint(quality_bp, url_prefix="/api/v1/quality")
    app.register_blueprint(config_bp, url_prefix="/api/v1/config")
    app.register_blueprint(cleaners_bp, url_prefix="/api/v1/cleaners")
    app.register_blueprint(users_bp, url_prefix="/api/v1/users")

    return app


def run_server(app, host: str, port: int, threads: int = 4) -> None:
    """使用 waitress 生产服务器启动."""
    from waitress import serve
    logger.info("Starting waitress server on %s:%d", host, port)
    serve(app, host=host, port=port, threads=threads)
