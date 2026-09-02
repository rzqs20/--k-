#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
布林线 + RSI 行情状态判定（趋势 / 盘整 / 突破）
================================================
设计口径（用户拍板，参数全部预留接口）：

【布林线】定结构、划边界、判波动率
    · 默认 N=20、标准差倍数 k=2.0（高波动品种可手动调 2.5）
    · 中轨 mid = MA20；upper/lower = mid ± k·std（总体标准差 ddof=0）
    · 带宽 bandwidth = (upper - lower) / mid
    · 中轨 20 周期斜率 slope = (mid[t] - mid[t-20]) / mid[t-20]

【RSI】定动能、判方向、验强弱（Wilder 平滑，默认 14）
    · 50 多空分界；60/40 强弱阈值（验证突破/跌破有效性）
    · 70/30 仅作「超买/超卖」预警标签，不参与主状态切换

【盘整】双条件，满足其一即盘整，同时满足为「强盘整」
    · 核心(波动率)：当前带宽处于近 250 根带宽的 20% 分位以下
    · 辅助(价格)  ：连续 8 根收盘价都落在各自布林上下轨之间，且 |中轨20斜率| < 0.5%（走平）

【突破】0.5% 幅度过滤 + 2 根站稳，拆分「突破中」与「有效突破」
    · 突破中：收盘价突破上/下轨，但尚未满足有效条件
    · 有效突破：超出轨道 ≥0.5% 且连续 2 根收在轨道外 且 RSI 同向走强(>60 / <40)
    · 破轨但 RSI 反向(<50 / >50) → 标注「RSI背离·存疑」（假突破嫌疑，不改主状态）

【趋势】收盘站上/跌破中轨 + 中轨斜率同向 + RSI 在 50 同侧

【优先级】有效突破 > 突破中 > 强盘整 > 盘整 > 趋势 > 中性
    布林定结构（区间/盘整/突破）优先，RSI 只做确认与过滤，不单独发起趋势信号。

计算基础：直接用【原始K线收盘价】，不做去包含。

用法：
    from indicators import analyze_regime, REGIME_CN
    signals, segs = analyze_regime(bars)          # bars: RawBar 列表（按时间升序）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Sequence

__all__ = [
    "BarSignal", "RegimeSeg", "analyze_regime",
    "bollinger", "rsi_wilder", "rolling_quantile_flag",
    "REGIME_CN", "REGIME_COLOR",
]

# ---- 主状态枚举 ----
TREND_UP = "TrendUp"          # 趋势·上
TREND_DN = "TrendDown"        # 趋势·下
BREAK_UP = "BreakUp"          # 向上突破中（待确认）
BREAK_DN = "BreakDown"        # 向下突破中（待确认）
STRONG_RANGE = "StrongRange"  # 强盘整（双条件同时满足）
RANGE = "Range"               # 盘整（满足其一）
NEUTRAL = "Neutral"           # 中性/过渡

REGIME_CN = {
    TREND_UP: "趋势·上", TREND_DN: "趋势·下",
    BREAK_UP: "向上突破中", BREAK_DN: "向下突破中",
    STRONG_RANGE: "强盘整", RANGE: "盘整", NEUTRAL: "中性",
}
# 图表色带颜色（半透明）
REGIME_COLOR = {
    TREND_UP: "rgba(224,80,62,0.10)",
    TREND_DN: "rgba(26,154,90,0.10)",
    BREAK_UP: "rgba(224,80,62,0.20)",
    BREAK_DN: "rgba(26,154,90,0.20)",
    STRONG_RANGE: "rgba(120,130,150,0.22)",
    RANGE: "rgba(120,130,150,0.13)",
    NEUTRAL: "rgba(0,0,0,0)",
}


# =====================================================================
# 一、基础指标
# =====================================================================

def bollinger(closes: Sequence[float], n: int = 20, k: float = 2.0):
    """布林线（总体标准差 ddof=0）。返回 mid/upper/lower/bw 四个等长列表，预热期为 None。"""
    size = len(closes)
    mid: List[Optional[float]] = [None] * size
    upper: List[Optional[float]] = [None] * size
    lower: List[Optional[float]] = [None] * size
    bw: List[Optional[float]] = [None] * size
    for t in range(n - 1, size):
        win = closes[t - n + 1:t + 1]
        m = sum(win) / n
        var = sum((x - m) ** 2 for x in win) / n          # 总体方差
        sd = var ** 0.5
        up, lo = m + k * sd, m - k * sd
        mid[t], upper[t], lower[t] = m, up, lo
        bw[t] = (up - lo) / m if m else 0.0
    return mid, upper, lower, bw


def rsi_wilder(closes: Sequence[float], period: int = 14):
    """RSI（Wilder 平滑）。等长列表，预热期为 None。"""
    size = len(closes)
    rsi: List[Optional[float]] = [None] * size
    if size < period + 1:
        return rsi
    gains, losses = [], []
    for i in range(1, period + 1):
        chg = closes[i] - closes[i - 1]
        gains.append(max(chg, 0.0))
        losses.append(max(-chg, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    def _rsi(g, l):
        if l == 0:
            return 100.0 if g > 0 else 50.0
        if g == 0:
            return 0.0
        rs = g / l
        return 100.0 - 100.0 / (1.0 + rs)

    rsi[period] = _rsi(avg_gain, avg_loss)
    for i in range(period + 1, size):
        chg = closes[i] - closes[i - 1]
        g = max(chg, 0.0)
        l = max(-chg, 0.0)
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
        rsi[i] = _rsi(avg_gain, avg_loss)
    return rsi


def rolling_quantile_flag(values: Sequence[Optional[float]], window: int = 250,
                          q: float = 0.20, min_window: int = 60):
    """对每个位置 t，判断 values[t] 是否 <= 过去 window 根（含自身）有效样本的 q 分位数。
    返回 (is_low_flag, percentile) 两个等长列表；样本不足 min_window 时为 (False, None)。"""
    size = len(values)
    flag = [False] * size
    pct: List[Optional[float]] = [None] * size
    for t in range(size):
        lo = max(0, t - window + 1)
        win = [v for v in values[lo:t + 1] if v is not None]
        if len(win) < min_window or values[t] is None:
            continue
        sw = sorted(win)
        # 分位数（线性插值）
        pos = q * (len(sw) - 1)
        lo_i = int(pos)
        hi_i = min(lo_i + 1, len(sw) - 1)
        thr = sw[lo_i] + (sw[hi_i] - sw[lo_i]) * (pos - lo_i)
        cur = values[t]
        # 当前值在窗口中的百分位（<= 当前值的占比）
        le = sum(1 for x in win if x <= cur) / len(win)
        pct[t] = le
        flag[t] = cur <= thr
    return flag, pct


# =====================================================================
# 二、数据结构
# =====================================================================

@dataclass
class BarSignal:
    """单根原始K线的指标与状态。"""
    idx: int
    dt: datetime
    close: float
    mid: Optional[float]
    upper: Optional[float]
    lower: Optional[float]
    bw: Optional[float]       # 带宽
    bw_pct: Optional[float]   # 带宽历史百分位 0~1
    slope: Optional[float]    # 中轨20周期斜率
    rsi: Optional[float]      # RSI14
    state: Optional[str]      # 主状态（预热期 None）
    warn: str = ""            # 预警标签：超买/超卖/RSI背离·存疑
    note: str = ""            # 有效突破 等备注


@dataclass
class RegimeSeg:
    """连续同状态聚合出的行情区段。"""
    kind: str
    i0: int
    i1: int
    dts: List[datetime] = field(default_factory=list)
    closes: List[float] = field(default_factory=list)
    rsis: List[float] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    warns: List[str] = field(default_factory=list)

    @property
    def start_dt(self) -> datetime:
        return self.dts[0]

    @property
    def end_dt(self) -> datetime:
        return self.dts[-1]

    @property
    def bar_count(self) -> int:
        return len(self.dts)

    @property
    def price0(self) -> float:
        return self.closes[0]

    @property
    def price1(self) -> float:
        return self.closes[-1]

    @property
    def net_change(self) -> float:
        return self.closes[-1] - self.closes[0]

    @property
    def net_pct(self) -> float:
        return (self.closes[-1] - self.closes[0]) / self.closes[0] * 100 if self.closes[0] else 0.0

    @property
    def rsi_mean(self) -> float:
        return sum(self.rsis) / len(self.rsis) if self.rsis else float("nan")

    @property
    def finished(self) -> bool:
        return getattr(self, "_finished", True)


# =====================================================================
# 三、逐根状态判定 + 区段聚合
# =====================================================================

def analyze_regime(bars,
                   boll_n: int = 20, boll_k: float = 2.0,
                   rsi_period: int = 14,
                   bw_window: int = 250, bw_q: float = 0.20, bw_min_window: int = 60,
                   range_bars: int = 8, flat_slope: float = 0.005,
                   breakout_pct: float = 0.005, hold_bars: int = 2,
                   rsi_mid: float = 50.0, rsi_strong: float = 60.0,
                   rsi_weak: float = 40.0, rsi_ob: float = 70.0, rsi_os: float = 30.0,
                   min_seg_bars: int = 8):
    """主入口：bars 为按时间升序的 RawBar 列表（用 .dt/.close）。
    返回 (signals: List[BarSignal], segments: List[RegimeSeg])。"""
    closes = [b.close for b in bars]
    dts = [b.dt for b in bars]
    size = len(bars)

    mid, upper, lower, bw = bollinger(closes, boll_n, boll_k)
    rsi = rsi_wilder(closes, rsi_period)
    low_bw, bw_pct = rolling_quantile_flag(bw, bw_window, bw_q, bw_min_window)

    # 中轨 lookback 斜率（回看 boll_n 根）
    slope: List[Optional[float]] = [None] * size
    for t in range(size):
        if mid[t] is not None and t - boll_n >= 0 and mid[t - boll_n]:
            slope[t] = (mid[t] - mid[t - boll_n]) / mid[t - boll_n]

    signals: List[BarSignal] = []
    raw_states: List[Optional[str]] = [None] * size

    for t in range(size):
        warn, note = "", ""
        state: Optional[str] = None
        r = rsi[t]

        # 指标未齐备（布林/RSI/斜率缺一）→ 预热
        ready = (upper[t] is not None and lower[t] is not None and
                 mid[t] is not None and slope[t] is not None and r is not None)
        if ready:
            c = closes[t]
            # ---- RSI 预警标签（不参与主状态切换）----
            if r > rsi_ob:
                warn = "超买"
            elif r < rsi_os:
                warn = "超卖"

            # ---- 盘整：核心(波动率) ----
            cond_vol = low_bw[t]
            # ---- 盘整：辅助(价格)：连续 range_bars 根收在各自轨内 + 中轨走平 ----
            cond_price = False
            if t >= range_bars - 1 and abs(slope[t]) < flat_slope:
                cond_price = all(
                    lower[k] is not None and lower[k] <= closes[k] <= upper[k]
                    for k in range(t - range_bars + 1, t + 1))
            strong_range = cond_vol and cond_price
            is_range = cond_vol or cond_price

            # ---- 突破轨道 ----
            break_up = c > upper[t]
            break_dn = c < lower[t]
            # 连续 hold_bars 根收在轨道外
            def _held_out(side):
                if t < hold_bars - 1:
                    return False
                for k in range(t - hold_bars + 1, t + 1):
                    if upper[k] is None:
                        return False
                    if side == "up" and not closes[k] > upper[k]:
                        return False
                    if side == "dn" and not closes[k] < lower[k]:
                        return False
                return True
            held_up = _held_out("up")
            held_dn = _held_out("dn")
            # 有效突破：幅度过滤 + 站稳 + RSI 同向走强
            valid_up = break_up and c > upper[t] * (1 + breakout_pct) and held_up and r > rsi_strong
            valid_dn = break_dn and c < lower[t] * (1 - breakout_pct) and held_dn and r < rsi_weak

            # ---- 趋势：中轨位置 + 斜率方向 + RSI 同侧 ----
            trend_up = c > mid[t] and slope[t] > 0 and r > rsi_mid
            trend_dn = c < mid[t] and slope[t] < 0 and r < rsi_mid

            # ---- 优先级判定 ----
            if valid_up:
                state, note = TREND_UP, "有效突破"
            elif valid_dn:
                state, note = TREND_DN, "有效突破"
            elif break_up:
                state = BREAK_UP
                if r < rsi_mid:
                    warn = "RSI背离·存疑"
            elif break_dn:
                state = BREAK_DN
                if r > rsi_mid:
                    warn = "RSI背离·存疑"
            elif strong_range:
                state = STRONG_RANGE
            elif is_range:
                state = RANGE
            elif trend_up:
                state = TREND_UP
            elif trend_dn:
                state = TREND_DN
            else:
                state = NEUTRAL
            raw_states[t] = state

        signals.append(BarSignal(
            idx=t, dt=dts[t], close=closes[t],
            mid=mid[t], upper=upper[t], lower=lower[t],
            bw=bw[t], bw_pct=bw_pct[t], slope=slope[t], rsi=r,
            state=state, warn=warn, note=note))

    segments = _aggregate(raw_states, signals, min_seg_bars)
    return signals, segments


def _major_of(kind: str) -> str:
    """具体状态 -> 大类：BULL 多头 / BEAR 空头 / RNG 盘整震荡。
    趋势/突破按方向归多空；盘整、强盘整、中性统一归 RNG（非趋势即盘整震荡）。"""
    if kind in (TREND_UP, BREAK_UP):
        return "BULL"
    if kind in (TREND_DN, BREAK_DN):
        return "BEAR"
    return "RNG"


def _aggregate(raw_states, signals, min_seg_bars):
    """逐根状态 -> 大类 -> 迭代吸收去抖 -> 区段。
    1) 连续同大类合并成块；
    2) 迭代吸收：短于 min_seg_bars 的块优先「两侧同类三合一」，否则并入更长邻块；
    3) 区段标签只在自身大类内取众数（盘整块不会被标成趋势/突破），备注同向过滤。"""
    from collections import Counter
    items = [(t, raw_states[t], signals[t])
             for t in range(len(raw_states)) if raw_states[t] is not None]
    if not items:
        return []

    # row = (idx, dt, close, rsi, state, note, warn)
    blocks = []
    for t, st, sg in items:
        mj = _major_of(st)
        row = (t, sg.dt, sg.close, sg.rsi, st, sg.note, sg.warn)
        if blocks and blocks[-1]["major"] == mj:
            blocks[-1]["rows"].append(row)
        else:
            blocks.append({"major": mj, "rows": [row]})

    def _absorbable(b):
        return len(b["rows"]) < min_seg_bars

    changed = True
    while changed and len(blocks) > 1:
        changed = False
        for i in range(len(blocks)):
            b = blocks[i]
            if not _absorbable(b):
                continue
            left = blocks[i - 1] if i > 0 else None
            right = blocks[i + 1] if i + 1 < len(blocks) else None
            # 两侧同大类 → 三合一
            if left and right and left["major"] == right["major"]:
                left["rows"] = left["rows"] + b["rows"] + right["rows"]
                del blocks[i:i + 2]
                changed = True
                break
            # 否则并入更长的相邻块
            if left and (not right or len(left["rows"]) >= len(right["rows"])):
                left["rows"] = left["rows"] + b["rows"]
                del blocks[i]
                changed = True
                break
            if right:
                right["rows"] = b["rows"] + right["rows"]
                del blocks[i]
                changed = True
                break

    # ---- 块定标签（含趋势方向一致性校验：净涨跌反向的"伪趋势"降级盘整）----
    labeled = []
    for b in blocks:
        rows = b["rows"]
        major = b["major"]
        if major == "BULL":
            pool = [r[4] for r in rows if _major_of(r[4]) == "BULL"]
            kind = Counter(pool).most_common(1)[0][0] if pool else TREND_UP
        elif major == "BEAR":
            pool = [r[4] for r in rows if _major_of(r[4]) == "BEAR"]
            kind = Counter(pool).most_common(1)[0][0] if pool else TREND_DN
        else:
            pool = [r[4] for r in rows if r[4] in (STRONG_RANGE, RANGE)]
            kind = Counter(pool).most_common(1)[0][0] if pool else RANGE
        net = (rows[-1][2] - rows[0][2]) / rows[0][2] * 100 if rows[0][2] else 0.0
        if major == "BULL" and net <= 0:
            kind = RANGE
        elif major == "BEAR" and net >= 0:
            kind = RANGE
        labeled.append([kind, rows])

    # ---- 相邻同大类再合并（方向降级后可能产生相邻盘整段）----
    merged_blocks = []
    for kind, rows in labeled:
        if merged_blocks and _major_of(merged_blocks[-1][0]) == _major_of(kind):
            merged_blocks[-1][1].extend(rows)
            if _major_of(kind) == "RNG":
                allk = [r[4] for r in merged_blocks[-1][1]]
                sr = sum(1 for x in allk if x == STRONG_RANGE)
                merged_blocks[-1][0] = STRONG_RANGE if sr > len(allk) / 2 else RANGE
        else:
            merged_blocks.append([kind, rows])

    segs = []
    for kind, rows in merged_blocks:
        major = _major_of(kind)
        notes = list(dict.fromkeys(
            r[5] for r in rows
            if r[5] and _major_of(r[4]) == major and r[4] in (TREND_UP, TREND_DN)))
        segs.append(RegimeSeg(
            kind=kind, i0=rows[0][0], i1=rows[-1][0],
            dts=[r[1] for r in rows],
            closes=[r[2] for r in rows],
            rsis=[r[3] for r in rows if r[3] is not None],
            notes=notes,
            warns=[f"{r[1]:%m-%d %H:%M}:{r[6]}" for r in rows if r[6]]))
    return segs


# =====================================================================
# 四、内置自检
# =====================================================================

def _mk(dt, close, symbol="T"):
    from datetime import datetime as _dt
    class _B:
        pass
    b = _B()
    b.symbol = symbol
    b.dt = dt if isinstance(dt, datetime) else _dt.strptime(dt, "%Y-%m-%d")
    b.open = b.high = b.low = b.close = float(close)
    b.vol = b.amount = 0.0
    b.id = 0
    b.freq = "日线"
    return b


def _selftest():
    # 场景A：长期窄幅横盘（低带宽 + 价格在轨内 + 中轨走平）→ 应判盘整/强盘整
    base = [100.0]
    closes = list(base)
    # 先造 300 根小幅震荡，带宽逐步收窄
    import math
    for i in range(300):
        closes.append(100 + 1.2 * math.sin(i / 6.0) * (1 - i / 600.0))
    bars = [_mk(f"2024-{1 + (i // 28):02d}-{1 + (i % 28):02d}", c) for i, c in enumerate(closes)]
    sigs, segs = analyze_regime(bars)
    kinds = [s.kind for s in segs]
    has_range = any(k in (RANGE, STRONG_RANGE) for k in kinds)
    assert has_range, f"窄幅横盘应出现盘整，实际 {kinds}"
    print("✓ 盘整判定通过：窄幅横盘(低带宽+轨内+走平) → 盘整/强盘整")

    # 场景B：横盘后连续放量单边上涨突破上轨（幅度>0.5%、站稳2根、RSI>60）→ 趋势上/有效突破
    closes2 = [100 + 0.3 * math.sin(i / 5.0) for i in range(120)]
    # 计算当时上轨，构造明确超出
    m, up, lo, bw = bollinger(closes2)
    for i in range(12):
        last_up = up[-1] if up[-1] else 101
        closes2.append(closes2[-1] * 1.02)  # 每根涨2%，远超0.5%且连续站稳
    bars2 = [_mk(f"2024-{1 + (i // 28):02d}-{1 + (i % 28):02d}", c) for i, c in enumerate(closes2)]
    sigs2, segs2 = analyze_regime(bars2)
    tail = [s for s in sigs2 if s.state is not None][-6:]
    assert any(s.state == TREND_UP and s.note == "有效突破" for s in tail), \
        f"单边强突破应出现 趋势上·有效突破，实际 {[(s.state, s.note, round(s.rsi or -1,1)) for s in tail]}"
    print("✓ 有效突破通过：单边强涨(>0.5%+站稳2根+RSI>60) → 趋势上·有效突破")

    # 场景C：RSI 分区不越界、预热期状态为 None
    assert all(s.rsi is None or 0 <= s.rsi <= 100 for s in sigs), "RSI 必须在 0~100"
    assert sigs[0].state is None and sigs[5].state is None, "指标预热期状态应为 None"
    print("✓ RSI 区间与预热通过：RSI∈[0,100]，指标未齐备时不判状态")

    # 场景D：区段连续覆盖（无空档、无重叠）
    for a, b in zip(segs2, segs2[1:]):
        assert b.i0 == a.i1 + 1, "区段必须首尾相接、无空档"
    print("✓ 区段连续性通过：聚合后区段首尾相接、无空档")
    print("（自检数据为合成正弦/单边序列，仅验证规则触发逻辑）")


if __name__ == "__main__":
    _selftest()
