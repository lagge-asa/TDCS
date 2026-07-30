"""
ETL Sandbox 清洗模板 — test_clean
协议：接收 List[dict] → 返回 List[dict]（非 pandas DataFrame）

清洗规则：
1. 过滤空 name 行
2. 填充缺失 value 为 0
3. 标准化 date 格式（非法 → None）
4. 钳制 score 到 0-100
5. status 全转小写，空填 'unknown'
"""
from datetime import datetime


def clean_data(rows: list) -> list:
    result = []
    for row in rows:
        # 1. 过滤空 name
        name = row.get("name", "")
        if not name or str(name).strip() == "" or str(name) == "None":
            continue

        # 2. 填充缺失 value
        try:
            value = float(row.get("value", 0) or 0)
        except (ValueError, TypeError):
            value = 0.0

        # 3. 标准化 date
        date_val = row.get("date", "")
        try:
            if date_val and str(date_val).strip():
                parsed = datetime.strptime(str(date_val)[:10], "%Y-%m-%d")
                date_val = parsed.strftime("%Y-%m-%d")
            else:
                date_val = None
        except (ValueError, IndexError):
            date_val = None

        # 4. 钳制 score
        try:
            score = int(float(row.get("score", 0) or 0))
            score = max(0, min(100, score))
        except (ValueError, TypeError):
            score = 0

        # 5. 标准化 status
        status = str(row.get("status", "")).lower().strip()
        if status in ("", "none", "nan"):
            status = "unknown"

        result.append({
            "id": row.get("id", ""),
            "name": str(name).strip(),
            "value": value,
            "date": date_val,
            "status": status,
            "score": score,
        })

    return result
