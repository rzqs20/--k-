# -*- coding: utf-8 -*-
"""
合成数据自检：验证 RangeBoxFinder 各规则是否按预期触发。
场景：
  A. 明确横盘箱体 + 之后连续上涨突破上沿 → 识别 1 个箱体，confirmed=向上突破，
     终点回填到突破第一根之前，确认时间=连续第3根突破K线
  B. V型反转（先涨后跌，首尾接近）→ 不应识别为持续盘整（峰/谷不足或重心不稳定）
  C. 上升趋势中的窄幅台阶 → 识别中间台阶箱体，向上确认
  D. 数据末尾仍在横盘（无突破）→ confirmed=False（尚未结束）
  E. 宽幅震荡（±20%）→ 开启 max_w_pct 后应被过滤
运行：python synthetic_check.py
"""
import sys
import os
import math

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
CHAN_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CHAN_PATH)

from chan_report import cb  # noqa: E402  调用已有模块（只读）
from range_box_finder import RangeBoxFinder  # noqa: E402

_DATE = __import__("datetime").datetime


def _bar(dt, o, c, h, l):
    return cb.RawBar("SYN", dt, o, c, h, l, 0.0, 0.0, 0, "日线")


def _mk(start_day, prices):
    """prices: list[(open, close, high, low)] → bars，日期从 start_day 天起递增"""
    return [_bar(_DATE(2024, 1, 1) + __import__("datetime").timedelta(days=start_day + i),
                 *p) for i, p in enumerate(prices)]


def _ohlc_from_close(closes, amp):
    """由收盘序列生成 OHLC（high/low 带振幅）"""
    out = []
    for i, c in enumerate(closes):
        prev = closes[i - 1] if i else c
        o = prev
        h = max(o, c) * (1 + amp / 2)
        l = min(o, c) * (1 - amp / 2)
        out.append((o, c, h, l))
    return out


def _sin_box(n=60, base=100.0, amp=0.03, period=6.0):
    """正弦横盘箱体：每 period 根一个完整周期"""
    closes = [base + base * amp * math.sin(2 * math.pi * i / period) for i in range(n)]
    return _ohlc_from_close(closes, amp * 0.8)


def _trend_up(n=20, start=90.0, step=0.01):
    closes = [start * (1 + step) ** i for i in range(n)]
    return _ohlc_from_close(closes, 0.01)


def _trend_dn(n=20, start=120.0, step=0.01):
    closes = [start * (1 - step) ** i for i in range(n)]
    return _ohlc_from_close(closes, 0.01)


def check(name, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}  {detail}")
    return cond


def main():
    ok_all = True

    # ============ A. 横盘 + 向上突破 ============
    bars_a = _mk(0, _sin_box())
    # 箱体后 6 根：收盘价直接站在上沿(≈103.8)之上，连续上涨
    bars_a += _mk(60, [(106.0 + 0.5 * i, 106.0 + 0.5 * i * 1.002,
                        106.0 + 0.5 * i * 1.004, 106.0 + 0.5 * i * 0.998)
                       for i in range(6)])
    boxes_a = RangeBoxFinder().find(bars_a)
    ok_all &= check("A 识别出箱体", len(boxes_a) >= 1,
                    f"boxes={len(boxes_a)}")
    if boxes_a:
        b = boxes_a[0]
        ok_all &= check("A 向上确认且确认时间非空",
                        b.confirmed and b.direction == "up" and b.confirm_time is not None,
                        f"dir={b.direction} confirm={b.confirm_time}")
        ok_all &= check("A 终点回填到突破第一根之前",
                        b.end_idx == b.breakout_first_idx - 1,
                        f"end_idx={b.end_idx} breakout_first={b.breakout_first_idx}")
        ok_all &= check("A 确认时间=连续第3根突破",
                        b.confirm_idx == b.breakout_first_idx + 2,
                        f"confirm_idx={b.confirm_idx}")
        ok_all &= check("A 上沿下沿合理", b.upper > b.lower and b.width > 0,
                        f"U={b.upper:.2f} L={b.lower:.2f} W={b.width:.2f}")

    # ============ B. V型反转（先涨后跌） ============
    v = [90.0 * (1 + 0.01) ** i for i in range(30)] + \
        [120.0 * (1 - 0.01) ** i for i in range(1, 31)]
    bars_b = _mk(0, _ohlc_from_close(v, 0.02))
    boxes_b = RangeBoxFinder().find(bars_b)
    # V型中峰1个谷1个 → 不满足2峰2谷，或重心不稳定
    ok_all &= check("B V型反转不识别为箱体", len(boxes_b) == 0,
                    f"boxes={len(boxes_b)}")

    # ============ C. 上升趋势中的窄幅台阶 ============
    bars_c = _mk(0, _trend_up(20, 90.0)) + \
             _mk(60, _sin_box(30, base=100.0, amp=0.02)) + \
             _mk(90, _trend_up(25, 102.0, 0.012))
    boxes_c = RangeBoxFinder().find(bars_c)
    ok_all &= check("C 识别出台阶箱体", len(boxes_c) >= 1,
                    f"boxes={len(boxes_c)}")
    if boxes_c:
        b = boxes_c[0]
        ok_all &= check("C 台阶为向上确认", b.confirmed and b.direction == "up",
                        f"dir={b.direction}")

    # ============ D. 数据末尾仍在横盘（未结束） ============
    bars_d = _mk(0, _sin_box(80, base=100.0, amp=0.02))
    boxes_d = RangeBoxFinder().find(bars_d)
    ok_all &= check("D 识别出箱体", len(boxes_d) >= 1, f"boxes={len(boxes_d)}")
    if boxes_d:
        b = boxes_d[0]
        ok_all &= check("D 无突破→尚未结束", (not b.confirmed) and b.direction is None,
                        f"confirmed={b.confirmed}")

    # ============ E. 宽幅震荡 + 窄幅限制 ============
    bars_e = _mk(0, _sin_box(80, base=100.0, amp=0.20, period=8.0))
    boxes_e = RangeBoxFinder().find(bars_e)
    ok_all &= check("E 默认参数可识别宽幅箱体", len(boxes_e) >= 1,
                    f"boxes={len(boxes_e)}")
    boxes_e2 = RangeBoxFinder(max_w_pct=8.0).find(bars_e)
    ok_all &= check("E max_w_pct=8% 过滤宽幅箱体", len(boxes_e2) == 0,
                    f"boxes={len(boxes_e2)}")

    print("-" * 50)
    print("全部通过" if ok_all else "存在失败项")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
