"""任务管理 API"""
from flask import Blueprint, jsonify, request, current_app
from ..auth import require_auth

bp = Blueprint("tasks", __name__)


@bp.get("/")
@require_auth("viewer")
def list_tasks():
    cm = current_app.config["config_manager"]
    tasks = [
        {"task_id": t.task_id, "name": t.name, "enabled": t.enabled}
        for t in cm.config.tasks
    ]
    return jsonify({"tasks": tasks})


def _get_tm_or_404(task_id):
    tm = current_app.config.get("task_manager")
    cm = current_app.config.get("config_manager")
    if not tm or not cm or not cm.get_task(task_id):
        return None, (jsonify({"error": "Task not found"}), 404)
    return tm, None


@bp.post("/<task_id>/pause")
@require_auth("operator")
def pause_task(task_id):
    tm, err = _get_tm_or_404(task_id)
    if err: return err
    tm.pause_task(task_id)
    return jsonify({"status": "paused"})


@bp.post("/<task_id>/resume")
@require_auth("operator")
def resume_task(task_id):
    tm, err = _get_tm_or_404(task_id)
    if err: return err
    tm.resume_task(task_id)
    return jsonify({"status": "resumed"})


@bp.post("/<task_id>/trigger")
@require_auth("operator")
def trigger_task(task_id):
    tm, err = _get_tm_or_404(task_id)
    if err: return err
    tm.trigger_task(task_id)
    return jsonify({"status": "triggered"})
