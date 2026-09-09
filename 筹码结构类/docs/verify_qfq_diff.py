# -*- coding: utf-8 -*-
"""验证：akshare 前复权(同花顺口径) vs 数据库 front 字段，量化差异"""
import sys
sys.path.insert(0, r"D:\量化k线\筹码结构类")
import duckdb
import akshare as ak
import pandas as pd

# 1) akshare 前复权全量（覆盖筹码窗口）——带重试
import time
ak_df = None
for attempt in range(5):
    try:
        ak_df = ak.stock_zh_a_hist(
            symbol="000001", period="daily",
            start_date="20240101", end_date="20260909",
            adjust="qfq",
        )
        if ak_df is not None and len(ak_df) > 0:
            break
    except Exception as e:
        print(f"akshare 第{attempt+1}次失败: {type(e).__name__}，3秒后重试")
        time.sleep(3)
if ak_df is None or len(ak_df) == 0:
    raise SystemExit("akshare 拉取失败")
ak_df["日期"] = pd.to_datetime(ak_df["日期"]).dt.strftime("%Y-%m-%d")
ak_map = ak_df.set_index("日期")

# 2) 数据库 front
con = duckdb.connect(r"D:\khData\SZ\000001.db", read_only=True)
db = con.execute("""SELECT CAST(time AS DATE) AS d, open, close, open_front, close_front, update_time
                    FROM kline_1d WHERE time >= '2024-01-01' ORDER BY time""").fetchdf()
con.close()
db["d"] = db["d"].astype(str)

# 3) 逐日对比
merged = db.merge(ak_map[["开盘", "收盘"]], left_on="d", right_index=True, how="inner")
merged["front_偏差"] = merged["open_front"] - merged["开盘"]
merged["raw_偏差"] = merged["open"] - merged["开盘"]

print(f"对比 {len(merged)} 天（akshare qfq 为基准）")
print(f"数据库 front 与 akshare 前复权开盘价完全一致的天数: {(merged['front_偏差'].abs()<0.005).sum()}")
print(f"数据库 原始价 与 akshare 前复权开盘价完全一致的天数: {(merged['raw_偏差'].abs()<0.005).sum()}")
print(f"front 偏差非零样本（前 8 个）:")
diff = merged[merged["front_偏差"].abs() >= 0.005]
print(diff[["d", "open", "open_front", "开盘", "front_偏差"]].head(8).to_string())

# 4) 按 update_time 批次统计偏差
print("\n按写入批次统计 front 偏差:")
merged["批次"] = merged["update_time"].astype(str).str[:10]
g = merged.groupby("批次").apply(lambda x: pd.Series({
    "天数": len(x),
    "front正确": int((x["front_偏差"].abs() < 0.005).sum()),
    "front错误": int((x["front_偏差"].abs() >= 0.005).sum()),
}), include_groups=False)
print(g.to_string())

# 5) 换手率样例
print("\nakshare 换手率样例（2026-05-06 ~ 05-13）:")
print(ak_df[ak_df["日期"].between("2026-05-06", "2026-05-13")][["日期", "换手率"]].to_string())
