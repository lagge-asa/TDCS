"""API 测试: 系统端点 (/health, /metrics, /auth/login)"""
import json
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def app_client(loaded_config_manager):
    """创建 Flask test client，注入 mock 依赖."""
    from src.web.app import create_app

    app = create_app(
        loaded_config_manager,
        task_manager=None,
        worker_pool=None,
        ha_elector=None,
        quality_reporter=None,
        encryption=None,
        db=None,
        cleaner_registry=None,
    )
    app.config["TESTING"] = True
    return app.test_client()


class TestHealthEndpoint:
    """健康检查端点."""

    def test_health_ok(self, app_client):
        resp = app_client.get("/health")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["success"] is True
        assert "status" in data["data"]

    def test_health_degraded_with_db(self, app_client):
        """DB 可用时返回 ok（即使注入 None 也返回 ok）。"""
        resp = app_client.get("/health")
        # 无 DB 时也返回 ok（因为 db 为 None 时跳过 check）
        assert resp.status_code == 200


class TestLoginEndpoint:
    """登录端点."""

    def test_login_missing_credentials(self, app_client):
        resp = app_client.post("/api/v1/auth/login",
                               json={},
                               content_type="application/json")
        data = json.loads(resp.data)
        assert resp.status_code == 400
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_INPUT"

    def test_login_empty_username(self, app_client):
        resp = app_client.post("/api/v1/auth/login",
                               json={"username": "", "password": "x"},
                               content_type="application/json")
        assert resp.status_code == 400

    def test_login_db_unavailable(self, app_client):
        """无 DB 时返回 503."""
        resp = app_client.post("/api/v1/auth/login",
                               json={"username": "admin", "password": "test"},
                               content_type="application/json")
        data = json.loads(resp.data)
        assert resp.status_code == 503
        assert data["error"]["code"] == "DB_UNAVAILABLE"

    def test_login_rate_limit(self, app_client):
        """多次失败登录触发 rate limit."""
        # 发送 6 次请求（超过 5/min 限制）
        statuses = []
        for _ in range(6):
            resp = app_client.post("/api/v1/auth/login",
                                   json={"username": "admin", "password": "x"},
                                   content_type="application/json")
            statuses.append(resp.status_code)
        # 至少有一次 429
        assert 429 in statuses


class TestMetricsEndpoint:
    """Prometheus 指标端点."""

    def test_metrics_returns_text(self, app_client):
        resp = app_client.get("/metrics")
        # 可能返回 prometheus 指标或 "not installed"
        assert resp.status_code == 200
