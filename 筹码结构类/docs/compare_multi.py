# -*- coding: utf-8 -*-
"""多只股票对比均价顶点 vs 收盘价顶点，看差异量级"""
import sys
sys.path.insert(0, r"D:\量化k线\筹码结构类")
from chip_distribution import ChipDistribution, load_front_daily

tests = [("000001", "SZ"), ("600519", "SH"), ("002594", "SZ"),
         ("300750", "SZ"), ("600000", "SH"), ("000002", "SZ")]
cd = ChipDistribution(window=250, decay=0.98, n_bins=200)

print(f'{"代码":<10}{"收盘":>7}{"获利盘差":>9}{"均本差":>8}  均价峰位 vs 收盘峰位')
for code, ex in tests:
    rows = load_front_daily(code, ex)
    if len(rows) < 300:
        continue
    a = cd.compute(rows)[-1]
    b = cd.compute([{**r, "avg": r["close"]} for r in rows])[-1]
    pa = ", ".join(f"{p['price']:.2f}" for p in a.peaks[:2])
    pb = ", ".join(f"{p['price']:.2f}" for p in b.peaks[:2])
    print(f"{code}.{ex} {a.close:7.2f}  {abs(a.profit_ratio-b.profit_ratio)*100:6.2f}%  {abs(a.avg_cost-b.avg_cost):6.3f}   {pa}  vs  {pb}")
