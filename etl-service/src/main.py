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

    # 5. Worker Pool
    process_fn = FileProcessor(cm, st, make_pipeline, qr, archiver)
    pool = WorkerPool(process_fn, cfg.worker_threads, cfg.queue_maxsize)

    # 6. HA
    ha = HAElector(
        db, cfg.instance_id, cfg.ha,
        on_become_active=lambda: logger.info("Became ACTIVE"),
        on_become_standby=lambda: logger.info("Became STANDBY"),
    )

    # 7. Task Manager
    tm = TaskManager(cm, db, pool, st, ha, archiver)

    # 8. Web
    app = create_app(cm, tm, pool, ha, qr, enc, db, cleaner_registry)

    # 9. 启动
    pool.start()
    if cfg.ha.enabled:
        ha.start()
    tm.start_all()

    if cfg.web.enabled:
        web_thread = threading.Thread(
            target=run_server,
            args=(app, cfg.web.host, cfg.web.port, cfg.web.threads),
            daemon=True,
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
        stop.wait()

    logger.info("ETL Service stopping...")
    pool.stop()
    ha.stop()
    cleaner_registry.stop_watching()
    db.dispose()


if __name__ == "__main__":
    bootstrap()
