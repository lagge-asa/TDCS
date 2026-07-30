"""TaskManager 配置热加载同步测试。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.core.task_manager import TaskManager


def task(task_id, enabled=True, folder="D:/input"):
    return SimpleNamespace(task_id=task_id, enabled=enabled, monitor_folder=folder, recursive=False)


def manager():
    cm = MagicMock()
    pool = MagicMock()
    tm = TaskManager(cm, MagicMock(), pool, MagicMock(), MagicMock(), MagicMock())
    return tm, cm, pool


def test_new_enabled_task_starts_after_reload():
    tm, _, _ = manager()
    old = SimpleNamespace(tasks=(task("existing"),))
    new = SimpleNamespace(tasks=(task("existing"), task("new")))
    tm._watchers["existing"] = MagicMock()
    tm._scanners["existing"] = MagicMock()

    with patch.object(tm, "start_task") as start, patch.object(tm, "stop_task"):
        tm._on_config_changed(old, new)

    start.assert_called_once_with("new")


def test_disabled_task_stops_and_resumes_pool():
    tm, _, pool = manager()
    old = SimpleNamespace(tasks=(task("existing"),))
    new = SimpleNamespace(tasks=(task("existing", enabled=False),))
    tm._watchers["existing"] = MagicMock()

    with patch.object(tm, "stop_task") as stop:
        tm._on_config_changed(old, new)

    stop.assert_called_once_with("existing")
    pool.resume_task.assert_called_once_with("existing")


def test_removed_task_stops():
    tm, _, _ = manager()
    old = SimpleNamespace(tasks=(task("removed"),))
    new = SimpleNamespace(tasks=())
    tm._scanners["removed"] = MagicMock()

    with patch.object(tm, "stop_task") as stop:
        tm._on_config_changed(old, new)

    stop.assert_called_once_with("removed")


def test_changed_running_task_restarts():
    tm, _, _ = manager()
    old = SimpleNamespace(tasks=(task("existing", folder="D:/old"),))
    new = SimpleNamespace(tasks=(task("existing", folder="D:/new"),))
    tm._watchers["existing"] = MagicMock()
    tm._scanners["existing"] = MagicMock()

    with patch.object(tm, "stop_task") as stop, patch.object(tm, "start_task") as start:
        tm._on_config_changed(old, new)

    stop.assert_called_once_with("existing")
    start.assert_called_once_with("existing")


def test_unchanged_running_task_is_not_restarted():
    tm, _, _ = manager()
    old = SimpleNamespace(tasks=(task("existing"),))
    new = SimpleNamespace(tasks=(task("existing"),))
    tm._watchers["existing"] = MagicMock()

    with patch.object(tm, "stop_task") as stop, patch.object(tm, "start_task") as start:
        tm._on_config_changed(old, new)

    stop.assert_not_called()
    start.assert_not_called()
