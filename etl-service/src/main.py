"""
程序入口

支持两种运行模式:
- Windows 服务: sc start ETLService
- 直接运行: python -m src.main
"""

import logging
import os
import signal
import sys
import threading

logger = logging.getLogger(__name__)


def bootstrap(config_path: str = None, stop_event=None) -> None:
    """初始化并启动所有组件."""
    from .utils.logging_config import setup_logging
    from .core.config import ConfigManager
    from .core.file_processor import FileProcessor
    from .infrastructure.database import DatabaseManager
    from .infrastructure.state_tracker import StateTracker
    from .infrastructure.worker_pool import WorkerPool
    from .infrastructure.ha_elector import HAElector
    from .infrastructure.file_archiver import FileArchiver
    from .infrastructure.cache import CacheManager
    from .etl.table_router import TableRouter
    from .etl.loader import Loader
    from .etl.encryption import Encryption
    from .etl.extractor import StreamingExtractor
    from .etl.transform_sandbox import TransformSandbox
    from .etl.cleaner_registry import CleanerRegistry
    from .monitoring.quality_reporter import QualityReporter
    from .monitoring.alerting import Alerter
    from .core.pipeline import ETLPipeline
    from .core.task_manager import TaskManager
    from .web.app import create_app, run_server

    if config_path is None:
        config_path = os.environ.get(
            "ETL_CONFIG", "config/config.yaml")

    # 1. 配置
    cm = ConfigManager(config_path)
    cm.load()
    cfg = cm.config

    # 2. 日志
    setup_logging(cfg.log_level)
    logger.info("ETL Service starting: %s", cfg.instance_id)

    # 3. 基础设施
    db = DatabaseManager(cfg)
    cache = CacheManager(
        maxsize=cfg.cache.local.maxsize,
        ttl=cfg.cache.local.ttl,
    )
    # 注: cfg.cache.redis 已配置但当前未启用，TableRouter 只使用本地 CacheManager
    st = StateTracker(db, cfg.instance_id)
    archiver = FileArchiver(st)
    enc = Encryption(cfg.encryption)
    qr = QualityReporter(db)

    # 4. ETL 组件
    extractor = StreamingExtractor()
    sandbox = TransformSandbox("custom_etl")

    # 热插拔清洗模板注册中心
    cleaner_registry = CleanerRegistry("clean_templates")
    cleaner_registry.start_watching()

    router = TableRouter(db, cache)
    loader = Loader(db)

    def make_pipeline(task_id: str) -> ETLPipeline:
        return ETLPipeline(extractor, sandbox, router, loader, enc, qr)

    # 5. 告警
    alerter = Alerter(cfg.monitoring.alerting)

    # 6. Worker Pool（先占位，process_fn 依赖 tm，tm 依赖 pool，循环依赖用 setter 解决）
    pool = WorkerPool(None, cfg.worker_threads, cfg.queue_maxsize)

    # 7. HA
    ha = HAElector(
        db, cfg.instance_id, cfg.ha,
        on_become_active=lambda: logger.info("Became ACTIVE"),
        on_become_standby=lambda: logger.info("Became STANDBY"),
    )

    # 8. Task Manager
    tm = TaskManager(cm, db, pool, st, ha, archiver)

    # 9. 现在 tm 已存在，完成 FileProcessor 并注入 pool
    process_fn = FileProcessor(cm, st, make_pipeline, qr, archiver,
                               alerter=alerter, task_manager=tm)
    pool._process_fn = process_fn

    # 10. Web
    app = create_app(cm, tm, pool, ha, qr, enc, db, cleaner_registry)

    # 11. 启动
    pool.start()
    if cfg.ha.enabled:
        ha.start()
    tm.start_all()

    _stop_for_web: threading.Event = None  # Web 线程崩溃时用于通知主线程

    if cfg.web.enabled:
        _stop_for_web = threading.Event() if stop_event is None else None

        def _web_wrapper():
            try:
                run_server(app, cfg.web.host, cfg.web.port, cfg.web.threads)
            except Exception:
                logger.exception("Web server crashed")
            finally:
                # Web 线程退出（含崩溃）时触发主停止信号
                if _stop_for_web is not None:
                    _stop_for_web.set()

        web_thread = threading.Thread(
            target=_web_wrapper,
            daemon=True,
            name="WebServer",
        )
        web_thread.start()

    logger.info("ETL Service started")

    # 等待停止信号
    if stop_event is not None:
        import win32event
        win32event.WaitForSingleObject(stop_event, win32event.INFINITE)
    else:
        stop = threading.Event()
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        # Web 线程崩溃也触发优雅退出
        if cfg.web.enabled and _stop_for_web is not None:
            threading.Thread(
                target=lambda: (_stop_for_web.wait(), stop.set()),
                daemon=True, name="WebCrashWatcher",
            ).start()
        stop.wait()

    logger.info("ETL Service stopping...")
    # 关闭顺序：先停 registry（worker 可能还在跑清洗），再等 pool 完成，最后释放 DB
    cleaner_registry.stop_watching()
    pool.stop()          # 发停止信号并等待所有 worker 线程退出
    if cfg.ha.enabled:
        ha.stop()
    db.dispose()         # 所有 worker 已退出后才释放连接池


if __name__ == "__main__":
    bootstrap()
