"""
Swagger UI — 交互式 API 文档 (/docs)

实现类似 FastAPI 的自动 API 文档体验。
"""

from flask import Blueprint, jsonify, send_file
import json
import os

bp = Blueprint("swagger", __name__)

# OpenAPI 3.0 spec
_SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": "TDCS ETL Service API",
        "version": "2.0.0",
        "description": "定时数据采集服务 — 管理面板 REST API",
        "contact": {"name": "TDCS Team"},
    },
    "servers": [{"url": "/", "description": "当前服务器"}],
    "security": [{"bearerAuth": []}],
    "components": {
        "securitySchemes": {
            "bearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "JWT Token，通过 /api/v1/auth/login 获取",
            }
        },
        "schemas": {
            "Error": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean", "example": False},
                    "error": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "example": "TASK_NOT_FOUND"},
                            "message": {"type": "string", "example": "任务不存在"},
                        },
                    },
                },
            },
            "Success": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean", "example": True},
                    "data": {"type": "object"},
                },
            },
            "Paginated": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean", "example": True},
                    "data": {"type": "array", "items": {"type": "object"}},
                    "meta": {
                        "type": "object",
                        "properties": {
                            "page": {"type": "integer"},
                            "page_size": {"type": "integer"},
                            "total": {"type": "integer"},
                            "total_pages": {"type": "integer"},
                        },
                    },
                },
            },
        },
    },
    "paths": {
        "/health": {
            "get": {
                "tags": ["系统"],
                "summary": "健康检查",
                "responses": {"200": {"description": "服务正常"}},
            }
        },
        "/metrics": {
            "get": {
                "tags": ["系统"],
                "summary": "Prometheus 指标",
                "responses": {"200": {"description": "Prometheus 格式指标"}},
            }
        },
        "/api/v1/auth/login": {
            "post": {
                "tags": ["认证"],
                "summary": "用户登录",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["username", "password"],
                                "properties": {
                                    "username": {"type": "string", "example": "admin"},
                                    "password": {"type": "string", "format": "password"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {"description": "登录成功，返回 JWT token"},
                    "401": {"$ref": "#/components/responses/Unauthorized"},
                    "429": {"description": "登录频率限制"},
                },
            }
        },
        "/api/v1/tasks/": {
            "get": {
                "tags": ["任务管理"],
                "summary": "获取所有任务",
                "responses": {"200": {"$ref": "#/components/responses/TaskList"}},
            }
        },
        "/api/v1/tasks/{task_id}": {
            "get": {
                "tags": ["任务管理"],
                "summary": "获取单个任务详情",
                "parameters": [{"name": "task_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "任务详情"}, "404": {"$ref": "#/components/responses/NotFound"}},
            }
        },
        "/api/v1/tasks/{task_id}/pause": {
            "post": {
                "tags": ["任务管理"],
                "summary": "暂停任务",
                "parameters": [{"name": "task_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "已暂停"}},
            }
        },
        "/api/v1/tasks/{task_id}/resume": {
            "post": {
                "tags": ["任务管理"],
                "summary": "恢复任务",
                "parameters": [{"name": "task_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "已恢复"}},
            }
        },
        "/api/v1/tasks/{task_id}/trigger": {
            "post": {
                "tags": ["任务管理"],
                "summary": "手动触发任务",
                "parameters": [{"name": "task_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "已触发"}},
            }
        },
        "/api/v1/files/": {
            "get": {
                "tags": ["文件管理"],
                "summary": "获取文件列表",
                "parameters": [
                    {"name": "task_id", "in": "query", "schema": {"type": "string"}, "description": "按任务过滤"},
                    {"name": "status", "in": "query", "schema": {"type": "string"}, "description": "按状态过滤"},
                    {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                    {"name": "page_size", "in": "query", "schema": {"type": "integer", "default": 50}},
                ],
                "responses": {"200": {"$ref": "#/components/responses/Paginated"}},
            }
        },
        "/api/v1/dashboard/": {
            "get": {
                "tags": ["仪表盘"],
                "summary": "获取仪表盘概览",
                "responses": {"200": {"description": "仪表盘数据"}},
            }
        },
        "/api/v1/quality/": {
            "get": {
                "tags": ["数据质量"],
                "summary": "获取质量报告",
                "parameters": [
                    {"name": "task_id", "in": "query", "schema": {"type": "string"}},
                    {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                ],
                "responses": {"200": {"$ref": "#/components/responses/Paginated"}},
            }
        },
        "/api/v1/monthly/": {
            "get": {
                "tags": ["月表管理"],
                "summary": "获取月表列表",
                "parameters": [{"name": "task_id", "in": "query", "schema": {"type": "string"}}],
                "responses": {"200": {"description": "月表列表"}},
            }
        },
        "/api/v1/config/": {
            "get": {
                "tags": ["系统配置"],
                "summary": "获取当前配置",
                "responses": {"200": {"description": "配置信息"}},
            }
        },
        "/api/v1/config/reload": {
            "put": {
                "tags": ["系统配置"],
                "summary": "热重载配置",
                "responses": {"200": {"description": "配置已重载"}},
            }
        },
        "/api/v1/users/": {
            "get": {
                "tags": ["用户管理"],
                "summary": "获取用户列表",
                "responses": {"200": {"description": "用户列表"}},
            }
        },
        "/api/v1/audit/": {
            "get": {
                "tags": ["审计日志"],
                "summary": "获取审计日志",
                "parameters": [{"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}}],
                "responses": {"200": {"$ref": "#/components/responses/Paginated"}},
            }
        },
        "/api/v1/cleaners/": {
            "get": {
                "tags": ["清洗工作台"],
                "summary": "获取清洗模板列表",
                "responses": {"200": {"description": "模板列表"}},
            }
        },
    },
}

# 添加公共响应引用（必须在 paths 之后以避免循环引用）
_SPEC["components"]["responses"] = {
    "Unauthorized": {"description": "未认证", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
    "NotFound": {"description": "资源不存在", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
    "TaskList": {"description": "任务列表", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Success"}}}},
    "Paginated": {"description": "分页数据", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Paginated"}}}},
}


@bp.get("/openapi.json")
def openapi_spec():
    """OpenAPI 3.0 规范 JSON."""
    return jsonify(_SPEC)


@bp.get("/docs")
def swagger_ui():
    """Swagger UI 交互式 API 文档."""
    return """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>TDCS API 文档 — Swagger UI</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
  <style>
    html { box-sizing: border-box; overflow: -moz-scrollbars-vertical; overflow-y: scroll; }
    *, *:before, *:after { box-sizing: inherit; }
    body { margin: 0; background: #fafafa; }
    .swagger-ui .topbar { background-color: #1a1a2e; }
    .swagger-ui .topbar .download-url-wrapper .select-label { color: #e2e8f0; }
    .swagger-ui .topbar a { color: #38bdf8; }
    .swagger-ui .info .title { color: #0f172a; }
    .swagger-ui .scheme-container { background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.1); }
    .swagger-ui .opblock-tag { color: #0f172a; }
    .swagger-ui .opblock.opblock-get { background: rgba(97,175,254,.1); border-color: #61affe; }
    .swagger-ui .opblock.opblock-post { background: rgba(73,204,144,.1); border-color: #49cc90; }
    .swagger-ui .opblock.opblock-put { background: rgba(252,161,48,.1); border-color: #fca130; }
    .swagger-ui .btn.authorize { background: #38bdf8; border-color: #38bdf8; color: #fff; }
    .swagger-ui .btn.authorize:hover { background: #0ea5e9; }
    .swagger-ui .btn.authorize svg { fill: #fff; }
  </style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js" crossorigin></script>
  <script>
    SwaggerUIBundle({
      url: "/openapi.json",
      dom_id: "#swagger-ui",
      deepLinking: true,
      presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
      layout: "StandaloneLayout",
      defaultModelsExpandDepth: -1,
      docExpansion: "list",
      filter: true,
      tryItOutEnabled: true,
    });
  </script>
</body>
</html>
"""
