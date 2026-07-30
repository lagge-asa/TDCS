"""
沙箱子进程入口

从 stdin 读取 JSON 行数据, 调用用户清洗函数, 结果写入 stdout.
此脚本在隔离子进程中运行, 无法访问父进程环境变量.

输出协议:
  成功: {"rows": [...], "original": N, "cleaned": N, "columns": [...]}
  失败: {"error": "message"}  (写入 stdout, exit 0)
  致命: exit(1) + stderr traceback
"""

import sys
import json
import importlib
import traceback


def main():
    if len(sys.argv) < 4:
        print("Usage: _sandbox_runner.py <module> <func> <etl_dir>",
              file=sys.stderr)
        sys.exit(1)

    module_name = sys.argv[1]
    func_name = sys.argv[2]
    etl_dir = sys.argv[3]

    sys.path.insert(0, etl_dir)

    # 读取输入
    try:
        rows = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON input: {e}"}), file=sys.stdout)
        sys.exit(0)

    # 导入模块
    try:
        mod = importlib.import_module(module_name)
    except ImportError as e:
        print(json.dumps({"error": f"ImportError: {e}"}), file=sys.stdout)
        sys.exit(0)

    # 获取函数
    func = getattr(mod, func_name, None)
    if func is None:
        print(json.dumps(
            {"error": f"Function '{func_name}' not found in module '{module_name}'"}
        ), file=sys.stdout)
        sys.exit(0)
    if not callable(func):
        print(json.dumps(
            {"error": f"'{func_name}' is not callable"}
        ), file=sys.stdout)
        sys.exit(0)

    # 执行
    try:
        result = func(rows)
        json.dump(result, sys.stdout, ensure_ascii=False)
    except Exception as e:
        print(json.dumps({
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        }), file=sys.stdout)
        sys.exit(0)


if __name__ == "__main__":
    main()
