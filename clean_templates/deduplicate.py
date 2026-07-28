"""去除完全重复的行（保留第一条）"""
import pandas as pd


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    before = len(df)
    df = df.drop_duplicates(keep="first")
    dropped = before - len(df)
    print(f"[deduplicate] {before} → {len(df)} 行，去重 {dropped} 条", flush=True)
    return df.reset_index(drop=True)
