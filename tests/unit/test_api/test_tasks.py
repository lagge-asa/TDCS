"""API 测试: 任务管理端点"""
import json
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def task_app_client(loaded_config_manager):
    """Flask test client，注入 mock task_manager."""
    from src.web.app import create_app

    mock_tm = MagicMock()
    mock_tm._cm = loaded_config_manager
    mock_tm._pool = None

    app = create_app(
        loaded_config_manager,
        task_manager=mock_tm,
    )
    app.config["TESTING"] = True
    return app.test_client(), mock_tm, app


class TestTaskList:
    """GET /api/v1/tasks/"""

    def test_list_tasks_no_auth(self, task_app_client):
        client, _, _ = task_app_client
        resp = client.get("/api/v1/tasks/")
        assert resp.status_code == 401

    def test_list_tasks_with_auth(self, task_app_client):
        client, mock_tm, app = task_app_client
        # mock 返回任务列表
        mock_tm.list_tasks.return_value = [
            {"task_id": "test_task", "name": "Test Task", "enabled": True, "status": "running"}
        ]

        with app.app_context():
            from src.web.auth import generate_token
            token = generate_token(user_id=1, username="admin", role="admin", expire_hours=1)

        resp = client.get("/api/v1/tasks/",
                          headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["success"] is True
        assert len(data["data"]["tasks"]) == 1

    def test_pause_task(self, task_app_client):
        """POST /api/v1/tasks/test_task/pause"""
        client, mock_tm, app = task_app_client
        mock_task = MagicMock()
        mock_task.enabled = True
        mock_tm.get_task.return_value = mock_task

        with app.app_context():
            from src.web.auth import generate_token
            token = generate_token(user_id=1, username="admin", role="admin", expire_hours=1)

        resp = client.post("/api/v1/tasks/test_task/pause",
                           headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["success"] is True
        assert data["data"]["status"] == "paused"

    def test_task_not_found(self, task_app_client):
        """GET /api/v1/tasks/nonexistent"""
        client, mock_tm, app = task_app_client
        mock_tm.get_task.side_effect = KeyError()

        with app.app_context():
            from src.web.auth import generate_token
            token = generate_token(user_id=1, username="admin", role="admin", expire_hours=1)

        resp = client.get("/api/v1/tasks/nonexistent",
                          headers={"Authorization": f"Bearer {token}"})
        data = json.loads(resp.data)
        assert resp.status_code == 404
        assert data["error"]["code"] == "TASK_NOT_FOUND"


class TestAuthRBAC:
    """RBAC 权限测试."""

    def test_viewer_cannot_pause(self, task_app_client):
        """viewer 角色无权操作任务."""
        client, mock_tm, app = task_app_client
        mock_task = MagicMock()
        mock_task.enabled = True
        mock_tm.get_task.return_value = mock_task

        with app.app_context():
            from src.web.auth import generate_token
            token = generate_token(user_id=3, username="viewer", role="viewer", expire_hours=1)

        resp = client.post("/api/v1/tasks/test_task/pause",
                           headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403
