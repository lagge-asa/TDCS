# 清洗模板目录 (clean_templates/)

## 热插拔说明

此目录下的每个 `.py` 文件都是一个独立的清洗模板。
**无需重启服务**，直接在此目录中：

- **新增** `.py` 文件 → 前端下拉框自动出现
- **修改** `.py` 文件 → 下次运行时自动使用新版本
- **删除** `.py` 文件 → 前端下拉框自动消失

## 模板编写规范

每个模板文件必须包含以下入口函数：

```python
def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    # 你的清洗逻辑
    return df
```

- **入参**：`df` — pandas DataFrame（从上传的 CSV/Excel 自动转换）
- **返回**：清洗后的 pandas DataFrame
- **文件顶部的 docstring** 会作为模板说明显示在前端

## 示例模板

| 文件 | 说明 |
|------|------|
| `deduplicate.py` | 去除完全重复的行 |
| `fillna_and_trim.py` | 填充缺失值 + 字符串去空格 |
| `normalize_dates.py` | 日期列自动标准化为 YYYY-MM-DD |

## 自定义模板示例

```python
"""过滤掉 age 列中小于 18 的行"""
import pandas as pd

def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    if 'age' in df.columns:
        df = df[df['age'] >= 18]
    return df.reset_index(drop=True)
```

保存为 `filter_adults.py`，刷新前端即可看到新模板。
