"""过滤空行，删除全为空的列（热插拔测试模板）"""
import pandas as pd

def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(how='all')
    df = df.dropna(axis=1, how='all')
    return df.reset_index(drop=True)
