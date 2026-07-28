"""
Cleaner subprocess entry point.

Protocol:
  argv[1] = absolute path to template script
  argv[2] = input format: csv | json
  stdin   = file content (UTF-8 text)
  stdout  = JSON: {"rows": [...], "original": N, "cleaned": N}
  stderr  = debug / error messages
"""

import io
import json
import sys
import traceback


def main():
    if len(sys.argv) < 3:
        print(
            '{"error": "Usage: _cleaner_runner.py <script_path> <fmt>"}',
            file=sys.stdout,
        )
        sys.exit(1)

    script_path = sys.argv[1]
    fmt = sys.argv[2].lower()

    raw = sys.stdin.read()

    try:
        import pandas as pd
    except ImportError:
        print(
            json.dumps({"error": "pandas is not installed"}),
            file=sys.stdout,
        )
        sys.exit(1)

    # parse input
    try:
        if fmt == "csv":
            df = pd.read_csv(io.StringIO(raw))
        elif fmt == "json":
            data = json.loads(raw)
            df = pd.DataFrame(data if isinstance(data, list) else [data])
        else:
            raise ValueError(f"Unsupported format: {fmt}")
    except Exception as e:
        print(
            json.dumps({"error": f"Failed to parse input as {fmt}: {e}"}),
            file=sys.stdout,
        )
        sys.exit(1)

    original_rows = len(df)

    # load template
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_user_cleaner", script_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        print(
            json.dumps({"error": f"Failed to load template: {e}"}),
            file=sys.stdout,
        )
        sys.exit(1)

    if not hasattr(mod, "clean_data"):
        print(
            json.dumps({"error": "Template has no clean_data(df) function"}),
            file=sys.stdout,
        )
        sys.exit(1)

    # redirect user print() to stderr so stdout stays clean JSON
    import builtins as _builtins
    _orig_print = _builtins.print

    def _stderr_print(*args, **kwargs):
        if kwargs.get("file") is None or kwargs.get("file") is sys.stdout:
            kwargs["file"] = sys.stderr
        _orig_print(*args, **kwargs)

    _builtins.print = _stderr_print
    try:
        result_df = mod.clean_data(df)
    except Exception:
        tb = traceback.format_exc()
        _builtins.print = _orig_print
        print(
            json.dumps({"error": f"clean_data() raised exception:\n{tb}"}),
            file=sys.stdout,
        )
        sys.exit(1)
    finally:
        _builtins.print = _orig_print

    # handle non-DataFrame return
    if not isinstance(result_df, pd.DataFrame):
        try:
            result_df = pd.DataFrame(result_df)
        except Exception:
            print(
                json.dumps({"error": "clean_data() must return a pandas DataFrame"}),
                file=sys.stdout,
            )
            sys.exit(1)

    # serialize output
    try:
        result_df = result_df.where(result_df.notna(), other=None)
        rows = result_df.to_dict(orient="records")
        columns = list(result_df.columns)
        output = {
            "original": original_rows,
            "cleaned": len(rows),
            "dropped": original_rows - len(rows),
            "columns": columns,
            "rows": rows,
        }
        print(json.dumps(output, ensure_ascii=False, default=str))
    except Exception as e:
        print(
            json.dumps({"error": f"Failed to serialize result: {e}"}),
            file=sys.stdout,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
