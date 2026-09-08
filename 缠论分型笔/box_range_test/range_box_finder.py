# -*- coding: utf-8 -*-
"""
盘整(水平箱体)事后识别器 —— RangeBoxFinder（未来函数版 · 仅供历史标注 / 回测研究）
================================================================================
设计口径（用户拍板，参数全部预留接口，默认值即示例值）：

【1. 用未来K线确认波峰 / 波谷】
    · 在 high 序列上用 scipy.signal.find_peaks 找局部高点，在 low 的相反数上找局部低点；
    · 用「显著度 prominence」过滤幅度太小的波动、「最小间距 distance」保证转折点不扎堆；
    · prominence 自适应 = max(prominence_atr × ATR14, min_prominence_pct × 价格中值)；
    · 相邻同类型转折点只保留更极端者（峰取更高、谷取更低）→ 得到严格交替的峰谷序列。

【2. 从连续峰谷中寻找稳定箱体（核心区间）】
    · 上沿 U = median(波峰价格)   下沿 L = median(波谷价格)   箱体高 W = U - L
    · 判定条件（默认值为示例，均可调）：
      - 持续足够久：至少 min_bars(20) 根K线；
      - 实质性来回震荡：至少 min_peaks(2) 个峰、min_troughs(2) 个谷，且天然交替；
      - 上下沿稳定：每个峰距上沿、每个谷距下沿均 <= 0.15W（peak_tol / trough_tol）；
      - 价格主要留在箱内：>= cover_ratio(90%) 的收盘价落在 [L - cover_tol·W, U + cover_tol·W]
        （cover_tol 默认 0.10）；
      - 内部重心稳定：前 / 中 / 后 三段收盘价中位数的最大差 <= median_tol(0.25)·W；
        —— 只凭首尾涨跌不够：先涨后跌首尾也可能接近，却不属于持续盘整。
    · 可选窄幅限制：max_w_pct 限定 W / 价格中值，用于「窄幅盘整」场景。

【3. 固定箱体上下沿，向左右扩展边界】
    · 核心区间定下后向两边逐根扩展K线，扩展时若没引入新转折点 → 上下沿固定不变，
      只复查「覆盖 + 重心」两条价格条件；
    · 若扩展引入了新的峰/谷转折点 → 重算 U/L，但要求上下沿调整幅度
      <= max_edge_shift(0.5)·W，防止把趋势也包进箱体。

【4. 重叠与相邻】
    · 重叠候选保留更完整的区间（K线更多、覆盖更高优先）；
    · 相邻箱体仅在合并后仍满足全部条件时才合并（max_gap_merge 内）。

【5. 利用后续走势确认结束，再回填终点】
    · 从箱体右边界之后扫描：连续 breakout_confirm(3) 根收盘价突破同一侧边界及容差
      （收盘 > U·(1+tol) 向上 / 收盘 < L·(1-tol) 向下）→ 确认离开箱体；
    · 终点(end_time) 回填到「该连续突破的第一根」之前一根；
    · 实际确认时间(confirm_time) = 连续第 3 根突破K线的时间；
    · 数据末尾尚未出现确认突破 → confirmed=False（标记「尚未结束」）。

【回测注意】
    起点 / 终点 / 上下沿都是「事后回填」的，确认时间 confirm_time 之前的信息
    才是当时可用的；不要把回填的起点当作当时已知的信号。

用法（只调用已有类，不修改任何源码）：
    from chan_report import load_bars
    from range_box_finder import RangeBoxFinder
    label, bars, prewarm = load_bars("000001", "SH", "日线", sdt, edt)
    boxes = RangeBoxFinder().find(bars)          # bars: cb.RawBar 列表
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from statistics import median
from typing import List, Optional, Sequence

from scipy.signal import find_peaks


# =====================================================================
# 一、数据结构
# =====================================================================

@dataclass
class Turn:
    """一个已确认的转折点。kind: 'P' 峰 / 'T' 谷"""
    idx: int
    kind: str
    price: float
    dt: datetime


@dataclass
class RangeBox:
    """一个识别出的盘整箱体（事后回填结果）。"""
    # 回填后的完整区间
    start_time: datetime
    end_time: datetime
    start_idx: int
    end_idx: int
    # 核心区间（由峰谷转折点直接确认，未扩展）
    core_start_time: datetime
    core_end_time: datetime
    core_start_idx: int
    core_end_idx: int
    # 箱体边界
    upper: float          # U = median(峰价)
    lower: float          # L = median(谷价)
    width: float          # W = U - L
    width_pct: float      # W / 价格中值 * 100
    # 质量指标
    n_peaks: int
    n_troughs: int
    cover_ratio: float    # 收盘价落在 [L-0.1W, U+0.1W] 的比例
    median_spread: float  # 前/中/后三段收盘价中位数最大差（W 倍数）
    # 结束确认（利用后续走势回填）
    confirmed: bool
    direction: Optional[str]      # 'up' 向上突破 / 'down' 向下突破 / None 未确认
    confirm_time: Optional[datetime]  # 实际确认时间（连续第3根突破K线）
    confirm_idx: Optional[int]
    breakout_first_idx: Optional[int]  # 连续突破的第一根K线索引
    # 转折点位置（用于画图）
    peak_idxs: List[int] = field(default_factory=list)
    trough_idxs: List[int] = field(default_factory=list)

    def to_dict(self):
        return {
            "start_time": self.start_time.strftime("%Y-%m-%d %H:%M"),
            "end_time": self.end_time.strftime("%Y-%m-%d %H:%M"),
            "core_start": self.core_start_time.strftime("%Y-%m-%d %H:%M"),
            "core_end": self.core_end_time.strftime("%Y-%m-%d %H:%M"),
            "upper": round(self.upper, 4),
            "lower": round(self.lower, 4),
            "width": round(self.width, 4),
            "width_pct": round(self.width_pct, 3),
            "n_peaks": self.n_peaks,
            "n_troughs": self.n_troughs,
            "cover_ratio": round(self.cover_ratio, 3),
            "median_spread_w": round(self.median_spread, 3),
            "bars_count": self.end_idx - self.start_idx + 1,
            "confirmed": self.confirmed,
            "direction": self.direction,
            "confirm_time": self.confirm_time.strftime("%Y-%m-%d %H:%M") if self.confirm_time else None,
            "status": ("尚未结束" if not self.confirmed
                       else f"已确认{'向上' if self.direction == 'up' else '向下'}突破"),
        }

    def __repr__(self):
        d = self.to_dict()
        return (f"<RangeBox {d['start_time']} -> {d['end_time']} "
                f"U={d['upper']} L={d['lower']} {d['status']}>")


# =====================================================================
# 二、盘整识别器
# =====================================================================

class RangeBoxFinder:
    """水平箱体事后识别器。所有参数在构造时配置，find() 执行识别。"""

    def __init__(self,
                 # ---- 转折点识别 ----
                 left: int = 5, right: int = 5,
                 min_distance: int = 5,
                 prominence_atr: float = 0.5,
                 min_prominence_pct: float = 0.0,
                 atr_n: int = 14,
                 # ---- 箱体条件 ----
                 min_bars: int = 20,
                 min_peaks: int = 2, min_troughs: int = 2,
                 peak_tol: float = 0.15, trough_tol: float = 0.15,
                 cover_ratio: float = 0.90, cover_tol: float = 0.10,
                 median_tol: float = 0.25,
                 max_w_pct: Optional[float] = None,
                 # ---- 扩展 / 合并 ----
                 max_edge_shift: float = 0.5,
                 max_gap_merge: int = 5,
                 extend_strict_band: bool = True,
                 # ---- 结束确认 ----
                 breakout_confirm: int = 3,
                 breakout_tol: float = 0.0,
                 ):
        self.left = left
        self.right = right
        self.min_distance = min_distance
        self.prominence_atr = prominence_atr
        self.min_prominence_pct = min_prominence_pct
        self.atr_n = atr_n
        self.min_bars = min_bars
        self.min_peaks = min_peaks
        self.min_troughs = min_troughs
        self.peak_tol = peak_tol
        self.trough_tol = trough_tol
        self.cover_ratio = cover_ratio
        self.cover_tol = cover_tol
        self.median_tol = median_tol
        self.max_w_pct = max_w_pct
        self.max_edge_shift = max_edge_shift
        self.max_gap_merge = max_gap_merge
        self.extend_strict_band = extend_strict_band
        self.breakout_confirm = breakout_confirm
        self.breakout_tol = breakout_tol

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------
    def find(self, bars: Sequence) -> List[RangeBox]:
        """对 bars（RawBar 列表，按时间升序）执行盘整识别。"""
        self.bars = list(bars)
        self._turns = self._detect_turns(self.bars)
        turns = self._turns
        if len(turns) < self.min_peaks + self.min_troughs:
            return []

        # ---- 1. 双指针扫描全部候选核心区间 ----
        cands = self._scan_candidates(bars, turns)
        if not cands:
            return []

        # ---- 2. 重叠候选：保留更完整区间（K线更多 → 覆盖更高） ----
        cands.sort(key=lambda c: (c[1] - c[0] + 1, c[2].get("cover_ratio", 0)),
                   reverse=True)
        chosen: List = []
        for c in cands:
            if any(not (c[1] < o[0] or c[0] > o[1]) for o in chosen):
                continue
            chosen.append(c)

        # ---- 3. 相邻箱体：合并后仍满足条件才合并 ----
        chosen.sort(key=lambda c: c[0])
        merged: List = []
        for c in chosen:
            if merged:
                last = merged[-1]
                gap = c[0] - last[1] - 1
                if gap <= self.max_gap_merge:
                    in_t = [t for t in turns if last[0] <= t.idx <= c[1]]
                    ok, m = self._check_full_window(bars, last[0], c[1], in_t)
                    if ok:
                        merged[-1] = (last[0], c[1], m)
                        continue
            merged.append(c)

        # ---- 4. 扩展 + 结束确认 + 组装 ----
        out: List[RangeBox] = []
        for si, ei, metrics in merged:
            box = self._build_box(bars, turns, si, ei, metrics)
            if box is not None:
                out.append(box)
        return out

    # ------------------------------------------------------------------
    # 转折点识别
    # ------------------------------------------------------------------
    def _detect_turns(self, bars) -> List[Turn]:
        n = len(bars)
        if n < 2:
            return []
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        price_mid = (max(highs) + min(lows)) / 2.0
        atr = self._atr(bars, self.atr_n)
        prom = max(atr * self.prominence_atr, price_mid * self.min_prominence_pct)
        if prom <= 0:
            prom = price_mid * 0.005
        dist = max(1, int(self.min_distance))

        pk, _ = find_peaks(highs, distance=dist, prominence=prom)
        tr, _ = find_peaks([-x for x in lows], distance=dist, prominence=prom)

        turns: List[Turn] = (
            [Turn(int(i), "P", highs[i], bars[i].dt) for i in pk] +
            [Turn(int(i), "T", lows[i], bars[i].dt) for i in tr])
        turns.sort(key=lambda t: (t.idx, 0 if t.kind == "P" else 1))

        # 强制交替：相邻同类型只保留更极端者
        out: List[Turn] = []
        for t in turns:
            if out and out[-1].kind == t.kind:
                if t.kind == "P" and t.price >= out[-1].price:
                    out[-1] = t
                elif t.kind == "T" and t.price <= out[-1].price:
                    out[-1] = t
            else:
                out.append(t)
        return out

    @staticmethod
    def _atr(bars, n: int) -> float:
        if len(bars) < 2:
            return 0.0
        trs = []
        for i in range(1, len(bars)):
            h, l, pc = bars[i].high, bars[i].low, bars[i - 1].close
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        if len(trs) < n:
            return sum(trs) / len(trs)
        return sum(trs[-n:]) / n

    # ------------------------------------------------------------------
    # 条件检查
    # ------------------------------------------------------------------
    def _check_window(self, bars, si: int, ei: int, U: float, L: float):
        """K线层面的两条条件：覆盖比例 + 三段重心稳定。返回 (ok, metrics)。"""
        if ei - si + 1 < self.min_bars:
            return False, {}
        W = U - L
        if W <= 0:
            return False, {}
        closes = [bars[i].close for i in range(si, ei + 1)]
        n = len(closes)
        lo, hi = L - self.cover_tol * W, U + self.cover_tol * W
        cover = sum(1 for c in closes if lo <= c <= hi) / n
        if cover < self.cover_ratio:
            return False, {"cover_ratio": cover}

        # 前 / 中 / 后 三段收盘价中位数
        third = n // 3
        m1 = median(closes[:third]) if third else closes[0]
        m2 = median(closes[third:2 * third]) if third else closes[-1]
        m3 = median(closes[2 * third:]) if closes[2 * third:] else closes[-1]
        spread = max(m1, m2, m3) - min(m1, m2, m3)
        if spread > self.median_tol * W:
            return False, {"cover_ratio": cover, "median_spread": spread}
        return True, {
            "cover_ratio": cover,
            "median_spread": spread / W if W else 0.0,
            "median1": m1, "median2": m2, "median3": m3,
        }

    def _check_full_window(self, bars, si: int, ei: int, in_turns: List[Turn]):
        """完整检查：峰谷数量/上下沿稳定/窄幅限制 + 覆盖/重心。返回 (ok, metrics)。"""
        if ei - si + 1 < self.min_bars:
            return False, {}
        P = [t.price for t in in_turns if t.kind == "P"]
        T = [t.price for t in in_turns if t.kind == "T"]
        if len(P) < self.min_peaks or len(T) < self.min_troughs:
            return False, {}
        U, L = median(P), median(T)
        if U <= L:
            return False, {}
        W = U - L
        # 上下沿稳定：峰距上沿、谷距下沿均 <= tol·W
        if any(abs(p - U) > self.peak_tol * W for p in P):
            return False, {}
        if any(abs(t - L) > self.trough_tol * W for t in T):
            return False, {}
        # 可选窄幅限制：箱体高 / 价格中值
        if self.max_w_pct is not None:
            mid = (U + L) / 2.0
            if mid and W / mid * 100 > self.max_w_pct:
                return False, {}
        ok, metrics = self._check_window(bars, si, ei, U, L)
        if not ok:
            return False, metrics
        metrics.update(upper=U, lower=L, width=W, n_peaks=len(P), n_troughs=len(T))
        return True, metrics

    def _scan_candidates(self, bars, turns: List[Turn]):
        """双指针扫描全部满足核心条件的候选区间。返回 [(si, ei, metrics), ...]"""
        cands = []
        k = len(turns)
        for s in range(k - 1):
            P, T = [], []
            for e in range(s + 1, k):
                t = turns[e]
                if t.kind == "P":
                    P.append(t.price)
                else:
                    T.append(t.price)
                si, ei = turns[s].idx, turns[e].idx
                if ei - si + 1 < self.min_bars:
                    continue
                if len(P) < self.min_peaks or len(T) < self.min_troughs:
                    continue
                sub = turns[s:e + 1]
                ok, metrics = self._check_full_window(bars, si, ei, sub)
                if ok:
                    cands.append((si, ei, metrics))
        return cands

    # ------------------------------------------------------------------
    # 扩展 / 结束确认 / 组装
    # ------------------------------------------------------------------
    def _edge_in_band(self, bars, idx: int, U: float, L: float) -> bool:
        """逐根扩展的严格约束：新纳入的边缘K线收盘价本身落在箱体容差带内，
        防止扩展把「突破/离开」段也吸进箱体（核心区间仍用 90% 覆盖容错）。"""
        if not self.extend_strict_band:
            return True
        W = U - L
        lo, hi = L - self.cover_tol * W, U + self.cover_tol * W
        return lo <= bars[idx].close <= hi

    def _extend(self, bars, si: int, ei: int, core_turns: List[Turn]):
        """固定上下沿（允许 <= max_edge_shift·W 的调整）向左右扩展K线边界。
        返回 (si, ei, U, L, turns_used)。"""
        all_turns = self._turns
        turns_used = list(core_turns)
        U = median([t.price for t in turns_used if t.kind == "P"])
        L = median([t.price for t in turns_used if t.kind == "T"])
        W = U - L
        n = len(bars)

        # ---- 向左扩展 ----
        while si > 0:
            nsi = si - 1
            if not self._edge_in_band(bars, nsi, U, L):
                break
            in_t = [t for t in all_turns if nsi <= t.idx <= ei]
            if set(map(id, in_t)) == set(map(id, turns_used)):
                ok, _ = self._check_window(bars, nsi, ei, U, L)
                if ok:
                    si = nsi
                    continue
                break
            nU = median([t.price for t in in_t if t.kind == "P"])
            nL = median([t.price for t in in_t if t.kind == "T"])
            if not in_t or nU is None or nL is None or nU <= nL:
                break
            nW = nU - nL
            if abs(nU - U) > self.max_edge_shift * W or abs(nL - L) > self.max_edge_shift * W:
                break
            ok, _ = self._check_full_window(bars, nsi, ei, in_t)
            if not ok:
                break
            si, U, L, W, turns_used = nsi, nU, nL, nW, in_t

        # ---- 向右扩展 ----
        while ei < n - 1:
            nei = ei + 1
            if not self._edge_in_band(bars, nei, U, L):
                break
            in_t = [t for t in all_turns if si <= t.idx <= nei]
            if set(map(id, in_t)) == set(map(id, turns_used)):
                ok, _ = self._check_window(bars, si, nei, U, L)
                if ok:
                    ei = nei
                    continue
                break
            nU = median([t.price for t in in_t if t.kind == "P"])
            nL = median([t.price for t in in_t if t.kind == "T"])
            if not in_t or nU is None or nL is None or nU <= nL:
                break
            nW = nU - nL
            if abs(nU - U) > self.max_edge_shift * W or abs(nL - L) > self.max_edge_shift * W:
                break
            ok, _ = self._check_full_window(bars, si, nei, in_t)
            if not ok:
                break
            ei, U, L, W, turns_used = nei, nU, nL, nW, in_t

        return si, ei, U, L, turns_used

    def _confirm_exit(self, bars, ei: int, U: float, L: float):
        """扫描箱体右边界之后，找连续 breakout_confirm 根收盘价突破同一侧边界+容差。
        返回 dict 或 None。"""
        n = len(bars)
        if ei >= n - self.breakout_confirm:
            return None
        up_thr = U * (1 + self.breakout_tol)
        dn_thr = L * (1 - self.breakout_tol)
        for j in range(ei + 1, n - self.breakout_confirm + 1):
            ups = all(bars[j + k].close > up_thr for k in range(self.breakout_confirm))
            dns = all(bars[j + k].close < dn_thr for k in range(self.breakout_confirm))
            if ups:
                return {"first_idx": j, "last_idx": j + self.breakout_confirm - 1,
                        "direction": "up"}
            if dns:
                return {"first_idx": j, "last_idx": j + self.breakout_confirm - 1,
                        "direction": "down"}
        return None

    def _build_box(self, bars, turns, si: int, ei: int, metrics) -> Optional[RangeBox]:
        core_turns = [t for t in turns if si <= t.idx <= ei]
        if not core_turns:
            return None
        nsi, nei, U, L, turns_used = self._extend(bars, si, ei, core_turns)
        W = U - L
        if W <= 0:
            return None

        confirm = self._confirm_exit(bars, nei, U, L)
        if confirm:
            end_idx = max(nsi, confirm["first_idx"] - 1)
            end_time = bars[end_idx].dt
            confirm_time = bars[confirm["last_idx"]].dt
            direction = confirm["direction"]
            confirmed = True
            breakout_first_idx = confirm["first_idx"]
        else:
            end_idx = nei
            end_time = bars[nei].dt
            confirm_time = None
            direction = None
            confirmed = False
            breakout_first_idx = None

        # 扩展后重算覆盖 / 重心（若扩展改变了上下沿则用新边界复查一次）
        closes = [bars[i].close for i in range(nsi, nei + 1)]
        n = len(closes)
        lo, hi = L - self.cover_tol * W, U + self.cover_tol * W
        cover = sum(1 for c in closes if lo <= c <= hi) / n if n else 0.0
        third = n // 3
        m1 = median(closes[:third]) if third else (closes[0] if closes else 0)
        m2 = median(closes[third:2 * third]) if third else (closes[-1] if closes else 0)
        m3 = median(closes[2 * third:]) if closes[2 * third:] else (closes[-1] if closes else 0)
        spread_w = (max(m1, m2, m3) - min(m1, m2, m3)) / W if W else 0.0

        return RangeBox(
            start_time=bars[nsi].dt, end_time=end_time,
            start_idx=nsi, end_idx=end_idx,
            core_start_time=bars[si].dt, core_end_time=bars[ei].dt,
            core_start_idx=si, core_end_idx=ei,
            upper=U, lower=L, width=W,
            width_pct=W / ((U + L) / 2.0) * 100 if (U + L) else 0.0,
            n_peaks=sum(1 for t in turns_used if t.kind == "P"),
            n_troughs=sum(1 for t in turns_used if t.kind == "T"),
            cover_ratio=cover, median_spread=spread_w,
            confirmed=confirmed, direction=direction,
            confirm_time=confirm_time, confirm_idx=confirm["last_idx"] if confirm else None,
            breakout_first_idx=breakout_first_idx,
            peak_idxs=[t.idx for t in turns_used if t.kind == "P"],
            trough_idxs=[t.idx for t in turns_used if t.kind == "T"],
        )

    # ------------------------------------------------------------------
    # 参数摘要（供报告展示）
    # ------------------------------------------------------------------
    @property
    def turns(self) -> List[Turn]:
        """最近一次 find() 识别出的全部转折点（峰谷交替序列），供画图/检查。"""
        return getattr(self, "_turns", [])

    def param_summary(self) -> dict:
        return {
            "min_distance": self.min_distance,
            "prominence_atr": self.prominence_atr,
            "min_prominence_pct": self.min_prominence_pct,
            "atr_n": self.atr_n,
            "min_bars": self.min_bars,
            "min_peaks": self.min_peaks,
            "min_troughs": self.min_troughs,
            "peak_tol": self.peak_tol,
            "trough_tol": self.trough_tol,
            "cover_ratio": self.cover_ratio,
            "cover_tol": self.cover_tol,
            "median_tol": self.median_tol,
            "max_w_pct": self.max_w_pct,
            "max_edge_shift": self.max_edge_shift,
            "max_gap_merge": self.max_gap_merge,
            "extend_strict_band": self.extend_strict_band,
            "breakout_confirm": self.breakout_confirm,
            "breakout_tol": self.breakout_tol,
        }
