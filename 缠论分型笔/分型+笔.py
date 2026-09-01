#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缠论 · 分型与笔 —— 纯 Python 移植
==================================
逻辑同步自 GitHub 仓库 czsc-master（Rust 版 czsc-core），只包含：
    原始K线 → 去包含关系(NewBar) → 分型(FX) → 笔(BI) 的完整算法。

按需求，刻意【不】包含：中枢(ZS)、买卖点、背驰、趋势判断等后续环节。

与本模块对应的 Rust 源码：
    crates/czsc-core/src/objects/{bar,mark,direction,fx,bi}.rs
    crates/czsc-core/src/analyze/{mod,utils}.rs

用法：
    from chan_fx_bi import RawBar, CZSC, bars_from_rows

    rows = [{"dt": ..., "open": .., "close": .., "high": .., "low": .., "vol": .., "amount": ..}, ...]
    bars = bars_from_rows(rows, symbol="600000.SH", freq="日线")
    c = CZSC(bars, max_bi_num=50, min_bi_len=6)

    for fx in c.fx_list:    # 全部分型（顶/底交替）
        ...
    for bi in c.bi_list:    # 已完成笔
        print(bi.direction, bi.start_dt, bi.end_dt, bi.get_high(), bi.get_low())

运行内置自检（用仓库 Rust 测试数据对拍）：
    python chan_fx_bi.py
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple

__all__ = [
    "RawBar", "NewBar", "FX", "BI",
    "remove_include", "check_fx", "check_fxs", "check_bi",
    "CZSC", "bars_from_rows",
]

# =====================================================================
# 一、数据结构（对齐 czsc-core：RawBar / NewBar / FX / BI）
# =====================================================================

@dataclass
class RawBar:
    """原始K线（对应 Rust RawBar）。id 为升序序号，freq 为K线级别字符串。"""
    symbol: str
    dt: datetime
    open: float
    close: float
    high: float
    low: float
    vol: float
    amount: float
    id: int = 0
    freq: str = ""


@dataclass
class NewBar:
    """去包含关系后的K线（对应 Rust NewBar）。
    elements: 构成它的原始K线列表（无包含合并时只有 1 根，合并后多根）。"""
    symbol: str
    dt: datetime
    open: float
    close: float
    high: float
    low: float
    vol: float
    amount: float
    id: int = 0
    freq: str = ""
    elements: List[RawBar] = field(default_factory=list)

    @staticmethod
    def from_raw(b: RawBar) -> "NewBar":
        return NewBar(b.symbol, b.dt, b.open, b.close, b.high, b.low,
                      b.vol, b.amount, b.id, b.freq, [b])


@dataclass
class FX:
    """分型（对应 Rust FX）。mark: 'G' 顶分型 / 'D' 底分型。
    fx 为分型值：顶=high，底=low。elements 为构成它的 3 根 NewBar。"""
    symbol: str
    dt: datetime
    mark: str              # 'G' / 'D'
    high: float
    low: float
    fx: float
    elements: List[NewBar] = field(default_factory=list)

    def power_str(self) -> str:
        """分型强度：强/中/弱（对应 Rust FX._power_str）"""
        k1, k2, k3 = self.elements
        if self.mark == "D":
            if k3.close > k1.high:
                return "强"
            if k3.close > k2.high:
                return "中"
            return "弱"
        if k3.close < k1.low:
            return "强"
        if k3.close < k2.low:
            return "中"
        return "弱"

    def power_volume(self) -> float:
        """成交量力度：构成分型的 3 根 K 线成交量之和"""
        return sum(x.vol for x in self.elements)

    def __repr__(self) -> str:
        return (f"FX(symbol={self.symbol}, dt={self.dt:%Y-%m-%d %H:%M:%S}, "
                f"mark={self.mark}, fx={self.fx})")


@dataclass
class BI:
    """笔（对应 Rust BI）。direction: 'Up' 向上笔 / 'Down' 向下笔。
    fx_a 为起点分型，fx_b 为终点分型，fxs 为笔内分型列表，bars 为笔的 NewBar 列表。"""
    symbol: str
    fx_a: FX
    fx_b: FX
    fxs: List[FX] = field(default_factory=list)
    direction: str = ""
    bars: List[NewBar] = field(default_factory=list)

    @property
    def start_dt(self) -> datetime:
        return self.fx_a.dt

    @property
    def end_dt(self) -> datetime:
        return self.fx_b.dt

    def get_high(self) -> float:
        return max(self.fx_a.high, self.fx_b.high)

    def get_low(self) -> float:
        return min(self.fx_a.low, self.fx_b.low)

    def get_power(self) -> float:
        """价差力度：|终点分型值 - 起点分型值|，保留2位小数"""
        return round(abs(self.fx_b.fx - self.fx_a.fx), 2)

    def get_power_volume(self) -> float:
        """成交量力度：笔内（不含首尾分型）K线量能之和"""
        if len(self.bars) <= 2:
            return 0.0
        return sum(x.vol for x in self.bars[1:-1])

    def get_length(self) -> int:
        """笔的无包含关系K线数量"""
        return len(self.bars)

    def __repr__(self) -> str:
        return (f"BI(symbol={self.symbol}, sdt={self.start_dt:%Y-%m-%d %H:%M:%S}, "
                f"edt={self.end_dt:%Y-%m-%d %H:%M:%S}, direction={self.direction}, "
                f"high={self.get_high()}, low={self.get_low()})")


# =====================================================================
# 二、缠论核心算法（复刻 czsc-core analyze/utils.rs）
# =====================================================================

def remove_include(k1: NewBar, k2: NewBar, k3: RawBar) -> Tuple[bool, NewBar]:
    """去除包含关系（对应 Rust remove_include）。

    输入 k1、k2 为相邻无包含关系的 K 线，k3 为原始新K线。
    用 k1-k2 的高点关系决定方向：向上取较高 high/low，向下取较低 high/low。
    返回 (has_include, merged)。has_include 为 True 表示 k3 与 k2 有包含关系并被合并。"""
    if k1.high < k2.high:
        direction = "Up"
    elif k1.high > k2.high:
        direction = "Down"
    else:
        return False, NewBar.from_raw(k3)

    has_inclusion = (k2.high <= k3.high and k2.low >= k3.low) or \
                    (k2.high >= k3.high and k2.low <= k3.low)
    if not has_inclusion:
        return False, NewBar.from_raw(k3)

    if direction == "Up":
        high = max(k2.high, k3.high)
        low = max(k2.low, k3.low)
        dt = k2.dt if k2.high > k3.high else k3.dt
    else:
        high = min(k2.high, k3.high)
        low = min(k2.low, k3.low)
        dt = k2.dt if k2.low < k3.low else k3.dt

    # 阳线 open>close 取 (high,low)，阴线取 (low,high)（对应 Rust 实现）
    open_, close = (high, low) if k3.open > k3.close else (low, high)

    # elements：k2 中与 k3 时间戳不同的元素 + k3 本身
    elements = [x for x in k2.elements if x.dt != k3.dt] + [k3]
    merged = NewBar(k2.symbol, dt, open_, close, high, low,
                    k2.vol + k3.vol, k2.amount + k3.amount,
                    k2.id, k2.freq, elements)
    return True, merged


def check_fx(k1: NewBar, k2: NewBar, k3: NewBar) -> Optional[FX]:
    """三根无包含关系K线构成分型（对应 Rust check_fx）。
    顶分型：中K高点最高且低点最高；底分型：中K低点最低且高点最低。"""
    if k1.high < k2.high and k2.high > k3.high and \
       k1.low < k2.low and k2.low > k3.low:
        return FX(k1.symbol, k2.dt, "G", k2.high, k2.low, k2.high, [k1, k2, k3])
    if k1.low > k2.low and k2.low < k3.low and \
       k1.high > k2.high and k2.high < k3.high:
        return FX(k1.symbol, k2.dt, "D", k2.high, k2.low, k2.low, [k1, k2, k3])
    return None


def check_fxs(bars: List[NewBar]) -> List[FX]:
    """扫描无包含K线序列，找出所有分型（对应 Rust check_fxs）。
    强制顶底交替：若新分型与上一个分型标记相同则丢弃新分型（Rust 会打错误日志）。"""
    fxs: List[FX] = []
    for i in range(len(bars) - 2):
        fx = check_fx(bars[i], bars[i + 1], bars[i + 2])
        if fx is None:
            continue
        if fxs and fx.mark == fxs[-1].mark:
            # Rust 对应 eprintln!("check_fxs错误: ...")，行为上直接丢弃该分型
            continue
        fxs.append(fx)
    return fxs


def _bisect_left(dts, target):
    """第一个 dt >= target 的索引（对应 Rust partition_point(dt < target)）"""
    return bisect.bisect_left(dts, target)


def _bisect_right(dts, target):
    """第一个 dt > target 的索引（对应 Rust partition_point(dt <= target)）"""
    return bisect.bisect_right(dts, target)


def check_bi(bars: List[NewBar], min_bi_len: int = 6) -> Tuple[Optional[BI], List[NewBar]]:
    """从无包含K线序列中识别一笔（对应 Rust check_bi）。
    返回 (BI or None, 剩余bars)。

    规则：
    - 起点分型为序列第一个分型 fx_a；
    - 底分型起笔 → 向上笔，终点在后续顶分型中选高点最高的；
    - 顶分型起笔 → 向下笔，终点在后续底分型中选低点最低的；
    - 并列时保留首次出现者（与 Rust reduce / 首遇替换语义一致）；
    - 首尾分型无包含关系，且起点到终点去包含K线数 >= min_bi_len 才成笔。"""
    fxs = check_fxs(bars)
    if len(fxs) < 2:
        return None, bars

    fx_a = fxs[0]
    fx_b: Optional[FX] = None
    if fx_a.mark == "D":
        # 向上笔：后续顶分型中选高点最高的（并列保留首个）
        for x in fxs:
            if x.mark == "G" and x.dt > fx_a.dt and x.fx > fx_a.fx:
                if fx_b is None or x.high > fx_b.high:
                    fx_b = x
    else:
        # 向下笔：后续底分型中选低点最低的（并列保留首个）
        for x in fxs:
            if x.mark == "D" and x.dt > fx_a.dt and x.fx < fx_a.fx:
                if fx_b is None or x.low < fx_b.low:
                    fx_b = x
    if fx_b is None:
        return None, bars

    dts = [b.dt for b in bars]
    start_dt = fx_a.elements[0].dt
    end_dt = fx_b.elements[2].dt
    start_idx = _bisect_left(dts, start_dt)
    end_idx = _bisect_right(dts, end_dt)
    if start_idx >= end_idx:
        return None, bars
    bars_a = bars[start_idx:end_idx]

    new_start_idx = _bisect_left(dts, fx_b.elements[0].dt)
    bars_b = bars[new_start_idx:]

    ab_include = (fx_a.high > fx_b.high and fx_a.low < fx_b.low) or \
                 (fx_a.high < fx_b.high and fx_a.low > fx_b.low)

    if not ab_include and len(bars_a) >= min_bi_len:
        direction = "Up" if fx_a.mark == "D" else "Down"
        fxs_in = [x for x in fxs if start_dt <= x.dt <= end_dt]
        bi = BI(symbol=fx_a.symbol, fx_a=fx_a, fx_b=fx_b,
                fxs=fxs_in, direction=direction, bars=bars_a)
        return bi, bars_b
    return None, bars


# =====================================================================
# 三、CZSC 分析器（逐K线增量更新，复刻 czsc-core analyze/mod.rs）
# =====================================================================

class CZSC:
    """缠论分析器。只维护：去包含K线 bars_ubi、已完成笔 bi_list。

    参数：
        max_bi_num: 最多保留的笔数量（默认 50）
        min_bi_len: 成笔的最小去包含K线数（默认 6）
    """

    def __init__(self, bars_raw: List[RawBar], max_bi_num: int = 50, min_bi_len: int = 6):
        self.max_bi_num = max_bi_num
        self.min_bi_len = min_bi_len
        self.bars_raw: List[RawBar] = []
        self.bars_ubi: List[NewBar] = []
        self.bi_list: List[BI] = []
        self.symbol = bars_raw[0].symbol
        for b in bars_raw:
            self.update_bar(b)

    # ---------------- 对外属性 ----------------

    @property
    def fx_list(self) -> List[FX]:
        """分型列表（含笔内部分型 + 未完成笔部分型，按时间去重递增）"""
        fxs: List[FX] = []
        for bi in self.bi_list:
            for x in bi.fxs[1:]:
                if not fxs or x.dt > fxs[-1].dt:
                    fxs.append(x)
        ubi_fxs = self.get_ubi_fxs()
        if ubi_fxs:
            for x in ubi_fxs:
                if not fxs or x.dt > fxs[-1].dt:
                    fxs.append(x)
        return fxs

    def get_finished_bis(self) -> List[BI]:
        """已确认完成的笔（最后一笔未完成时剔除）"""
        if not self.bi_list:
            return []
        if len(self.bars_ubi) < 5:
            return self.bi_list[:-1]
        return list(self.bi_list)

    def get_ubi_fxs(self) -> Optional[List[FX]]:
        """未完成笔（bars_ubi）中的分型"""
        if not self.bars_ubi:
            return None
        return check_fxs(self.bars_ubi)

    @property
    def last_bi_extend(self) -> bool:
        """最后一笔是否仍在延伸中"""
        if not self.bi_list or not self.bars_ubi:
            return False
        last = self.bi_list[-1]
        if last.direction == "Up":
            return max(b.high for b in self.bars_ubi) > last.get_high()
        return min(b.low for b in self.bars_ubi) < last.get_low()

    # ---------------- 增量更新 ----------------

    def _sync_extended_last_ubi_in_bis(self, last_ubi: NewBar, bar: RawBar) -> None:
        """同一时间戳K线延伸时，同步已入笔结构中引用的 last_ubi 镜像副本。
        对应 Rust CZSC::sync_extended_last_ubi_in_bis。"""
        def patch_new_bar(nb: NewBar) -> None:
            # nb 与弹出的 last_ubi 相等，且其最后元素时间戳与延伸K线一致 → 替换
            if nb == last_ubi and nb.elements and nb.elements[-1].dt == bar.dt:
                nb.elements[-1] = bar

        def patch_fx(fx: FX) -> None:
            for nb in fx.elements:
                patch_new_bar(nb)

        for bi in self.bi_list:
            for nb in bi.bars:
                patch_new_bar(nb)
            patch_fx(bi.fx_a)
            patch_fx(bi.fx_b)
            for fx in bi.fxs:
                patch_fx(fx)

    def update_bar(self, bar: RawBar) -> None:
        """喂入一根新的原始K线（对应 Rust CZSC::update_bar）。
        若 bar.dt 与上一根相同，则视为同一根K线的时间延伸（就地更新）。"""
        if not self.bars_raw or bar.dt != self.bars_raw[-1].dt:
            self.bars_raw.append(bar)
            last_bars = [bar]
        else:
            # 同一时间戳延伸：替换 bars_raw 末尾，弹出 bars_ubi 末尾并同步
            self.bars_raw[-1] = bar
            last_ubi = self.bars_ubi.pop()
            self._sync_extended_last_ubi_in_bis(last_ubi, bar)
            last_bars = list(last_ubi.elements)
            assert bar.dt == last_bars[-1].dt, \
                f"时间错位: {bar.dt} != {last_bars[-1].dt}"
            last_bars[-1] = bar

        # 去除包含关系
        for b in last_bars:
            if len(self.bars_ubi) < 2:
                self.bars_ubi.append(NewBar.from_raw(b))
            else:
                has_inc, merged = remove_include(self.bars_ubi[-2], self.bars_ubi[-1], b)
                if has_inc:
                    self.bars_ubi[-1] = merged
                else:
                    self.bars_ubi.append(merged)

        self._update_bi()

        # 限制笔数量
        if len(self.bi_list) > self.max_bi_num:
            start = len(self.bi_list) - self.max_bi_num
            self.bi_list = self.bi_list[start:]

        # 裁剪 bars_raw：只保留第一笔起始K线之后的部分
        if self.bi_list:
            sdt = self.bi_list[0].fx_a.elements[0].dt
            dts = [b.dt for b in self.bars_raw]
            idx = _bisect_left(dts, sdt)
            if idx:
                self.bars_raw = self.bars_raw[idx:]

    def _update_bi(self) -> None:
        """更新笔列表（对应 Rust CZSC::__update_bi）"""
        if len(self.bars_ubi) < 3:
            return

        if not self.bi_list:
            # 第一笔的查找
            fxs = check_fxs(self.bars_ubi)
            if not fxs:
                return
            first = fxs[0]
            # 起点分型：与第一个分型同标记中，底取最低、顶取最高（并列保留首个）
            if first.mark == "D":
                fx_a = min((x for x in fxs if x.mark == "D"), key=lambda x: x.low)
            else:
                fx_a = max((x for x in fxs if x.mark == "G"), key=lambda x: x.high)
            bars_ubi = [x for x in self.bars_ubi if x.dt >= fx_a.elements[0].dt]
            bi, rest = check_bi(bars_ubi, self.min_bi_len)
            if bi:
                self.bi_list.append(bi)
            self.bars_ubi = list(rest)
            return

        bi, rest = check_bi(self.bars_ubi, self.min_bi_len)
        if bi:
            self.bi_list.append(bi)
        self.bars_ubi = list(rest)

        # 后处理：若当前未完成笔突破了最后一笔极值，则当前笔被破坏，
        # 将最后一笔的 bars 与 bars_ubi 合并回退，并丢弃该笔
        if not self.bi_list or not self.bars_ubi:
            return
        last_bi = self.bi_list[-1]
        if last_bi.direction == "Up" and self.bars_ubi[-1].high > last_bi.get_high():
            merge_point = last_bi.bars[-2].dt
            merged = list(last_bi.bars[:-2]) + \
                     [x for x in self.bars_ubi if x.dt >= merge_point]
            self.bars_ubi = merged
            self.bi_list.pop()
        elif last_bi.direction == "Down" and self.bars_ubi[-1].low < last_bi.get_low():
            merge_point = last_bi.bars[-2].dt
            merged = list(last_bi.bars[:-2]) + \
                     [x for x in self.bars_ubi if x.dt >= merge_point]
            self.bars_ubi = merged
            self.bi_list.pop()


# =====================================================================
# 四、辅助：把数据行转换为 RawBar 列表
# =====================================================================

def bars_from_rows(rows, symbol: str, freq: str = "") -> List[RawBar]:
    """把形如 [{'dt','open','close','high','low','vol','amount'}, ...] 的行
    转换为 RawBar 列表（id 按行号升序，对应 Rust format_standard_kline）。
    dt 支持 datetime 或 '%Y-%m-%d[ %H:%M:%S]' 字符串。"""
    bars = []
    for i, r in enumerate(rows):
        dt = r["dt"]
        if isinstance(dt, str):
            dt = dt.strip()
            fmt = "%Y-%m-%d %H:%M:%S" if " " in dt else "%Y-%m-%d"
            dt = datetime.strptime(dt, fmt)
        bars.append(RawBar(
            symbol=symbol, dt=dt,
            open=float(r["open"]), close=float(r["close"]),
            high=float(r["high"]), low=float(r["low"]),
            vol=float(r["vol"]), amount=float(r["amount"]),
            id=i, freq=freq,
        ))
    return bars


# =====================================================================
# 五、内置自检：用 Rust 仓库自带测试数据对拍
# =====================================================================

_TEST_CSV = """dt,symbol,open,close,high,low,vol,amount
2025-01-02,002515.SZ,50.73,51.29,52.97,50.62,32900684.0,152798823.0
2025-01-03,002515.SZ,51.4,48.72,51.85,48.6,33224687.0,147184323.0
2025-01-06,002515.SZ,48.83,48.6,49.39,47.48,17419634.0,75608391.0
2025-01-07,002515.SZ,48.6,48.94,49.05,48.27,13929982.0,60500438.0
2025-01-08,002515.SZ,48.27,48.04,48.94,47.26,17697397.0,75973887.0
2025-01-09,002515.SZ,48.27,48.16,48.83,47.6,14284260.0,61391856.0
2025-01-10,002515.SZ,48.04,46.92,48.94,46.81,16080374.0,68834125.0
2025-01-13,002515.SZ,46.59,46.92,47.26,45.47,12508818.0,52037636.0
2025-01-14,002515.SZ,46.92,48.16,48.27,46.92,16407679.0,69944802.0
2025-01-15,002515.SZ,49.5,49.5,50.73,49.05,29140842.0,129502353.0
2025-01-16,002515.SZ,49.5,49.72,50.28,48.94,19124511.0,84774186.0
2025-01-17,002515.SZ,49.28,50.28,51.74,49.05,22228511.0,99754272.0
2025-01-20,002515.SZ,50.4,50.4,50.73,49.61,14908933.0,66989586.0
2025-01-21,002515.SZ,50.62,50.06,50.73,49.61,11565100.0,51612511.0
2025-01-22,002515.SZ,50.06,49.16,50.06,48.83,10889797.0,47963340.0
2025-01-23,002515.SZ,49.39,48.72,49.95,48.72,13050206.0,57522568.0
2025-01-24,002515.SZ,48.49,48.83,48.94,48.27,12042388.0,52334558.0
2025-01-27,002515.SZ,49.05,49.39,51.74,49.05,22813802.0,102357601.0
2025-02-05,002515.SZ,49.39,49.16,49.95,48.72,13525075.0,59524887.0
2025-02-06,002515.SZ,48.83,49.05,49.28,48.16,17429613.0,75782611.0
2025-02-07,002515.SZ,48.94,49.5,49.95,48.72,17447114.0,76989329.0
2025-02-10,002515.SZ,49.39,50.4,50.51,49.16,18733821.0,83810683.0
2025-02-11,002515.SZ,50.4,49.84,50.73,49.61,13189816.0,58803966.0
2025-02-12,002515.SZ,50.06,50.06,50.4,49.5,15881392.0,70692291.0
2025-02-13,002515.SZ,49.84,49.84,50.51,49.61,18048669.0,80671035.0
2025-02-14,002515.SZ,49.72,49.05,49.95,48.94,17455299.0,76786904.0
2025-02-17,002515.SZ,49.16,49.39,49.61,48.6,15791678.0,69303481.0
2025-02-18,002515.SZ,49.16,47.71,49.39,47.48,20599809.0,88885983.0
2025-02-19,002515.SZ,47.48,48.04,48.16,47.37,12911258.0,55064600.0
2025-02-20,002515.SZ,48.04,48.27,48.83,47.71,12823411.0,55267260.0
2025-02-21,002515.SZ,48.27,47.6,48.72,47.48,16547084.0,70527761.0
2025-02-24,002515.SZ,47.71,52.41,52.41,47.71,93355060.0,426873493.0
2025-02-25,002515.SZ,51.96,50.51,51.96,50.17,54431026.0,246916111.0
2025-02-26,002515.SZ,50.62,52.52,52.86,50.17,50584995.0,232883144.0
2025-02-27,002515.SZ,52.41,53.64,53.98,51.96,47142936.0,224200231.0
2025-02-28,002515.SZ,53.2,52.52,53.53,52.41,29058781.0,137329596.0"""


def _run_selftest() -> None:
    """用 czsc-master 仓库 Rust 测试用例（analyze/mod.rs tests）对拍：
    期望的 bi_list 与 fx_list 来自 Rust 测试断言。"""
    import csv
    import io

    rows = list(csv.DictReader(io.StringIO(_TEST_CSV)))
    bars = bars_from_rows(rows, symbol="002515.SZ", freq="日线")
    c = CZSC(bars, max_bi_num=50, min_bi_len=6)

    # ---- 笔：与 Rust test_czsc_bi_list 期望一致 ----
    expected_bis = [
        ("2025-01-13 00:00:00", "2025-01-17 00:00:00", "Up", 51.74, 45.47),
        ("2025-01-17 00:00:00", "2025-02-06 00:00:00", "Down", 51.74, 48.16),
        ("2025-02-06 00:00:00", "2025-02-11 00:00:00", "Up", 50.73, 48.16),
        ("2025-02-11 00:00:00", "2025-02-19 00:00:00", "Down", 50.73, 47.37),
    ]
    assert len(c.bi_list) == len(expected_bis), \
        f"笔数量不符: {len(c.bi_list)} != {len(expected_bis)}"
    for i, (bi, exp) in enumerate(zip(c.bi_list, expected_bis)):
        sdt, edt, direction, high, low = exp
        assert bi.start_dt.strftime("%Y-%m-%d %H:%M:%S") == sdt, f"第{i}笔 sdt 不符"
        assert bi.end_dt.strftime("%Y-%m-%d %H:%M:%S") == edt, f"第{i}笔 edt 不符"
        assert bi.direction == direction, f"第{i}笔 direction 不符"
        assert abs(bi.get_high() - high) < 1e-4, f"第{i}笔 high 不符"
        assert abs(bi.get_low() - low) < 1e-4, f"第{i}笔 low 不符"

    # ---- 分型：与 Rust test_czsc_fx_list 期望一致 ----
    expected_fxs = [
        ("2025-01-15 00:00:00", 50.73), ("2025-01-16 00:00:00", 48.94),
        ("2025-01-17 00:00:00", 51.74), ("2025-01-24 00:00:00", 48.27),
        ("2025-01-27 00:00:00", 51.74), ("2025-02-06 00:00:00", 48.16),
        ("2025-02-11 00:00:00", 50.73), ("2025-02-12 00:00:00", 49.50),
        ("2025-02-13 00:00:00", 50.51), ("2025-02-19 00:00:00", 47.37),
        ("2025-02-20 00:00:00", 48.83), ("2025-02-21 00:00:00", 47.48),
    ]
    fxs = c.fx_list
    assert len(fxs) == len(expected_fxs), \
        f"分型数量不符: {len(fxs)} != {len(expected_fxs)}"
    for i, (fx, exp) in enumerate(zip(fxs, expected_fxs)):
        dt, val = exp
        assert fx.dt.strftime("%Y-%m-%d %H:%M:%S") == dt, f"第{i}个分型 dt 不符"
        assert abs(fx.fx - val) < 1e-4, f"第{i}个分型 fx 不符"

    print("✓ 对拍通过：bi_list 4 笔、fx_list 12 个分型 与 Rust 测试期望完全一致")


if __name__ == "__main__":
    _run_selftest()
    print()
    print("用法示例：")
    print("    from chan_fx_bi import RawBar, CZSC, bars_from_rows")
    print("    bars = bars_from_rows(rows, symbol='600000.SH', freq='日线')")
    print("    c = CZSC(bars)")
    print("    for bi in c.bi_list: print(bi)")
