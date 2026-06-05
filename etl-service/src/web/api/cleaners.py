"""
清洗模板 API

GET  /api/v1/cleaners/           → 所有模板列表（热插拔，实时）
GET  /api/v1/cleaners/<name>     → 单模板详情 + 源码预览
POST /api/v1/cleaners/run        → 上传文件 + 选模板 → 清洗结果
GET  /api/v1/cleaners/download/<token> → 下载完整清洗结果 CSV
POST /api/v1/cleaners/<name>/validate  → 语法检查（保留原有）
"""

import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from flask import Blueprint, Response, current_app, jsonify, request, send_file

from ..auth import require_auth

logger = logging.getLogger(__name__)
bp = Blueprint("cleaners", __name__)

# 临时下载文件存活时间（秒）
_DOWNLOAD_TTL = 1800  # 30分钟
# 运行时上传文件大小限制
_MAX_UPLOAD_MB = 20

# 内存中暂存下载任务 {token: (csv_bytes, filename, expire_ts)}
_download_store: dict = {}
_download_lock = threading.Lock()  # 保护 _download_store 多线程并发读写

_CLEANER_RUNNER = Path(__file__).parent.parent.parent / "etl" / "_cleaner_runner.py"

# 敏感环境变量关键词（用 'in' 包含检查，覆盖前缀/中缀/后缀）
_SENSITIVE_KEYWORDS = (
    "ETL_", "SECRET", "PASSWORD", "PASSWD", "TOKEN",
    "API_KEY", "APIKEY", "AWS_", "ENCRYPTION", "PRIVATE",
    "CREDENTIAL", "DB_PASS", "MYSQL_", "REDIS_PASS",
)


def _build_subprocess_env() -> dict:
    """构建子进程环境变量：保留 Windows 系统必要变量，过滤敏感凭证。"""
    env = {}
    for k, v in os.environ.items():
        upper = k.upper()
        if any(kw in upper for kw in _SENSITIVE_KEYWORDS):
            continue
        env[k] = v
    # 确保 Python 子进程能正确编码
    env["PYTHONIOENCODING"] = "utf-8"
    return env


# 防止 Flask reloader / pytest import 时重复启动后台线程
_purge_thread_started = False


def _start_purge_thread():
    """启动后台定时清理线程（每 5 分钟清理过期下载令牌），模块生命周期内只启动一次。"""
    global _purge_thread_started
    if _purge_thread_started:
        return
    _purge_thread_started = True

    def _loop():
        while True:
            time.sleep(300)
            _purge_expired_downloads()
    t = threading.Thread(target=_loop, daemon=True, name="CleanerTokenPurge")
    t.start()


_start_purge_thread()


# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────

def _get_registry():
    """从 Flask app.config 获取 CleanerRegistry 实例。"""
    reg = current_app.config.get("cleaner_registry")
    if reg is None:
        raise RuntimeError("CleanerRegistry not initialized")
    return reg


def _run_cleaner_subprocess(script_path: Path, file_bytes: bytes,
                             fmt: str, timeout: int = 60) -> dict:
    """在子进程中执行清洗脚本，返回结果字典。"""
    proc = subprocess.Popen(
        [sys.executable, str(_CLEANER_RUNNER), str(script_path), fmt],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_build_subprocess_env(),
        text=True,
        encoding="utf-8",
    )
    try:
        stdout, stderr = proc.communicate(
            input=file_bytes.decode("utf-8", errors="replace"),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise TimeoutError(f"清洗脚本执行超时（>{timeout}s）")

    if proc.returncode != 0 and not stdout.strip():
        raise RuntimeError(f"子进程异常退出: {stderr[:500]}")

    try:
        result = json.loads(stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"子进程输出非法 JSON: {stdout[:300]}")

    if "error" in result:
        raise RuntimeError(result["error"])

    return result


def _purge_expired_downloads():
    """清理过期下载令牌（线程安全）。"""
    now = time.time()
    with _download_lock:
        expired = [k for k, v in _download_store.items() if v[2] < now]
        for k in expired:
            del _download_store[k]
        if expired:
            logger.debug("Purged %d expired download token(s)", len(expired))


# ─────────────────────────────────────────────────────────────────────────────
# 路由
# ─────────────────────────────────────────────────────────────────────────────

@bp.get("/")
@require_auth("viewer")
def list_templates():
    """返回所有可用清洗模板列表（实时，热插拔）。"""
    reg = _get_registry()
    templates = reg.list_templates()
    return jsonify({
        "templates": templates,
        "count": len(templates),
        "valid_count": sum(1 for t in templates if t["valid"]),
        "templates_dir": str(reg.get_templates_dir()),
    })


@bp.get("/<name>")
@require_auth("viewer")
def get_template(name: str):
    """返回单个模板详情 + 源码。"""
    reg = _get_registry()
    templates = reg.list_templates()
    info = next((t for t in templates if t["name"] == name), None)
    if not info:
        return jsonify({"error": f"模板 '{name}' 不存在"}), 404

    source = reg.get_source(name) or ""
    return jsonify({**info, "source": source})


@bp.post("/run")
@require_auth("operator")
def run_cleaner():
    """
    上传文件 + 选择模板 → 执行清洗 → 返回预览 + 下载令牌。

    form-data:
        file:     CSV 或 Excel 文件（最大 20MB）
        template: 模板名称（不含 .py）
        preview:  true/false（默认 true，只返回前 50 行）
    """
    _purge_expired_downloads()

    # ── 参数校验 ──────────────────────────────────────────────────────────
    if "file" not in request.files:
        return jsonify({"error": "缺少上传文件字段 'file'"}), 400
    if "template" not in request.form:
        return jsonify({"error": "缺少模板名称字段 'template'"}), 400

    uploaded = request.files["file"]
    template_name = request.form["template"].strip()
    preview_only = request.form.get("preview", "true").lower() != "false"

    if not uploaded.filename:
        return jsonify({"error": "文件名为空"}), 400

    # 文件大小限制：先检查 content_length 再读入内存，超限直接拒绝
    content_length = request.content_length or 0
    if content_length > _MAX_UPLOAD_MB * 1024 * 1024:
        return jsonify({"error": f"文件超过 {_MAX_UPLOAD_MB}MB 限制"}), 413

    file_bytes = uploaded.read()
    # 再次检查实际读取大小（content_length 可能不可信或为零）
    if len(file_bytes) > _MAX_UPLOAD_MB * 1024 * 1024:
        return jsonify({"error": f"文件超过 {_MAX_UPLOAD_MB}MB 限制"}), 413

    # 检测格式
    fname = uploaded.filename.lower()
    if fname.endswith(".csv"):
        fmt = "csv"
    elif fname.endswith((".xlsx", ".xls")):
        fmt = "excel"
        # Excel → CSV 转换（子进程只处理 csv/json）
        try:
            import io as _io
            import pandas as pd
            df = pd.read_excel(_io.BytesIO(file_bytes))
            file_bytes = df.to_csv(index=False).encode("utf-8")
            fmt = "csv"
        except Exception as e:
            return jsonify({"error": f"Excel 解析失败: {e}"}), 400
    else:
        return jsonify({"error": "仅支持 .csv / .xlsx / .xls 格式"}), 400

    # ── 获取模板路径 ───────────────────────────────────────────────────────
    reg = _get_registry()
    script_path = reg.get_path(template_name)
    if script_path is None:
        return jsonify({"error": f"模板 '{template_name}' 不存在或语法无效"}), 404

    # ── 执行清洗 ──────────────────────────────────────────────────────────
    t0 = time.monotonic()
    try:
        result = _run_cleaner_subprocess(script_path, file_bytes, fmt)
    except TimeoutError as e:
        return jsonify({"error": str(e)}), 408
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 422
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    rows = result.get("rows", [])
    columns = result.get("columns", [])
    original = result.get("original", 0)
    cleaned = result.get("cleaned", len(rows))
    dropped = result.get("dropped", original - cleaned)

    # ── 生成下载令牌 ───────────────────────────────────────────────────────
    download_token = None
    if rows:
        import csv as _csv
        buf = io.StringIO()
        writer = _csv.DictWriter(buf, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
        csv_bytes = buf.getvalue().encode("utf-8")
        download_token = str(uuid.uuid4()).replace("-", "")
        expire_ts = time.time() + _DOWNLOAD_TTL
        clean_fname = f"cleaned_{template_name}_{int(time.time())}.csv"
        with _download_lock:
            _download_store[download_token] = (csv_bytes, clean_fname, expire_ts)

    preview = rows[:50] if preview_only else rows

    return jsonify({
        "template": template_name,
        "original_rows": original,
        "cleaned_rows": cleaned,
        "dropped_rows": dropped,
        "elapsed_ms": elapsed_ms,
        "columns": columns,
        "preview": preview,
        "download_token": download_token,
        "download_url": f"/api/v1/cleaners/download/{download_token}" if download_token else None,
    })


@bp.get("/download/<token>")
@require_auth("viewer")
def download_result(token: str):
    """下载完整清洗结果 CSV（令牌一次性消费，取走即删）。"""
    with _download_lock:
        entry = _download_store.get(token)
        # 统一判断：不存在或已过期
        if not entry or time.time() > entry[2]:
            _download_store.pop(token, None)
            return jsonify({"error": "下载令牌不存在或已过期（30分钟有效）"}), 404
        # 一次性消费：取走后立即删除，防止 token 泄露后被重放
        csv_bytes, filename, _ = _download_store.pop(token)

    # 过滤 filename 中可能导致 HTTP Header Injection 的字符
    safe_filename = filename.replace('"', '').replace('\r', '').replace('\n', '')

    return Response(
        csv_bytes,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


@bp.post("/<name>/validate")
@require_auth("operator")
def validate_cleaner(name: str):
    """语法检查：检查脚本是否包含 clean_data 函数且语法正确。"""
    data = request.get_json() or {}
    code = data.get("code", "")
    if not code:
        # 如果没传 code，检查注册中心里的模板
        reg = _get_registry()
        source = reg.get_source(name)
        if source is None:
            return jsonify({"valid": False, "message": f"模板 '{name}' 不存在"}), 404
        code = source

    import ast as _ast
    try:
        tree = _ast.parse(code)
        has_func = any(
            isinstance(node, _ast.FunctionDef) and node.name == "clean_data"
            for node in _ast.walk(tree)
        )
        if not has_func:
            return jsonify({"valid": False, "message": "未找到 def clean_data(df) 函数"})
        return jsonify({"valid": True, "message": "语法检查通过"})
    except SyntaxError as e:
        return jsonify({"valid": False, "message": f"语法错误: {e}"})
