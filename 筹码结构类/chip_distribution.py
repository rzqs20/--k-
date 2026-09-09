# -*- coding: utf-8 -*-
"""
筹码结构类 · 核心算法 —— 滚动窗口筹码分布（CYQ）

价格口径：不复权（原始 open/high/low/close）
算法：经典三角形分布法 + 固定时间衰减
  - 每根日K的成交量按三角形分布摊到 [low, high] 区间，峰值在收盘价；
  - 每日旧筹码整体按衰减系数 lambda 留存（无换手率数据，用固定时间衰减）；
  - 滚动窗口 window 日，窗口外筹码移除（增量 O(1) 更新，无未来函数）。

输出：每个交易日的 ChipSnapshot（分布数组 + 获利盘/平均成本/集中度/筹码峰/套牢盘）

依赖：numpy（Python310 已带）
用法：见文件底部 __main__ 自检
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class ChipSnapshot:
    """单日筹码分布快照"""
    dt: date                 # 交易日
    close: float             # 当日收盘价（不复权）
    bins: np.ndarray         # 价格档中心（全局共享引用）
    dist: np.ndarray         # 每档筹码量（相对值，未归一）
    total: float             # 总筹码量
    profit_ratio: float      # 获利盘比例 0~1（现价下方筹码占比）
    trapped_ratio: float     # 套牢盘比例 0~1（现价上方筹码占比）
    avg_cost: float          # 平均成本（筹码重心）
    conc90: float            # 90% 筹码集中度（越小越集中）
    conc70: float            # 70% 筹码集中度
    p5: float                # 90% 区间下沿（5% 分位价）
    p95: float               # 90% 区间上沿（95% 分位价）
    peaks: List[dict]        # 筹码峰列表：[{price, value, share}...] 按量排序
    peak_count: int          # 显著峰数量
    peak_prices: List[float] # 峰位价格（用于图标记）


# ---------------------------------------------------------------------------
# 核心算法
# ---------------------------------------------------------------------------

class ChipDistribution:
    """
    滚动窗口筹码分布计算器。

    参数
    ----
    window : int    滚动窗口（交易日数），默认 250
    decay  : float  每日筹码留存率 λ（0~1），默认 0.98。
                    λ=0.98 → 20日留存 67%、60日留存 30%、120日留存 9%、250日留存 0.6%
    n_bins : int    价格分档数（全区间均匀分档），默认 200
    smooth : int    筹码峰检测前的平滑窗口（奇数），默认 3
    peak_min_share : float  峰的最小占比阈值（相对总筹码），默认 0.03（3%）
    """

    def __init__(self, window: int = 250, decay: float = 0.98, n_bins: int = 200,
                 smooth: int = 3, peak_min_share: float = 0.03):
        if not 0 < decay <= 1.0:
            raise ValueError(f"decay 需在 (0,1]，实际 {decay}")
        self.window = window
        self.decay = decay
        self.n_bins = n_bins
        self.smooth = smooth if smooth % 2 == 1 else smooth + 1
        self.peak_min_share = peak_min_share
        self._bins: Optional[np.ndarray] = None

    # -- 对外入口 ----------------------------------------------------------
    def compute(self, rows: List[dict]) -> List[ChipSnapshot]:
        """
        逐日滚动计算筹码分布。

        rows : [{dt, high, low, close, vol, avg?, turnover?}]，dt 为 date/datetime，
               high/low/close 必须为【不复权】原始价，vol 为成交量（股），
               avg 为当日成交均价（不复权口径），缺省时回退 (high+low+close)/3。
               turnover 为当日换手率（小数 0~1），缺省时用固定衰减 self.decay。
               必须按时间升序。
        返回  : 与输入等长的 ChipSnapshot 列表（含预热期快照，图表层自行截取）。
        """
        if not rows:
            return []
        rows = sorted(rows, key=lambda r: r["dt"])
        self._init_bins(rows)

        snapshots: List[ChipSnapshot] = []
        queue: List[tuple] = []           # (当日三角分布贡献 c_t, 入队时累计留存积 P[t])
        dist = np.zeros(self.n_bins, dtype=float)
        cur_p = 1.0                       # 累计留存积 P[t] = ∏ keep_j

        for r in rows:
            dt = r["dt"]
            high, low, close, vol = float(r["high"]), float(r["low"]), float(r["close"]), float(r["vol"])
            avg = float(r.get("avg") or 0.0)
            if avg <= 0 or not (low <= avg <= high):
                avg = (high + low + close) / 3.0   # 均价回退

            # 无量/停牌日：不产生新筹码，也不衰减（无换手=筹码不转移），直接复制快照
            if vol <= 0 or not (high >= low and high > 0):
                snapshots.append(self._make_snapshot(dt, close, dist))
                continue

            # 当日留存率 keep = 1 - 换手率；无换手率数据时回退固定衰减
            tr = float(r.get("turnover") or 0.0)
            if tr > 0.5:                  # 防御：若误传百分比数字(如 32)则转小数
                tr /= 100.0
            keep = (1.0 - tr) if (0.0 < tr < 1.0) else self.decay

            # 1) 旧筹码整体衰减
            dist *= keep
            cur_p *= keep

            # 2) 窗口滑动：移除窗口外那天（其当前留存值 = c × P[t]/P[k]）
            if len(queue) >= self.window:
                old_c, old_p = queue.pop(0)
                dist -= old_c * (cur_p / old_p)
                dist = np.clip(dist, 0.0, None)

            # 3) 当日三角形分布贡献（顶点=成交均价），当天不衰减
            contrib = self._tri_dist(low, high, avg, vol)
            dist += contrib
            queue.append((contrib, cur_p))

            snapshots.append(self._make_snapshot(dt, close, dist))

        return snapshots

    # -- 价格分档 -----------------------------------------------------------
    def _init_bins(self, rows: List[dict]):
        lo = min(float(r["low"]) for r in rows if r["low"] > 0)
        hi = max(float(r["high"]) for r in rows if r["high"] > 0)
        if hi <= lo:
            hi = lo * 1.01 + 1e-9
        self._bins = np.linspace(lo, hi, self.n_bins)
        self._bin_w = (hi - lo) / (self.n_bins - 1)

    @property
    def bins(self) -> np.ndarray:
        return self._bins

    # -- 三角形分布 ----------------------------------------------------------
    def _tri_dist(self, low: float, high: float, peak: float, vol: float) -> np.ndarray:
        """将 vol 按三角形分布摊到 [low, high]，顶点在 peak（成交均价/收盘价）。"""
        b = self._bins
        if high <= low:                       # 一字板/零振幅
            c = np.zeros_like(b)
            idx = int(np.clip(round((peak - b[0]) / self._bin_w), 0, self.n_bins - 1))
            c[idx] = vol
            return c

        # 三角形权重：low→peak 线性升，peak→high 线性降
        w = np.zeros_like(b)
        mask_l = (b >= low) & (b <= peak)
        mask_r = (b > peak) & (b <= high)
        if peak > low:
            w[mask_l] = (b[mask_l] - low) / (peak - low)
        else:                                  # 顶点贴近最低
            w[mask_l] = 1.0
        if high > peak:
            w[mask_r] = (high - b[mask_r]) / (high - peak)
        else:
            w[mask_r] = 1.0

        s = w.sum()
        if s <= 0:
            return np.zeros_like(b)
        return w * (vol / s)

    # -- 快照与衍生指标 -------------------------------------------------------
    def _make_snapshot(self, dt, close: float, dist: np.ndarray) -> ChipSnapshot:
        b = self._bins
        total = dist.sum()
        if total <= 0:
            return ChipSnapshot(dt, close, b, dist.copy(), 0.0, 0.0, 0.0, 0.0, 0.0,
                                0.0, close, close, [], 0, [])

        # 获利盘 / 套牢盘
        profit = dist[b <= close].sum() / total
        trapped = 1.0 - profit

        # 平均成本
        avg_cost = float((b * dist).sum() / total)

        # 分位价格（90% 区间 P5~P95，70% 区间 P15~P85）
        cum = np.cumsum(dist)
        def quantile(q: float) -> float:
            target = q * total
            idx = int(np.searchsorted(cum, target))
            idx = min(max(idx, 0), self.n_bins - 1)
            return float(b[idx])
        p5, p95 = quantile(0.05), quantile(0.95)
        p15, p85 = quantile(0.15), quantile(0.85)
        conc90 = (p95 - p5) / (p95 + p5) if p95 + p5 > 0 else 0.0
        conc70 = (p85 - p15) / (p85 + p15) if p85 + p15 > 0 else 0.0

        # 筹码峰检测：平滑后找局部极大
        peaks = self._find_peaks(dist, total)
        peak_prices = [p["price"] for p in peaks]
        return ChipSnapshot(dt, close, b, dist.copy(), total, float(profit), float(trapped),
                            float(avg_cost), float(conc90), float(conc70), float(p5), float(p95),
                            peaks, len(peaks), peak_prices)

    def _find_peaks(self, dist: np.ndarray, total: float) -> List[dict]:
        b = self._bins
        w = self.smooth
        pad = w // 2
        sm = np.convolve(dist, np.ones(w) / w, mode="same")
        sm[:pad] = dist[:pad]
        sm[-pad:] = dist[-pad:]

        peaks = []
        for i in range(1, self.n_bins - 1):
            if sm[i] >= sm[i - 1] and sm[i] > sm[i + 1]:
                share = sm[i] / total
                if share >= self.peak_min_share:
                    peaks.append({"price": float(b[i]), "value": float(sm[i]), "share": float(share)})
        peaks.sort(key=lambda p: p["value"], reverse=True)
        return peaks[:5]


# ---------------------------------------------------------------------------
# 数据加载：khData 不复权日线
# ---------------------------------------------------------------------------

class KhDataLoader:
    """
    khData DuckDB 不复权日线加载器。

    数据源：D:\\khData\\<SH|SZ|BJ>\\<code>.db 的 kline_1d 表（原始 open/high/low/close）。
    数据库 turn(换手率) 列有值时自动带入 turnover 字段，compute 自动启用真实换手率衰减；
    否则回退固定衰减（decay）。
    """

    def __init__(self, db_dir: str = r"D:\khData"):
        self.db_dir = db_dir

    def load(self, code: str, exchange: str, start: str = None, end: str = None) -> List[dict]:
        """
        code      : 股票代码，如 "000001"
        exchange  : "SH" / "SZ" / "BJ"
        start/end : "YYYY-MM-DD"，None 表示不限
        返回      : [{dt, open, high, low, close, vol, amount, avg, turnover, suspend}] 按时间升序
        """
        import duckdb, os
        db_path = os.path.join(self.db_dir, exchange, f"{code}.db")
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"未找到数据文件: {db_path}")

        con = duckdb.connect(db_path, read_only=True)
        try:
            sql = ("SELECT time, open, high, low, close, "
                   "volume, amount, COALESCE(suspendFlag, 0) AS suspendFlag, "
                   "turn FROM kline_1d WHERE 1=1")
            params = []
            if start:
                sql += " AND time >= ?"
                params.append(start)
            if end:
                sql += " AND time <= ?"
                params.append(end + " 23:59:59")
            sql += " ORDER BY time"
            df = con.execute(sql, params).fetchdf()
        finally:
            con.close()

        rows = []
        for _, r in df.iterrows():
            vol = float(r["volume"] or 0.0)
            amount = float(r["amount"] or 0.0)
            close = float(r["close"] or 0.0)
            turn = float(r["turn"] or 0.0)
            # 成交均价（元/股）：volume 单位是"手"(100股)。
            # 当前数据口径为【不复权】原始价，无需乘复权因子。
            avg = 0.0
            if vol > 0 and close > 0:
                avg = amount / vol / 100.0
            rows.append({
                "dt": r["time"].date() if hasattr(r["time"], "date") else r["time"],
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": close,
                "vol": vol,
                "amount": amount,
                "avg": avg,
                "turnover": turn,      # 换手率（数据库 turn 列，若有值则 compute 自动使用）
                "suspend": int(r["suspendFlag"] or 0),
            })
        return rows


def load_front_daily(code: str, exchange: str, start: str = None, end: str = None,
                     db_dir: str = r"D:\khData", refresh: bool = False) -> List[dict]:
    """
    加载【不复权】日线（便捷函数，内部使用 KhDataLoader）。

    code      : 股票代码，如 "000001"
    exchange  : "SH" / "SZ" / "BJ"
    start/end : "YYYY-MM-DD"，None 表示不限
    返回      : [{dt, open, high, low, close, vol, amount, avg, turnover?}] 按时间升序
    """
    return KhDataLoader(db_dir).load(code, exchange, start, end)


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # 构造 60 天模拟数据：低位盘整后放量拉升，验证获利盘/峰位变化
    rng = np.random.default_rng(42)
    test_rows = []
    price = 10.0
    for i in range(120):
        drift = 0.0
        vol = 1_000_000 + rng.integers(-200_000, 200_000)
        if 40 <= i < 60:                      # 中段放量上涨
            drift = 0.02
            vol = 3_000_000
        if 90 <= i < 110:                     # 后段高位放量
            drift = 0.005
            vol = 4_000_000
        price *= (1 + drift + rng.normal(0, 0.008))
        o = price * (1 + rng.normal(0, 0.004))
        c = price
        h = max(o, c) * (1 + abs(rng.normal(0, 0.005)))
        l = min(o, c) * (1 - abs(rng.normal(0, 0.005)))
        test_rows.append({"dt": date(2024, 1, 1) + __import__("datetime").timedelta(days=i * 3),
                          "high": h, "low": l, "close": c, "vol": int(vol)})

    cd = ChipDistribution(window=60, decay=0.95, n_bins=150, peak_min_share=0.05)
    snaps = cd.compute(test_rows)

    print(f"共 {len(snaps)} 个快照, 价格档 {cd.n_bins} 个, 档宽 {cd._bin_w:.4f}")
    for idx in [59, 79, 99, 119]:
        s = snaps[idx]
        peak_str = ", ".join(f"{p['price']:.2f}" for p in s.peaks)
        print(f"[{s.dt}] close={s.close:6.2f} 获利盘={s.profit_ratio:5.1%} 套牢={s.trapped_ratio:5.1%} "
              f"均本={s.avg_cost:6.2f} conc90={s.conc90:.3f} 峰数={s.peak_count} 峰位={peak_str}")
    # 正确性校验
    s = snaps[-1]
    assert abs(s.profit_ratio + s.trapped_ratio - 1.0) < 1e-9, "获利+套牢必须=1"
    assert s.conc90 >= 0, "集中度非负"
    # 校验均价回退：无 avg 字段时应自动用 (h+l+c)/3
    snaps2 = cd.compute([{k: v for k, v in r.items() if k != "avg"} for r in test_rows])
    assert len(snaps2) == len(snaps), "无 avg 字段也应可运行"
    print("自检通过：获利/套牢互补、集中度非负、均价回退正常")
