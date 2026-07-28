"""自动识别列名含 date/time/日期/时间 的列，统一转为 YYYY-MM-DD 格式"""
import pandas as pd


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    date_keywords = ("date", "time", "日期", "时间", "dt", "ts")

    for col in df.columns:
        col_lower = col.lower()
        if any(kw in col_lower for kw in date_keywords):
            try:
                converted = pd.to_datetime(df[col], errors="coerce")
                valid_ratio = converted.notna().mean()
                if valid_ratio > 0.5:  # 超过50%能成功解析才转换
                    df[col] = converted.dt.strftime("%Y-%m-%d")
                    print(
                        f"[normalize_dates] 列 '{col}' 已标准化"
                        f"（有效率 {valid_ratio:.0%}）",
                        flush=True,
                    )
            except Exception as e:
                print(f"[normalize_dates] 列 '{col}' 转换失败: {e}", flush=True)

    return df
