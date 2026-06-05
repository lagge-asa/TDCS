"""字符串列去首尾空格，数值列填 0，文本列填空字符串，删除全空行"""
import pandas as pd


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    # 删除全空行
    df = df.dropna(how="all")

    for col in df.columns:
        if df[col].dtype == object:
            # 字符串：去空格 + 空值填 ""
            df[col] = df[col].astype(str).str.strip()
            df[col] = df[col].replace({"nan": "", "None": "", "NaN": ""})
        elif pd.api.types.is_numeric_dtype(df[col]):
            # 数值：填 0
            df[col] = df[col].fillna(0)

    print(f"[fillna_and_trim] 处理完成，共 {len(df)} 行", flush=True)
    return df.reset_index(drop=True)
