"""
trace_id 上下文管理

使用 ContextVar 实现跨线程/协程的 trace 传递，
避免 threading.local 在线程池复用时 trace_id 串扰。

用法:
    from src.utils.trace import new_trace, get_trace_id, get_task_id

    # 开始一个新的 trace
    new_trace(task_id="order_import")
    # 后续日志自动包含 trace_id 和 task_id
"""

from contextvars import ContextVar
import uuid


# ContextVar 在 asyncio 和 threading 场景下均可正确隔离
_trace_id: ContextVar[str] = ContextVar("trace_id", default="")
_task_id: ContextVar[str] = ContextVar("task_id", default="")


def new_trace(task_id: str = "") -> str:
    """创建新的 trace，返回 trace_id。

    每次调用生成唯一 trace_id，同时绑定 task_id。
    同一线程内后续 get_trace_id() / get_task_id() 均返回此值。
    """
    tid = uuid.uuid4().hex[:16]
    _trace_id.set(tid)
    _task_id.set(task_id)
    return tid


def get_trace_id() -> str:
    """获取当前 trace_id。"""
    return _trace_id.get()


def get_task_id() -> str:
    """获取当前 task_id。"""
    return _task_id.get()


def set_trace_id(trace_id: str) -> None:
    """显式设置 trace_id（用于跨线程传递场景）。"""
    _trace_id.set(trace_id)


def set_task_id(task_id: str) -> None:
    """显式设置 task_id（用于跨线程传递场景）。"""
    _task_id.set(task_id)
