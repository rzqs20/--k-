# -*- coding: utf-8 -*-
"""用 preClose 检测除权日，从最新往前累计因子，重算前复权价。
验证目标：
  1) 2025-04-30 重算 front close 应 = 9.952（数据库 2025 年值，已知与同花顺一致）
  2) 2026-04-30 重算 front open 应 ≈ 11.14（同花顺口径）
"""
import duckdb
import numpy as np
import pandas as pd

con = duckdb.connect(r"D:\khData\SZ\000001.db", read_only=True)
df = con.execute("""SELECT CAST(time AS DATE) AS d, open, high, low, close, preClose,
                    open_front, high_front, low_front, close_front
                    FROM kline_1d ORDER BY time""").fetchdf()
con.close()

df = df.sort_values("d").reset_index(drop=True)

# --- 除权日检测：preClose 显著 ≠ 前一交易日 close（且向下），因子 = preClose/前收 ---
events = []
for i in range(1, len(df)):
    pc = df.loc[i, "preClose"]
    prev_c = df.loc[i - 1, "close"]
    if pd.notna(pc) and pd.notna(prev_c) and pc > 0 and prev_c > 0:
        ratio = pc / prev_c
        if ratio < 0.995 and ratio >= 0.5:   # 除权向下，因子范围 [0.5, 0.995)
            events.append((df.loc[i, "d"], round(prev_c, 3), round(pc, 3), round(ratio, 6)))

print("=== 检测到的除权事件（日期, 前收, preClose, 因子）===")
for e in events:
    print(e)

# --- 从最新往前累计因子，重算前复权 ---
n = len(df)
factor = 1.0
factors = np.ones(n)
ev_idx = 0
# 反向扫描：最新日为基准 factor=1，遇到除权日，更早的乘因子
for i in range(n - 1, -1, -1):
    factors[i] = factor
    # 若 i 是除权日（当日价格已跳低），则 i 之前（不含 i）都要乘因子
    if i > 0:
        pc = df.loc[i, "preClose"]
        prev_c = df.loc[i - 1, "close"]
        if pd.notna(pc) and pd.notna(prev_c) and pc > 0 and prev_c > 0:
            ratio = pc / prev_c
            if ratio < 0.995 and ratio >= 0.5:
                factor *= ratio   # 除权日之前的价格整体再缩 factor

# 重算 front
recalc = pd.DataFrame({
    "d": df["d"],
    "open_raw": df["open"], "close_raw": df["close"],
    "open_recalc": df["open"] * factors,
    "close_recalc": df["close"] * factors,
    "factor": factors,
    "open_front_db": df["open_front"], "close_front_db": df["close_front"],
})

# --- 验证 ---
for target in ["2025-04-30", "2026-04-30", "2026-05-06", "2026-06-12", "2026-09-09", "2024-08-19"]:
    row = recalc[recalc["d"] == target]
    if len(row):
        r = row.iloc[0]
        print(f"\n{target}: 重算 open={r['open_recalc']:.3f} close={r['close_recalc']:.3f} "
              f"(因子={r['factor']:.5f}) | 库内front open={r['open_front_db']:.3f} close={r['close_front_db']:.3f}")

# 全量对比：数据库 front vs 重算 front（close）
diff = (recalc["close_recalc"] - recalc["close_front_db"]).abs()
print(f"\n=== 重算 vs 数据库 front（close）===")
print(f"一致天数: {(diff < 0.005).sum()} / {len(recalc)}")
mismatch = recalc[diff >= 0.005]
print(f"不一致天数: {len(mismatch)}")
if len(mismatch):
    print("不一致样本（前10）:")
    print(mismatch[["d", "close_raw", "close_recalc", "close_front_db", "factor"]].head(10).to_string())
