#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缠论趋势分析程序
================
基于 czsc（缠中说禅技术分析工具）的算法逻辑，纯 Python 实现：
K线去包含 → 分型 → 笔 → 中枢 → 背驰/买卖点 → 趋势判断。

数据源：D:\khData（DuckDB，每个标的一个 .db 文件，SH/SZ 目录）

用法（交互）：
    python chan_trend.py
    按提示输入：股票代码 / 周期级别 / 起始日期 / 终止日期

用法（命令行）：
    python chan_trend.py 000001.SZ 日线 2024-01-01 2024-12-31

支持周期：1分钟 / 5分钟 / 15分钟 / 30分钟 / 60分钟 / 120分钟 / 日线 / 周线 / 月线
"""

import sys
import os
import math
import bisect
from datetime import datetime, date, timedelta
from dataclasses import dataclass, field

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass

import duckdb

KHDATA = r"D:\khData"

# =====================================================================
# 一、数据结构（对齐 czsc：RawBar / NewBar / FX / BI / ZS）
# =====================================================================

@dataclass
class RawBar:
    """原始K线"""
    symbol: str
    dt: datetime
    open: float
    close: float
    high: float
    low: float
    vol: float
    amount: float


@dataclass
class NewBar:
    """去包含关系后的K线"""
    symbol: str
    dt: datetime
    open: float
    close: float
    high: float
    low: float
    vol: float
    amount: float
    elements: list = field(default_factory=list)  # 构成它的原始K线

    @staticmethod
    def from_raw(b: RawBar) -> "NewBar":
        return NewBar(b.symbol, b.dt, b.open, b.close, b.high, b.low, b.vol, b.amount, [b])


@dataclass
class FX:
    """分型：mark='G' 顶分型 / 'D' 底分型"""
    mark: str
    dt: datetime
    high: float
    low: float
    fx: float          # 分型值：顶=high，底=low
    elements: list     # 3 根 NewBar

    def power_str(self) -> str:
        """分型强度（复刻 czsc FX._power_str）"""
        k1, k2, k3 = self.elements
        if self.mark == "D":
            if k3.close > k1.high:
                return "强"
            if k3.close > k2.high:
                return "中"
            return "弱"
        else:
            if k3.close < k1.low:
                return "强"
            if k3.close < k2.low:
                return "中"
            return "弱"

    def power_volume(self) -> float:
        return sum(x.vol for x in self.elements)


@dataclass
class BI:
    """笔"""
    fx_a: FX
    fx_b: FX
    fxs: list
    direction: str      # 'Up' / 'Down'
    bars: list          # NewBar 列表

    @property
    def start_dt(self):
        return self.fx_a.dt

    @property
    def end_dt(self):
        return self.fx_b.dt

    def get_high(self):
        return max(self.fx_a.high, self.fx_b.high)

    def get_low(self):
        return min(self.fx_a.low, self.fx_b.low)

    def get_power(self):
        """价差力度"""
        return round(abs(self.fx_b.fx - self.fx_a.fx), 2)

    def get_power_volume(self):
        """成交量力度：笔内（不含首尾分型）K线量能之和"""
        if len(self.bars) <= 2:
            return 0.0
        return sum(x.vol for x in self.bars[1:-1])

    def get_length(self):
        """笔的无包含K线数量"""
        return len(self.bars)

    def get_snr(self):
        """笔内部信噪比：总变化 / 逐K变化之和"""
        raw = [b for nb in self.bars[1:-1] for b in nb.elements]
        n = len(raw)
        if n == 0:
            return 0.0
        if n == 1:
            return abs(raw[0].close - raw[0].open)
        total = abs(raw[-1].close - raw[0].open)
        diff = sum(abs(b.close - b.open) for b in raw)
        return total / diff if diff != 0 else 0.0


# 有效中枢的最小构成笔数：连续 3 笔价格重叠（ZD ≤ ZG）即构成笔中枢，
# 但仅保留延伸后至少 ZS_MIN_BIS 笔的中枢（>=5 笔，过滤短暂形成的 3-4 笔中枢）。
ZS_MIN_BIS = 5

# 中枢雏形 3 笔与重叠区 [zd, zg] 的最小交集占比。
# 排除"单边穿过"的伪中枢：某笔若只沾重叠区边缘就单边离开（如突破后一路涨走），
# 它与重叠区的交集占比会很低（<20%），不构成真实震荡；真实震荡笔通常 >30%。
ZS_OVERLAP_RATIO = 0.20


@dataclass
class ZS:
    """中枢"""
    bis: list
    sdt: datetime
    edt: datetime
    sdir: str
    edir: str
    zg: float   # 上沿
    zd: float   # 下沿
    zz: float   # 中轴
    gg: float   # 最高
    dd: float   # 最低
    direction: str = ""   # 上升/下降/震荡，由 get_zs_seq 填充

    @staticmethod
    def new(bis: list) -> "ZS":
        sdt = bis[0].start_dt
        edt = bis[-1].end_dt
        sdir = bis[0].direction
        edir = bis[-1].direction
        zg = min(b.get_high() for b in bis[:3])
        zd = max(b.get_low() for b in bis[:3])
        gg = max(b.get_high() for b in bis)
        dd = min(b.get_low() for b in bis)
        zz = zd + (zg - zd) * 0.5
        return ZS(bis, sdt, edt, sdir, edir, zg, zd, zz, gg, dd)

    def is_valid(self) -> bool:
        """中枢有效：重叠区间存在（ZD ≤ ZG）"""
        return self.zg >= self.zd


# =====================================================================
# 二、缠论核心算法（复刻 czsc Rust 实现）
# =====================================================================

def remove_include(k1: NewBar, k2: NewBar, k3: RawBar):
    """去除包含关系。输入 k1,k2 为无包含相邻K线，k3 为原始新K线。
    返回 (has_include, NewBar)"""
    if k1.high < k2.high:
        direction = "Up"
    elif k1.high > k2.high:
        direction = "Down"
    else:
        return False, NewBar.from_raw(k3)

    has_inclusion = (k2.high <= k3.high and k2.low >= k3.low) or                     (k2.high >= k3.high and k2.low <= k3.low)
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

    open_, close = (high, low) if k3.open > k3.close else (low, high)
    elements = [x for x in k2.elements if x.dt != k3.dt] + [k3]
    merged = NewBar(k2.symbol, dt, open_, close, high, low,
                    k2.vol + k3.vol, k2.amount + k3.amount, elements)
    return True, merged


def remove_include_all(bars_raw):
    """对整个K线序列做去包含处理，返回完整的去包含K线列表（用于前端图表展示）。
    说明：CZSC.bars_ubi 只保留未完成笔尾部K线，不是全序列，故单独重算。
    合并规则即 remove_include：方向由相邻无包含K线 high 大小决定，
    向上取较高high/较高low，向下取较低high/较低low；vol/amount累加，
    elements拼接（保留原始K线，去重同dt），dt取极值所在K线时间。"""
    ubi = []
    for b in bars_raw:
        if len(ubi) < 2:
            ubi.append(NewBar.from_raw(b))
        else:
            has_inc, merged = remove_include(ubi[-2], ubi[-1], b)
            if has_inc:
                ubi[-1] = merged
            else:
                ubi.append(merged)
    return ubi


def check_fx(k1: NewBar, k2: NewBar, k3: NewBar):
    """三根无包含K线构成分型"""
    # 顶分型：中K高点最高且低点最高
    if k1.high < k2.high > k3.high and k1.low < k2.low > k3.low:
        return FX("G", k2.dt, k2.high, k2.low, k2.high, [k1, k2, k3])
    # 底分型：中K低点最低且高点最低
    if k1.low > k2.low < k3.low and k1.high > k2.high < k3.high:
        return FX("D", k2.dt, k2.high, k2.low, k2.low, [k1, k2, k3])
    return None


def check_fxs(bars):
    """扫描无包含K线序列，找出所有分型（强制顶底交替）"""
    fxs = []
    for i in range(len(bars) - 2):
        fx = check_fx(bars[i], bars[i + 1], bars[i + 2])
        if fx is None:
            continue
        if fxs and fx.mark == fxs[-1].mark:
            continue  # 顶底交替
        fxs.append(fx)
    return fxs


def _partition(dts, target, right=False):
    """对齐 Rust partition_point：返回第一个 >= target（或 > target）的索引"""
    if right:
        return bisect.bisect_right(dts, target)
    return bisect.bisect_left(dts, target)


def check_bi(bars, min_bi_len=6):
    """从无包含K线序列中识别一笔，返回 (BI or None, 剩余bars)"""
    fxs = check_fxs(bars)
    if len(fxs) < 2:
        return None, bars

    fx_a = fxs[0]
    fx_b = None
    if fx_a.mark == "D":
        # 向上笔：后续顶分型中选高点最高的
        cands = [x for x in fxs if x.mark == "G" and x.dt > fx_a.dt and x.fx > fx_a.fx]
        if cands:
            fx_b = max(cands, key=lambda x: x.high)
    else:
        # 向下笔：后续底分型中选低点最低的
        cands = [x for x in fxs if x.mark == "D" and x.dt > fx_a.dt and x.fx < fx_a.fx]
        if cands:
            fx_b = min(cands, key=lambda x: x.low)
    if fx_b is None:
        return None, bars

    dts = [b.dt for b in bars]
    start_idx = _partition(dts, fx_a.elements[0].dt)
    end_idx = _partition(dts, fx_b.elements[2].dt, right=True)
    if start_idx >= end_idx:
        return None, bars
    bars_a = bars[start_idx:end_idx]

    new_start_idx = _partition(dts, fx_b.elements[0].dt)
    bars_b = bars[new_start_idx:]

    ab_include = (fx_a.high > fx_b.high and fx_a.low < fx_b.low) or                  (fx_a.high < fx_b.high and fx_a.low > fx_b.low)

    if not ab_include and len(bars_a) >= min_bi_len:
        direction = "Up" if fx_a.mark == "D" else "Down"
        fxs_in = [x for x in fxs if start_idx <= 0 or x.dt >= bars_a[0].dt and x.dt <= bars_a[-1].dt]
        bi = BI(fx_a=fx_a, fx_b=fx_b, fxs=fxs_in, direction=direction, bars=bars_a)
        return bi, bars_b
    return None, bars


def _bi_overlap_ratio(bi, zg, zd):
    """笔与中枢区间 [zd, zg] 的交集占比（衡量是否真实参与震荡）"""
    inter = min(bi.get_high(), zg) - max(bi.get_low(), zd)
    amp = bi.get_high() - bi.get_low()
    if amp <= 0:
        return 0.0
    return round(inter / amp, 6)


def _trend_strength(bis, i):
    """先判断当前走势（用户规则）：顶分型的顶越来越低 → 走弱；
    底分型的底越来越高 → 走强。

    窗口覆盖中枢本体附近（i-4 ~ i+7，含前后走势段），取：
    - 顶（向上笔高点）序列：最近顶 < 前顶 → 走弱信号
    - 底（向下笔低点）序列：最近底 > 前底 → 走强信号
    顶降且底降 → 下降；顶升且底升 → 上升；否则震荡。
    """
    window = bis[max(0, i - 4):min(len(bis), i + 7)]
    if len(window) < 3:
        return "震荡"
    up_highs = [b.get_high() for b in window if b.direction == "Up"]
    down_lows = [b.get_low() for b in window if b.direction == "Down"]
    top_down = len(up_highs) >= 2 and up_highs[-1] < up_highs[-2]
    top_up = len(up_highs) >= 2 and up_highs[-1] > up_highs[-2]
    bottom_up = len(down_lows) >= 2 and down_lows[-1] > down_lows[-2]
    bottom_down = len(down_lows) >= 2 and down_lows[-1] < down_lows[-2]
    if top_down and bottom_down:
        return "下降"
    if top_up and bottom_up:
        return "上升"
    if top_down or bottom_down:
        return "下降"
    if top_up or bottom_up:
        return "上升"
    return "震荡"


def _bi_intersect(bi, zg, zd):
    """笔与中枢区间 [zd, zg] 是否有交集"""
    return min(bi.get_high(), zg) - max(bi.get_low(), zd) > 0


def _zs_price_overlap(z1, z2):
    """两个中枢价格区间是否有重叠"""
    return min(z1.zg, z2.zg) - max(z1.zd, z2.zd) > 0


def _zs_merge(z1, z2):
    """中枢扩展：两个价格重叠的中枢合并为更高级别中枢
    高级别中枢区间 = 两个中枢的整体价格范围
    """
    bis = z1.bis + z2.bis
    return ZS(
        bis=bis, sdt=z1.sdt, edt=z2.edt,
        sdir=z1.sdir, edir=z2.edir,
        zg=max(z1.zg, z2.zg), zd=min(z1.zd, z2.zd),
        zz=(min(z1.zd, z2.zd) + max(z1.zg, z2.zg)) / 2,
        gg=max(z1.gg, z2.gg), dd=min(z1.dd, z2.dd),
        direction=z1.direction or z2.direction,
    )


def get_zs_seq(bis):
    """笔中枢识别（用户新逻辑）

    1. 连续 3 笔（方向交替）价格重叠 → 中枢形成：
       ZD = max(三笔 low)，ZG = min(三笔 high)，ZD ≤ ZG 即成立
    2. 方向 = 进入中枢的第一笔方向：向下 → 下降中枢 / 向上 → 上升中枢
    3. 延伸：后续每笔价格区间与 [ZD, ZG] 有交集 → 并入（不改变区间），
       可延伸为 5、7、9 笔……只要不出现第三类买卖点
    4. 三类买卖点终结：
       - 上升中枢：向上离开笔后，回调笔低点 > ZG → 三买确认，中枢终结
       - 下降中枢：向下离开笔后，反弹笔高点 < ZD → 三卖确认，中枢终结
       - 回调笔回到中枢区间 → 中枢继续延伸
    5. 新生：旧中枢终结后，再次出现连续 3 笔重叠 → 新中枢
    6. 扩展：新中枢与旧中枢价格重叠 → 合并为更高级别中枢
    """
    zs_list = []
    i = 0
    n = len(bis)
    while i < n - 2:
        s0, s1, s2 = bis[i], bis[i + 1], bis[i + 2]
        # 方向交替：s0 与 s2 同向、s1 反向
        if not (s0.direction != s1.direction and s1.direction != s2.direction):
            i += 1
            continue
        ZD = max(s0.get_low(), s1.get_low(), s2.get_low())
        ZG = min(s0.get_high(), s1.get_high(), s2.get_high())
        if ZD > ZG:
            i += 1
            continue  # 无重叠，无中枢
        direction = "上升" if s0.direction == "Up" else "下降"
        cand = [s0, s1, s2]
        j = i + 3
        while j < n:
            bi = bis[j]
            if _bi_intersect(bi, ZG, ZD):
                cand.append(bi)
                j += 1
                continue  # 延伸
            # 无交集：离开笔，检查三类买卖点
            if direction == "上升":
                if bi.direction == "Up" and j + 1 < n and bis[j + 1].direction == "Down":
                    nxt = bis[j + 1]
                    if nxt.get_low() > ZG:
                        break  # 三买确认，中枢终结
                    if _bi_intersect(nxt, ZG, ZD):
                        cand.append(bi)
                        cand.append(nxt)
                        j += 2
                        continue  # 回调回中枢，延伸持续
                break
            else:  # 下降中枢
                if bi.direction == "Down" and j + 1 < n and bis[j + 1].direction == "Up":
                    nxt = bis[j + 1]
                    if nxt.get_high() < ZD:
                        break  # 三卖确认，中枢终结
                    if _bi_intersect(nxt, ZG, ZD):
                        cand.append(bi)
                        cand.append(nxt)
                        j += 2
                        continue
                break
        zs = ZS.new(cand)
        zs.direction = direction
        zs_list.append(zs)
        i = j  # 新生：从中枢终结后的笔继续（互斥）

    # 扩展：相邻中枢价格重叠 → 合并为更高级别中枢
    merged = []
    for zs in zs_list:
        if merged and _zs_price_overlap(merged[-1], zs):
            merged[-1] = _zs_merge(merged[-1], zs)
        else:
            merged.append(zs)
    return [z for z in merged if z.is_valid() and len(z.bis) >= ZS_MIN_BIS]


def zs_direction(zs, bis_all, latest_close):
    """中枢方向：由离开段（中枢后第一笔）相对中枢区间的突破方向决定

    规则（缠论）：中枢结束 = 离开段突破/跌破确认
    - 离开笔向上突破上沿（高点 > zg）或完全位于中枢上方 → 上升中枢
    - 离开笔向下跌破下沿（低点 < zd）或完全位于中枢下方 → 下降中枢
    - 无离开笔（最后一个中枢）或未突破：按当前最新价相对区间的位置判断
    """
    zg, zd = zs.zg, zs.zd
    idx_out = bis_all.index(zs.bis[-1])
    if idx_out < len(bis_all) - 1:
        # 离开段 = 离开笔 + 紧随一笔（确认离开方向，不受对齐边界影响）
        after = bis_all[idx_out + 1:idx_out + 3]
        last_bi = after[-1]
        end = last_bi.fx_b.fx  # 末笔终点：上笔=高点、下笔=低点
        if end > zg:
            return "上升"          # 离开段末笔终点在上沿上方
        if end < zd:
            return "下降"          # 离开段末笔终点在下沿下方
        # 终点仍在区间内：看离开段整体是否突破/跌破
        hi = max(b.get_high() for b in after)
        lo = min(b.get_low() for b in after)
        if hi > zg and lo >= zd:
            return "上升"
        if lo < zd and hi <= zg:
            return "下降"
    if latest_close > zg:
        return "上升"
    if latest_close < zd:
        return "下降"
    return "震荡"


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def check_first_buy(bis):
    """一买：下跌结构完整 + 背驰（复刻 czsc check_first_buy）"""
    if len(bis) % 2 != 1 or len(bis) < 3:
        return False
    if bis[-1].direction != "Down" or bis[0].direction != bis[-1].direction:
        return False
    max_high = max(b.get_high() for b in bis)
    min_low = min(b.get_low() for b in bis)
    if max_high != bis[0].get_high() or min_low != bis[-1].get_low():
        return False
    key_bis = []
    for i in range(0, len(bis) - 2, 2):
        if i == 0:
            key_bis.append(bis[i])
        else:
            b1, b3 = bis[i - 2], bis[i]
            if b3.get_low() < b1.get_low():
                key_bis.append(b3)
    if not key_bis:
        return False
    last, prev = bis[-1], bis[-2]
    bc_price = last.get_power() < max(prev.get_power(), _mean([b.get_power() for b in key_bis]))
    bc_volume = last.get_power_volume() < max(prev.get_power_volume(),
                                              _mean([b.get_power_volume() for b in key_bis]))
    bc_length = last.get_length() < max(prev.get_length(), _mean([b.get_length() for b in key_bis]))
    return bc_price and (bc_volume or bc_length)


def check_first_sell(bis):
    """一卖：上涨结构完整 + 背驰"""
    if len(bis) % 2 != 1 or len(bis) < 3:
        return False
    if bis[-1].direction != "Up" or bis[0].direction != bis[-1].direction:
        return False
    max_high = max(b.get_high() for b in bis)
    min_low = min(b.get_low() for b in bis)
    if max_high != bis[-1].get_high() or min_low != bis[0].get_low():
        return False
    key_bis = []
    for i in range(0, len(bis) - 2, 2):
        if i == 0:
            key_bis.append(bis[i])
        else:
            b1, b3 = bis[i - 2], bis[i]
            if b3.get_high() > b1.get_high():
                key_bis.append(b3)
    if not key_bis:
        return False
    last, prev = bis[-1], bis[-2]
    bc_price = last.get_power() < max(prev.get_power(), _mean([b.get_power() for b in key_bis]))
    bc_volume = last.get_power_volume() < max(prev.get_power_volume(),
                                              _mean([b.get_power_volume() for b in key_bis]))
    bc_length = last.get_length() < max(prev.get_length(), _mean([b.get_length() for b in key_bis]))
    return bc_price and (bc_volume or bc_length)


# =====================================================================
# 三、CZSC 分析器（逐K线增量更新，复刻 czsc CZSC）
# =====================================================================

class CZSC:
    def __init__(self, bars_raw, max_bi_num=50, min_bi_len=6):
        self.max_bi_num = max_bi_num
        self.min_bi_len = min_bi_len
        self.bars_raw = []
        self.bars_ubi = []   # 去包含后的K线
        self.bi_list = []
        self.symbol = bars_raw[0].symbol
        for b in bars_raw:
            self.update_bar(b)

    # ---- 属性 ----
    @property
    def fx_list(self):
        fxs = []
        for bi in self.bi_list:
            for x in bi.fxs[1:]:
                if not fxs or x.dt > fxs[-1].dt:
                    fxs.append(x)
        for x in self.get_ubi_fxs() or []:
            if not fxs or x.dt > fxs[-1].dt:
                fxs.append(x)
        return fxs

    @property
    def zs_list(self):
        return get_zs_seq(self.get_finished_bis())

    def get_finished_bis(self):
        if not self.bi_list:
            return []
        if len(self.bars_ubi) < 5:
            return self.bi_list[:-1]
        return list(self.bi_list)

    def get_ubi_fxs(self):
        if not self.bars_ubi:
            return None
        return check_fxs(self.bars_ubi)

    @property
    def last_bi_extend(self):
        """最后一笔是否延伸中"""
        if not self.bi_list or not self.bars_ubi:
            return False
        last = self.bi_list[-1]
        if last.direction == "Up":
            return max(b.high for b in self.bars_ubi) > last.get_high()
        return min(b.low for b in self.bars_ubi) < last.get_low()

    # ---- 增量更新 ----
    def update_bar(self, bar: RawBar):
        if not self.bars_raw or bar.dt != self.bars_raw[-1].dt:
            self.bars_raw.append(bar)
            last_bars = [bar]
        else:
            # 同一根K线时间延伸：替换
            self.bars_raw[-1] = bar
            if not self.bars_ubi:
                return
            last_ubi = self.bars_ubi.pop()
            last_bars = list(last_ubi.elements)
            last_bars[-1] = bar

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

        if len(self.bi_list) > self.max_bi_num:
            self.bi_list = self.bi_list[-(self.max_bi_num):]

        if self.bi_list:
            sdt = self.bi_list[0].fx_a.elements[0].dt
            dts = [b.dt for b in self.bars_raw]
            idx = _partition(dts, sdt)
            if idx:
                self.bars_raw = self.bars_raw[idx:]

    def _update_bi(self):
        if len(self.bars_ubi) < 3:
            return
        if not self.bi_list:
            fxs = check_fxs(self.bars_ubi)
            if not fxs:
                return
            first = fxs[0]
            if first.mark == "D":
                fx_a = min([x for x in fxs if x.mark == "D"], key=lambda x: x.low)
            else:
                fx_a = max([x for x in fxs if x.mark == "G"], key=lambda x: x.high)
            dts = [b.dt for b in self.bars_ubi]
            idx = _partition(dts, fx_a.elements[0].dt)
            bars = self.bars_ubi[idx:]
            bi, rest = check_bi(bars, self.min_bi_len)
            if bi:
                self.bi_list.append(bi)
            self.bars_ubi = list(rest)
            return

        bi, rest = check_bi(self.bars_ubi, self.min_bi_len)
        if bi:
            self.bi_list.append(bi)
        self.bars_ubi = list(rest)

        # 笔破坏后处理：若未完成笔超出最后一笔极值，合并回退
        if not self.bi_list or not self.bars_ubi:
            return
        last_bi = self.bi_list[-1]
        if last_bi.direction == "Up" and self.bars_ubi[-1].high > last_bi.get_high():
            merge_point = last_bi.bars[-2].dt
            merged = list(last_bi.bars[:-2]) +                      [b for b in self.bars_ubi if b.dt >= merge_point]
            self.bars_ubi = merged
            self.bi_list.pop()
        elif last_bi.direction == "Down" and self.bars_ubi[-1].low < last_bi.get_low():
            merge_point = last_bi.bars[-2].dt
            merged = list(last_bi.bars[:-2]) +                      [b for b in self.bars_ubi if b.dt >= merge_point]
            self.bars_ubi = merged
            self.bi_list.pop()


# =====================================================================
# 四、数据层：从 D:\khData 读取
# =====================================================================

FREQ_ALIASES = {
    "1分钟": "1分钟", "1m": "1分钟", "1min": "1分钟", "1分": "1分钟",
    "5分钟": "5分钟", "5m": "5分钟", "5min": "5分钟", "5分": "5分钟",
    "15分钟": "15分钟", "15m": "15分钟",
    "30分钟": "30分钟", "30m": "30分钟",
    "60分钟": "60分钟", "60m": "60分钟", "1小时": "60分钟",
    "120分钟": "120分钟", "120m": "120分钟",
    "日线": "日线", "日": "日线", "d": "日线", "D": "日线", "day": "日线",
    "周线": "周线", "周": "周线", "w": "周线", "W": "周线", "week": "周线",
    "月线": "月线", "月": "月线", "m": "月线", "M": "月线", "month": "月线",
}


def resolve_symbol(code):
    """解析股票代码 → (代码, 市场)。支持 000001.SH / 000001.SZ / 600000 / 300750"""
    code = code.strip().upper()
    if "." in code:
        c, ex = code.split(".")
        return c, ex.upper()
    if code.startswith(("60", "68", "51", "58", "56", "9")):
        return code, "SH"
    if code.startswith(("00", "30", "12", "15", "16", "18", "2")):
        return code, "SZ"
    if code.startswith(("8", "4", "92")):
        return code, "BJ"
    return code, None


def find_db(code, exchange):
    """定位数据库文件路径"""
    if exchange:
        p = os.path.join(KHDATA, exchange, code + ".db")
        if os.path.exists(p):
            return p
        return None
    for ex in ("SH", "SZ", "BJ"):
        p = os.path.join(KHDATA, ex, code + ".db")
        if os.path.exists(p):
            return p
    return None


def _parse_date(s):
    s = s.strip().replace("/", "-")
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"无法解析日期: {s}（支持 YYYY-MM-DD 或 YYYYMMDD）")


def load_bars(code, exchange, freq, sdt, edt, prewarm_bars=600):
    """从 DuckDB 读取K线并按需重采样。返回 (symbol_label, bars, table, prewarm_count)"""
    db_path = find_db(code, exchange)
    if not db_path:
        raise FileNotFoundError(f"未找到 {code} 的数据文件（D:\khData 下无 {code}.db）")

    con = duckdb.connect(db_path, read_only=True)
    try:
        tables = {r[0] for r in con.sql("SHOW TABLES").fetchall()}

        # 基础数据：1分钟 / 5分钟 / 日线
        if freq in ("1分钟", "15分钟", "30分钟", "60分钟", "120分钟"):
            need = "kline_1m"
            if need not in tables:
                raise RuntimeError(f"{code} 没有 {need} 数据")
            rows = con.execute(
                f"SELECT time, open, high, low, close, volume, amount FROM {need} "
                f"WHERE time::DATE >= ? AND time::DATE <= ? ORDER BY time",
                [sdt.date(), edt.date()]).fetchall()
            bars = [RawBar(f"{code}.{exchange}", r[0], float(r[1]), float(r[4]),
                           float(r[2]), float(r[3]), float(r[5]), float(r[6] or 0))
                    for r in rows if r[1] is not None and r[4] is not None]
            if freq != "1分钟":
                bars = resample_minutes(bars, int(freq.replace("分钟", "")))
        elif freq == "5分钟":
            need = "kline_5m"
            if need not in tables:
                raise RuntimeError(f"{code} 没有 {need} 数据")
            rows = con.execute(
                f"SELECT time, open, high, low, close, volume, amount FROM {need} "
                f"WHERE time::DATE >= ? AND time::DATE <= ? ORDER BY time",
                [sdt.date(), edt.date()]).fetchall()
            bars = [RawBar(f"{code}.{exchange}", r[0], float(r[1]), float(r[4]),
                           float(r[2]), float(r[3]), float(r[5]), float(r[6] or 0))
                    for r in rows if r[1] is not None and r[4] is not None]
        elif freq in ("日线", "周线", "月线"):
            need = "kline_1d"
            if need not in tables:
                raise RuntimeError(f"{code} 没有 {need} 数据")
            rows = con.execute(
                f"SELECT time, open, high, low, close, volume, amount FROM {need} "
                f"WHERE time::DATE >= ? AND time::DATE <= ? ORDER BY time",
                [sdt.date(), edt.date()]).fetchall()
            bars = [RawBar(f"{code}.{exchange}", r[0], float(r[1]), float(r[4]),
                           float(r[2]), float(r[3]), float(r[5]), float(r[6] or 0))
                    for r in rows if r[1] is not None and r[4] is not None]
            if freq == "周线":
                bars = resample_daily(bars, "W")
            elif freq == "月线":
                bars = resample_daily(bars, "M")
        else:
            raise ValueError(f"不支持的周期: {freq}")
    finally:
        con.close()

    if not bars:
        raise RuntimeError(f"{code} 在 {sdt.date()}~{edt.date()} 区间内无 {freq} 数据")

    # 预热：向前补足K线，保证缠论结构充分构建
    if prewarm_bars > 0 and len(bars) < prewarm_bars:
        pre = _load_prewarm(db_path, bars[0], freq, prewarm_bars - len(bars))
        bars = pre + bars
        prewarm = len(pre)
    else:
        prewarm = 0
    return f"{code}.{exchange}", bars, prewarm


def _load_prewarm(db_path, first_bar, freq, n):
    """向前补 n 根K线（freq 与主数据一致）"""
    try:
        con = duckdb.connect(db_path, read_only=True)
        try:
            if freq in ("1分钟", "15分钟", "30分钟", "60分钟", "120分钟"):
                table = "kline_1m"
            elif freq == "5分钟":
                table = "kline_5m"
            else:
                table = "kline_1d"
            # 分钟级重采样会稀释K线数，按目标分钟数放大取数（至少4倍）
            mult = 4
            if freq in ("15分钟", "30分钟", "60分钟", "120分钟"):
                mult = max(mult, int(freq.replace("分钟", "")))
            rows = con.execute(
                f"SELECT time, open, high, low, close, volume, amount FROM {table} "
                f"WHERE time < ? ORDER BY time DESC LIMIT ?",
                [first_bar.dt, n * mult]).fetchall()
        finally:
            con.close()
    except Exception:
        return []
    rows = list(reversed(rows))
    bars = [RawBar(first_bar.symbol, r[0], float(r[1]), float(r[4]),
                   float(r[2]), float(r[3]), float(r[5]), float(r[6] or 0))
            for r in rows if r[1] is not None and r[4] is not None]
    if freq in ("15分钟", "30分钟", "60分钟", "120分钟"):
        bars = resample_minutes(bars, int(freq.replace("分钟", "")))
        bars = [b for b in bars if b.dt < first_bar.dt]
    elif freq == "周线":
        bars = resample_daily(bars, "W")
        bars = [b for b in bars if b.dt < first_bar.dt]
    elif freq == "月线":
        bars = resample_daily(bars, "M")
        bars = [b for b in bars if b.dt < first_bar.dt]
    return bars[-n:]


def resample_minutes(bars_1m, minutes):
    """1分钟 → N分钟（A股 09:30-11:30 / 13:00-15:00 分桶）"""
    buckets = {}
    for b in bars_1m:
        t = b.dt
        hm = t.hour * 60 + t.minute
        if 9 * 60 + 30 <= hm <= 11 * 60 + 29:
            off = hm - (9 * 60 + 30)
            sess = 0
        elif 13 * 60 <= hm <= 15 * 60 - 1:
            off = hm - 13 * 60
            sess = 1
        else:
            continue
        key = (t.date(), sess, off // minutes)
        buckets.setdefault(key, []).append(b)
    out = []
    for key in sorted(buckets):
        bs = buckets[key]
        out.append(RawBar(
            symbol=bs[0].symbol,
            dt=bs[-1].dt,
            open=bs[0].open,
            close=bs[-1].close,
            high=max(b.high for b in bs),
            low=min(b.low for b in bs),
            vol=sum(b.vol for b in bs),
            amount=sum(b.amount for b in bs),
        ))
    return out


def resample_daily(bars_1d, target):
    """日线 → 周线/月线"""
    buckets = {}
    for b in bars_1d:
        t = b.dt
        key = t.isocalendar()[:2] if target == "W" else (t.year, t.month)
        buckets.setdefault(key, []).append(b)
    out = []
    for key in sorted(buckets):
        bs = buckets[key]
        out.append(RawBar(
            symbol=bs[0].symbol,
            dt=bs[-1].dt,
            open=bs[0].open,
            close=bs[-1].close,
            high=max(b.high for b in bs),
            low=min(b.low for b in bs),
            vol=sum(b.vol for b in bs),
            amount=sum(b.amount for b in bs),
        ))
    return out


# =====================================================================
# 五、买卖点与趋势判断（前置定义：趋势 → 背驰 → 三类买卖点）
# =====================================================================

# 背驰容错阈值（MACD 面积比较加 5% 容错，避免微小差异误判）
DIV_TOLERANCE = 1.05


def _seg_stats(closes, dts, dif, hist, sdt, edt):
    """[sdt, edt] 段的 MACD 统计（用于 b/c 段力度比较）
    返回：绿柱面积 / 红柱面积 / DIF 低点 / DIF 高点 / 涨跌幅 / K线数 / 斜率(涨跌幅/根)
    """
    i0 = bisect.bisect_left(dts, sdt)
    i1 = bisect.bisect_right(dts, edt)
    if i1 <= i0:
        return None
    seg_hist = hist[i0:i1]
    seg_dif = dif[i0:i1]
    green = round(sum(abs(x) for x in seg_hist if x < 0), 6)
    red = round(sum(x for x in seg_hist if x > 0), 6)
    dif_lo = min(seg_dif)
    dif_hi = max(seg_dif)
    c0, c1 = closes[i0], closes[i1 - 1]
    pct = (c1 - c0) / c0 if c0 else 0.0
    n_bar = i1 - i0
    return {"green": green, "red": red, "dif_lo": dif_lo, "dif_hi": dif_hi,
            "pct": pct, "n": n_bar, "slope": pct / max(n_bar, 1)}


def _bear_divergence(b, c):
    """下跌背驰：c 段相对 b 段（MACD 优先，价格斜率备用）
    - MACD：c 绿柱总面积 < b 绿柱总面积（×容错）且 c 黄白线低点 > b 黄白线低点
    - 备用：c 段涨跌幅/根数 < b 段涨跌幅/根数（斜率衰减）
    """
    if not b or not c:
        return False
    macd_ok = c["green"] < b["green"] * DIV_TOLERANCE and c["dif_lo"] > b["dif_lo"]
    price_ok = c["slope"] < b["slope"] * DIV_TOLERANCE
    return macd_ok or price_ok


def _bull_divergence(b, c):
    """上涨背驰：c 段相对 b 段（对称）
    - MACD：c 红柱总面积 < b 红柱总面积（×容错）且 c 黄白线高点 < b 黄白线高点
    - 备用：c 段斜率 < b 段斜率（涨速衰减）
    """
    if not b or not c:
        return False
    macd_ok = c["red"] < b["red"] * DIV_TOLERANCE and c["dif_hi"] < b["dif_hi"]
    price_ok = c["slope"] < b["slope"] * DIV_TOLERANCE
    return macd_ok or price_ok


def _identify_trends(zs_seq):
    """识别趋势（前置定义）：
    - 下跌趋势：至少 2 个依次下移的下降中枢（后中枢.ZD < 前中枢.ZD）
    - 上涨趋势：至少 2 个依次上移的上升中枢（后中枢.ZG > 前中枢.ZG）
    返回 [{'kind':'下跌'/'上涨', 'zs_list':[...]}, ...]
    """
    trends = []
    cur = None
    for zs in zs_seq:
        kind = "下跌" if zs.direction == "下降" else "上涨"
        if cur and cur["kind"] == kind:
            last = cur["zs_list"][-1]
            if kind == "下跌" and zs.zd < last.zd:
                cur["zs_list"].append(zs)
                continue
            if kind == "上涨" and zs.zg > last.zg:
                cur["zs_list"].append(zs)
                continue
        if cur and len(cur["zs_list"]) >= 2:
            trends.append(cur)
        cur = {"kind": kind, "zs_list": [zs]}
    if cur and len(cur["zs_list"]) >= 2:
        trends.append(cur)
    return trends


def find_all_bs_points(bars, bis, zs_seq):
    """前置定义买卖点识别（输入：K线 + 笔列表 + 中枢列表）

    1B/1S：趋势背驰（a+A+b+B+c 完整结构，c 段相对 b 段背驰 + 末端分型）
    2B/2S：一买/一卖后的回踩/反弹确认（不破前低/前高）
    3B/3S：中枢突破回踩（离开笔后回调不回到中枢区间）
    输出：[{'type','time','price','level','status','desc'}]
    status: confirmed（后续走势确认）/ unconfirmed（最后一个信号，实时未走完）
    """
    if not bis or not bars:
        return []
    closes = [b.close for b in bars]
    dts = [b.dt for b in bars]
    dif, dea, hist = _macd_series(closes)
    n = len(bis)
    points = []

    def seg(bi):
        return _seg_stats(closes, dts, dif, hist, bi.start_dt, bi.end_dt)

    # ---- 1) 趋势背驰 → 1B / 1S ----
    for trend in _identify_trends(zs_seq):
        if len(trend["zs_list"]) < 2:
            continue
        A, B = trend["zs_list"][-2], trend["zs_list"][-1]
        a_idx = bis.index(A.bis[-1])
        b_idx = bis.index(B.bis[0])
        conn = bis[a_idx + 1:b_idx]
        if not conn:
            continue
        b_bi = conn[0]  # 连接笔（A→B）
        bl_idx = bis.index(B.bis[-1])
        if bl_idx + 1 >= n:
            continue
        c_bi = bis[bl_idx + 1]  # 离开笔（B 之后）
        if trend["kind"] == "下跌":
            if b_bi.direction != "Down" or c_bi.direction != "Down":
                continue
            if _bear_divergence(seg(b_bi), seg(c_bi)):
                points.append({
                    "type": "1B", "time": c_bi.end_dt, "price": c_bi.fx_b.fx,
                    "level": "笔", "status": "confirmed" if bl_idx + 2 < n else "unconfirmed",
                    "desc": f"下跌趋势背驰（两中枢 {A.edt:%y-%m-%d}→{B.edt:%y-%m-%d} 下移），c段动能衰竭",
                })
        else:  # 上涨
            if b_bi.direction != "Up" or c_bi.direction != "Up":
                continue
            if _bull_divergence(seg(b_bi), seg(c_bi)):
                points.append({
                    "type": "1S", "time": c_bi.end_dt, "price": c_bi.fx_b.fx,
                    "level": "笔", "status": "confirmed" if bl_idx + 2 < n else "unconfirmed",
                    "desc": f"上涨趋势背驰（两中枢 {A.edt:%y-%m-%d}→{B.edt:%y-%m-%d} 上移），c段动能衰竭",
                })

    # ---- 2) 1B/1S 之后 → 2B / 2S（回踩/反弹确认）----
    for p in [x for x in points if x["type"] in ("1B", "1S")]:
        c_idx = None
        for k in range(n):
            if bis[k].end_dt == p["time"]:
                c_idx = k
                break
        if c_idx is None or c_idx + 2 >= n:
            continue
        reb, call = bis[c_idx + 1], bis[c_idx + 2]
        if p["type"] == "1B":
            # 反弹笔（向上）+ 回调笔（向下），回调低点 > 一买低点
            if reb.direction == "Up" and call.direction == "Down" and call.get_low() > p["price"]:
                points.append({
                    "type": "2B", "time": call.end_dt, "price": call.fx_b.fx,
                    "level": "笔", "status": "confirmed" if c_idx + 3 < n else "unconfirmed",
                    "desc": f"一买后回踩不破前低（低点{call.get_low():.3f} > 一买{p['price']:.3f}）",
                })
        else:
            # 回调笔（向下）+ 反弹笔（向上），反弹高点 < 一卖高点
            if reb.direction == "Down" and call.direction == "Up" and call.get_high() < p["price"]:
                points.append({
                    "type": "2S", "time": call.end_dt, "price": call.fx_b.fx,
                    "level": "笔", "status": "confirmed" if c_idx + 3 < n else "unconfirmed",
                    "desc": f"一卖后反弹不破前高（高点{call.get_high():.3f} < 一卖{p['price']:.3f}）",
                })

    # ---- 3) 每个中枢 → 3B / 3S（突破回踩 / 跌破反抽）----
    # 注意：向上突破笔可能已被延伸并入中枢末笔，故从中枢末笔起扫描
    # 突破（向上笔 high>ZG 或末笔自身突破），再找向下回调笔低点>ZG → 3B
    for zs in zs_seq:
        bl_idx = bis.index(zs.bis[-1])
        if zs.direction == "上升":
            for k in range(bl_idx, min(bl_idx + 3, n - 1)):
                bk = bis[k]
                if bk.direction == "Up" and bk.get_high() > zs.zg                         and k + 1 < n and bis[k + 1].direction == "Down"                         and bis[k + 1].get_low() > zs.zg:
                    call = bis[k + 1]
                    points.append({
                        "type": "3B", "time": call.end_dt, "price": call.fx_b.fx,
                        "level": "笔", "status": "confirmed" if k + 2 < n else "unconfirmed",
                        "desc": f"向上离开中枢后回调低点{call.get_low():.3f} > 上沿{zs.zg:.3f}",
                    })
                    break
        else:
            for k in range(bl_idx, min(bl_idx + 3, n - 1)):
                bk = bis[k]
                if bk.direction == "Down" and bk.get_low() < zs.zd                         and k + 1 < n and bis[k + 1].direction == "Up"                         and bis[k + 1].get_high() < zs.zd:
                    call = bis[k + 1]
                    points.append({
                        "type": "3S", "time": call.end_dt, "price": call.fx_b.fx,
                        "level": "笔", "status": "confirmed" if k + 2 < n else "unconfirmed",
                        "desc": f"向下离开中枢后反弹高点{call.get_high():.3f} < 下沿{zs.zd:.3f}",
                    })
                    break

    # ---- 4) 补充：5 笔窗口三买三卖（对齐 czsc cxt_third_bs_V230318）----
    # 结构 下-上-下-上-下：b1/b3 重叠 [zd,zg]，b5（下跌笔）低点 > zg → 三买
    # 结构 上-下-上-下-上：b1/b3 重叠，b5（上涨笔）高点 < zd → 三卖
    for i in range(n - 4):
        b1, b2, b3, b4, b5 = bis[i:i + 5]
        if not (b1.direction == "Down" and b3.direction == "Down" and b5.direction == "Down"):
            if not (b1.direction == "Up" and b3.direction == "Up" and b5.direction == "Up"):
                continue
        zd = max(b1.get_low(), b3.get_low())
        zg = min(b1.get_high(), b3.get_high())
        if zd > zg:
            continue
        if b5.direction == "Down" and b5.get_low() > zg:
            points.append({
                "type": "3B", "time": b5.end_dt, "price": b5.fx_b.fx,
                "level": "笔", "status": "confirmed" if i + 5 < n else "unconfirmed",
                "desc": f"五笔结构三买：回调笔低点{b5.get_low():.3f} > 中枢上沿{zg:.3f}",
            })
        if b5.direction == "Up" and b5.get_high() < zd:
            points.append({
                "type": "3S", "time": b5.end_dt, "price": b5.fx_b.fx,
                "level": "笔", "status": "confirmed" if i + 5 < n else "unconfirmed",
                "desc": f"五笔结构三卖：反弹笔高点{b5.get_high():.3f} < 中枢下沿{zd:.3f}",
            })

    # 按时间排序 + 去重
    seen = set()
    out = []
    for p in sorted(points, key=lambda x: x["time"]):
        key = (p["type"], p["time"])
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def find_third_bs_points(bis):
    """三类买卖点（对齐 czsc cxt_third_bs_V230318 几何条件）：
    - 三买：3 笔中枢 [zd, zg] 后，向上离开笔突破上沿，
      随后回调笔（向下）低点 > ZG → 三买确认
    - 三卖：3 笔中枢后，向下离开笔跌破下沿，
      随后反弹笔（向上）高点 < ZD → 三卖确认
    扫描全部 3 笔重叠中枢，按时间去重。
    """
    points = []
    n = len(bis)
    seen = set()
    for i in range(n - 4):
        s0, s1, s2 = bis[i], bis[i + 1], bis[i + 2]
        if not (s0.direction != s1.direction and s1.direction != s2.direction):
            continue
        zd = max(s0.get_low(), s1.get_low(), s2.get_low())
        zg = min(s0.get_high(), s1.get_high(), s2.get_high())
        if zd > zg:
            continue  # 无重叠，无中枢
        leave, confirm = bis[i + 3], bis[i + 4]
        # 三买：向上离开 → 回调笔低点 > 上沿
        if leave.direction == "Up" and leave.get_high() > zg                 and confirm.direction == "Down" and confirm.get_low() > zg:
            key = ("三买", confirm.end_dt)
            if key not in seen:
                seen.add(key)
                points.append(("三买", confirm.end_dt,
                               f"离开中枢后回调低点{confirm.get_low():.3f} > 上沿{zg:.3f}"))
        # 三卖：向下离开 → 反弹笔高点 < 下沿
        if leave.direction == "Down" and leave.get_low() < zd                 and confirm.direction == "Up" and confirm.get_high() < zd:
            key = ("三卖", confirm.end_dt)
            if key not in seen:
                seen.add(key)
                points.append(("三卖", confirm.end_dt,
                               f"离开中枢后反弹高点{confirm.get_high():.3f} < 下沿{zd:.3f}"))
    return points


_BS_NAME = {"1B": "一买", "2B": "二买", "3B": "三买",
           "1S": "一卖", "2S": "二卖", "3S": "三卖"}


def find_buy_sell_points(bis, bars, zs_seq):
    """识别全部缠论买卖点（前置定义）。
    返回 [(中文名, 时间, 价格, 描述), ...]"""
    out = []
    for p in find_all_bs_points(bars, bis, zs_seq):
        name = _BS_NAME.get(p["type"], p["type"])
        desc = p["desc"] + ("（已确认）" if p["status"] == "confirmed" else "（待确认）")
        out.append((name, p["time"], p["price"], desc))
    return out


def analyze_trend(c: CZSC):
    """核心趋势判断。返回结论 dict"""
    bis = c.get_finished_bis()
    ubi_fxs = c.get_ubi_fxs() or []
    latest_close = c.bars_raw[-1].close
    latest_dt = c.bars_raw[-1].dt

    result = {
        "direction": "震荡",
        "strength": "中",
        "latest_close": latest_close,
        "latest_dt": latest_dt,
        "reasons": [],
        "signals": [],
        "advice": "",
        "ubi_direction": None,
        "last_bi": None,
        "last_zs": None,
    }

    if len(bis) < 2:
        result["direction"] = "数据不足"
        result["reasons"].append("笔数量不足 2，无法判断趋势")
        return result

    # 未完成笔方向
    if bis:
        ubi_dir = "向上" if bis[-1].direction == "Down" else "向下"
        result["ubi_direction"] = ubi_dir
        result["last_bi"] = bis[-1]

    # 最后一个有效中枢（缠论标准：至少 3 笔重叠）
    valid_zs = [z for z in get_zs_seq(bis) if z.is_valid() and len(z.bis) >= ZS_MIN_BIS]
    if valid_zs:
        result["last_zs"] = valid_zs[-1]
        zs = valid_zs[-1]

    # 买卖点（前置定义：趋势背驰 → 一二三类买卖点）
    # 【需求】关闭买卖点信号：仅保留笔/中枢/分型结构，signals 恒为空
    bs = []
    result["signals"] = bs
    bs_names = [s[0] for s in bs]

    last_bi = bis[-1]
    bi_dir = "向上" if last_bi.direction == "Up" else "向下"

    # ---- 趋势方向判定 ----
    if result["last_zs"] is None:
        # 无中枢：按最近3笔高低点
        seg = bis[-3:]
        if len(seg) == 3:
            up_highs = [b.get_high() for b in seg if b.direction == "Up"]
            down_lows = [b.get_low() for b in seg if b.direction == "Down"]
            if len(up_highs) >= 2 and up_highs[-1] > up_highs[-2]:
                result["direction"] = "上涨"
            elif len(down_lows) >= 2 and down_lows[-1] < down_lows[-2]:
                result["direction"] = "下跌"
            else:
                result["direction"] = "震荡"
            result["reasons"].append("中枢尚未形成，按最近 3 笔高低点判断")
    else:
        zs = result["last_zs"]
        price = latest_close
        # 结合未完成笔方向：已确认笔可能滞后，ubi 反映当前正在进行的走势
        ubi_dir = result["ubi_direction"]
        moving_up = (bi_dir == "向上") or (ubi_dir == "向上")
        moving_down = (bi_dir == "向下") or (ubi_dir == "向下")
        if price > zs.zg:
            if moving_up:
                result["direction"] = "上涨"
                result["reasons"].append(
                    f"价格 {price:.3f} 位于最近中枢上方（zg={zs.zg:.3f}），"
                    f"最后一笔{bi_dir}、未完成笔{ubi_dir}")
                if price > zs.zg * 1.08:
                    result["reasons"].append(
                        f"价格已超出中枢上沿 {((price / zs.zg - 1) * 100):.1f}%，离开中枢的强势走势")
            else:
                result["direction"] = "震荡偏多"
                result["reasons"].append(
                    f"价格 {price:.3f} 在中枢上方（zg={zs.zg:.3f}）但走势向下，属上涨回踩")
        elif price < zs.zd:
            if moving_down:
                result["direction"] = "下跌"
                result["reasons"].append(
                    f"价格 {price:.3f} 位于最近中枢下方（zd={zs.zd:.3f}），"
                    f"最后一笔{bi_dir}、未完成笔{ubi_dir}")
                if price < zs.zd * 0.92:
                    result["reasons"].append(
                        f"价格已低于中枢下沿 {((1 - price / zs.zd) * 100):.1f}%，跌破中枢的弱势走势")
            else:
                result["direction"] = "震荡偏空"
                result["reasons"].append(
                    f"价格 {price:.3f} 在中枢下方（zd={zs.zd:.3f}）但走势向上，属下跌反弹")
        else:
            result["direction"] = "震荡"
            result["reasons"].append(
                f"价格 {price:.3f} 处于最近中枢区间 [{zs.zd:.3f}, {zs.zg:.3f}] 内")

    # 最近3笔高低点趋势
    if len(bis) >= 3:
        seg = bis[-3:]
        lows = [b.get_low() for b in seg if b.direction == "Down"]
        highs = [b.get_high() for b in seg if b.direction == "Up"]
        if len(lows) >= 2 and lows[-1] > lows[-2]:
            result["reasons"].append(f"最近低点抬高（{lows[-2]:.3f} → {lows[-1]:.3f}），多头占优")
        elif len(lows) >= 2 and lows[-1] < lows[-2]:
            result["reasons"].append(f"最近低点降低（{lows[-2]:.3f} → {lows[-1]:.3f}），空头占优")
        if len(highs) >= 2 and highs[-1] > highs[-2]:
            result["reasons"].append(f"最近高点抬高（{highs[-2]:.3f} → {highs[-1]:.3f}），多头占优")
        elif len(highs) >= 2 and highs[-1] < highs[-2]:
            result["reasons"].append(f"最近高点降低（{highs[-2]:.3f} → {highs[-1]:.3f}），空头占优")

    # 背驰/买卖点增强
    if bs:
        for name, dt, price, desc in bs:
            if name in ("一买", "二买", "三买"):
                result["reasons"].append(f"缠论信号：{name}（{desc}）→ 看多")
            else:
                result["reasons"].append(f"缠论信号：{name}（{desc}）→ 看空")
    else:
        # 无买卖点时检测背驰迹象
        if bi_dir == "向上" and len(bis) >= 3:
            prev = bis[-2]
            if last_bi.get_power() < prev.get_power() * 0.8:
                result["reasons"].append("最后一笔向上但力度较前笔明显减弱，警惕顶背驰")
        if bi_dir == "向下" and len(bis) >= 3:
            prev = bis[-2]
            if last_bi.get_power() < prev.get_power() * 0.8:
                result["reasons"].append("最后一笔向下但力度较前笔明显减弱，警惕底背驰")

    # 强度：方向一致 + 买卖点/远离中枢 → 强；仅方向一致 → 中；方向背离 → 弱
    d = result["direction"]
    bull_sig = any(b in ("一买", "二买", "三买") for b in bs_names)
    bear_sig = any(b in ("一卖", "二卖", "三卖") for b in bs_names)
    zs_ref = result["last_zs"]
    if "上涨" in d:
        strong = moving_up and (bull_sig or (zs_ref is not None and latest_close > zs_ref.zg * 1.05))
        result["strength"] = "强" if strong else ("中" if moving_up else "弱")
    elif "下跌" in d:
        strong = moving_down and (bear_sig or (zs_ref is not None and latest_close < zs_ref.zd * 0.95))
        result["strength"] = "强" if strong else ("中" if moving_down else "弱")
    else:
        result["strength"] = "中"

    # 操作建议
    adv = []
    if "上涨" in result["direction"]:
        adv.append("多头趋势：持有多单可继续持有，回踩不破前低/中枢上沿可加仓")
        if "三买" in bs_names:
            adv.append("出现三买：突破回踩确认，多头信号增强")
        if "一卖" in bs_names or "二卖" in bs_names:
            adv.append("注意：出现卖出信号，谨防趋势反转")
    elif "下跌" in result["direction"]:
        adv.append("空头趋势：持有空单可继续持有，反弹不破前高/中枢下沿可加仓")
        if "三卖" in bs_names:
            adv.append("出现三卖：破位反抽确认，空头信号增强")
        if "一买" in bs_names or "二买" in bs_names:
            adv.append("注意：出现买入信号，谨防趋势反转")
    else:
        adv.append("震荡格局：观望为主，突破中枢上沿做多 / 跌破下沿做空")
        if "三买" in bs_names:
            adv.append("出现三买：突破回踩确认，可尝试做多")
        if "三卖" in bs_names:
            adv.append("出现三卖：破位反抽确认，可尝试做空")
    adv.append("（以上为缠论技术分析参考，不构成投资建议）")
    result["advice"] = "；".join(adv)
    return result


# =====================================================================
# 六、报告输出
# =====================================================================

def print_report(code_label, freq, sdt, edt, bars, prewarm, c: CZSC, res: dict):
    line = "=" * 62
    sub = "-" * 62
    print()
    print(line)
    print("                     缠 论 趋 势 分 析 报 告")
    print(line)
    print(f"标的：{code_label}")
    print(f"周期：{freq}   |   判断区间：{sdt.date()} ~ {edt.date()}")
    print(f"K线：{len(bars)} 根（含 {prewarm} 根历史预热）"
          f"   |   最新K线时间：{c.bars_raw[-1].dt}")
    print(sub)

    # 缠论结构
    ubi_count = len(c.bars_ubi)
    fxs = c.fx_list
    g_cnt = sum(1 for x in fxs if x.mark == "G")
    d_cnt = sum(1 for x in fxs if x.mark == "D")
    bis = c.get_finished_bis()
    up_cnt = sum(1 for b in bis if b.direction == "Up")
    dn_cnt = sum(1 for b in bis if b.direction == "Down")
    zs_list = [z for z in c.zs_list if z.is_valid() and len(z.bis) >= ZS_MIN_BIS]

    print("[缠论结构]")
    print(f"  未完成笔K线（去包含）：{ubi_count} 根")
    print(f"  分型：{len(fxs)} 个（顶 {g_cnt} / 底 {d_cnt}，含笔内部分型）")
    print(f"  完成笔：{len(bis)} 笔（向上 {up_cnt} / 向下 {dn_cnt}）")
    print(f"  有效中枢：{len(zs_list)} 个")
    print(f"  未完成笔方向：{res['ubi_direction'] or '无'}"
          f"{'（延伸中）' if c.last_bi_extend else ''}")
    print(sub)

    # 最近3笔
    print("[最近 3 笔]")
    for b in bis[-3:]:
        d = "向上" if b.direction == "Up" else "向下"
        print(f"  {d}  {b.start_dt:%Y-%m-%d %H:%M} -> {b.end_dt:%Y-%m-%d %H:%M}"
              f"  |  幅度 {b.get_power():.3f}  长度 {b.get_length()} 根"
              f"  |  区间 [{b.get_low():.3f}, {b.get_high():.3f}]")
    print(sub)

    # 最近中枢
    if res["last_zs"]:
        zs = res["last_zs"]
        print("[最近有效中枢]")
        # 时间范围取中间震荡段（去掉首尾方向笔）
        if len(zs.bis) >= 2:
            disp_sdt, disp_edt = zs.bis[1].fx_a.dt, zs.bis[-2].fx_b.dt
        else:
            disp_sdt, disp_edt = zs.sdt, zs.edt
        print(f"  {disp_sdt:%Y-%m-%d %H:%M} ~ {disp_edt:%Y-%m-%d %H:%M}")
        note = "（延伸中）" if len(zs.bis) < 3 else ""
        d1 = "上" if zs.bis[0].direction == "Up" else "下"
        d2 = "上" if zs.bis[-1].direction == "Up" else "下"
        d = zs_direction(zs, c.get_finished_bis(), res["latest_close"])
        print(f"  区间 [{zs.zd:.3f}, {zs.zg:.3f}]  中轴 {zs.zz:.3f}"
              f"  极值 [{zs.dd:.3f}, {zs.gg:.3f}]  构成笔数 {len(zs.bis)}"
              f"（首{d1}尾{d2}）· 方向：{d}{note}")
    else:
        print("[最近有效中枢] 无")
    print(sub)

    print(sub)

    # 趋势结论
    print("[趋势结论]")
    print(f"  当前趋势：{res['direction']}（强度：{res['strength']}）")
    print(f"  最新收盘：{res['latest_close']:.3f}（{res['latest_dt']:%Y-%m-%d %H:%M}）")
    print()
    print("  判断依据：")
    for i, r_ in enumerate(res["reasons"], 1):
        print(f"    {i}. {r_}")
    print()
    print("  操作建议：")
    for adv in res["advice"].split("；"):
        if adv.strip():
            print(f"    - {adv.strip()}")
    print(line)


# =====================================================================
# 七、主程序
# =====================================================================

def main():
    args = sys.argv[1:]
    if len(args) >= 4:
        code_in, freq_in, sdt_in, edt_in = args[:4]
    else:
        print("=" * 62)
        print("                   缠论趋势分析程序")
        print("=" * 62)
        print("数据源：D:\khData（DuckDB）")
        print("支持周期：1分钟 / 5分钟 / 15分钟 / 30分钟 / 60分钟 / 120分钟 / 日线 / 周线 / 月线")
        print("示例：000001.SZ  或  600000（沪市） / 300750（深市）")
        print("输入 q 退出")
        print("-" * 62)
        code_in = input("请输入股票代码：").strip()
        if code_in.lower() in ("q", "quit", "exit"):
            return
        freq_in = input("请输入周期级别（如 日线 / 30分钟 / 5分钟）：").strip()
        if freq_in.lower() in ("q", "quit", "exit"):
            return
        sdt_in = input("请输入起始日期（YYYY-MM-DD）：").strip()
        if sdt_in.lower() in ("q", "quit", "exit"):
            return
        edt_in = input("请输入终止日期（YYYY-MM-DD）：").strip()
        if edt_in.lower() in ("q", "quit", "exit"):
            return

    code_in = code_in.strip()
    freq_in = freq_in.strip()
    freq = FREQ_ALIASES.get(freq_in)
    if not freq:
        print(f"[错误] 不支持的周期：{freq_in}")
        return

    try:
        sdt = _parse_date(sdt_in)
        edt = _parse_date(edt_in)
    except ValueError as e:
        print(f"[错误] {e}")
        return
    if sdt > edt:
        print("[错误] 起始日期不能晚于终止日期")
        return

    code, exchange = resolve_symbol(code_in)
    if not exchange:
        print(f"[错误] 无法判断 {code_in} 的市场（沪市60/68开头，深市00/30开头）")
        return

    try:
        label, bars, prewarm = load_bars(code, exchange, freq, sdt, edt)
        c = CZSC(bars)
        res = analyze_trend(c)
        print_report(label, freq, sdt, edt, bars, prewarm, c, res)

        # ---- HTML 图表报告 ----
        auto_mode = len(args) >= 4
        want_html = True
        out_html = None
        if not auto_mode:
            ans = input("\n是否生成 HTML 图表报告（含K线图）？(y/n，默认 y)：").strip().lower()
            want_html = ans not in ("n", "no")
            if want_html:
                p = input("输出路径（回车自动命名到 reports 目录）：").strip()
                out_html = p or None
        if want_html:
            html_path = render_html(label, freq, sdt, edt, bars, prewarm, c, res, out_html)
            print(f"\n[HTML] 报告已生成：{html_path}")
            open_browser = True
            if not auto_mode:
                ans = input("是否用浏览器打开？(y/n，默认 y)：").strip().lower()
                open_browser = ans not in ("n", "no")
            if open_browser:
                try:
                    import webbrowser
                    webbrowser.open("file:///" + html_path.replace("\\", "/"))
                except Exception:
                    pass
    except Exception as e:
        print(f"[错误] {e}")
        return


# =====================================================================
# 八、HTML 图表报告（ECharts：K线 + 笔 + 分型 + 中枢 + 买卖点 + MACD）
# =====================================================================

def _ts(dt):
    """datetime -> JS 毫秒时间戳"""
    return int(dt.timestamp() * 1000)


def _ma_series(vals, n):
    """简单移动平均，前 n-1 个为 None"""
    out, s = [], 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n:
            s -= vals[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def _ema_series(vals, n):
    k = 2.0 / (n + 1)
    e, out = None, []
    for v in vals:
        e = v if e is None else v * k + e * (1 - k)
        out.append(e)
    return out


def _macd_series(closes):
    """MACD(12,26,9)，hist 按国内习惯 ×2"""
    dif = [a - b for a, b in zip(_ema_series(closes, 12), _ema_series(closes, 26))]
    dea = _ema_series(dif, 9)
    hist = [(d - s) * 2 for d, s in zip(dif, dea)]
    return dif, dea, hist


def _bs_price(bis, dt):
    """买卖点时间 -> 价格（取对应笔端点）"""
    for b in bis:
        if b.end_dt == dt:
            return b.fx_b.fx
    return bis[-1].fx_b.fx if bis else 0.0


def _echarts_src(html_path):
    """优先本地 assets/echarts.min.js，否则 CDN"""
    base = os.path.dirname(os.path.abspath(__file__))
    local = os.path.join(base, "assets", "echarts.min.js")
    if os.path.exists(local):
        rel = os.path.relpath(local, os.path.dirname(os.path.abspath(html_path)))
        return rel.replace("\\", "/")
    return "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<script src="__ECHARTS__"></script>
<script>if(!window.echarts){document.write('<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"><\/script>')}</script>
<style>
body{font-family:"Microsoft YaHei","PingFang SC",sans-serif;margin:0;background:#f5f6fa;color:#333}
.wrap{max-width:1280px;margin:0 auto;padding:16px}
.header{background:#fff;border-radius:10px;padding:16px 22px;margin-bottom:14px;box-shadow:0 1px 4px rgba(0,0,0,.08)}
.header h1{margin:0 0 8px;font-size:22px;color:#1a1a1a}
.header .meta{color:#666;font-size:13px;line-height:1.9}
.badges{margin-top:10px}
.badge{display:inline-block;padding:4px 16px;border-radius:20px;color:#fff;font-size:14px;font-weight:bold;margin-right:8px}
.badge.up{background:#e0503e}.badge.down{background:#1a9a5a}.badge.flat{background:#7f8c9b}
.badge.strong{background:#b3200e}.badge.mid{background:#e67e22}.badge.weak{background:#bdc3c7}
.badge.bs{background:#2f6fed}
#chart{background:#fff;border-radius:10px;padding:6px;box-shadow:0 1px 4px rgba(0,0,0,.08)}
.report{background:#fff;border-radius:10px;padding:18px 22px;margin-top:14px;box-shadow:0 1px 4px rgba(0,0,0,.08);font-size:14px;line-height:1.95}
.report h2{font-size:16px;border-left:4px solid #2f6fed;padding-left:10px;margin:16px 0 8px}
.report h2:first-child{margin-top:0}
.reasons{margin:0;padding-left:22px}
table.kv{width:100%;border-collapse:collapse;margin-top:4px}
table.kv td{border:1px solid #eee;padding:6px 12px}
table.kv td:first-child{background:#fafbfc;color:#666;width:130px}
table.bs{width:100%;border-collapse:collapse;margin-top:4px}
table.bs th,table.bs td{border:1px solid #eee;padding:6px 12px;text-align:left}
table.bs th{background:#fafbfc;color:#666;font-weight:normal}
.advice{background:#fff8e6;border:1px solid #f0d990;border-radius:6px;padding:8px 14px;color:#7a5b00;margin-top:4px}
.footer{color:#999;font-size:12px;text-align:center;margin:16px 0 30px}
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <h1>缠论趋势分析 · __SYMBOL__</h1>
    <div class="meta">
      周期：__FREQ__ ｜ 判断区间：__SDT__ ~ __EDT__ ｜ 数据：__BARS__ 根原始K线（去包含后 __UBI__ 根，含 __PREWARM__ 根历史预热）<br>
      最新收盘：__CLOSE__（__CLOSEDT__）｜ 缠论结构：__BIS__ 笔 / __ZS__ 个中枢 / __FXS__ 个分型
    </div>
    <div class="badges">
      <span class="badge __DIR_CLASS__">__DIRECTION__</span>
      <span class="badge __STR_CLASS__">强度：__STRENGTH__</span>
      __BS_BADGES__
    </div>
  </div>
  <div id="chart" style="width:100%;height:__CHART_H__px;"></div>
  <div class="report">
    <h2>趋势结论与判断依据</h2>
    <ul class="reasons">__REASONS__</ul>
    <h2>操作建议</h2>
    <div class="advice">__ADVICE__</div>
    <h2>缠论结构统计</h2>
    <table class="kv">__KV__</table>
  </div>
  <div class="footer">本报告由 chan_trend.py 自动生成 ｜ 缠论技术分析仅供参考，不构成投资建议</div>
</div>
<script>
var DATA = __DATA__;
var chart = echarts.init(document.getElementById('chart'));
var option = {
  animation:false,
  tooltip:{trigger:'axis',axisPointer:{type:'cross'},backgroundColor:'rgba(255,255,255,.96)',borderColor:'#ddd',textStyle:{color:'#333',fontSize:12}},
  legend:{data:['K线','MA5','MA20','MA60','笔','顶分型','底分型'],top:6,textStyle:{fontSize:12}},
  axisPointer:{link:[{xAxisIndex:'all'}]},
  grid:[
    {left:70,right:28,top:42,height:'46%'},
    {left:70,right:28,top:'57%',height:'12%'},
    {left:70,right:28,top:'74%',height:'13%'}
  ],
  xAxis:[
    {type:'category',gridIndex:0,data:DATA.catLabels,axisLabel:{interval:DATA.labelInterval,color:'#666',formatter:function(v){return v}},axisLine:{lineStyle:{color:'#ccc'}}},
    {type:'category',gridIndex:1,data:DATA.catLabels,axisLabel:{show:false}},
    {type:'category',gridIndex:2,data:DATA.catLabels,axisLabel:{interval:DATA.labelInterval,color:'#666',formatter:function(v){return v}},axisLine:{lineStyle:{color:'#ccc'}}}
  ],
  yAxis:[
    {gridIndex:0,scale:true,splitLine:{lineStyle:{color:'#f0f0f0'}},axisLabel:{color:'#666'}},
    {gridIndex:1,scale:true,splitLine:{show:false},axisLabel:{color:'#999',fontSize:10}},
    {gridIndex:2,scale:true,splitLine:{show:false},axisLabel:{color:'#999',fontSize:10}}
  ],
  dataZoom:[
    {type:'inside',xAxisIndex:[0,1,2],start:DATA.zoomStart,end:100},
    {type:'slider',xAxisIndex:[0,1,2],bottom:4,start:DATA.zoomStart,end:100,height:16}
  ],
  series:[
    {name:'K线',type:'candlestick',data:DATA.kline,itemStyle:{color:'#e0503e',color0:'#1a9a5a',borderColor:'#e0503e',borderColor0:'#1a9a5a'}},
    {name:'MA5',type:'line',data:DATA.ma5,symbol:'none',lineStyle:{width:1,color:'#f6a821'}},
    {name:'MA20',type:'line',data:DATA.ma20,symbol:'none',lineStyle:{width:1,color:'#2f6fed'}},
    {name:'MA60',type:'line',data:DATA.ma60,symbol:'none',lineStyle:{width:1,color:'#9b59b6'}},
    {name:'笔',type:'line',data:DATA.biLine,symbol:'none',lineStyle:{width:1.6,color:'#222'},z:6},
    {name:'中枢',type:'line',data:[],markArea:{silent:true,data:DATA.zsAreas},z:5},
    {name:'区间起点',type:'line',data:[],markLine:{silent:true,symbol:'none',lineStyle:{color:'#999',type:'dashed'},label:{show:true,formatter:'区间起点',color:'#999'},data:[{xAxis:DATA.sdtIdx}]}},
    {name:'顶分型',type:'scatter',data:DATA.topFx,symbol:'triangle',symbolSize:11,itemStyle:{color:'#e0503e',borderColor:'#a02010',borderWidth:0.5},z:7},
    {name:'底分型',type:'scatter',data:DATA.bottomFx,symbol:'triangle',symbolRotate:180,symbolSize:11,itemStyle:{color:'#1a9a5a',borderColor:'#0a6a3a',borderWidth:0.5},z:7},
    {name:'成交量',type:'bar',xAxisIndex:1,yAxisIndex:1,data:DATA.vols,itemStyle:{color:function(p){return p.data[1]>0?'#e0503e':'#1a9a5a'}}},
    {name:'MACD',type:'bar',xAxisIndex:2,yAxisIndex:2,data:DATA.macd,itemStyle:{color:function(p){return p.data[1]>=0?'#e0503e':'#1a9a5a'}}},
    {name:'DIF',type:'line',xAxisIndex:2,yAxisIndex:2,data:DATA.dif,symbol:'none',lineStyle:{width:1,color:'#f6a821'}},
    {name:'DEA',type:'line',xAxisIndex:2,yAxisIndex:2,data:DATA.dea,symbol:'none',lineStyle:{width:1,color:'#2f6fed'}}
  ]
};
chart.setOption(option);
window.addEventListener('resize',function(){chart.resize();});
</script>
</body>
</html>
"""


def render_html(code_label, freq, sdt, edt, bars, prewarm, c: CZSC, res: dict, out_path=None):
    """生成自包含 HTML 图表报告，返回文件路径"""
    import json

    # 前端K线 = 去包含关系后的缠论K线（c.bars_ubi），
    # 每个 NewBar.elements 记录构成它的原始K线：包含合并时 elements>1，
    # 其 dt 列表就是被合并的多个交易日。
    ubi = remove_include_all(bars)
    n = len(ubi)
    dts = [b.dt for b in ubi]
    opens = [b.open for b in ubi]
    closes = [b.close for b in ubi]
    highs = [b.high for b in ubi]
    lows = [b.low for b in ubi]
    vols = [b.vol for b in ubi]

    def _to_idx(dt, mode="right"):
        """时间 -> K线索引（category 轴，去包含K线等距无空档）"""
        if mode == "left":
            return bisect.bisect_left(dts, dt)
        return bisect.bisect_right(dts, dt) - 1

    # x 轴标签：按去包含K线连续排列；遇到包含合并K线（elements>1），
    # 标注构成它的全部原始日期，如 "2025-03-03、2025-03-04"
    def _fmt_dt(dt):
        if freq in ("日线", "周线", "月线"):
            return dt.strftime("%Y-%m-%d")
        return dt.strftime("%m-%d %H:%M")

    cat_labels = []
    for nb in ubi:
        ds = [e.dt for e in nb.elements]
        if len(ds) == 1:
            cat_labels.append(_fmt_dt(ds[0]))
        else:
            cat_labels.append("、".join(_fmt_dt(d) for d in ds))
    label_interval = max(1, n // 14)

    # K线/成交量（category 轴：纯值 + 索引）
    kline = [[opens[i], closes[i], lows[i], highs[i]] for i in range(n)]
    vol_data = [[vols[i], 1 if closes[i] >= opens[i] else -1] for i in range(n)]

    def _line(series_vals, rnd=3):
        return [None if series_vals[i] is None else round(series_vals[i], rnd)
                for i in range(n)]

    ma5 = _line(_ma_series(closes, 5))
    ma20 = _line(_ma_series(closes, 20))
    ma60 = _line(_ma_series(closes, 60))
    dif, dea, hist = _macd_series(closes)
    macd = [[round(hist[i], 4), 1 if hist[i] >= 0 else -1] for i in range(n)]
    dif_d = _line(dif)
    dea_d = _line(dea)

    # 笔线（端点连线，索引坐标）
    bis = c.get_finished_bis()
    bi_line = []
    for b in bis:
        bi_line.append([_to_idx(b.fx_a.dt), round(b.fx_a.fx, 3)])
        bi_line.append([_to_idx(b.fx_b.dt), round(b.fx_b.fx, 3)])

    # 分型（笔端点分型，避免笔内部分型堆叠）
    top_fx, bottom_fx, seen = [], [], set()
    for b in bis:
        for fx in (b.fx_a, b.fx_b):
            key = (_to_idx(fx.dt), fx.mark)
            if key in seen:
                continue
            seen.add(key)
            if fx.mark == "G":
                top_fx.append([_to_idx(fx.dt), round(fx.high, 3)])
            else:
                bottom_fx.append([_to_idx(fx.dt), round(fx.low, 3)])

    # 中枢区域：虚线边框 + 淡色填充 + 上下沿范围（缠论标准画法）
    zs_list = [z for z in c.zs_list if z.is_valid() and len(z.bis) >= ZS_MIN_BIS]
    zs_areas = []
    for i, z in enumerate(zs_list):
        # 框框只包含中间震荡段：去掉首笔（进入性质）和末笔（离开性质）的时间跨度
        if len(z.bis) >= 2:
            s_i = _to_idx(z.bis[1].fx_a.dt)
            e_i = _to_idx(z.bis[-2].fx_b.dt)
        else:
            s_i, e_i = _to_idx(z.sdt), _to_idx(z.edt)
        d = z.direction or zs_direction(z, bis, res["latest_close"])
        zs_areas.append([
            {"xAxis": s_i, "yAxis": round(z.zg, 3),
             "itemStyle": {"color": "rgba(47,111,237,0.16)",
                           "borderColor": "#2f6fed", "borderWidth": 1,
                           "borderType": "dashed"},
             "label": {"show": True,
                       "formatter": "中枢%d %d笔 %s [%.2f,%.2f]"
                                    % (i + 1, len(z.bis), d, z.zd, z.zg),
                       "color": "#2f6fed", "fontSize": 10, "position": "insideTop"}},
            {"xAxis": e_i, "yAxis": round(z.zd, 3)},
        ])
    # 买卖点（已关闭：图上不再标注买卖点）
    bs_points = []

    sdt_idx = bisect.bisect_left(dts, sdt)

    # ---- 汇总统计 ----
    fxs = c.fx_list
    g_cnt = sum(1 for x in fxs if x.mark == "G")
    d_cnt = sum(1 for x in fxs if x.mark == "D")
    up_cnt = sum(1 for b in bis if b.direction == "Up")
    dn_cnt = sum(1 for b in bis if b.direction == "Down")

    # ---- 买卖点徽章与表格（已关闭） ----
    bs_badges = ""
    bs_table = ""

    reasons_html = "".join("<li>%s</li>" % r for r in res["reasons"])
    advice_html = "；".join(a for a in res["advice"].split("；") if a.strip())
    advice_html = advice_html.replace("（以上为缠论技术分析参考，不构成投资建议）",
                                      "<b>（以上为缠论技术分析参考，不构成投资建议）</b>")

    kv_rows = [
        ("标的", code_label),
        ("周期", freq),
        ("判断区间", "%s ~ %s" % (sdt.date(), edt.date())),
        ("K线总数", "%d 根（含 %d 根历史预热）" % (len(bars), prewarm)),
        ("去包含K线（未完成笔）", "%d 根" % len(c.bars_ubi)),
        ("分型", "%d 个（顶 %d / 底 %d，含笔内部分型）" % (len(fxs), g_cnt, d_cnt)),
        ("完成笔", "%d 笔（向上 %d / 向下 %d）" % (len(bis), up_cnt, dn_cnt)),
        ("有效中枢", "%d 个" % len(zs_list)),
        ("未完成笔方向", "%s%s" % (res["ubi_direction"] or "无", "（延伸中）" if c.last_bi_extend else "")),
        ("最新收盘", "%.3f（%s）" % (res["latest_close"], res["latest_dt"])),
    ]
    kv = "".join("<tr><td>%s</td><td>%s</td></tr>" % (k, v) for k, v in kv_rows)

    dir_class = "up" if "上涨" in res["direction"] else ("down" if "下跌" in res["direction"] else "flat")
    str_class = {"强": "strong", "中": "mid", "弱": "weak"}.get(res["strength"], "mid")
    chart_h = 680 if n > 200 else 600

    js_data = {
        "catLabels": cat_labels, "labelInterval": label_interval,
        "kline": kline, "ma5": ma5, "ma20": ma20, "ma60": ma60,
        "biLine": bi_line,
        "topFx": top_fx, "bottomFx": bottom_fx,
        "bsPoints": bs_points, "zsAreas": zs_areas, "sdtIdx": sdt_idx,
        "vols": vol_data, "macd": macd, "dif": dif_d, "dea": dea_d,
        "zoomStart": max(0, round((1 - 800.0 / max(n, 1)) * 100)),
        "isMinute": freq not in ("日线", "周线", "月线"),
    }

    if out_path:
        out_path = os.path.abspath(out_path)
    else:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "%s_%s_%s.html" % (code_label.replace(".", "_"), freq, edt.strftime("%Y%m%d")))

    html = _HTML_TEMPLATE
    html = html.replace("__TITLE__", "缠论趋势分析 %s %s" % (code_label, freq))
    html = html.replace("__ECHARTS__", _echarts_src(out_path))
    html = html.replace("__SYMBOL__", code_label)
    html = html.replace("__FREQ__", freq)
    html = html.replace("__SDT__", str(sdt.date()))
    html = html.replace("__EDT__", str(edt.date()))
    html = html.replace("__BARS__", str(len(bars)))
    html = html.replace("__UBI__", str(len(c.bars_ubi)))
    html = html.replace("__PREWARM__", str(prewarm))
    html = html.replace("__CLOSE__", "%.3f" % res["latest_close"])
    html = html.replace("__CLOSEDT__", res["latest_dt"].strftime("%Y-%m-%d %H:%M"))
    html = html.replace("__BIS__", str(len(bis)))
    html = html.replace("__ZS__", str(len(zs_list)))
    html = html.replace("__FXS__", str(len(fxs)))
    html = html.replace("__DIR_CLASS__", dir_class)
    html = html.replace("__DIRECTION__", res["direction"])
    html = html.replace("__STR_CLASS__", str_class)
    html = html.replace("__STRENGTH__", res["strength"])
    html = html.replace("__BS_BADGES__", bs_badges)
    html = html.replace("__REASONS__", reasons_html)
    html = html.replace("__ADVICE__", advice_html)
    html = html.replace("__BS_TABLE__", bs_table)
    html = html.replace("__KV__", kv)
    html = html.replace("__CHART_H__", str(chart_h))
    html = html.replace("__DATA__", json.dumps(js_data, ensure_ascii=False))

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


if __name__ == "__main__":
    main()

