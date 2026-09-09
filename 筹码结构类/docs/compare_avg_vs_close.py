# -*- coding: utf-8 -*-
"""对比：均价顶点 vs 收盘价顶点 的筹码结果差异"""
import sys
sys.path.insert(0, r"D:\量化k线\筹码结构类")
from chip_distribution import ChipDistribution, load_front_daily

rows = load_front_daily("000001", "SZ")
rowsA = rows                                    # 均价顶点（amount/volume）
rowsB = [{**r, "avg": r["close"]} for r in rows]  # 收盘价顶点（模拟旧版）

cd = ChipDistribution(window=250, decay=0.98, n_bins=200)
snapA = cd.compute(rowsA)
snapB = cd.compute(rowsB)

print(f'{"日期":<12}{"方法":<5}{"收盘":>7}{"获利盘":>8}{"均本":>8}  峰位')
for i in range(len(snapA) - 6, len(snapA)):
    a, b = snapA[i], snapB[i]
    pa = ", ".join(f"{p['price']:.2f}({p['share']*100:.0f}%)" for p in a.peaks[:3])
    pb = ", ".join(f"{p['price']:.2f}({p['share']*100:.0f}%)" for p in b.peaks[:3])
    print(f"{a.dt}  均价 {a.close:7.2f}{a.profit_ratio*100:7.1f}%{a.avg_cost:8.2f}  {pa}")
    print(f"{b.dt}  收盘 {b.close:7.2f}{b.profit_ratio*100:7.1f}%{b.avg_cost:8.2f}  {pb}")
