"""
测试数据清洗模板 — test_clean

清洗规则：
1. 过滤空 name 行
2. 填充缺失 value 为 0
3. 标准化 date 格式（非法日期 → None）
4. 钳制 score 到 0-100
5. status 全转小写，空值填 'unknown'
"""

import pandas as pd
from datetime import datetime


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    # 1. 过滤空 name
    df = df[df["name"].notna() & (df["name"].astype(str).str.strip() != "")]
    df = df[df["name"] != "None"]

    # 2. 填充缺失 value
    df["value"] = pd.to_numeric(df["value"], errors="coerce").fillna(0)

    # 3. 标准化 date
    def _parse_date(val):
        try:
            if pd.isna(val) or str(val).strip() == "":
                return None
            return datetime.strptime(str(val)[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
        except (ValueError, IndexError):
            return None

    df["date"] = df["date"].apply(_parse_date)

    # 4. 钳制 score
    df["score"] = pd.to_numeric(df["score"], errors="coerce").fillna(0).clip(0, 100).astype(int)

    # 5. 标准化 status
    df["status"] = df["status"].astype(str).str.lower().str.strip()
    df.loc[df["status"].isin(["", "none", "nan"]), "status"] = "unknown"

    return df
