# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, r"D:\量化k线\筹码结构类")
from chip_distribution import load_front_daily, ChipDistribution

rows = load_front_daily("000001", "SZ")
for r in rows:
    if str(r["dt"]) == "2025-04-30":
        print(f"2025-04-30: front low={r['low']:.3f} high={r['high']:.3f} close={r['close']:.3f} avg={r['avg']:.3f}")
        print("avg 在 [low,high] 内:", r["low"] <= r["avg"] <= r["high"])

cd = ChipDistribution()
snaps = cd.compute(rows)
s = snaps[-1]
print(f"最新日 {s.dt} 获利盘={s.profit_ratio:.1%} 峰={[round(p['price'],2) for p in s.peaks]}")
