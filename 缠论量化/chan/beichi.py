# -*- coding: utf-8 -*-
"""模块7：背驰计算（趋势背驰 + 盘整背驰）

输入：走势类型 + 对应段 MACD 数据（DIF、DEA、柱体高度）
输出：背驰信号列表（type: top/bottom, level, time, price, compare_segments, is_confirmed, method）

规则：
1. 对比段：同方向、同级别、相邻的两段连接走势（b段、c段）
2. MACD 面积法（优先）：
   - 底背驰：c 创新低（c.low < b.low）且 c 绿柱总面积 < b 绿柱总面积
             且 c 段 DIF 最低点 > b 段 DIF 最低点
   - 顶背驰：c 创新高（c.high > b.high）且 c 红柱总面积 < b 红柱总面积
             且 c 段 DIF 最高点 < b 段 DIF 最高点
3. 纯价格斜率法（备用）：力度 = 涨跌幅/K线数，后段 < 前段 → 背驰
4. 确认：必须出现反向分型（由调用方结合分型判定）
5. 分类：趋势背驰（趋势最后中枢离开段）/ 盘整背驰（盘整进出中枢段）
"""
from .models import Beichi
from . import config


def calc_macd(closes, fast=None, slow=None, signal=None):
    """计算 MACD：返回 (DIF, DEA, HIST) 列表（长度 = len(closes)）"""
    fast = fast or config.MACD_FAST
    slow = slow or config.MACD_SLOW
    signal = signal or config.MACD_SIGNAL

    def ema(vals, n):
        k = 2.0 / (n + 1)
        e, out = None, []
        for v in vals:
            e = v if e is None else v * k + e * (1 - k)
            out.append(e)
        return out

    dif = [a - b for a, b in zip(ema(closes, fast), ema(closes, slow))]
    dea = ema(dif, signal)
    hist = [(d - s) * 2 for d, s in zip(dif, dea)]
    return dif, dea, hist


def _seg_stats(closes, dts, dif, hist, sdt, edt):
    """段 [sdt, edt] 的 MACD 统计"""
    import bisect
    i0 = bisect.bisect_left(dts, sdt)
    i1 = bisect.bisect_right(dts, edt)
    if i1 <= i0:
        return None
    seg_hist = hist[i0:i1]
    seg_dif = dif[i0:i1]
    green = sum(abs(x) for x in seg_hist if x < 0)
    red = sum(x for x in seg_hist if x > 0)
    c0, c1 = closes[i0], closes[i1 - 1]
    pct = (c1 - c0) / c0 if c0 else 0.0
    n_bar = i1 - i0
    return {'green': green, 'red': red, 'dif_lo': min(seg_dif),
            'dif_hi': max(seg_dif), 'low': min(closes[i0:i1]),
            'high': max(closes[i0:i1]), 'slope': pct / max(n_bar, 1)}


def _bottom_divergence(b, c):
    """底背驰（c 相对 b）"""
    if not b or not c:
        return False, 'none'
    if c['low'] >= b['low'] - 1e-9:
        return False, 'none'  # c 未创新低
    macd_ok = c['green'] < b['green'] * config.DIV_TOLERANCE and c['dif_lo'] > b['dif_lo']
    if macd_ok:
        return True, 'macd'
    price_ok = c['slope'] < b['slope'] * config.DIV_TOLERANCE
    return price_ok, 'price'


def _top_divergence(b, c):
    """顶背驰（c 相对 b）"""
    if not b or not c:
        return False, 'none'
    if c['high'] <= b['high'] + 1e-9:
        return False, 'none'  # c 未创新高
    macd_ok = c['red'] < b['red'] * config.DIV_TOLERANCE and c['dif_hi'] < b['dif_hi']
    if macd_ok:
        return True, 'macd'
    price_ok = c['slope'] < b['slope'] * config.DIV_TOLERANCE
    return price_ok, 'price'


def calc_beichi(trends, closes, dts, dif, hist, units, level='stroke'):
    """计算趋势背驰（趋势走势最后中枢的 b/c 段）
    units: 对应级别单元（笔/线段），含 start_time/end_time/high/low
    返回背驰列表（is_confirmed 由调用方根据末端分型补充）
    """
    beichis = []
    for t in trends:
        if t.type not in ('trend_up', 'trend_down'):
            continue
        centers = t.center_list
        if len(centers) < 2:
            continue
        A, B = centers[-2], centers[-1]
        # 连接段 b：A 末单元之后、B 首单元之前的单元（取与趋势同向的一笔）
        a_last = A.units[-1]
        b_first = B.units[0]
        a_idx = units.index(a_last)
        b_idx = units.index(b_first)
        conn = units[a_idx + 1:b_idx]
        dirname = t.type.replace('trend_', '')
        # b 段：A→B 之间与趋势同向的单元；若无（连接段为回调），取 A 的末单元（向上离开段）
        b_units = [u for u in conn if u.direction == dirname]
        b_u = b_units[0] if b_units else a_last
        # c 段：B 末单元之后与趋势同向的单元；若无，取 B 后第一单元
        bl_idx = units.index(B.units[-1])
        c_units = [u for u in units[bl_idx + 1:] if u.direction == dirname]
        c_u = c_units[0] if c_units else (units[bl_idx + 1] if bl_idx + 1 < len(units) else None)
        if c_u is None:
            continue
        sb = _seg_stats(closes, dts, dif, hist, b_u.start_time, b_u.end_time)
        sc = _seg_stats(closes, dts, dif, hist, c_u.start_time, c_u.end_time)
        if t.type == 'trend_down':
            ok, method = _bottom_divergence(sb, sc)
            btype = 'bottom'
        else:
            ok, method = _top_divergence(sb, sc)
            btype = 'top'
        if ok:
            beichis.append(Beichi(
                type=btype, level=level, time=c_u.end_time,
                price=c_u.end_price,
                compare_segments=(f'b:{b_u.start_time:%Y-%m-%d}~{b_u.end_time:%Y-%m-%d}',
                                  f'c:{c_u.start_time:%Y-%m-%d}~{c_u.end_time:%Y-%m-%d}'),
                is_confirmed=False, method=method,
            ))
    return beichis
