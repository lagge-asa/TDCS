"""
文件标识值对象 — FileRef

将 (task_id, file_path, file_mtime, file_size, file_hash) 五元组
提炼为不可变值对象。消除 state_tracker、file_processor、worker_pool
之间裸参数传递的数据泥团。

用法:
    ref = FileRef("order_import", "/data/orders.csv", 1719000000000, 4096, "a1b2c3")
    state_tracker.try_claim(ref, max_retries=3)
"""

from dataclasses import dataclass
import hashlib
import os


@dataclass(frozen=True)
class FileRef:
    """不可变文件引用。task_id + file_path + file_mtime 构成业务唯一键。"""
    task_id: str
    file_path: str
    file_mtime: int   # 毫秒时间戳
    file_size: int
    file_hash: str

    @classmethod
    def from_stat(cls, task_id: str, file_path: str, stat: os.stat_result) -> "FileRef":
        """从 os.stat() 结果构造 FileRef，封装 mtime 转换和哈希计算."""
        h = hashlib.md5()
        with open(file_path, "rb") as f:
            h.update(f.read(4096))
            if stat.st_size > 8192:
                f.seek(-4096, 2)
                h.update(f.read(4096))
        h.update(str(stat.st_size).encode())
        return cls(
            task_id=task_id,
            file_path=file_path,
            file_mtime=int(stat.st_mtime * 1000),
            file_size=stat.st_size,
            file_hash=h.hexdigest()[:16],
        )
