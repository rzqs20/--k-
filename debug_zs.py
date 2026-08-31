# -*- coding: utf-8 -*-
"""调试：打印每个中枢的构成笔，看中枢是怎么判断出来的"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\量化k线")
from czsc_report import load_khdata, resolve_symbol
from czsc import CZSC

code, exchange = resolve_symbol("002714.SZ")
bars = load_khdata(code, exchange, "日线", "2024-08-27", "2026-08-27")
c = CZSC(bars)

print("=" * 70)
print("总笔数:", len(c.bi_list), "  总中枢数:", len(c.zs_list))
print("=" * 70)

for i, z in enumerate(c.zs_list, 1):
    print(f"\n【中枢{i}】 时间 {z.sdt:%Y-%m-%d} ~ {z.edt:%Y-%m-%d}")
    print(f"  中枢区间 [zd={z.zd:.3f}, zg={z.zg:.3f}]  中轴 zz={z.zz:.3f}")
    print(f"  极端范围 [dd={z.dd:.3f}, gg={z.gg:.3f}]  (dd=所有笔最低, gg=所有笔最高)")
    print(f"  第一笔方向={z.sdir.name}  最后一笔方向={z.edir.name}  有效={z.is_valid()}")
    print(f"  构成笔数: {len(z.bis)}")
    print(f"  {'笔序':<4} {'方向':<5} {'起始':<12} {'结束':<12} {'低点':>8} {'高点':>8}")
    print(f"  {'-'*4} {'-'*5} {'-'*12} {'-'*12} {'-'*8} {'-'*8}")
    for j, b in enumerate(z.bis, 1):
        d = "向上" if b.direction.name == "Up" else "向下"
        print(f"  {j:<4} {d:<5} {b.sdt:%Y-%m-%d}  {b.edt:%Y-%m-%d}  {b.low:>8.3f} {b.high:>8.3f}")

    # 手动验证中枢区间：前三笔的 max(low) 和 min(high)
    if len(z.bis) >= 3:
        first3 = z.bis[:3]
        calc_zd = max(b.low for b in first3)
        calc_zg = min(b.high for b in first3)
        print(f"  >> 验证: 前三笔 max(low)={calc_zd:.3f}, min(high)={calc_zg:.3f}")
        print(f"  >> 实际: zd={z.zd:.3f}, zg={z.zg:.3f}  {'一致' if abs(calc_zd-z.zd)<0.001 and abs(calc_zg-z.zg)<0.001 else '不一致(后续笔扩展了)'}")
