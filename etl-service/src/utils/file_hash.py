"""
文件快速哈希工具

取文件头 4KB + 尾 4KB + 文件大小 做 MD5,
适用于大文件增量检测, 不读全量.
"""

import hashlib


def quick_hash(file_path: str, size: int) -> str:
    """对文件取首尾各 4KB + 文件大小的 MD5 摘要.

    Args:
        file_path: 文件路径
        size: 文件大小 (字节)

    Returns:
        32 字符 hex MD5 摘要
    """
    h = hashlib.md5()
    with open(file_path, "rb") as f:
        h.update(f.read(4096))
        if size > 8192:
            f.seek(-4096, 2)
            h.update(f.read(4096))
    h.update(str(size).encode())
    return h.hexdigest()
