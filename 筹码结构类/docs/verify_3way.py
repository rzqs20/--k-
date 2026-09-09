# -*- coding: utf-8 -*-
"""三方对比：我的 preClose 重算法 vs 数据库 front vs akshare qfq（真值基准）"""
import sys, time
sys.path.insert(0, r"D:\量化k线\筹码结构类")
import duckdb
import numpy as np
import pandas as pd
import akshare as ak

# 1) akshare qfq（真值）——带重试
ak_df = None
for attempt in range(8):
    try:
        ak_df = ak.stock_zh_a_hist(symbol="000001", period="daily",
                                   start_date="20240801", end_date="20260909", adjust="qfq")
        if ak_df is not None and len(ak_df) > 100:
            break
    except Exception as e:
        print(f"akshare 第{attempt+1}次失败: {type(e).__name__}")
        time.sleep(4)
if ak_df is None or len(ak_df) == 0:
    raise SystemExit("akshare 拉取失败")
ak_df["日期"] = pd.to_datetime(ak_df["日期"]).dt.strftime("%Y-%m-%d")
ak_map = ak_df.set_index("日期")
print(f"akshare 拉到 {len(ak_df)} 天")

# 2) 数据库
con = duckdb.connect(r"D:\khData\SZ\000001.db", read_only=True)
df = con.execute("""SELECT CAST(time AS DATE) AS d, open, high, low, close, preClose,
                    open_front, close_front FROM kline_1d WHERE time >= '2024-01-01' ORDER BY time""").fetchdf()
con.close()
df = df.sort_values("d").reset_index(drop=True)

# 3) preClose 因子重算
n = len(df)
factor = 1.0
factors = np.ones(n)
for i in range(n - 1, -1, -1):
    factors[i] = factor
    if i > 0:
        pc = df.loc[i, "preClose"]; prev_c = df.loc[i - 1, "close"]
        if pd.notna(pc) and pd.notna(prev_c) and pc > 0 and prev_c > 0:
            ratio = pc / prev_c
            if ratio < 0.995 and ratio >= 0.5:
                factor *= ratio
df["open_recalc"] = df["open"] * factors

# 4) 三方对比（open 口径）
m = df.merge(ak_map[["开盘"]], left_on="d", right_index=True, how="inner")
m["db_err"] = m["open_front"] - m["开盘"]
m["recalc_err"] = m["open_recalc"] - m["开盘"]
print(f"对比 {len(m)} 天（akshare 为真值）")
print(f"数据库 front 平均绝对误差: {m['db_err'].abs().mean():.4f}，一致天数(<0.005): {(m['db_err'].abs()<0.005).sum()}")
print(f"重算 front 平均绝对误差: {m['recalc_err'].abs().mean():.4f}，一致天数(<0.005): {(m['recalc_err'].abs()<0.005).sum()}")

print("\n关键日期对比:")
for t in ["2024-08-19", "2025-04-30", "2026-04-30", "2026-05-06", "2026-06-12", "2026-09-09"]:
    row = m[m["d"] == t]
    if len(row):
        r = row.iloc[0]
        print(f"{t}: akshare={r['开盘']:.3f} | 重算={r['open_recalc']:.3f} | 数据库front={r['open_front']:.3f}")

# 误差大的日期
print("\n重算误差 > 0.05 的日期（前10）:")
big = m[m["recalc_err"].abs() > 0.05]
if len(big):
    print(big[["d", "开盘", "open_recalc", "open_front", "recalc_err"]].head(10).to_string())
else:
    print("无")
