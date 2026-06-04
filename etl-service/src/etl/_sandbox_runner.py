"""
沙箱子进程入口

从 stdin 读取 JSON 行数据, 调用用户清洗函数, 结果写入 stdout.
此脚本在隔离子进程中运行, 无法访问父进程环境变量.
"""

import sys
import json
import importlib


def main():
    if len(sys.argv) < 4:
        print("Usage: _sandbox_runner.py <module> <func> <etl_dir>",
              file=sys.stderr)
        sys.exit(1)

    module_name = sys.argv[1]
    func_name = sys.argv[2]
    etl_dir = sys.argv[3]

    sys.path.insert(0, etl_dir)

    rows = json.load(sys.stdin)
    mod = importlib.import_module(module_name)
    func = getattr(mod, func_name)
    result = func(rows)
    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
